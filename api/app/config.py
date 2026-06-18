from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

# Resolve .env from project root (two levels up from this file: app/ -> api/ -> project root)
_ENV_FILE = Path(__file__).resolve().parents[2] / ".env"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=str(_ENV_FILE), extra="ignore")

    database_url: str
    redis_url: str
    celery_broker_url: str
    celery_result_backend: str

    gemini_api_key: str = ""
    gemini_model: str = "gemini-1.5-flash"

    llm_batch_size: int = 20
    llm_max_retries: int = 3
    max_upload_mb: int = 10

    log_level: str = "INFO"
    env: str = "development"


settings = Settings()
