import importlib
import os
import sys
import tempfile
from contextlib import contextmanager
from pathlib import Path

from fastapi.testclient import TestClient


@contextmanager
def _build_client():
    api_root = Path(__file__).resolve().parents[1] / "api"
    if str(api_root) not in sys.path:
        sys.path.insert(0, str(api_root))

    db_file = Path(tempfile.gettempdir()) / "cloudide-test-workspaces.db"
    os.environ["DB_PATH"] = str(db_file)

    main_mod = importlib.import_module("app.main")
    main_mod.start_reaper = lambda: None
    main_mod.stop_reaper = lambda: None
    with TestClient(main_mod.app) as client:
        yield client


def test_health():
    with _build_client() as client:
        resp = client.get("/health")
        assert resp.status_code == 200
        assert resp.json() == {"ok": True}


def test_list_workspaces_empty():
    with _build_client() as client:
        resp = client.get("/api/workspaces")
        assert resp.status_code == 200
        assert resp.json() == []


def test_get_workspace_not_found():
    with _build_client() as client:
        resp = client.get("/api/workspaces/does-not-exist")
        assert resp.status_code == 404
        assert resp.json()["detail"] == "workspace not found"
