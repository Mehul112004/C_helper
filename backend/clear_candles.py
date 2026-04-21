"""
Standalone script to clear the corrupted candles and sr_zones data.
Connects directly to PostgreSQL using the DATABASE_URL environment variable.
"""
import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

db_url = os.environ.get('DATABASE_URL', 'postgresql://postgres:password@localhost:5432/signals_db')

print(f"Connecting to: {db_url.split('@')[1] if '@' in db_url else db_url}")

try:
    conn = psycopg2.connect(db_url)
    conn.autocommit = True
    cur = conn.cursor()

    print("\nWARNING: This will delete ALL data from the 'candles' and 'sr_zones' tables.")
    confirm = input("Type 'yes' to proceed: ")
    
    if confirm.lower() == 'yes':
        print("Clearing sr_zones table...")
        cur.execute("TRUNCATE TABLE sr_zones CASCADE;")
        print("✅ sr_zones cleared.")
        
        print("Clearing candles table...")
        cur.execute("TRUNCATE TABLE candles CASCADE;")
        print("✅ candles cleared.")
        
        print("\nSuccessfully wiped corrupt timezone data. You can now re-import Binance data from the UI.")
    else:
        print("Operation cancelled. No data was modified.")

    cur.close()
    conn.close()
    
except Exception as e:
    print(f"\n❌ Error connecting or executing query: {e}")
