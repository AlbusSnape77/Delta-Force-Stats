"""SQLite storage for player profiles. One row per player (keyed by nickname),
holding the latest OCR snapshot plus user-added tags/notes."""
import os
import json
import sqlite3
from datetime import datetime, timezone

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "players.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS players (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  nickname TEXT NOT NULL UNIQUE,
  tags TEXT NOT NULL DEFAULT '[]',
  note TEXT,
  data TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);
"""


def _now():
    return datetime.now(timezone.utc).isoformat()


def connect(db_path=None):
    path = db_path or DB_PATH
    os.makedirs(os.path.dirname(path), exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    return conn


def _row_to_player(row):
    return {
        "id": row["id"],
        "nickname": row["nickname"],
        "tags": json.loads(row["tags"] or "[]"),
        "note": row["note"],
        "data": json.loads(row["data"] or "{}"),
        "created_at": row["created_at"],
        "updated_at": row["updated_at"],
    }


def upsert_snapshot(conn, nickname, data):
    """Insert or update a player's snapshot. Existing tags/note are preserved;
    each provided data section (overview/ranked/recent/home) overwrites the old one."""
    now = _now()
    row = conn.execute("SELECT * FROM players WHERE nickname = ?", (nickname,)).fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO players (nickname, tags, note, data, created_at, updated_at) VALUES (?,?,?,?,?,?)",
            (nickname, "[]", None, json.dumps(data, ensure_ascii=False), now, now),
        )
    else:
        merged = json.loads(row["data"] or "{}")
        merged.update(data)
        conn.execute(
            "UPDATE players SET data = ?, updated_at = ? WHERE id = ?",
            (json.dumps(merged, ensure_ascii=False), now, row["id"]),
        )
    conn.commit()
    return get_by_nickname(conn, nickname)


def get_by_nickname(conn, nickname):
    row = conn.execute("SELECT * FROM players WHERE nickname = ?", (nickname,)).fetchone()
    return _row_to_player(row) if row else None


def get_by_id(conn, pid):
    row = conn.execute("SELECT * FROM players WHERE id = ?", (pid,)).fetchone()
    return _row_to_player(row) if row else None


def search(conn, query):
    q = (query or "").strip()
    if q == "":
        rows = conn.execute("SELECT * FROM players ORDER BY updated_at DESC").fetchall()
    else:
        like = f"%{q}%"
        rows = conn.execute(
            "SELECT * FROM players WHERE nickname LIKE ? OR tags LIKE ? OR note LIKE ? ORDER BY updated_at DESC",
            (like, like, like),
        ).fetchall()
    return [_row_to_player(r) for r in rows]


def update_player(conn, pid, *, nickname=None, tags=None, note=None, data=None):
    row = conn.execute("SELECT * FROM players WHERE id = ?", (pid,)).fetchone()
    if row is None:
        return None
    new_nick = nickname if nickname is not None else row["nickname"]
    new_tags = json.dumps(tags, ensure_ascii=False) if tags is not None else row["tags"]
    new_note = note if note is not None else row["note"]
    new_data = json.dumps(data, ensure_ascii=False) if data is not None else row["data"]
    conn.execute(
        "UPDATE players SET nickname=?, tags=?, note=?, data=?, updated_at=? WHERE id=?",
        (new_nick, new_tags, new_note, new_data, _now(), pid),
    )
    conn.commit()
    return get_by_id(conn, pid)


def delete_player(conn, pid):
    cur = conn.execute("DELETE FROM players WHERE id = ?", (pid,))
    conn.commit()
    return cur.rowcount > 0
