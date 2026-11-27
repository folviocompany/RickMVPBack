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
    extracta_allow_external_ai: bool = False
    extracta_ocr_dpi: int = Field(default=300, ge=150, le=400)
    extracta_ocr_lang: str = "por+eng"
    extracta_tesseract_cmd: str = "tesseract"
    extracta_tessdata_dir: Path | None = None
    extracta_max_pages_per_document: int = Field(default=30, ge=1, le=100)
    extracta_max_documents_per_batch: int = Field(default=10, ge=1, le=50)
    extracta_ocr_timeout_seconds: int = Field(default=60, ge=1, le=180)
    extracta_samples_dir: Path = Path("samples/atacadao")
    extracta_results_dir: Path = Path("data/extracta")
    extracta_storage: Literal["postgres", "local"] = "postgres"
    extracta_max_llm_calls_per_document: int = Field(default=3, ge=0, le=10)
    extracta_max_llm_calls_per_batch: int = Field(default=9, ge=0, le=50)
    extracta_max_retries: int = Field(default=1, ge=0, le=2)
    extracta_llm_timeout_seconds: float = Field(default=20, gt=0, le=60)
    extracta_llm_deadline_seconds: float = Field(default=45, gt=0, le=120)
    extracta_llm_max_input_chars: int = Field(default=7000, ge=1000, le=16000)
    extracta_llm_max_output_tokens: int = Field(default=1024, ge=128, le=2048)
    extracta_llm_response_format: Literal["json_object", "text"] = "json_object"
    extracta_max_processing_attempts: int = Field(default=3, ge=1, le=10)

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
