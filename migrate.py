"""One-time migration: add session_id column to document_files."""
import os
import psycopg2
from dotenv import load_dotenv
from pathlib import Path

load_dotenv(Path(__file__).resolve().parent / ".env")
db_url = os.environ.get("DATABASE_URL")
if not db_url:
    print("ERROR: DATABASE_URL not set")
    raise SystemExit(1)

conn = psycopg2.connect(db_url)
cur = conn.cursor()

# Show current columns
cur.execute(
    "SELECT column_name FROM information_schema.columns WHERE table_name = 'document_files'"
)
cols = [r[0] for r in cur.fetchall()]
print("Current columns:", cols)

if "session_id" not in cols:
    cur.execute("ALTER TABLE document_files ADD COLUMN session_id TEXT")
    print("Added session_id column.")
else:
    print("session_id column already exists.")

# Drop old single-column unique constraint if it exists
cur.execute(
    "ALTER TABLE document_files DROP CONSTRAINT IF EXISTS document_files_filename_key"
)
print("Dropped old filename-only unique constraint (if existed).")

conn.commit()
cur.close()
conn.close()
print("Migration complete!")
