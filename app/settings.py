import os

from pydantic import BaseModel
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_host: str = "127.0.0.1"  # nosec B104 - локальный хост для разработки
    app_port: int = 8000
    env: str = "local"

    # OpenAI settings
    openai_api_key: str | None = None
    summarize_model: str = "gpt-4o-mini"
    summarize_temperature: float = 0.2
    
    # Notion settings
    notion_token: str | None = None
    notion_db_meetings_id: str | None = None
    commits_db_id: str | None = None
    review_db_id: str | None = None

    model_config = SettingsConfigDict(
        env_prefix="APP_",
        env_file=os.getenv("ENV_FILE", ".env"),
        case_sensitive=False,
        extra="ignore",
    )


settings = Settings()


class Healthz(BaseModel):
    status: str
    env: str
