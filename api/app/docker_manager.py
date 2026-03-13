import docker
import os

client = docker.from_env()

VS_IMAGE = os.getenv("VS_IMAGE", "codercom/code-server:latest")
VS_CPU_LIMIT = float(os.getenv("VS_CPU_LIMIT", "0.5"))
VS_MEM_LIMIT = os.getenv("VS_MEM_LIMIT", "512m")
VS_PASSWORD = os.getenv("VS_PASSWORD", "devpass123")
NETWORK_NAME = os.getenv("DOCKER_NETWORK", "cloudide_net")


def _ensure_network():
    try:
        client.networks.get(NETWORK_NAME)
    except docker.errors.NotFound:
        client.networks.create(NETWORK_NAME, driver="bridge")


def _volume_name(vs_id: str) -> str:
    return f"vs_{vs_id}"


def create_workspace(vs_id: str, token: str, port: int) -> str:
    """Create and start a code-server container. Returns container ID."""
    _ensure_network()
    vol = _volume_name(vs_id)

    nano_cpus = int(VS_CPU_LIMIT * 1e9)

    container = client.containers.run(
        VS_IMAGE,
        detach=True,
        name=f"vs-{vs_id}",
        hostname=f"vs-{vs_id}",
        ports={"8080/tcp": ("0.0.0.0", port)},
        environment={
            "PASSWORD": VS_PASSWORD,
        },
        volumes={vol: {"bind": "/home/coder/project", "mode": "rw"}},
        nano_cpus=nano_cpus,
        mem_limit=VS_MEM_LIMIT,
        restart_policy={"Name": "unless-stopped"},
        labels={
            "cloudide.workspace": vs_id,
            "cloudide.token": token,
        },
        network=NETWORK_NAME,
    )
    container.exec_run("chown -R coder:coder /home/coder/project", user="root")
    return container.id


def start_workspace(vs_id: str, token: str, port: int) -> str:
    """Restart a stopped workspace."""
    name = f"vs-{vs_id}"
    try:
        c = client.containers.get(name)
        if c.status != "running":
            c.start()
        return c.id
    except docker.errors.NotFound:
        return create_workspace(vs_id, token, port)


def stop_workspace(vs_id: str):
    """Stop container but keep volume."""
    try:
        c = client.containers.get(f"vs-{vs_id}")
        c.stop(timeout=10)
    except docker.errors.NotFound:
        pass


def remove_workspace(vs_id: str, purge_volume: bool = False):
    """Remove container. Can remove volume too on user request."""
    name = f"vs-{vs_id}"
    try:
        c = client.containers.get(name)
        c.remove(force=True)
    except docker.errors.NotFound:
        pass
    if purge_volume:
        try:
            client.volumes.get(_volume_name(vs_id)).remove(force=True)
        except docker.errors.NotFound:
            pass


def container_running(vs_id: str) -> bool:
    try:
        c = client.containers.get(f"vs-{vs_id}")
        return c.status == "running"
    except docker.errors.NotFound:
        return False


def pull_image():
    """Pulling code server image."""
    print(f"Pulling {VS_IMAGE} ...")
    client.images.pull(VS_IMAGE)
    print("Image ready.")
