from functools import lru_cache
from typing import Any

from pydantic import Field
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    notion_token: str = Field(..., description="Notion API token")
    notion_db_meetings_id: str = Field(..., description="Notion database ID for meetings")
    
    model_config = {"env_file": ".env", "extra": "ignore"}


@lru_cache(maxsize=1)
def _settings() -> Settings:
    """Получает настройки с кэшированием."""
    return Settings()


@lru_cache(maxsize=1)
def _client():
    """Получает Notion клиент с кэшированием."""
    from notion_client import Client
    return Client(auth=_settings().notion_token)

# -------- helpers --------


def _props(payload: dict[str, Any]) -> dict[str, Any]:
    """Собирает properties под фактические поля базы."""
    name = payload["title"][:200] if payload.get("title") else "Meeting"
    date = payload.get("date")  # ISO YYYY-MM-DD
    attendees: list[str] = payload.get("attendees", [])
    source = payload.get("source", "telegram")
    raw_hash = payload["raw_hash"]
    summary_md = (payload.get("summary_md") or "")[:1900]  # ограничим rich_text
    tags: list[str] = payload.get("tags", [])

    props = {
        "Name": {"title": [{"text": {"content": name}}]},
        "Date": {"date": {"start": date}} if date else {"date": None},
        "Attendees": {"multi_select": [{"name": a} for a in attendees]},
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
    properties = _props(payload)
    client = _client()
    db_id = _settings().notion_db_meetings_id

    # Всегда создаем новую запись
    page = client.pages.create(
        parent={"database_id": db_id},
        properties=properties,
    )
    page_id = page["id"]

    page = client.pages.retrieve(page_id)
    return page["url"]
