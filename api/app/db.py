"""
SQLite persistence layer for workspace metadata.

Thread safety: each thread gets its own sqlite3 connection via threading.local().
WAL mode + 5 s busy-timeout keep concurrent reads fast.
"""

import os
import sqlite3
import threading
from datetime import datetime, timezone

DB_PATH = os.getenv("DB_PATH", "/data/workspaces.db")

_local = threading.local()


def _conn() -> sqlite3.Connection:
    if not hasattr(_local, "conn"):
        # Ensure the parent directory exists.
        # os.path.dirname("filename") returns "" which would crash makedirs,
        # so we guard for that edge case.
        parent = os.path.dirname(DB_PATH)
        if parent:
            os.makedirs(parent, exist_ok=True)

        _local.conn = sqlite3.connect(DB_PATH)
        _local.conn.row_factory = sqlite3.Row
        _local.conn.execute("PRAGMA journal_mode=WAL")
        _local.conn.execute("PRAGMA busy_timeout=5000")
    return _local.conn


def init_db() -> None:
    c = _conn()
    c.execute("""
        CREATE TABLE IF NOT EXISTS workspaces (
            id            TEXT PRIMARY KEY,
            token         TEXT UNIQUE NOT NULL,
            user_id       TEXT NOT NULL,
            container_id  TEXT,
            status        TEXT NOT NULL DEFAULT 'running',
            deleted_at    TEXT,
            created_at    TEXT NOT NULL,
            last_active   TEXT NOT NULL,
            password_hash TEXT
        )
    """)

    # ── backward-compat migrations ──────────────────────────────────────────
    columns = {row[1] for row in c.execute("PRAGMA table_info(workspaces)").fetchall()}

    if "deleted_at" not in columns:
        c.execute("ALTER TABLE workspaces ADD COLUMN deleted_at TEXT")
    if "password_hash" not in columns:
        c.execute("ALTER TABLE workspaces ADD COLUMN password_hash TEXT")

    c.execute("CREATE INDEX IF NOT EXISTS idx_workspaces_status      ON workspaces(status)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_workspaces_last_active ON workspaces(last_active)")
    c.commit()


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── write ops ──────────────────────────────────────────────────────────────────

def add_workspace(vs_id: str, token: str, user_id: str, container_id: str, password_hash: str) -> None:
    now = _now()
    _conn().execute(
        "INSERT INTO workspaces "
        "(id, token, user_id, container_id, status, deleted_at, created_at, last_active, password_hash) "
        "VALUES (?, ?, ?, ?, 'running', NULL, ?, ?, ?)",
        (vs_id, token, user_id, container_id, now, now, password_hash),
    )
    _conn().commit()


def update_status(vs_id: str, status: str, container_id: str | None = None) -> None:
    if container_id:
        _conn().execute(
            "UPDATE workspaces SET status = ?, container_id = ? WHERE id = ?",
            (status, container_id, vs_id),
        )
    else:
        _conn().execute("UPDATE workspaces SET status = ? WHERE id = ?", (status, vs_id))
    _conn().commit()


def touch_active(vs_id: str) -> None:
    _conn().execute(
        "UPDATE workspaces SET last_active = ? WHERE id = ?", (_now(), vs_id)
    )
    _conn().commit()


def mark_deleted(vs_id: str) -> None:
    _conn().execute(
        "UPDATE workspaces SET status = 'deleted', deleted_at = ? WHERE id = ?",
        (_now(), vs_id),
    )
    _conn().commit()


def clear_deleted_mark(vs_id: str) -> None:
    _conn().execute("UPDATE workspaces SET deleted_at = NULL WHERE id = ?", (vs_id,))
    _conn().commit()


def purge_workspace(vs_id: str) -> None:
    _conn().execute("DELETE FROM workspaces WHERE id = ?", (vs_id,))
    _conn().commit()


# ── read ops ────────────────────────────────────────────────────────────────────

def get_workspace(vs_id: str) -> dict | None:
    row = _conn().execute(
        "SELECT * FROM workspaces WHERE id = ?", (vs_id,)
    ).fetchone()
    return dict(row) if row else None


def get_workspace_by_token(token: str) -> dict | None:
    row = _conn().execute(
        "SELECT * FROM workspaces WHERE token = ?", (token,)
    ).fetchone()
    return dict(row) if row else None


def list_workspaces() -> list[dict]:
    rows = _conn().execute(
        "SELECT * FROM workspaces ORDER BY created_at DESC"
    ).fetchall()
    return [dict(r) for r in rows]


def get_idle_workspaces(timeout_minutes: int) -> list[dict]:
    """
    Return running workspaces that have been inactive longer than
    timeout_minutes.  Uses SQL datetime comparison to avoid loading every
    row into Python.
    """
    rows = _conn().execute(
        """
        SELECT * FROM workspaces
        WHERE  status = 'running'
          AND  last_active <= datetime('now', ? || ' minutes')
        """,
        (f"-{timeout_minutes}",),
    ).fetchall()
    return [dict(r) for r in rows]
