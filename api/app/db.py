import sqlite3
import os
import threading
from datetime import datetime, timezone

DB_PATH = os.getenv("DB_PATH", "/data/workspaces.db")

_local = threading.local()


def _conn() -> sqlite3.Connection:
    if not hasattr(_local, "conn"):
        os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
        _local.conn = sqlite3.connect(DB_PATH)
        _local.conn.row_factory = sqlite3.Row
    return _local.conn


def init_db():
    c = _conn()
    c.execute("""
        CREATE TABLE IF NOT EXISTS workspaces (
            id          TEXT PRIMARY KEY,
            token       TEXT UNIQUE NOT NULL,
            user_id     TEXT NOT NULL,
            container_id TEXT,
            port        INTEGER,
            status      TEXT DEFAULT 'running',
            created_at  TEXT NOT NULL,
            last_active TEXT NOT NULL
        )
    """)
    c.commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def add_workspace(vs_id: str, token: str, user_id: str, container_id: str, port: int):
    now = _now()
    _conn().execute(
        "INSERT INTO workspaces (id, token, user_id, container_id, port, status, created_at, last_active) "
        "VALUES (?, ?, ?, ?, ?, 'running', ?, ?)",
        (vs_id, token, user_id, container_id, port, now, now),
    )
    _conn().commit()


def get_workspace(vs_id: str) -> dict | None:
    row = _conn().execute("SELECT * FROM workspaces WHERE id = ?", (vs_id,)).fetchone()
    return dict(row) if row else None


def get_workspace_by_token(token: str) -> dict | None:
    row = _conn().execute("SELECT * FROM workspaces WHERE token = ?", (token,)).fetchone()
    return dict(row) if row else None


def list_workspaces() -> list[dict]:
    rows = _conn().execute("SELECT * FROM workspaces ORDER BY created_at DESC").fetchall()
    return [dict(r) for r in rows]


def update_status(vs_id: str, status: str, container_id: str | None = None):
    if container_id:
        _conn().execute(
            "UPDATE workspaces SET status = ?, container_id = ? WHERE id = ?",
            (status, container_id, vs_id),
        )
    else:
        _conn().execute("UPDATE workspaces SET status = ? WHERE id = ?", (status, vs_id))
    _conn().commit()


def touch_active(vs_id: str):
    _conn().execute("UPDATE workspaces SET last_active = ? WHERE id = ?", (_now(), vs_id))
    _conn().commit()


def delete_workspace(vs_id: str):
    _conn().execute("DELETE FROM workspaces WHERE id = ?", (vs_id,))
    _conn().commit()


def get_idle_workspaces(timeout_minutes: int) -> list[dict]:
    """Return running workspaces inactive longer than timeout_minutes."""
    rows = _conn().execute(
        "SELECT * FROM workspaces WHERE status = 'running'"
    ).fetchall()
    result = []
    now = datetime.now(timezone.utc)
    for r in rows:
        last = datetime.fromisoformat(r["last_active"])
        if (now - last).total_seconds() > timeout_minutes * 60:
            result.append(dict(r))
    return result
