import json
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from .config import DATABASE_PATH

_lock = threading.RLock()

def _conn():
    db = sqlite3.connect(DATABASE_PATH, check_same_thread=False)
    db.row_factory = sqlite3.Row
    db.execute("PRAGMA journal_mode=WAL")
    return db

def init_db():
    with _lock, _conn() as db:
        db.executescript("""
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS relays(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          name TEXT NOT NULL DEFAULT 'My relay',
          source_link TEXT NOT NULL,
          destination_link TEXT NOT NULL,
          enabled INTEGER NOT NULL DEFAULT 0,
          import_media INTEGER NOT NULL DEFAULT 1,
          last_source_id INTEGER NOT NULL DEFAULT 0,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS deliveries(
          id INTEGER PRIMARY KEY AUTOINCREMENT,
          relay_id INTEGER NOT NULL,
          source_chat_id TEXT,
          source_message_id INTEGER NOT NULL,
          destination_message_ids TEXT,
          kind TEXT NOT NULL,
          status TEXT NOT NULL,
          error TEXT,
          created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL,
          UNIQUE(relay_id, source_message_id)
        );
        CREATE INDEX IF NOT EXISTS deliveries_relay_status ON deliveries(relay_id,status);
        """)

def now():
    return datetime.now(timezone.utc).isoformat()

def set_setting(key, value):
    with _lock, _conn() as db:
        db.execute("INSERT INTO settings(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))

def get_setting(key, default=None):
    with _conn() as db:
        row = db.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
        return row["value"] if row else default

def list_relays():
    with _conn() as db:
        return [dict(r) for r in db.execute("SELECT * FROM relays ORDER BY id")]

def get_relay(relay_id):
    with _conn() as db:
        row = db.execute("SELECT * FROM relays WHERE id=?", (relay_id,)).fetchone()
        return dict(row) if row else None

def save_relay(data):
    stamp = now()
    with _lock, _conn() as db:
        if data.get("id"):
            db.execute("UPDATE relays SET name=?,source_link=?,destination_link=?,import_media=?,updated_at=? WHERE id=?",
                (data["name"], data["source_link"], data["destination_link"], int(data.get("import_media", True)), stamp, data["id"]))
            return int(data["id"])
        cur = db.execute("INSERT INTO relays(name,source_link,destination_link,import_media,created_at,updated_at) VALUES(?,?,?,?,?,?)",
            (data["name"], data["source_link"], data["destination_link"], int(data.get("import_media", True)), stamp, stamp))
        return cur.lastrowid

def set_enabled(relay_id, enabled):
    with _lock, _conn() as db:
        db.execute("UPDATE relays SET enabled=?,updated_at=? WHERE id=?", (int(enabled), now(), relay_id))

def set_checkpoint(relay_id, message_id):
    with _lock, _conn() as db:
        db.execute("UPDATE relays SET last_source_id=MAX(last_source_id,?),updated_at=? WHERE id=?", (message_id, now(), relay_id))

def delivery_exists(relay_id, source_message_id):
    with _conn() as db:
        row = db.execute("SELECT 1 FROM deliveries WHERE relay_id=? AND source_message_id=? AND status='delivered'", (relay_id, source_message_id)).fetchone()
        return bool(row)

def record_delivery(relay_id, source_chat_id, source_message_id, kind, status, destination_ids=None, error=None):
    stamp = now()
    ids = json.dumps(destination_ids or [])
    with _lock, _conn() as db:
        db.execute("""INSERT INTO deliveries(relay_id,source_chat_id,source_message_id,destination_message_ids,kind,status,error,created_at,updated_at)
        VALUES(?,?,?,?,?,?,?,?,?) ON CONFLICT(relay_id,source_message_id) DO UPDATE SET destination_message_ids=excluded.destination_message_ids,kind=excluded.kind,status=excluded.status,error=excluded.error,updated_at=excluded.updated_at""",
        (relay_id, str(source_chat_id or ""), source_message_id, ids, kind, status, error, stamp, stamp))

def recent_deliveries(limit=100):
    with _conn() as db:
        return [dict(r) for r in db.execute("SELECT d.*,r.name relay_name FROM deliveries d JOIN relays r ON r.id=d.relay_id ORDER BY d.updated_at DESC LIMIT ?", (limit,))]

def failed_deliveries(relay_id, limit=25):
    with _conn() as db:
        return [dict(r) for r in db.execute("SELECT * FROM deliveries WHERE relay_id=? AND status='failed' AND source_message_id>0 ORDER BY updated_at LIMIT ?", (relay_id, limit))]

def stats():
    with _conn() as db:
        rows = db.execute("SELECT status,COUNT(*) count FROM deliveries GROUP BY status").fetchall()
        out = {"delivered": 0, "failed": 0, "pending": 0}
        out.update({r["status"]: r["count"] for r in rows})
        return out

def cleanup_old_deliveries(retention_days=30):
    """Remove old activity details without touching relay checkpoints or credentials."""
    cutoff = (datetime.now(timezone.utc) - timedelta(days=retention_days)).isoformat()
    with _lock, _conn() as db:
        cursor = db.execute("DELETE FROM deliveries WHERE updated_at < ?", (cutoff,))
        removed = max(0, cursor.rowcount)
        db.execute("PRAGMA optimize")
        return removed
