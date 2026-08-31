import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    # Public domain used to build workspace URLs (e.g. "ide.example.com" or "localhost")
    domain: str = os.getenv("DOMAIN", "localhost")

    # Idle auto-stop: workspaces inactive longer than this are stopped by the reaper
    idle_timeout_min: int = int(os.getenv("VS_IDLE_TIMEOUT_MIN", "30"))

    # Optional API key to protect mutation endpoints (empty = no auth required)
    api_key: str = os.getenv("API_KEY", "")

    # CORS origins — comma-separated list or "*"
    cors_allow_origins: str = os.getenv("CORS_ALLOW_ORIGINS", "*")

    # Rate limiting for workspace creation
    rate_limit_window_sec: int = int(os.getenv("RATE_LIMIT_WINDOW_SEC", "60"))
    rate_limit_create_per_window: int = int(os.getenv("RATE_LIMIT_CREATE_PER_WINDOW", "5"))


settings = Settings()
