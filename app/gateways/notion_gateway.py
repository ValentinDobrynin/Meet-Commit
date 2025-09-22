import logging
import os
from functools import lru_cache
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings

logger = logging.getLogger(__name__)


class Settings(BaseSettings):
    notion_token: str = Field(..., description="Notion API token")
    notion_db_meetings_id: str = Field(..., description="Notion database ID for meetings")

    model_config = {"env_file": ".env", "extra": "ignore"}


@lru_cache(maxsize=1)
def _settings() -> Settings:
    """Получает настройки с кэшированием."""
    return Settings(
        notion_token=os.environ.get("NOTION_TOKEN", ""),
        notion_db_meetings_id=os.environ.get("NOTION_DB_MEETINGS_ID", ""),
    )


@lru_cache(maxsize=1)
def _client():
    """Получает Notion клиент с кэшированием."""
    from notion_client import Client

    return Client(auth=_settings().notion_token)


# -------- helpers --------


def _props(payload: dict[str, Any]) -> dict[str, Any]:
    """Собирает properties под фактические поля базы."""
    name = (payload.get("title") or "Untitled Meeting")[:200]
    date = payload.get("date")  # ISO YYYY-MM-DD
    attendees: list[str] = payload.get("attendees", [])
    source = payload.get("source", "telegram")
    raw_hash = payload["raw_hash"]
    summary_md = (payload.get("summary_md") or "")[:1900]  # ограничим rich_text
    tags: list[str] = payload.get("tags", [])

    # Логируем данные для диагностики
    logger.debug(f"Building props for meeting: title='{name}', date='{date}'")
    logger.debug(f"Attendees raw: {attendees} (type: {type(attendees)}, len: {len(attendees)})")
    logger.debug(f"Tags raw: {tags} (type: {type(tags)}, len: {len(tags)})")

    # Создаем multi_select для attendees
    attendees_multi_select = [{"name": str(a)} for a in attendees if a and str(a).strip()]
    logger.debug(f"Attendees multi_select: {attendees_multi_select}")

    props = {
        "Name": {"title": [{"text": {"content": name}}]},
        "Date": {"date": {"start": date} if date else None},
        "Attendees": {"multi_select": attendees_multi_select},
        "Source": {"rich_text": [{"text": {"content": source}}]},
        "Raw hash": {"rich_text": [{"text": {"content": raw_hash}}]},
        "Summary MD": {"rich_text": [{"text": {"content": summary_md}}]},
        "Tags": {"multi_select": [{"name": t} for t in tags]},
    }
    return props


# -------- public API --------


def upsert_meeting(payload: dict[str, Any]) -> str:
    """
    Создаёт новую страницу Meeting для каждой суммаризации.
    Возвращает URL страницы.
    Ожидаемые поля payload: title, date, attendees, source, raw_hash, summary_md, tags.
    """
    try:
        properties = _props(payload)
        client = _client()
        db_id = _settings().notion_db_meetings_id

        title = payload.get("title", "Untitled Meeting")
        tags_count = len(payload.get("tags", []))
        attendees_count = len(payload.get("attendees", []))

        logger.info(
            f"Creating meeting page: '{title}' with {tags_count} tags, {attendees_count} attendees"
        )

        # Всегда создаем новую запись
        page = client.pages.create(
            parent={"database_id": db_id},
            properties=properties,
        )
        page_id = page["id"]

        page = client.pages.retrieve(page_id)
        url = str(page["url"])

        logger.info(f"Meeting page created successfully: {url}")
        return url

    except Exception as e:
        logger.error(f"Failed to create meeting page: {e}", exc_info=True)
        raise
