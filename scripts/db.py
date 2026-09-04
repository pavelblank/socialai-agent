"""SocialAI - shared SQLite memory. Used by make_video.py, dashboard.py, and later run_daily/run_weekly."""
import sqlite3, time
from pathlib import Path

DB = Path(__file__).resolve().parents[1] / "data" / "brain.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS runs (
  id         INTEGER PRIMARY KEY AUTOINCREMENT,
  topic      TEXT NOT NULL,
  kind       TEXT DEFAULT 'video',   -- video | image | text
  started    REAL NOT NULL,
  finished   REAL,
  status     TEXT NOT NULL DEFAULT 'running',   -- running | ok | failed
  stage      TEXT,                              -- current step, for live view
  scenes     INTEGER,
  seconds    REAL,                              -- video length
  build_secs REAL,                              -- how long it took to build
  size_kb    INTEGER,
  path       TEXT,
  error      TEXT,
  approval   TEXT DEFAULT 'pending',   -- pending | approved | rejected | auto
  approved_at REAL,
  published  INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS posts (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  run_id    INTEGER,
  platform  TEXT,
  posted    REAL,
  remote_id TEXT,
  url       TEXT,
  status    TEXT,
  views_48h INTEGER,
  score     TEXT,
  category  TEXT
);
CREATE TABLE IF NOT EXISTS topics_used (
  topic TEXT PRIMARY KEY, first_used REAL, times INTEGER DEFAULT 1
);
"""

def conn():
    DB.parent.mkdir(parents=True, exist_ok=True)
    c = sqlite3.connect(DB, timeout=20)
    c.row_factory = sqlite3.Row
    c.executescript(SCHEMA)
    cols = [r[1] for r in c.execute("PRAGMA table_info(runs)")]
    if "kind" not in cols:                       # migrate older databases
        c.execute("ALTER TABLE runs ADD COLUMN kind TEXT DEFAULT 'video'")
        c.execute("UPDATE runs SET kind='image' WHERE topic LIKE '[image]%'")
        c.execute("UPDATE runs SET kind='text'  WHERE topic LIKE '[text]%'")
        c.commit()
    for col, ddl in (("approval", "TEXT DEFAULT 'pending'"),
                     ("approved_at", "REAL"),
                     ("published", "INTEGER DEFAULT 0")):
        if col not in cols:
            c.execute("ALTER TABLE runs ADD COLUMN " + col + " " + ddl)
            c.commit()
    pcols = [r[1] for r in c.execute("PRAGMA table_info(posts)")]
    if "category" not in pcols:                     # migrate older databases
        c.execute("ALTER TABLE posts ADD COLUMN category TEXT")
        c.commit()
    return c

def start_run(topic, kind="video"):
    with conn() as c:
        cur = c.execute("INSERT INTO runs(topic,kind,started,status,stage) VALUES(?,?,?,'running','starting')",
                        (topic, kind, time.time()))
        return cur.lastrowid

def set_stage(run_id, stage):
    with conn() as c:
        c.execute("UPDATE runs SET stage=? WHERE id=?", (stage, run_id))

def finish_run(run_id, **kw):
    if not run_id: return
    kw["finished"] = time.time()
    cols = ",".join(f"{k}=?" for k in kw)
    with conn() as c:
        c.execute(f"UPDATE runs SET {cols} WHERE id=?", (*kw.values(), run_id))

def note_topic(topic):
    with conn() as c:
        c.execute("""INSERT INTO topics_used(topic,first_used) VALUES(?,?)
                     ON CONFLICT(topic) DO UPDATE SET times=times+1""", (topic, time.time()))

def topic_seen(topic):
    with conn() as c:
        return c.execute("SELECT 1 FROM topics_used WHERE topic=?", (topic,)).fetchone() is not None


def set_approval(run_id, decision):
    """decision: approved | rejected | pending"""
    with conn() as c:
        c.execute("UPDATE runs SET approval=?, approved_at=? WHERE id=?",
                  (decision, time.time(), run_id))

def mark_published(run_id):
    with conn() as c:
        c.execute("UPDATE runs SET published=1 WHERE id=?", (run_id,))

def pending_approvals():
    with conn() as c:
        return c.execute(
            "SELECT * FROM runs WHERE status='ok' AND approval='pending' AND published=0 "
            "ORDER BY id DESC").fetchall()

def approved_unpublished():
    with conn() as c:
        return c.execute(
            "SELECT * FROM runs WHERE status='ok' AND approval IN ('approved','auto') "
            "AND published=0 ORDER BY id ASC").fetchall()


def total_published():
    """Count of distinct content pieces actually published (not per-platform sends) -
    what growth-vs-steady schedule phase reads to decide when to slow down."""
    with conn() as c:
        return c.execute("SELECT COUNT(*) n FROM runs WHERE published=1").fetchone()["n"]


def schedule_phase(R):
    """'growth' (daily, ramping up while the channel is new) until growth_threshold
    published posts are reached, then 'steady' (the light weekly cadence) forever
    after - the intent: post as much as safely possible early on,
    then ease off once there's a real track record."""
    threshold = R.get("growth_threshold", 50)
    return "growth" if total_published() < threshold else "steady"


def active_schedule(R):
    phase = schedule_phase(R)
    key = "schedule_growth" if phase == "growth" else "schedule_steady"
    return R.get(key, []) or R.get("schedule", [])   # legacy fallback for old configs
