"""Gateway для работы с базой Commits в Notion."""

from __future__ import annotations

import logging
from typing import Any

import httpx

from app.settings import settings

logger = logging.getLogger(__name__)

NOTION_API = "https://api.notion.com/v1"


def _create_client() -> httpx.Client:
    """Создает новый HTTP клиент для Notion API."""
    if not settings.notion_token or not settings.commits_db_id:
        raise RuntimeError("Notion credentials missing: NOTION_TOKEN or COMMITS_DB_ID")

    headers = {
        "Authorization": f"Bearer {settings.notion_token}",
        "Notion-Version": "2022-06-28",
        "Content-Type": "application/json",
    }
    return httpx.Client(timeout=30, headers=headers)


def _query_by_key(client: httpx.Client, key: str) -> str | None:
    """
    Находит страницу коммита по уникальному ключу.

    Args:
        client: HTTP клиент для Notion API
        key: Уникальный ключ коммита (SHA256 hash)

    Returns:
        ID страницы если найдена, иначе None

    Используется для дедупликации коммитов при повторной обработке.
    """
    payload = {
        "filter": {
            "property": "Key",
            "rich_text": {"equals": key},
        },
        "page_size": 1,
    }

    try:
        logger.debug(f"Querying for key: {key}")
        logger.debug(f"Query payload: {payload}")
        response = client.post(
            f"{NOTION_API}/databases/{settings.commits_db_id}/query", json=payload
        )
        logger.debug(f"Query response status: {response.status_code}")
        response.raise_for_status()
        results = response.json().get("results", [])

        if results:
            logger.debug(f"Found existing commit with key: {key}")
            return str(results[0]["id"])
        else:
            logger.debug(f"No existing commit found for key: {key}")
            return None

    except Exception as e:
        logger.error(f"Error in _query_by_key: {type(e).__name__}: {e}")
        raise


def _props_commit(item: dict, meeting_page_id: str) -> dict[str, Any]:
    """Создает properties для страницы Commit."""
    due = item.get("due_iso")

    # Обеспечиваем читаемый Name даже если title не задан
    title = (item.get("title") or "").strip()[:200]
    if not title:
        # Fallback: создаем title из owner + text + due
        assignees = item.get("assignees") or []
        owner = assignees[0] if assignees else "Unassigned"
        base_text = (item.get("text") or "").strip().replace("\n", " ")[:80]
        due_suffix = f" [due {due}]" if due else ""
        title = f"{owner}: {base_text}{due_suffix}"

    props = {
        "Name": {"title": [{"text": {"content": title}}]},
        "Text": {"rich_text": [{"text": {"content": item["text"][:1800]}}]},
        "Direction": {"select": {"name": item["direction"]}},
        "Assignee": {"multi_select": [{"name": a} for a in (item.get("assignees") or [])]},
        "Due": {"date": {"start": due} if due else None},
        "Confidence": {"number": float(item.get("confidence", 0.0))},
        "Flags": {"multi_select": [{"name": f} for f in (item.get("flags") or [])]},
        "Meeting": {"relation": [{"id": meeting_page_id}]},
        "Key": {"rich_text": [{"text": {"content": item["key"]}}]},
        "Status": {"select": {"name": item.get("status", "open")}},
        "Tags": {"multi_select": [{"name": t} for t in (item.get("tags") or [])]},
    }
    logger.debug(f"Created props for commit: {item.get('title', 'Unknown')}")
    logger.debug(f"Props: {props}")
    return props


def upsert_commits(meeting_page_id: str, commits: list[dict]) -> dict[str, list[str]]:
    """
    Создает или обновляет коммиты в базе данных с дедупликацией по ключу.

    Args:
        meeting_page_id: ID страницы встречи в Notion
        commits: Список коммитов для создания/обновления

    Returns:
        Словарь с ID созданных и обновленных страниц

    Логика дедупликации:
        1. Для каждого коммита ищем существующую запись по полю Key
        2. Если найдена - обновляем (update)
        3. Если не найдена - создаем новую (create)

    Это предотвращает создание дубликатов при повторной обработке
    одних и тех же встреч или коммитов.
    """
    if not commits:
        logger.info("No commits to process")
        return {"created": [], "updated": []}

    created, updated = [], []
    client = _create_client()

    try:
        logger.info(f"Processing {len(commits)} commits for meeting {meeting_page_id}")

        for item in commits:
            # Валидация обязательных полей
            if not item.get("key") or not item.get("title") or not item.get("text"):
                logger.warning(
                    f"Skipping commit with missing required fields: {item.get('title', 'Unknown')}"
                )
                continue

            # Поиск существующего коммита по ключу (дедупликация)
            page_id = _query_by_key(client, item["key"])
            props = _props_commit(item, meeting_page_id)

            if page_id:
                # Обновляем существующую страницу
                response = client.patch(f"{NOTION_API}/pages/{page_id}", json={"properties": props})
                response.raise_for_status()
                updated.append(page_id)
                logger.debug(f"Updated existing commit: {item.get('title', 'Unknown')}")
            else:
                # Создаем новую страницу
                response = client.post(
                    f"{NOTION_API}/pages",
                    json={"parent": {"database_id": settings.commits_db_id}, "properties": props},
                )
                logger.debug(f"Notion create commits http={response.status_code}")
                if response.status_code != 200:
                    logger.error(f"Notion API Error {response.status_code}: {response.text}")
                    logger.error(
                        f"Payload was: {{'parent': {{'database_id': '{settings.commits_db_id}'}}, 'properties': {props}}}"
                    )
                response.raise_for_status()
                created.append(response.json()["id"])
                logger.debug(f"Created new commit: {item.get('title', 'Unknown')}")

    except Exception as e:
        logger.error(f"Error in upsert_commits: {type(e).__name__}: {e}")
        raise
    finally:
        client.close()

    logger.info(f"Commits processing completed: {len(created)} created, {len(updated)} updated")
    return {"created": created, "updated": updated}
