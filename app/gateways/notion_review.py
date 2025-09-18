"""Gateway для работы с базой Review Queue в Notion."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import httpx

from app.settings import settings

NOTION_API = "https://api.notion.com/v1"


@lru_cache(maxsize=1)
def _client() -> httpx.Client:
    """Создает HTTP клиент для Notion API с кэшированием."""
    if not settings.notion_token or not settings.review_db_id:
        raise RuntimeError("Notion credentials missing: NOTION_TOKEN or REVIEW_DB_ID")

    headers = {
        "Authorization": f"Bearer {settings.notion_token}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }
    return httpx.Client(timeout=30, headers=headers)


def _props_review(item: dict, meeting_page_id: str) -> dict[str, Any]:
    """Создает properties для страницы Review Queue."""
    due = item.get("due_iso")
    short = (item.get("text") or "")[:80]

    return {
        "Name": {"title": [{"text": {"content": short}}]},
        "Commit text": {"rich_text": [{"text": {"content": (item.get("text") or "")[:1800]}}]},
        "Direction": {"select": {"name": item.get("direction", "theirs")}},
        "Assignee": {"multi_select": [{"name": a} for a in (item.get("assignees") or [])]},
        "Due": {"date": {"start": due}} if due else {"date": {"start": None}},
        "Confidence": {"number": float(item.get("confidence", 0.0))},
        "Reason": {"multi_select": [{"name": r} for r in (item.get("reasons") or [])]},
        "Context": {"rich_text": [{"text": {"content": (item.get("context") or "")[:1800]}}]},
        "Meeting": {"relation": [{"id": meeting_page_id}]},
        "Status": {"select": {"name": item.get("status", "pending")}},
    }


def enqueue(items: list[dict], meeting_page_id: str) -> list[str]:
    """
    Добавляет элементы в очередь на ревью.

    Args:
        items: Список элементов для ревью
        meeting_page_id: ID страницы встречи в Notion

    Returns:
        Список ID созданных страниц
    """
    if not items:
        return []

    ids: list[str] = []
    client = _client()

    try:
        for item in items:
            props = _props_review(item, meeting_page_id)
            response = client.post(
                f"{NOTION_API}/pages",
                json={"parent": {"database_id": settings.review_db_id}, "properties": props},
            )
            response.raise_for_status()
            ids.append(response.json()["id"])

    except Exception as e:
        print(f"Error in enqueue: {type(e).__name__}: {e}")
        raise
    finally:
        client.close()

    return ids


def set_status(page_id: str, status: str) -> None:
    """
    Обновляет статус элемента в очереди ревью.

    Args:
        page_id: ID страницы в Notion
        status: Новый статус (pending, confirmed, rejected)
    """
    client = _client()

    try:
        response = client.patch(
            f"{NOTION_API}/pages/{page_id}",
            json={"properties": {"Status": {"select": {"name": status}}}},
        )
        response.raise_for_status()

    except Exception as e:
        print(f"Error in set_status: {type(e).__name__}: {e}")
        raise
    finally:
        client.close()
