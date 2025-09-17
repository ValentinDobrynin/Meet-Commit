"""Gateway для работы с базой Commits в Notion."""

from __future__ import annotations

from functools import lru_cache
from typing import Any

import httpx

from app.settings import settings

NOTION_API = "https://api.notion.com/v1"


@lru_cache(maxsize=1)
def _client() -> httpx.Client:
    """Создает HTTP клиент для Notion API с кэшированием."""
    if not settings.notion_token or not settings.commits_db_id:
        raise RuntimeError("Notion credentials missing: NOTION_TOKEN or COMMITS_DB_ID")
    
    headers = {
        "Authorization": f"Bearer {settings.notion_token}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }
    return httpx.Client(timeout=30, headers=headers)


def _query_by_key(client: httpx.Client, key: str) -> str | None:
    """Находит страницу по ключу."""
    payload = {
        "filter": {
            "property": "Key",
            "rich_text": {"equals": key},
        },
        "page_size": 1,
    }
    
    try:
        response = client.post(
            f"{NOTION_API}/databases/{settings.commits_db_id}/query",
            json=payload
        )
        response.raise_for_status()
        results = response.json().get("results", [])
        return results[0]["id"] if results else None
        
    except Exception as e:
        print(f"Error in _query_by_key: {type(e).__name__}: {e}")
        raise


def _props_commit(item: dict, meeting_page_id: str) -> dict[str, Any]:
    """Создает properties для страницы Commit."""
    due = item.get("due_iso")
    
    return {
        "Name": {"title": [{"text": {"content": item["title"][:200]}}]},
        "Text": {"rich_text": [{"text": {"content": item["text"][:1800]}}]},
        "Direction": {"select": {"name": item["direction"]}},
        "Assignee": {"multi_select": [{"name": a} for a in (item.get("assignees") or [])]},
        "Due": {"date": {"start": due}} if due else {"date": {"start": None}},
        "Confidence": {"number": float(item.get("confidence", 0.0))},
        "Flags": {"multi_select": [{"name": f} for f in (item.get("flags") or [])]},
        "Meeting": {"relation": [{"id": meeting_page_id}]},
        "Key": {"rich_text": [{"text": {"content": item["key"]}}]},
        "Status": {"select": {"name": item.get("status", "open")}},
        "Tags": {"multi_select": [{"name": t} for t in (item.get("tags") or [])]},
    }


def upsert_commits(meeting_page_id: str, commits: list[dict]) -> dict[str, list[str]]:
    """
    Создает или обновляет коммиты в базе данных.
    
    Args:
        meeting_page_id: ID страницы встречи в Notion
        commits: Список коммитов для создания/обновления
        
    Returns:
        Словарь с ID созданных и обновленных страниц
    """
    if not commits:
        return {"created": [], "updated": []}
    
    created, updated = [], []
    client = _client()
    
    try:
        for item in commits:
            # Валидация обязательных полей
            if not item.get("key") or not item.get("title") or not item.get("text"):
                print(f"Skipping commit with missing required fields: {item}")
                continue
                
            page_id = _query_by_key(client, item["key"])
            props = _props_commit(item, meeting_page_id)
            
            if page_id:
                # Обновляем существующую страницу
                response = client.patch(
                    f"{NOTION_API}/pages/{page_id}",
                    json={"properties": props}
                )
                response.raise_for_status()
                updated.append(page_id)
            else:
                # Создаем новую страницу
                response = client.post(
                    f"{NOTION_API}/pages",
                    json={
                        "parent": {"database_id": settings.commits_db_id},
                        "properties": props
                    }
                )
                response.raise_for_status()
                created.append(response.json()["id"])
                
    except Exception as e:
        print(f"Error in upsert_commits: {type(e).__name__}: {e}")
        raise
    finally:
        client.close()
        
    return {"created": created, "updated": updated}
