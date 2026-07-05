import secrets
import threading
import time
import uuid
import logging
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from prometheus_client import CONTENT_TYPE_LATEST, Counter, generate_latest

from . import db
from .config import settings
from .docker_manager import (
    WorkspaceRuntimeError,
    pull_image,
    create_workspace,
    start_workspace,
    stop_workspace,
    remove_workspace,
    container_running,
)
from .idle_reaper import start_reaper, stop_reaper
from .schemas import WorkspaceCreate, WorkspaceCreateOut, WorkspacePublic

DOMAIN = settings.domain
PORT_RANGE_START = settings.port_range_start  # each workspace gets 9000 + n
PORT_ALLOC_LOCK = threading.Lock()

WORKSPACE_OPERATIONS_TOTAL = Counter(
    "cloudide_workspace_operations_total",
    "Workspace operations labeled by operation and outcome",
    ["operation", "outcome"],
)

logger = logging.getLogger("cloudide.api")
if not logger.handlers:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


class InMemoryRateLimiter:
    def __init__(self, limit: int, window_seconds: int):
        self.limit = max(1, limit)
        self.window_seconds = max(1, window_seconds)
        self._lock = threading.Lock()
        self._bucket: dict[str, list[float]] = {}

    def allow(self, key: str) -> bool:
        now = time.time()
        threshold = now - self.window_seconds
        with self._lock:
            hits = [ts for ts in self._bucket.get(key, []) if ts > threshold]
            if len(hits) >= self.limit:
                self._bucket[key] = hits
                return False
            hits.append(now)
            self._bucket[key] = hits
            return True


create_rate_limiter = InMemoryRateLimiter(
    settings.rate_limit_create_per_window,
    settings.rate_limit_window_sec,
)


def _next_port() -> int:
    """Pick the next free port from our range."""
    used = {w["port"] for w in db.list_workspaces() if w["port"]}
    port = PORT_RANGE_START
    while port in used:
        port += 1
    return port


def _vs_url(port: int) -> str:
    return f"http://{DOMAIN}:{port}/?folder=/home/coder/project"


def _to_out(vs: dict) -> WorkspacePublic:
    payload = dict(vs)
    payload["url"] = _vs_url(payload["port"]) if payload.get("port") else None
    payload.pop("token", None)
    return WorkspacePublic.model_validate(payload)


def _to_create_out(vs: dict) -> WorkspaceCreateOut:
    payload = dict(vs)
    payload["url"] = _vs_url(payload["port"]) if payload.get("port") else None
    return WorkspaceCreateOut.model_validate(payload)


def _ensure_not_deleted(vs: dict):
    if vs.get("status") == "deleted":
        raise HTTPException(409, "workspace is in deleted section; restore it before using it")


def _track(op: str, success: bool):
    WORKSPACE_OPERATIONS_TOTAL.labels(operation=op, outcome="success" if success else "error").inc()


def _require_api_key(x_api_key: str | None = Header(default=None)):
    if not settings.api_key:
        return
    if x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="invalid API key")


def _client_ip(req: Request) -> str:
    forwarded = req.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return req.client.host if req.client else "unknown"


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    try:
        pull_image()
    except WorkspaceRuntimeError:
        # Keep API bootable even when the runtime image cannot be pulled on startup.
        pass
    start_reaper()
    yield
    stop_reaper()


app = FastAPI(
    title="Cloud IDE Platform",
    version="1.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_allow_origins.split(",") if origin.strip()],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    start = time.perf_counter()
    response = await call_next(request)
    elapsed_ms = (time.perf_counter() - start) * 1000
    logger.info("request path=%s method=%s status=%s duration_ms=%.2f", request.url.path, request.method, response.status_code, elapsed_ms)
    return response


@app.exception_handler(WorkspaceRuntimeError)
def runtime_error_handler(_request: Request, exc: WorkspaceRuntimeError):
    return PlainTextResponse(str(exc), status_code=503)


#Health check
@app.get("/health")
def health():
    return {
        "ok": True,
        "db": "ok",
    }


@app.get("/metrics")
def metrics():
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


# Create Workspace
@app.post("/api/workspaces", response_model=WorkspaceCreateOut, status_code=201)
def api_create(body: WorkspaceCreate, request: Request, _auth: None = Depends(_require_api_key)):
    key = _client_ip(request)
    if not create_rate_limiter.allow(key):
        _track("create", False)
        raise HTTPException(429, "rate limit exceeded for workspace creation")

    vs_id = uuid.uuid4().hex[:8]
    token = secrets.token_urlsafe(16)
    with PORT_ALLOC_LOCK:
        port = _next_port()

    cid = create_workspace(vs_id, token, port)
    db.add_workspace(vs_id, token, body.user_id, cid, port)
    _track("create", True)

    vs = db.get_workspace(vs_id)
    return _to_create_out(vs)


# List Workspaces 
@app.get("/api/workspaces")
def api_list():
    rows = db.list_workspaces()
    out: list[WorkspacePublic] = []
    for r in rows:
        # live-check status
        if r["status"] == "running" and not container_running(r["id"]):
            r["status"] = "stopped"
            db.update_status(r["id"], "stopped")
        out.append(_to_out(r))
    return out


#  Get Single Workspace Details
@app.get("/api/workspaces/{vs_id}", response_model=WorkspacePublic)
def api_get(vs_id: str):
    vs = db.get_workspace(vs_id)
    if not vs:
        raise HTTPException(404, "workspace not found")
    return _to_out(vs)


#  Start (resume) Workspace 
@app.post("/api/workspaces/{vs_id}/start", response_model=WorkspacePublic)
def api_start(vs_id: str, _auth: None = Depends(_require_api_key)):
    vs = db.get_workspace(vs_id)
    if not vs:
        raise HTTPException(404, "workspace not found")
    cid = start_workspace(vs_id, vs["token"], vs["port"])
    db.update_status(vs_id, "running", cid)
    db.clear_deleted_mark(vs_id)
    db.touch_active(vs_id)
    _track("start", True)
    return _to_out(db.get_workspace(vs_id))


#  Stop Workspace 
@app.post("/api/workspaces/{vs_id}/stop", response_model=WorkspacePublic)
def api_stop(vs_id: str, _auth: None = Depends(_require_api_key)):
    vs = db.get_workspace(vs_id)
    if not vs:
        raise HTTPException(404, "workspace not found")
    _ensure_not_deleted(vs)
    stop_workspace(vs_id)
    db.update_status(vs_id, "stopped")
    _track("stop", True)
    return _to_out(db.get_workspace(vs_id))


#  Delete Workspace 
@app.delete("/api/workspaces/{vs_id}")
def api_delete(vs_id: str, purge: bool = Query(False), _auth: None = Depends(_require_api_key)):
    vs = db.get_workspace(vs_id)
    if not vs:
        raise HTTPException(404, "workspace not found")
    remove_workspace(vs_id, purge_volume=purge)
    if purge:
        db.purge_workspace(vs_id)
        _track("purge", True)
        return {"deleted": vs_id, "volume_purged": True}

    db.mark_deleted(vs_id)
    _track("delete", True)
    return {"deleted": vs_id, "volume_purged": False, "status": "deleted"}


#  Heartbeat (keeps workspace alive) 
@app.post("/api/workspaces/{vs_id}/heartbeat")
def api_heartbeat(vs_id: str, _auth: None = Depends(_require_api_key)):
    vs = db.get_workspace(vs_id)
    if not vs:
        raise HTTPException(404, "workspace not found")
    _ensure_not_deleted(vs)
    db.touch_active(vs_id)
    _track("heartbeat", True)
    return {"ok": True}
