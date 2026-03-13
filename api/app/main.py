import os
import secrets
import uuid
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException, Query

from . import db
from .docker_manager import (
    create_workspace,
    start_workspace,
    stop_workspace,
    remove_workspace,
    container_running,
)
from .idle_reaper import start_reaper, stop_reaper
from .schemas import WorkspaceCreate, WorkspaceOut

DOMAIN = os.getenv("DOMAIN", "localhost")
PORT_RANGE_START = 9000  # each workspace gets 9000 + n


def _next_port() -> int:
    """Pick the next free port from our range."""
    used = {w["port"] for w in db.list_workspaces() if w["port"]}
    port = PORT_RANGE_START
    while port in used:
        port += 1
    return port


def _vs_url(port: int) -> str:
    return f"http://{DOMAIN}:{port}/?folder=/home/coder/project"


def _to_out(vs: dict) -> dict:
    vs["url"] = _vs_url(vs["port"]) if vs.get("port") else None
    return vs


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    start_reaper()
    yield
    stop_reaper()


app = FastAPI(
    title="Cloud IDE Platform",
    version="1.0.0",
    lifespan=lifespan,
)


#Health check
@app.get("/health")
def health():
    return {"ok": True}


# Create Workspace
@app.post("/api/workspaces", response_model=WorkspaceOut, status_code=201)
def api_create(body: WorkspaceCreate):
    vs_id = uuid.uuid4().hex[:8]
    token = secrets.token_urlsafe(16)
    port = _next_port()

    cid = create_workspace(vs_id, token, port)
    db.add_workspace(vs_id, token, body.user_id, cid, port)

    vs = db.get_workspace(vs_id)
    return _to_out(vs)


# List Workspaces 
@app.get("/api/workspaces")
def api_list():
    rows = db.list_workspaces()
    for r in rows:
        r["url"] = _vs_url(r["port"]) if r.get("port") else None
        # live-check status
        if r["status"] == "running" and not container_running(r["id"]):
            r["status"] = "stopped"
            db.update_status(r["id"], "stopped")
    return rows


#  Get Single Workspace Details
@app.get("/api/workspaces/{vs_id}", response_model=WorkspaceOut)
def api_get(vs_id: str):
    vs = db.get_workspace(vs_id)
    if not vs:
        raise HTTPException(404, "workspace not found")
    return _to_out(vs)


#  Start (resume) Workspace 
@app.post("/api/workspaces/{vs_id}/start", response_model=WorkspaceOut)
def api_start(vs_id: str):
    vs = db.get_workspace(vs_id)
    if not vs:
        raise HTTPException(404, "workspace not found")
    cid = start_workspace(vs_id, vs["token"], vs["port"])
    db.update_status(vs_id, "running", cid)
    db.touch_active(vs_id)
    return _to_out(db.get_workspace(vs_id))


#  Stop Workspace 
@app.post("/api/workspaces/{vs_id}/stop", response_model=WorkspaceOut)
def api_stop(vs_id: str):
    vs = db.get_workspace(vs_id)
    if not vs:
        raise HTTPException(404, "workspace not found")
    stop_workspace(vs_id)
    db.update_status(vs_id, "stopped")
    return _to_out(db.get_workspace(vs_id))


#  Delete Workspace 
@app.delete("/api/workspaces/{vs_id}")
def api_delete(vs_id: str, purge: bool = Query(False)):
    vs = db.get_workspace(vs_id)
    if not vs:
        raise HTTPException(404, "workspace not found")
    remove_workspace(vs_id, purge_volume=purge)
    db.delete_workspace(vs_id)
    return {"deleted": vs_id, "volume_purged": purge}


#  Heartbeat (keeps workspace alive) 
@app.post("/api/workspaces/{vs_id}/heartbeat")
def api_heartbeat(vs_id: str):
    vs = db.get_workspace(vs_id)
    if not vs:
        raise HTTPException(404, "workspace not found")
    db.touch_active(vs_id)
    return {"ok": True}
