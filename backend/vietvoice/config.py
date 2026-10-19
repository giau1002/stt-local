import os
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Settings:
    model_dir: Path = Path(os.getenv("MODEL_DIR", "models"))
    static_dir: Path = Path(os.getenv("STATIC_DIR", "frontend/dist"))
    database_url: str = os.getenv("DATABASE_URL", "sqlite:///data/vietvoice.db")
    app_key: str = os.getenv("APP_KEY", "")
    secure_cookie: bool = os.getenv("SECURE_COOKIE", "false").lower() == "true"
    origins: tuple = tuple(os.getenv("ALLOWED_ORIGINS", "http://localhost:8080,http://127.0.0.1:8080").split(","))
    diar_device: str = os.getenv("DIAR_DEVICE", "cuda")
    diar_mode: str = os.getenv("DIAR_MODE", "low_latency")
    threads: int = int(os.getenv("CPU_THREADS", "4"))
    max_sessions: int = int(os.getenv("MAX_SESSIONS", "1"))
    max_seconds: int = int(os.getenv("MAX_SESSION_SECONDS", "7200"))
    segment_seconds: float = float(os.getenv("MAX_SEGMENT_SECONDS", "12"))
    startup_models: bool = os.getenv("LOAD_MODELS", "true").lower() == "true"

    def validate(self):
        if len(self.app_key) < 32:
            raise ValueError("APP_KEY must contain at least 32 characters; run scripts/bootstrap.py")
        if self.max_sessions < 1 or self.segment_seconds < 2:
            raise ValueError("Invalid concurrency or segment duration")
