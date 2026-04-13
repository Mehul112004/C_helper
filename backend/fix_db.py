"""
Standalone migration script — connects directly to PostgreSQL
without going through create_app() to avoid the chicken-and-egg problem.
"""
import os
import psycopg2
from dotenv import load_dotenv

load_dotenv()

db_url = os.environ.get('DATABASE_URL', 'postgresql://postgres:password@localhost:5432/signals_db')

conn = psycopg2.connect(db_url)
conn.autocommit = True
cur = conn.cursor()

migrations = [
    ("telegram_status", "ALTER TABLE confirmed_signals ADD COLUMN telegram_status VARCHAR(20) DEFAULT 'PENDING';"),
    ("telegram_retries", "ALTER TABLE confirmed_signals ADD COLUMN telegram_retries INTEGER DEFAULT 0;"),
    ("telegram_message_id", "ALTER TABLE confirmed_signals ADD COLUMN telegram_message_id VARCHAR(50);"),
]

for col_name, sql in migrations:
    try:
        cur.execute(sql)
        print(f"  ✅ Added column: {col_name}")
    except psycopg2.errors.DuplicateColumn:
        conn.rollback()
        print(f"  ⏭️  Column already exists: {col_name}")

cur.close()
conn.close()
print("\nDone! You can now run: python run.py")
