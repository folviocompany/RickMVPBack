from functools import lru_cache
from pathlib import Path
from typing import Literal

from pydantic import AliasChoices, Field, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    app_env: Literal["development", "test", "production"] = "development"
    database_url: str = "postgresql+psycopg://postgres:postgres@localhost:5432/adi"

    llm_provider: Literal["nvidia"] = "nvidia"
    nvidia_api_key: SecretStr | None = None
    nvidia_base_url: str = "https://integrate.api.nvidia.com/v1"
    nvidia_model: str = "nvidia/nemotron-3.5-lightning-30b-a3b"
    nvidia_ocr_url: str = "https://ai.api.nvidia.com/v1/cv/nvidia/nemotron-ocr-v2"

    frontend_origins_csv: str = Field(
        default="http://localhost:5173",
        validation_alias=AliasChoices("FRONTEND_ORIGINS", "frontend_origins_csv"),
    )
    upload_dir: Path = Path("data/uploads")
    max_upload_mb: int = Field(default=20, ge=1, le=100)

    @field_validator("database_url")
    @classmethod
    def normalize_database_url(cls, value: str) -> str:
        if value.startswith("postgres://"):
            return value.replace("postgres://", "postgresql+psycopg://", 1)
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+psycopg://", 1)
        return value

    @property
    def frontend_origins(self) -> list[str]:
        return [origin.strip() for origin in self.frontend_origins_csv.split(",") if origin.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
