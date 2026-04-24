"""
Database cleanup script for corrupted candle data.

Modes:
  --mode partial  (default) Delete only unclosed/partial candles
  --mode full               TRUNCATE all candles + sr_zones (full wipe)

Usage:
  python clear_candles.py                  # partial cleanup
  python clear_candles.py --mode partial   # same as above
  python clear_candles.py --mode full      # nuclear option
"""
import argparse
import os
import sys
import psycopg2
from dotenv import load_dotenv

load_dotenv()

PARTIAL_DELETE_SQL = """
DELETE FROM candles
WHERE (symbol, timeframe, open_time) IN (
    SELECT c.symbol, c.timeframe, c.open_time
    FROM candles c
    INNER JOIN (
        SELECT symbol, timeframe, MAX(open_time) AS max_ot
        FROM candles
        GROUP BY symbol, timeframe
    ) latest ON c.symbol = latest.symbol
              AND c.timeframe = latest.timeframe
              AND c.open_time = latest.max_ot
    WHERE c.open_time + (
        CASE c.timeframe
            WHEN '1m'  THEN INTERVAL '1 minute'
            WHEN '3m'  THEN INTERVAL '3 minutes'
            WHEN '5m'  THEN INTERVAL '5 minutes'
            WHEN '15m' THEN INTERVAL '15 minutes'
            WHEN '30m' THEN INTERVAL '30 minutes'
            WHEN '1h'  THEN INTERVAL '1 hour'
            WHEN '2h'  THEN INTERVAL '2 hours'
            WHEN '4h'  THEN INTERVAL '4 hours'
            WHEN '6h'  THEN INTERVAL '6 hours'
            WHEN '8h'  THEN INTERVAL '8 hours'
            WHEN '12h' THEN INTERVAL '12 hours'
            WHEN '1d'  THEN INTERVAL '1 day'
            WHEN '3d'  THEN INTERVAL '3 days'
            WHEN '1w'  THEN INTERVAL '7 days'
        END
    ) > NOW()
);
"""

# Preview query to show which rows would be deleted
PARTIAL_PREVIEW_SQL = """
SELECT c.symbol, c.timeframe, c.open_time, c.close, c.volume,
       c.open_time + (
        CASE c.timeframe
            WHEN '1m'  THEN INTERVAL '1 minute'
            WHEN '3m'  THEN INTERVAL '3 minutes'
            WHEN '5m'  THEN INTERVAL '5 minutes'
            WHEN '15m' THEN INTERVAL '15 minutes'
            WHEN '30m' THEN INTERVAL '30 minutes'
            WHEN '1h'  THEN INTERVAL '1 hour'
            WHEN '2h'  THEN INTERVAL '2 hours'
            WHEN '4h'  THEN INTERVAL '4 hours'
            WHEN '6h'  THEN INTERVAL '6 hours'
            WHEN '8h'  THEN INTERVAL '8 hours'
            WHEN '12h' THEN INTERVAL '12 hours'
            WHEN '1d'  THEN INTERVAL '1 day'
            WHEN '3d'  THEN INTERVAL '3 days'
            WHEN '1w'  THEN INTERVAL '7 days'
        END
       ) AS expected_close
FROM candles c
INNER JOIN (
    SELECT symbol, timeframe, MAX(open_time) AS max_ot
    FROM candles
    GROUP BY symbol, timeframe
) latest ON c.symbol = latest.symbol
          AND c.timeframe = latest.timeframe
          AND c.open_time = latest.max_ot
WHERE c.open_time + (
    CASE c.timeframe
        WHEN '1m'  THEN INTERVAL '1 minute'
        WHEN '3m'  THEN INTERVAL '3 minutes'
        WHEN '5m'  THEN INTERVAL '5 minutes'
        WHEN '15m' THEN INTERVAL '15 minutes'
        WHEN '30m' THEN INTERVAL '30 minutes'
        WHEN '1h'  THEN INTERVAL '1 hour'
        WHEN '2h'  THEN INTERVAL '2 hours'
        WHEN '4h'  THEN INTERVAL '4 hours'
        WHEN '6h'  THEN INTERVAL '6 hours'
        WHEN '8h'  THEN INTERVAL '8 hours'
        WHEN '12h' THEN INTERVAL '12 hours'
        WHEN '1d'  THEN INTERVAL '1 day'
        WHEN '3d'  THEN INTERVAL '3 days'
        WHEN '1w'  THEN INTERVAL '7 days'
    END
) > NOW()
ORDER BY c.symbol, c.timeframe;
"""


def run_partial(conn):
    """Delete only the most recent unclosed candle per symbol/timeframe pair."""
    cur = conn.cursor()

    # Preview
    cur.execute(PARTIAL_PREVIEW_SQL)
    rows = cur.fetchall()

    if not rows:
        print("✅ No unclosed/partial candles found. Database is clean.")
        cur.close()
        return

    print(f"\n🔍 Found {len(rows)} partial candle(s) to delete:\n")
    print(f"{'Symbol':<12} {'TF':<6} {'Open Time':<28} {'Close':<12} {'Volume':<14} {'Expected Close':<28}")
    print("-" * 102)
    for row in rows:
        print(f"{row[0]:<12} {row[1]:<6} {str(row[2]):<28} {row[3]:<12.2f} {row[4]:<14.2f} {str(row[5]):<28}")

    print()
    confirm = input("Delete these partial candles? Type 'yes' to proceed: ")
    if confirm.lower() != 'yes':
        print("Operation cancelled.")
        cur.close()
        return

    cur.execute(PARTIAL_DELETE_SQL)
    deleted = cur.rowcount
    conn.commit()
    print(f"\n✅ Deleted {deleted} partial candle(s).")
    cur.close()


def run_full(conn):
    """TRUNCATE all candles and sr_zones tables."""
    print("\n⚠️  WARNING: This will delete ALL data from 'candles' and 'sr_zones' tables.")
    confirm = input("Type 'yes' to proceed: ")

    if confirm.lower() != 'yes':
        print("Operation cancelled. No data was modified.")
        return

    cur = conn.cursor()

    print("Clearing sr_zones table...")
    cur.execute("TRUNCATE TABLE sr_zones CASCADE;")
    print("✅ sr_zones cleared.")

    print("Clearing candles table...")
    cur.execute("TRUNCATE TABLE candles CASCADE;")
    print("✅ candles cleared.")

    conn.commit()
    print("\nSuccessfully wiped all candle and S/R data. "
          "The next session start will trigger a full backfill.")
    cur.close()


def main():
    parser = argparse.ArgumentParser(
        description="Clean corrupted candle data from the database."
    )
    parser.add_argument(
        '--mode', choices=['partial', 'full'], default='partial',
        help="'partial' (default): delete only unclosed candles. "
             "'full': TRUNCATE all candles + sr_zones."
    )
    args = parser.parse_args()

    db_url = os.environ.get('DATABASE_URL', 'postgresql://postgres:password@localhost:5432/signals_db')
    display_url = db_url.split('@')[1] if '@' in db_url else db_url
    print(f"Connecting to: {display_url}")

    try:
        conn = psycopg2.connect(db_url)
        conn.autocommit = False  # We control commits explicitly

        if args.mode == 'partial':
            run_partial(conn)
        else:
            run_full(conn)

        conn.close()

    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)


if __name__ == '__main__':
    main()
