import os
from typing import Optional
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    # Audiobookshelf
    ABS_BASE_URL: str
    ABS_TOKEN: str
    ABS_USER_ID: Optional[str] = None
    ABS_LIBRARY_ID: Optional[str] = None
    ABS_ALLOW_DUPLICATE_ASIN: bool = False

    # Audible
    AUDIBLE_LOCALE: str = "us"
    AUDIBLE_MARKETPLACE: Optional[str] = None
    AUDIBLE_AUTH_JSON_PATH: str = "/data/audible_session.json"
    AUDIBLE_AUTH_JSON_B64: Optional[str] = None
    AUDIBLE_BATCH_SIZE: int = 20
    AUDIBLE_LIBRARY_DISCOVERY_INTERVAL_SECONDS: int = 21600  # 6h
    AUDIBLE_DEEP_SCAN_INTERVAL_SECONDS: int = 86400  # 24h
    DEEP_SCAN_MAX_IN_PROGRESS: int = 200
    AUDIBLE_RECENTLY_PLAYED_LIMIT: int = 10

    # Persistence
    STATE_PATH: str = "/data/state.json"
    PERSIST_ENABLED: bool = True

    # Sync Logic
    SYNC_INTERVAL_SECONDS: int = 120
    SYNC_TOLERANCE_SECONDS: int = 5
    SYNC_COOLDOWN_SECONDS: int = 60
    SYNC_CONFLICT_MIN_TIME_DELTA_SECONDS: int = 30
    SYNC_MAX_REWIND_SECONDS: int = 600
    WATCHLIST_MAX_SIZE: int = 500
    ONE_WAY_MODE: str = "bidirectional"  # bidirectional, audible_to_abs, abs_to_audible

    # System
    LOG_LEVEL: str = "INFO"
    DRY_RUN: bool = False
    HTTP_SERVER_ENABLED: bool = False
    HTTP_SERVER_PORT: int = 8080
    HTTP_SERVER_TOKEN: Optional[str] = None
    REQUEST_TIMEOUT_SECONDS: int = 30

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=True,
        extra="ignore"
    )

settings = Settings()
