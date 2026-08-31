"""
Cloud IDE — API integration tests.

Uses FastAPI's TestClient with all Docker/scheduler calls stubbed out
so tests run in any environment with no Docker daemon required.

Design:
  - A single app instance is created per process (module-level fixture).
  - Each test gets a fresh SQLite DB via a function-scoped fixture.
  - Docker / scheduler side-effects are patched at the app.main level.
"""
import os
import sys
import tempfile
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# ── path setup ────────────────────────────────────────────────────────────────
API_ROOT = Path(__file__).resolve().parents[1] / "api"
if str(API_ROOT) not in sys.path:
    sys.path.insert(0, str(API_ROOT))

# ── import app modules (docker stub is already in sys.modules via conftest) ───
import app.db as db_mod
from app.main import app
import app.main as main_mod

# ── stub out all Docker / scheduler side-effects ─────────────────────────────
main_mod.start_reaper      = lambda: None
main_mod.stop_reaper       = lambda: None
main_mod.pull_image        = lambda: None
main_mod.create_workspace  = lambda vs_id, token, password: f"fake-cid-{vs_id}"
main_mod.start_workspace   = lambda vs_id, token, password: f"fake-cid-{vs_id}"
main_mod.stop_workspace    = lambda vs_id: None
main_mod.remove_workspace  = lambda vs_id, purge_volume=False: None
main_mod.container_running = lambda vs_id: True

# ── helpers ───────────────────────────────────────────────────────────────────
VALID_PAYLOAD = {"user_id": "test-user", "password": "secret123"}


@pytest.fixture()
def client(tmp_path):
    """Each test gets a fresh SQLite database."""
    db_file = tmp_path / f"test-{uuid.uuid4().hex}.db"
    os.environ["DB_PATH"] = str(db_file)
    db_mod.DB_PATH = str(db_file)
    # Reset the thread-local connection so a new one opens against the new DB
    if hasattr(db_mod._local, "conn"):
        try:
            db_mod._local.conn.close()
        except Exception:
            pass
        del db_mod._local.conn

    with TestClient(app) as c:
        yield c


# ── tests ─────────────────────────────────────────────────────────────────────

def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["db"] == "ok"


def test_list_workspaces_empty(client):
    r = client.get("/api/workspaces")
    assert r.status_code == 200
    assert r.json() == []


def test_create_workspace_returns_token_list_hides_it(client):
    r = client.post("/api/workspaces", json=VALID_PAYLOAD)
    assert r.status_code == 201
    body = r.json()
    assert "token" in body
    assert body["user_id"] == "test-user"
    assert body["status"] == "running"
    assert body["url"] is not None

    listed = client.get("/api/workspaces")
    assert listed.status_code == 200
    assert len(listed.json()) == 1
    assert "token" not in listed.json()[0]


def test_create_workspace_requires_password(client):
    r = client.post("/api/workspaces", json={"user_id": "test-user"})
    assert r.status_code == 422


def test_create_workspace_password_min_length(client):
    r = client.post("/api/workspaces", json={"user_id": "test-user", "password": "abc"})
    assert r.status_code == 422


def test_create_workspace_invalid_user_id(client):
    r = client.post("/api/workspaces", json={"user_id": "bad name!", "password": "secret123"})
    assert r.status_code == 422


def test_get_workspace_not_found(client):
    r = client.get("/api/workspaces/does-not-exist")
    assert r.status_code == 404
    assert r.json()["detail"] == "workspace not found"


def test_stop_and_start_workspace(client):
    ws_id = client.post("/api/workspaces", json=VALID_PAYLOAD).json()["id"]

    stopped = client.post(f"/api/workspaces/{ws_id}/stop")
    assert stopped.status_code == 200
    assert stopped.json()["status"] == "stopped"

    started = client.post(f"/api/workspaces/{ws_id}/start")
    assert started.status_code == 200
    assert started.json()["status"] == "running"


def test_heartbeat(client):
    ws_id = client.post("/api/workspaces", json=VALID_PAYLOAD).json()["id"]
    r = client.post(f"/api/workspaces/{ws_id}/heartbeat")
    assert r.status_code == 200
    assert r.json()["ok"] is True


def test_heartbeat_deleted_workspace_rejected(client):
    ws_id = client.post("/api/workspaces", json=VALID_PAYLOAD).json()["id"]
    client.delete(f"/api/workspaces/{ws_id}")
    r = client.post(f"/api/workspaces/{ws_id}/heartbeat")
    assert r.status_code == 409


def test_full_lifecycle_soft_delete_restore_purge(client):
    ws_id = client.post("/api/workspaces", json=VALID_PAYLOAD).json()["id"]

    # Stop
    assert client.post(f"/api/workspaces/{ws_id}/stop").json()["status"] == "stopped"

    # Soft delete
    deleted = client.delete(f"/api/workspaces/{ws_id}")
    assert deleted.status_code == 200
    assert deleted.json()["status"] == "deleted"
    assert deleted.json()["volume_purged"] is False

    # Visible in list as deleted
    items = client.get("/api/workspaces").json()
    assert any(w["id"] == ws_id and w["status"] == "deleted" for w in items)

    # Restore via start
    restored = client.post(f"/api/workspaces/{ws_id}/start")
    assert restored.status_code == 200
    assert restored.json()["status"] == "running"

    # Delete again then hard-purge
    client.delete(f"/api/workspaces/{ws_id}")
    purged = client.delete(f"/api/workspaces/{ws_id}?purge=true")
    assert purged.status_code == 200
    assert purged.json()["volume_purged"] is True

    # Row must be gone
    assert client.get(f"/api/workspaces/{ws_id}").status_code == 404


def test_stop_deleted_workspace_rejected(client):
    ws_id = client.post("/api/workspaces", json=VALID_PAYLOAD).json()["id"]
    client.delete(f"/api/workspaces/{ws_id}")
    r = client.post(f"/api/workspaces/{ws_id}/stop")
    assert r.status_code == 409
