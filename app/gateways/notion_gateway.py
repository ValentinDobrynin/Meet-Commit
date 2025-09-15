import os
from typing import Any

from notion_client import Client

# Проверяем наличие обязательных переменных окружения
try:
    NOTION_DB = os.environ["NOTION_DB_MEETINGS_ID"]
    NOTION_TOKEN = os.environ["NOTION_TOKEN"]
except KeyError as e:
    raise ValueError(f"Required environment variable not found: {e}") from None

notion = Client(auth=NOTION_TOKEN)

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
    
    # Всегда создаем новую запись
    page = notion.pages.create(
        parent={"database_id": NOTION_DB},
        properties=properties,
    )
    page_id = page["id"]

    page = notion.pages.retrieve(page_id)
    return page["url"]
