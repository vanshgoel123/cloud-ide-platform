"""Check for idle workspaces and stop them."""

import os
from apscheduler.schedulers.background import BackgroundScheduler
from .db import get_idle_workspaces, update_status
from .docker_manager import stop_workspace

IDLE_TIMEOUT = int(os.getenv("VS_IDLE_TIMEOUT_MIN", "30"))
CHECK_INTERVAL_SEC = 60  # check every minute


def _reap():
    idle = get_idle_workspaces(IDLE_TIMEOUT)
    for vs in idle:
        print(f"[reaper] stopping idle workspace {vs['id']}")
        stop_workspace(vs["id"])
        update_status(vs["id"], "stopped")


scheduler = BackgroundScheduler()


def start_reaper():
    scheduler.add_job(_reap, "interval", seconds=CHECK_INTERVAL_SEC, id="idle_reaper")
    scheduler.start()
    print(f"[reaper] running — idle timeout = {IDLE_TIMEOUT} min")


def stop_reaper():
    scheduler.shutdown(wait=False)
