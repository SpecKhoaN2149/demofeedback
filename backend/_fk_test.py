import sqlite3, os, tempfile

db = os.path.join(os.path.dirname(__file__), "_fk_probe.db")
if os.path.exists(db): os.remove(db)
conn = sqlite3.connect(db)
conn.execute("PRAGMA foreign_keys=ON")
conn.execute("""
CREATE TABLE tickets (
    id TEXT PRIMARY KEY,
    submission_id TEXT NOT NULL,
    issue_category TEXT, description TEXT, priority TEXT, status TEXT, created_at TEXT
)
""")
conn.commit()

try:
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS tickets (
        ticket_id TEXT PRIMARY KEY, issue_category TEXT NOT NULL, description TEXT NOT NULL,
        priority TEXT NOT NULL DEFAULT 'high', status TEXT NOT NULL DEFAULT 'open', created_at TEXT NOT NULL
    );
    CREATE TABLE IF NOT EXISTS feedback (
        feedback_id TEXT PRIMARY KEY, text TEXT NOT NULL, created_at TEXT NOT NULL,
        needs_review INTEGER NOT NULL DEFAULT 0, ticket_id TEXT REFERENCES tickets(ticket_id)
    );
    """)
    print("schema creation OK")
except Exception as e:
    print("schema creation ERROR:", repr(e))

try:
    conn.execute("INSERT INTO feedback (feedback_id, text, created_at, needs_review, ticket_id) VALUES ('f1','t','2020',0,NULL)")
    conn.commit()
    print("insert feedback NULL ticket OK")
except Exception as e:
    print("insert NULL ticket ERROR:", repr(e))

try:
    conn.execute("INSERT INTO feedback (feedback_id, text, created_at, needs_review, ticket_id) VALUES ('f2','t','2020',0,'tk1')")
    conn.commit()
    print("insert feedback with ticket_id OK")
except Exception as e:
    print("insert with ticket_id ERROR:", repr(e))

cols = [r[1] for r in conn.execute("PRAGMA table_info(tickets)").fetchall()]
print("tickets columns:", cols)
conn.close()
os.remove(db)
