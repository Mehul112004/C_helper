"""
Quick DB candle inspection — shows count and latest candle per symbol/timeframe pair.

Usage:
    python test_db.py

Requires DATABASE_URL env var.
"""
import os
import sys
from dotenv import load_dotenv

# Load environment variables from backend/.env
env_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'backend', '.env')
load_dotenv(env_path)

def main():
    from sqlalchemy import create_engine, text

    url = os.environ.get("DATABASE_URL")
    if not url:
        print("ERROR: DATABASE_URL environment variable not set.")
        sys.exit(1)

    engine = create_engine(url)

    print("═" * 70)
    print("  CANDLE DATABASE INSPECTION")
    print("═" * 70)

    with engine.connect() as conn:
        rows = conn.execute(text("""
            SELECT symbol, timeframe,
                   COUNT(*) as cnt,
                   MIN(open_time) as earliest,
                   MAX(open_time) as latest
            FROM candles
            GROUP BY symbol, timeframe
            ORDER BY symbol, timeframe
        """)).fetchall()

        if not rows:
            print("  No candle data in DB.")
        else:
            print(f"  {'Symbol':<12} {'TF':<6} {'Count':>8}   {'Earliest':<22} {'Latest':<22}")
            print("-" * 70)
            for row in rows:
                print(f"  {row[0]:<12} {row[1]:<6} {row[2]:>8}   {str(row[3]):<22} {str(row[4]):<22}")

    print("═" * 70)


if __name__ == "__main__":
    main()
