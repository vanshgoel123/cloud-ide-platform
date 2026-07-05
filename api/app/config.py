import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    domain: str = os.getenv("DOMAIN", "localhost")
    port_range_start: int = int(os.getenv("PORT_RANGE_START", "9000"))
    idle_timeout_min: int = int(os.getenv("VS_IDLE_TIMEOUT_MIN", "30"))
    api_key: str = os.getenv("API_KEY", "")
    cors_allow_origins: str = os.getenv("CORS_ALLOW_ORIGINS", "*")
    rate_limit_window_sec: int = int(os.getenv("RATE_LIMIT_WINDOW_SEC", "60"))
    rate_limit_create_per_window: int = int(os.getenv("RATE_LIMIT_CREATE_PER_WINDOW", "5"))


settings = Settings()
