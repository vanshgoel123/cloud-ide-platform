"""
Docker lifecycle management for code-server workspaces.

Key design decisions:
- Containers are NOT port-mapped to the host.  Nginx proxies to them by
  name on the shared Docker network (cloudide_net) via /ws/{vs_id}/.
- Each workspace uses the user-supplied password so users control their
  own credentials and cannot log into each other's IDEs.
- ROOT_PATH env var tells code-server its public sub-path prefix so asset
  URLs are correct when served through /ws/{vs_id}/.
"""

import logging
import os

import docker
import docker.errors

logger = logging.getLogger("cloudide.docker")

VS_IMAGE = os.getenv("VS_IMAGE", "codercom/code-server:latest")
VS_CPU_LIMIT = float(os.getenv("VS_CPU_LIMIT", "0.5"))
VS_MEM_LIMIT = os.getenv("VS_MEM_LIMIT", "512m")
NETWORK_NAME = os.getenv("DOCKER_NETWORK", "cloudide_net")


class WorkspaceRuntimeError(RuntimeError):
    pass


# ── helpers ──────────────────────────────────────────────────────────────────


def _client() -> docker.DockerClient:
    return docker.from_env()


def _ensure_network() -> None:
    client = _client()
    try:
        client.networks.get(NETWORK_NAME)
    except docker.errors.NotFound:
        client.networks.create(NETWORK_NAME, driver="bridge")
        logger.info("created Docker network %s", NETWORK_NAME)


def _volume_name(vs_id: str) -> str:
    return f"vs_{vs_id}"


def _container_name(vs_id: str) -> str:
    return f"vs-{vs_id}"


# ── public API ────────────────────────────────────────────────────────────────


def create_workspace(vs_id: str, token: str, password: str) -> str:
    """
    Create and start a code-server container.

    - No host port binding — Nginx proxies by container name.
    - PASSWORD is the user-chosen password for this workspace.
    - ROOT_PATH tells code-server its public sub-path.

    Returns the container ID.
    """
    client = _client()
    _ensure_network()

    vol = _volume_name(vs_id)
    name = _container_name(vs_id)
    base_path = f"/ws/{vs_id}"
    nano_cpus = int(VS_CPU_LIMIT * 1e9)

    try:
        container = client.containers.run(
            VS_IMAGE,
            command=["--disable-telemetry"],
            detach=True,
            name=name,
            hostname=name,
            environment={
                "PASSWORD": password,  # user-chosen password
                "ROOT_PATH": base_path,  # public sub-path for asset URLs
            },
            volumes={
                vol: {"bind": "/home/coder/project", "mode": "rw"},
            },
            nano_cpus=nano_cpus,
            mem_limit=VS_MEM_LIMIT,
            restart_policy={"Name": "unless-stopped"},
            labels={
                "cloudide.workspace": vs_id,
                "cloudide.managed": "true",
            },
            network=NETWORK_NAME,
            init=True,
        )
        try:
            container.exec_run("chown -R coder:coder /home/coder/project", user="root")
        except Exception as exc:
            logger.warning("chown failed for workspace %s: %s", vs_id, exc)

        logger.info("created workspace container %s (id=%s)", name, container.short_id)
        return container.id

    except docker.errors.DockerException as exc:
        raise WorkspaceRuntimeError(f"failed to create workspace runtime: {exc}") from exc


def start_workspace(vs_id: str, token: str, password: str) -> str:
    """
    Restart a stopped workspace container.
    If the container no longer exists, recreate it with the stored password.
    Returns the container ID.
    """
    client = _client()
    name = _container_name(vs_id)
    try:
        c = client.containers.get(name)
        c.reload()
        if c.status != "running":
            c.start()
            logger.info("started existing container %s", name)
        return c.id
    except docker.errors.NotFound:
        logger.info("container %s not found, recreating", name)
        return create_workspace(vs_id, token, password)
    except docker.errors.DockerException as exc:
        raise WorkspaceRuntimeError(f"failed to start workspace runtime: {exc}") from exc


def stop_workspace(vs_id: str) -> None:
    """Stop a container but keep its volume (files are preserved)."""
    client = _client()
    name = _container_name(vs_id)
    try:
        c = client.containers.get(name)
        c.stop(timeout=10)
        logger.info("stopped container %s", name)
    except docker.errors.NotFound:
        logger.debug("stop_workspace: container %s not found (already stopped)", name)
    except docker.errors.DockerException as exc:
        raise WorkspaceRuntimeError(f"failed to stop workspace runtime: {exc}") from exc


def remove_workspace(vs_id: str, purge_volume: bool = False) -> None:
    """Remove the container and optionally its persistent volume."""
    client = _client()
    name = _container_name(vs_id)

    try:
        c = client.containers.get(name)
        c.remove(force=True)
        logger.info("removed container %s", name)
    except docker.errors.NotFound:
        pass
    except docker.errors.DockerException as exc:
        raise WorkspaceRuntimeError(f"failed to remove workspace runtime: {exc}") from exc

    if purge_volume:
        vol_name = _volume_name(vs_id)
        try:
            client.volumes.get(vol_name).remove(force=True)
            logger.info("purged volume %s", vol_name)
        except docker.errors.NotFound:
            pass
        except docker.errors.DockerException as exc:
            raise WorkspaceRuntimeError(f"failed to purge workspace volume: {exc}") from exc


def container_running(vs_id: str) -> bool:
    """Return True if the workspace container is currently running."""
    client = _client()
    try:
        c = client.containers.get(_container_name(vs_id))
        c.reload()
        return c.status == "running"
    except docker.errors.NotFound:
        return False
    except docker.errors.DockerException:
        return False


def pull_image() -> None:
    """Pull the code-server image so the first workspace create is fast."""
    client = _client()
    logger.info("pulling image %s …", VS_IMAGE)
    try:
        client.images.pull(VS_IMAGE)
        logger.info("image %s ready", VS_IMAGE)
    except docker.errors.DockerException as exc:
        raise WorkspaceRuntimeError(f"failed to pull image: {exc}") from exc
