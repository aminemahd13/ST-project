from pathlib import Path
from typing import List

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Application configuration settings."""

    model_config = SettingsConfigDict(
        env_prefix="GRID_APP_",
        env_file=".env",
        extra="ignore",
    )

    app_name: str = "Grid Log AI Orchestrator"
    environment: str = "development"
    cors_allow_origins: List[str] = Field(default_factory=lambda: ["http://localhost:3000"])

    database_url: str = "sqlite+aiosqlite:///./grid_log.db"
    storage_dir: str = "./storage"
    rag_seed_dir: str = "../context_file/logs_document"

    max_upload_size_bytes: int = 25 * 1024 * 1024
    allowed_upload_extensions: List[str] = Field(default_factory=lambda: [".pdf"])

    api_key: str = ""
    rate_limit_enabled: bool = True
    rate_limit_requests_per_minute: int = 60

    job_timeout_seconds: float = 120.0
    job_max_retries: int = 2
    max_concurrent_jobs: int = 2

    llm_provider: str = "auto"
    hf_token: str = ""
    hf_model: str = "katanemo/Arch-Router-1.5B:hf-inference"
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "llama3.2:1b"
    llm_timeout_seconds: float = 20.0

    @property
    def storage_path(self) -> Path:
        return Path(self.storage_dir).resolve()

    @property
    def rag_seed_path(self) -> Path:
        return Path(self.rag_seed_dir).resolve()


settings = Settings()

