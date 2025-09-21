import os

from pydantic import BaseModel, Field
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

    # Эти переменные читаются без APP_ префикса
    commits_db_id: str | None = Field(default=None, alias="COMMITS_DB_ID")
    review_db_id: str | None = Field(default=None, alias="REVIEW_DB_ID")

    # Unified tagging settings
    tags_mode: str = "both"  # v0 | v1 | both

    # Tagger v1 settings (kept for compatibility)
    tagger_v1_enabled: bool = True
    tagger_v1_rules_file: str = "data/tag_rules.yaml"

    model_config = SettingsConfigDict(
        env_prefix="APP_",
        env_file=os.getenv("ENV_FILE", ".env"),
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,  # Позволяет использовать alias для переменных окружения
    )


settings = Settings()


class Healthz(BaseModel):
    status: str
    env: str
