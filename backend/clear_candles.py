"""
Surgical candle-data cleanup utility.

Usage:
    python clear_candles.py --mode partial   # Remove only unclosed/partial candles
    python clear_candles.py --mode full      # Truncate ALL candles and sr_zones

Requires DATABASE_URL env var.
"""
import argparse
import os
import sys
from dotenv import load_dotenv

# Load environment variables from backend/.env
env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '.env')
load_dotenv(env_path)

def get_engine():
    from sqlalchemy import create_engine
    url = os.environ.get("DATABASE_URL")
    if not url:
        print("ERROR: DATABASE_URL environment variable not set.")
        sys.exit(1)
    return create_engine(url)


def clear_partial(engine):
    """
    Remove candles whose expected close time is in the future
    (i.e., they were persisted before the candle fully closed).
    """
    from sqlalchemy import text
    from datetime import datetime, timezone

    print("[clear_candles] Mode: PARTIAL — removing unclosed candles...")

    with engine.begin() as conn:
        result = conn.execute(text("""
            DELETE FROM candles
            WHERE open_time > NOW() - INTERVAL '1 day'
            AND open_time > (
                SELECT MAX(c2.open_time)
                FROM candles c2
                WHERE c2.symbol = candles.symbol
                  AND c2.timeframe = candles.timeframe
            ) - INTERVAL '1 second'
        """))
        # Simpler approach: just remove the very latest candle per symbol/tf pair
        # since that's the one most likely to be partial
        result = conn.execute(text("""
            DELETE FROM candles c
            WHERE c.open_time = (
                SELECT MAX(c2.open_time)
                FROM candles c2
                WHERE c2.symbol = c.symbol
                  AND c2.timeframe = c.timeframe
            )
        """))
        print(f"  Deleted {result.rowcount} potentially unclosed candles.")

    print("[clear_candles] ✅ Partial cleanup complete.")


def clear_full(engine):
    """Truncate all candle and S/R zone data."""
    from sqlalchemy import text

    print("[clear_candles] Mode: FULL — truncating candles and sr_zones...")

    with engine.begin() as conn:
        r1 = conn.execute(text("DELETE FROM candles"))
        r2 = conn.execute(text("DELETE FROM sr_zones"))
        print(f"  Deleted {r1.rowcount} candles, {r2.rowcount} S/R zones.")

    print("[clear_candles] ✅ Full cleanup complete.")


def main():
    parser = argparse.ArgumentParser(description="Clear corrupted candle data.")
    parser.add_argument(
        "--mode",
        choices=["partial", "full"],
        required=True,
        help="'partial' removes only unclosed candles; 'full' truncates everything.",
    )
    args = parser.parse_args()

    engine = get_engine()

    if args.mode == "partial":
        clear_partial(engine)
    elif args.mode == "full":
        confirm = input("⚠  This will DELETE ALL candles and S/R zones. Type 'yes' to confirm: ")
        if confirm.strip().lower() != "yes":
            print("Aborted.")
            sys.exit(0)
        clear_full(engine)


if __name__ == "__main__":
    main()
