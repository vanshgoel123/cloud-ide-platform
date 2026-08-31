"""
Cloud IDE Platform — FastAPI application entry point.

Routing design
──────────────
Workspaces no longer bind a host port.  Each code-server container lives
on the shared Docker network and is reachable from Nginx by its container
name (vs-{vs_id}) on port 8080.  The public URL is therefore:

    http(s)://{DOMAIN}/ws/{vs_id}/

This eliminates the port-range allocation, the port-leak race, and the
requirement to open a range of host ports.
"""

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

WORKSPACE_OPERATIONS_TOTAL = Counter(
    "cloudide_workspace_operations_total",
    "Workspace operations labelled by operation and outcome",
    ["operation", "outcome"],
)

logger = logging.getLogger("cloudide.api")
if not logger.handlers:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


# ── rate limiter ──────────────────────────────────────────────────────────────

class InMemoryRateLimiter:
    """Sliding-window per-key rate limiter (thread-safe)."""

    def __init__(self, limit: int, window_seconds: int) -> None:
        self.limit          = max(1, limit)
        self.window_seconds = max(1, window_seconds)
        self._lock: threading.Lock        = threading.Lock()
        self._bucket: dict[str, list[float]] = {}

    def allow(self, key: str) -> bool:
        now       = time.time()
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


# ── helpers ───────────────────────────────────────────────────────────────────

def _vs_url(vs_id: str) -> str:
    """
    Build the public URL for a workspace.
    Traffic goes through Nginx → /ws/{vs_id}/ → container:8080.
    No ports involved on the public side.
    """
    return f"http://{DOMAIN}/ws/{vs_id}/?folder=/home/coder/project"


def _to_out(vs: dict) -> WorkspacePublic:
    payload = dict(vs)
    payload["url"] = _vs_url(payload["id"]) if payload.get("status") != "deleted" else None
    payload.pop("token", None)
    return WorkspacePublic.model_validate(payload)


def _to_create_out(vs: dict) -> WorkspaceCreateOut:
    payload = dict(vs)
    payload["url"] = _vs_url(payload["id"])
    return WorkspaceCreateOut.model_validate(payload)


def _ensure_not_deleted(vs: dict) -> None:
    if vs.get("status") == "deleted":
        raise HTTPException(409, "workspace is deleted; restore it first")


def _track(op: str, success: bool) -> None:
    WORKSPACE_OPERATIONS_TOTAL.labels(
        operation=op, outcome="success" if success else "error"
    ).inc()


def _require_api_key(x_api_key: str | None = Header(default=None)) -> None:
    if not settings.api_key:
        return
    if x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="invalid API key")


def _client_ip(req: Request) -> str:
    forwarded = req.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return req.client.host if req.client else "unknown"


# ── lifespan ──────────────────────────────────────────────────────────────────

