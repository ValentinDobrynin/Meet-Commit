import os
from typing import Any

from dotenv import load_dotenv
from pydantic import BaseModel, Field
from pydantic_settings import BaseSettings, SettingsConfigDict

# Загружаем .env файл для переменных, которые не в Settings классе
load_dotenv()


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

    # Новые базы для синхронизации
    notion_db_tag_catalog_id: str | None = Field(default=None, alias="NOTION_DB_TAG_CATALOG_ID")
    notion_db_project_catalog_id: str | None = Field(
        default=None, alias="NOTION_DB_PROJECT_CATALOG_ID"
    )

    # Unified tagging settings
    tags_mode: str = "both"  # v0 | v1 | both

    # Tagger v1 scoring settings
    tags_min_score: float = 0.8

    # User identification for queries
    me_name_en: str = Field(default="Valya Dobrynin", description="English name for 'mine' queries")

    # Agendas database
    agendas_db_id: str | None = Field(default=None, alias="AGENDAS_DB_ID")

    # Tagger v1 settings (kept for compatibility)
    tagger_v1_enabled: bool = True
    tagger_v1_rules_file: str = "data/tag_rules.yaml"

    # Tags review settings
    tags_review_enabled: bool = True
    tags_review_ttl_sec: int = 900  # 15 минут на интерактивную сессию
    enable_tag_edit_log: bool = True

    # Notion Tag Catalog sync settings
    notion_sync_enabled: bool = False  # По умолчанию выключено (опциональная функция)
    notion_sync_interval_hours: int = 24  # Автосинхронизация каждые 24 часа
    notion_sync_fallback_to_yaml: bool = True  # Fallback на YAML при ошибках

    def is_admin(self, user_id: int | None) -> bool:
        """Проверяет, является ли пользователь администратором."""
        return user_id is not None and user_id in _admin_ids_set

    model_config = SettingsConfigDict(
        env_prefix="APP_",
        env_file=os.getenv("ENV_FILE", ".env"),
        case_sensitive=False,
        extra="ignore",
        populate_by_name=True,  # Позволяет использовать alias для переменных окружения
        env_ignore_empty=True,
    )


settings = Settings()

# Парсинг admin_user_ids из переменной окружения
_admin_ids_set: set[int] = set()
_admin_ids_source: str = "не настроено"

# Ищем админские ID в переменных окружения (приоритет APP_ADMIN_USER_IDS)
raw_admin_ids = os.getenv("APP_ADMIN_USER_IDS") or os.getenv("ADMIN_USER_IDS")
if raw_admin_ids:
    try:
        admin_ids = [int(x.strip()) for x in raw_admin_ids.split(",") if x.strip().isdigit()]
        _admin_ids_set = set(admin_ids)
        source_var = "APP_ADMIN_USER_IDS" if os.getenv("APP_ADMIN_USER_IDS") else "ADMIN_USER_IDS"
        _admin_ids_source = f"{source_var}={raw_admin_ids}"

        # Логируем источник настроек для диагностики
        import logging

        logger = logging.getLogger(__name__)
        logger.info(f"Admin IDs loaded from {_admin_ids_source}: {admin_ids}")

    except ValueError as e:
        import logging

        logger = logging.getLogger(__name__)
        logger.warning(f"Failed to parse admin IDs from {raw_admin_ids}: {e}")


def get_admin_config_info() -> dict[str, Any]:
    """Возвращает информацию о настройке админских прав для диагностики."""
    return {
        "admin_ids": list(_admin_ids_set),
        "source": _admin_ids_source,
        "count": len(_admin_ids_set),
        "env_file_exists": os.path.exists(".env"),
        "recommended_setup": "Создайте .env файл с APP_ADMIN_USER_IDS=your_telegram_id",
    }


class Healthz(BaseModel):
    status: str
    env: str
