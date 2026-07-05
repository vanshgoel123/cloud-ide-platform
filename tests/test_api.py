import importlib
import os
import sys
import tempfile
import uuid
from contextlib import contextmanager
from pathlib import Path

from fastapi.testclient import TestClient


@contextmanager
def _build_client():
    api_root = Path(__file__).resolve().parents[1] / "api"
    if str(api_root) not in sys.path:
        sys.path.insert(0, str(api_root))

    db_file = Path(tempfile.gettempdir()) / f"cloudide-test-workspaces-{uuid.uuid4().hex}.db"
    os.environ["DB_PATH"] = str(db_file)

    db_mod = importlib.import_module("app.db")
    importlib.reload(db_mod)
    main_mod = importlib.import_module("app.main")
    main_mod = importlib.reload(main_mod)
    main_mod.start_reaper = lambda: None
    main_mod.stop_reaper = lambda: None
    main_mod.create_workspace = lambda _vs_id, _token, _port: f"fake-{_vs_id}"
    main_mod.start_workspace = lambda _vs_id, _token, _port: f"fake-{_vs_id}"
    main_mod.stop_workspace = lambda _vs_id: None
    main_mod.remove_workspace = lambda _vs_id, purge_volume=False: None
    main_mod.container_running = lambda _vs_id: True
    main_mod.pull_image = lambda: None
    with TestClient(main_mod.app) as client:
        yield client


def test_health():
    with _build_client() as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True
        assert resp.json()["db"] == "ok"


def test_list_workspaces_empty():
    with _build_client() as client:
        resp = client.get("/api/workspaces")
        assert resp.status_code == 200
        assert resp.json() == []


def test_create_workspace_returns_bootstrap_token_but_list_hides_it():
    with _build_client() as client:
        created = client.post("/api/workspaces", json={"user_id": "test-user"})
        assert created.status_code == 201
        assert "token" in created.json()

        listed = client.get("/api/workspaces")
        assert listed.status_code == 200
        assert listed.json()
        assert "token" not in listed.json()[0]


def test_get_workspace_not_found():
    with _build_client() as client:
        resp = client.get("/api/workspaces/does-not-exist")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "workspace not found"


def test_soft_delete_then_purge_workspace():
    with _build_client() as client:
        created = client.post("/api/workspaces", json={"user_id": "test-user"})
        assert created.status_code == 201
        workspace_id = created.json()["id"]

        deleted = client.delete(f"/api/workspaces/{workspace_id}")
        assert deleted.status_code == 200
        assert deleted.json()["status"] == "deleted"

        listed = client.get("/api/workspaces")
        assert any(item["id"] == workspace_id and item["status"] == "deleted" for item in listed.json())

        restore = client.post(f"/api/workspaces/{workspace_id}/start")
        assert restore.status_code == 200
        assert restore.json()["status"] == "running"

        repurged_delete = client.delete(f"/api/workspaces/{workspace_id}")
        assert repurged_delete.status_code == 200
        assert repurged_delete.json()["status"] == "deleted"

        purged = client.delete(f"/api/workspaces/{workspace_id}?purge=true")
        assert purged.status_code == 200
        assert purged.json()["volume_purged"] is True

        missing = client.get(f"/api/workspaces/{workspace_id}")
        assert missing.status_code == 404
