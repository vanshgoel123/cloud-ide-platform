# ☁️ Cloud IDE Platform
> On-demand VS Code environments in the browser — each user gets an isolated, persistent workspace.
## Architecture

This project has two main parts:

- The API service keeps track of workspaces, creates containers, and stores workspace details in SQLite.
- Each user workspace runs as its own `code-server` container, so files stay isolated per user.

How a request flows:

1. A user sends a request to the FastAPI service.
2. The API creates or manages a workspace container through Docker.
3. That workspace gets its own volume, port, and password.
4. The API returns the URL, and the user opens VS Code in the browser.

There is also a small background reaper inside the API service. It checks for inactive workspaces and stops them after the idle timeout, but it does not delete the saved files.

---

## Prerequisites

- **Docker**
- **Docker Compose**
- Ports **8000** (API) and **9000–9099** (workspaces) available

---

## Quick Start 

```bash
# 1. Clone
git clone https://github.com/vanshgoel123/cloud-ide-platform.git

# 2. Copy env file
cp .env.example .env

# 3. Launch
docker compose up -d --build

# 4. First it will automatically pull code-server image (first time only)

# 5. Verify (is it running?)
curl http://localhost:8000/health
# {"ok": true}
```

---

## API Usage

- API Endpoints:
    - POST   /api/workspaces           → create workspace
    - GET    /api/workspaces           → list all
    - GET    /api/workspaces/{id}      → get details of one workspace
    - POST   /api/workspaces/{id}/start  → restart stopped workspace or start the new workspace
    - POST   /api/workspaces/{id}/stop   → stop workspace (keep data)
    - DELETE /api/workspaces/{id}      → destroy workspace
    - POST   /api/workspaces/{id}/heartbeat → mark workspace as active
    - GET    /health                   → liveness check

### Create a workspace

```bash
curl -s -X POST http://localhost:8000/api/workspaces \
  -H "Content-Type: application/json" \
  -d '{"user_id": "Vansh"}' | jq .
```

Response:
```json
{
  "id": "de6f748c",
  "token": "YUSsOy1ubLp-FwMphKXqhg",
  "user_id": "Vansh",
  "container_id": "9ed6a7218bd92838d5f999d05a96642d8fe135b5121e6d7728ce8c9539f68813",
  "port": 9000,
  "status": "running",
  "created_at": "2026-03-13T09:08:41.316470+00:00",
  "last_active": "2026-03-13T09:08:41.316470+00:00",
  "url": "http://localhost:9000/?folder=/home/coder/project"
}
```

Open the `url` in your browser → VS Code in the browser! Password: `devpass123`

### Create a second workspace

```bash
curl -s -X POST http://localhost:8000/api/workspaces \
  -H "Content-Type: application/json" \
  -d '{"user_id": "Vardan"}' | jq .
```

### List all workspaces

```bash
curl -s http://localhost:8000/api/workspaces | jq .
```

### Stop a workspace (preserve data)

```bash
curl -s -X POST http://localhost:8000/api/workspaces/<workspace_id>/stop | jq .
```

### Restart a stopped workspace (data is still there!)

```bash
curl -s -X POST http://localhost:8000/api/workspaces/<workspace_id>/start | jq .
```

### Delete a workspace

```bash
# Keep volume (can restart later)
curl -s -X DELETE http://localhost:8000/api/workspaces/<workspace_id>

# Purge everything including stored code
curl -s -X DELETE "http://localhost:8000/api/workspaces/<workspace_id>?purge=true"
```

### Heartbeat (keep alive)

```bash
curl -s -X POST http://localhost:8000/api/workspaces/<workspace_id>/heartbeat
```

---

## Proving Resource Limits

```bash
docker stats --no-stream | grep vs-
```

Output shows each workspace container capped at the configured CPU/memory limits:

```
CONTAINER ID   NAME           CPU %   MEM USAGE / LIMIT   MEM %
e222fe8aa2f8   vs-c357bf7d    0.00%   35.45MiB / 512MiB   6.92%
9ed6a7218bd9   vs-de6f748c    0.53%   240MiB / 512MiB     46.87%
```

---

## Idle Timeout

- Background reaper runs every 60 seconds.
- Any workspace with no heartbeat for **30 minutes** (configurable via `VS_IDLE_TIMEOUT_MIN`) is automatically stopped.
- Data is preserved — only the container is stopped.

---

## Configuration

| Variable              | Default                       | Description                    |
|-----------------------|-------------------------------|--------------------------------|
| `API_PORT`            | `8000`                        | Host port used for the API     |
| `DOMAIN`              | `localhost`                   | Host domain for workspace URLs |
| `VS_IMAGE`            | `codercom/code-server:latest` | VS Code server image           |
| `VS_CPU_LIMIT`        | `0.5`                         | CPU cores per workspace        |
| `VS_MEM_LIMIT`        | `512m`                        | Memory limit per workspace     |
| `VS_IDLE_TIMEOUT_MIN` | `30`                          | Minutes before idle cleanup    |
| `VS_PASSWORD`         | `devpass123`                  | code-server password           |

---

## Project Structure

```
.
├── api/
│   ├── Dockerfile          # Build API container
│   ├── requirements.txt
│   └── app/
│       ├── main.py            # FastAPI endpoints
│       ├── docker_manager.py  # Docker create or delete containers
│       ├── db.py              # Database
│       ├── idle_reaper.py     # Removes idle workspaces
│       └── schemas.py         
├── infra/                     
├── .github/
│   └── workflows/
│       └── main.yml          
├── tests/
│   └── test_api.py
├── docker-compose.yml        
├── .env
├── .env.example
└── README.md
```

---

## Optional: CI/CD

GitHub Actions pipeline (`.github/workflows/main.yml`):
- **On PR**: Lint (`ruff check api/`)
- **On PR**: Tests (`pytest -q`)
- **On push to main**: Build Docker image -> push to Docker Hub

---

## Trade-offs & Design Decisions

| Decision                 | Rationale                                                                                                |
|--------------------------|----------------------------------------------------------------------------------------------------------|
| **SQLite over Postgres** | Zero-dependency, perfect for single-node.                                                                |
| **Docker SDK**           | API container manages workspace containers via mounted Docker socket. Simple, effective for single-host. |
| **Port-per-workspace**   | Each workspace gets a unique port (9000+). Simple routing without reverse proxy complexity.              |
| **In-process reaper**    | APScheduler background thread. Production: separate worker or CronJob.                                   |
| **code-server image**    | Tested the full VS Code experience, easy to configure.                                                   |

## What I'd Improve With More Time

1. **Authentication** — JWT/OAuth so users can only access their own workspaces.
2. **Workspace templates** — pre-configured environments (Node, Python, Go, etc.).
3. **Monitoring** — Prometheus metrics, Grafana dashboard for active workspaces.
4. **WebSocket activity tracking** — detect real IDE usage instead of relying on heartbeat.
5. **Rate limiting** — prevent maximum workspace limits per user.
6. **Backup** — periodic volume snapshots.

---
