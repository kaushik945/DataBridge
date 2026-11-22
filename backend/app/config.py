from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env", extra="ignore", env_ignore_empty=True
    )
    database_url: str = "postgresql+psycopg://databridge:local-development-only@localhost:5432/databridge"
    ai_mode: str = "mock"
    tier_mapping_strategy: Literal["profile_lookup", "lookup", "agent"] = (
        "profile_lookup"
    )
    cookie_secure: bool = False
    allowed_origins: str = "http://localhost:5173"
    max_upload_bytes: int = 5 * 1024 * 1024
    max_rows: int = 10000
    max_columns: int = 50
    uploads_per_minute: int = 20
    google_cloud_project: str = ""
    google_cloud_location: str = "us-central1"
    vertex_model: str = ""
    embedding_model: str = ""
    embedding_dimensions: int = 768
    model_timeout_seconds: int = 45
    pricing_date: str = ""
    input_usd_per_million: float | None = None
    output_usd_per_million: float | None = None
    gcs_bucket: str = ""
    local_endpoint: str = "http://host.docker.internal:11434"
    local_model: str = "qwen3:4b"
    local_embedding_model: str = "nomic-embed-text:v1.5"
    local_context: int = Field(default=4096, ge=1024, le=4096)
    local_timeout_seconds: int = Field(default=120, ge=5, le=120)
    local_output_tokens: int = Field(default=1400, ge=64, le=2048)


settings = Settings()