def _pull_image_background():
    """Pull the code-server image in a background thread so startup isn't blocked."""
    try:
        pull_image()
    except WorkspaceRuntimeError as exc:
        logger.warning("background image pre-pull failed: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    db.init_db()
    # Pull the image in background — don't block startup / health check
    threading.Thread(target=_pull_image_background, daemon=True, name="image-puller").start()
    start_reaper()
    yield
    stop_reaper()


# ── app ───────────────────────────────────────────────────────────────────────

app = FastAPI(
    title="Cloud IDE Platform",
    version="2.0.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        o.strip()
        for o in settings.cors_allow_origins.split(",")
        if o.strip()
    ],
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_logging_middleware(request: Request, call_next):
    start    = time.perf_counter()
    response = await call_next(request)
    elapsed  = (time.perf_counter() - start) * 1000
    logger.info(
        "path=%s method=%s status=%s %.2fms",
        request.url.path, request.method, response.status_code, elapsed,
    )
    return response


@app.exception_handler(WorkspaceRuntimeError)
def runtime_error_handler(_request: Request, exc: WorkspaceRuntimeError):
    return PlainTextResponse(str(exc), status_code=503)


# ── endpoints ─────────────────────────────────────────────────────────────────

@app.get("/health", tags=["ops"])
def health():
    """Liveness check. Returns 200 when the API is up and the DB is reachable."""
    # Ping the DB
    db._conn().execute("SELECT 1")
    return {"ok": True, "db": "ok"}


@app.get("/metrics", tags=["ops"])
def metrics():
    """Prometheus metrics endpoint."""
    return PlainTextResponse(generate_latest(), media_type=CONTENT_TYPE_LATEST)


# ── workspaces ────────────────────────────────────────────────────────────────

@app.post(
    "/api/workspaces",
    response_model=WorkspaceCreateOut,
    status_code=201,
    tags=["workspaces"],
    summary="Create a new workspace",
)
def api_create(
    body: WorkspaceCreate,
    request: Request,
    _auth: None = Depends(_require_api_key),
):
    key = _client_ip(request)
    if not create_rate_limiter.allow(key):
        _track("create", False)
        raise HTTPException(429, "rate limit exceeded — try again shortly")

    vs_id = uuid.uuid4().hex[:8]
    token = secrets.token_urlsafe(16)

    # Hash the user's password before storing (never store plaintext)
    import hashlib
    password_hash = hashlib.sha256(body.password.encode()).hexdigest()

    # create_workspace raises WorkspaceRuntimeError on failure.
    cid = create_workspace(vs_id, token, body.password)

    # Only write to DB after the container is successfully created.
    db.add_workspace(vs_id, token, body.user_id, cid, password_hash)
    _track("create", True)

    vs = db.get_workspace(vs_id)
    return _to_create_out(vs)


@app.get(
    "/api/workspaces",
    response_model=list[WorkspacePublic],
    tags=["workspaces"],
    summary="List all workspaces",
)
def api_list():
    rows = db.list_workspaces()
    out: list[WorkspacePublic] = []
    for r in rows:
        # Reconcile DB state with actual Docker state
        if r["status"] == "running" and not container_running(r["id"]):
            r["status"] = "stopped"
            db.update_status(r["id"], "stopped")
        out.append(_to_out(r))
    return out


@app.get(
    "/api/workspaces/{vs_id}",
    response_model=WorkspacePublic,
    tags=["workspaces"],
    summary="Get a single workspace",
)
def api_get(vs_id: str):
    vs = db.get_workspace(vs_id)
    if not vs:
        raise HTTPException(404, "workspace not found")
    return _to_out(vs)


@app.post(
    "/api/workspaces/{vs_id}/start",
    response_model=WorkspacePublic,
    tags=["workspaces"],
    summary="Start (or restore) a workspace",
)
def api_start(vs_id: str, _auth: None = Depends(_require_api_key)):
    vs = db.get_workspace(vs_id)
    if not vs:
        raise HTTPException(404, "workspace not found")

    # start_workspace uses the stored token + password
    cid = start_workspace(vs_id, vs["token"], vs.get("password_hash", ""))
    db.update_status(vs_id, "running", cid)
    db.clear_deleted_mark(vs_id)
    db.touch_active(vs_id)
    _track("start", True)
    return _to_out(db.get_workspace(vs_id))


@app.post(
    "/api/workspaces/{vs_id}/stop",
    response_model=WorkspacePublic,
    tags=["workspaces"],
    summary="Stop a running workspace",
)
def api_stop(vs_id: str, _auth: None = Depends(_require_api_key)):
    vs = db.get_workspace(vs_id)
    if not vs:
        raise HTTPException(404, "workspace not found")
    _ensure_not_deleted(vs)

    stop_workspace(vs_id)
    db.update_status(vs_id, "stopped")
    _track("stop", True)
    return _to_out(db.get_workspace(vs_id))


@app.delete(
    "/api/workspaces/{vs_id}",
    tags=["workspaces"],
    summary="Delete or purge a workspace",
)
def api_delete(
    vs_id: str,
    purge: bool = Query(False, description="If true, also removes the persistent volume"),
    _auth: None = Depends(_require_api_key),
):
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


@app.post(
    "/api/workspaces/{vs_id}/heartbeat",
    tags=["workspaces"],
    summary="Keep a workspace alive (reset idle timer)",
)
def api_heartbeat(vs_id: str, _auth: None = Depends(_require_api_key)):
    vs = db.get_workspace(vs_id)
    if not vs:
        raise HTTPException(404, "workspace not found")
    _ensure_not_deleted(vs)

    db.touch_active(vs_id)
    _track("heartbeat", True)
    return {"ok": True, "vs_id": vs_id}
