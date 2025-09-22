"""Gateway для работы с базой Review Queue в Notion."""

from __future__ import annotations

import logging
from datetime import UTC
from typing import Any

import httpx

from app.core.constants import REVIEW_STATUS_PENDING
from app.settings import settings

logger = logging.getLogger(__name__)

NOTION_API = "https://api.notion.com/v1"


def _create_client() -> httpx.Client:
    """Создает новый HTTP клиент для Notion API."""
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
    # Восстанавливаем поля согласно патчу
    reason = (item.get("reason") or "")[:1000]
    key = (item.get("key") or "")[:128]

    return {
        "Name": {"title": [{"text": {"content": short}}]},
        "Commit text": {"rich_text": [{"text": {"content": (item.get("text") or "")[:1800]}}]},
        "Direction": {"select": {"name": item.get("direction", "theirs")}},
        "Assignee": {"multi_select": [{"name": a} for a in (item.get("assignees") or [])]},
        "Due": {"date": {"start": due}} if due else {"date": None},
        "Confidence": {"number": float(item.get("confidence", 0.0))},
        "Reason": {
            "rich_text": [{"text": {"content": reason}}]
        },  # Восстанавливаем rich_text как в патче
        "Context": {"rich_text": [{"text": {"content": (item.get("context") or "")[:1800]}}]},
        "Key": {"rich_text": [{"text": {"content": key}}]},  # Добавляем поле Key
        "Meeting": {"relation": [{"id": meeting_page_id}]},
        "Status": {"select": {"name": item.get("status", REVIEW_STATUS_PENDING)}},
    }


def find_pending_by_key(key: str) -> dict | None:
    """
    Ищет pending элемент в Review Queue по ключу.

    Args:
        key: Ключ для поиска

    Returns:
        Словарь с page_id и properties если найден, иначе None
    """
    if not key:
        return None

    body = {
        "filter": {
            "and": [
                {"property": "Key", "rich_text": {"equals": key}},
                {"property": "Status", "select": {"equals": REVIEW_STATUS_PENDING}},
            ]
        },
        "page_size": 1,
    }

    client = _create_client()
    try:
        response = client.post(f"{NOTION_API}/databases/{settings.review_db_id}/query", json=body)
        response.raise_for_status()
        results = response.json().get("results", [])

        if not results:
            return None

        item = results[0]
        return {"page_id": item["id"], "properties": item["properties"]}

    except Exception as e:
        logger.error(f"Error in find_pending_by_key: {e}")
        raise
    finally:
        client.close()


def upsert_review(item: dict, meeting_page_id: str) -> dict:
    """
    Создает или обновляет элемент в Review Queue с дедупликацией по ключу.

    Args:
        item: Данные элемента для review
        meeting_page_id: ID страницы встречи

    Returns:
        Словарь со статистикой: {"created": int, "updated": int, "page_id": str}
    """
    key = item.get("key") or ""
    existing = find_pending_by_key(key)

    client = _create_client()
    try:
        if existing:
            # Обновляем существующий элемент
            page_id = existing["page_id"]
            props = _props_review(item, meeting_page_id)
            # При обновлении оставляем статус pending
            props["Status"] = {"select": {"name": REVIEW_STATUS_PENDING}}

            response = client.patch(f"{NOTION_API}/pages/{page_id}", json={"properties": props})
            if response.status_code != 200:
                logger.error(f"Review Update API Error {response.status_code}: {response.text}")
                logger.error(f"Update Payload: {{'properties': {props}}}")
            response.raise_for_status()

            return {"created": 0, "updated": 1, "page_id": page_id}
        else:
            # Создаем новый элемент
            payload = {
                "parent": {"database_id": settings.review_db_id},
                "properties": _props_review(item, meeting_page_id),
            }

            response = client.post(f"{NOTION_API}/pages", json=payload)
            if response.status_code != 200:
                logger.error(f"Review Create API Error {response.status_code}: {response.text}")
                logger.error(f"Create Payload: {payload}")
            response.raise_for_status()

            page_id = response.json()["id"]
            return {"created": 1, "updated": 0, "page_id": page_id}

    except Exception as e:
        logger.error(f"Error in upsert_review: {e}")
        raise
    finally:
        client.close()


def enqueue_with_upsert(items: list[dict], meeting_page_id: str) -> dict:
    """
    Добавляет элементы в очередь на ревью с дедупликацией по ключу.

    Args:
        items: Список элементов для ревью
        meeting_page_id: ID страницы встречи в Notion

    Returns:
        Словарь со статистикой: {"created": int, "updated": int, "page_ids": list[str]}
    """
    if not items:
        return {"created": 0, "updated": 0, "page_ids": []}

    stats: dict[str, int | list[str]] = {"created": 0, "updated": 0, "page_ids": []}

    for item in items:
        try:
            result = upsert_review(item, meeting_page_id)
            stats["created"] += result.get("created", 0)
            stats["updated"] += result.get("updated", 0)
            page_ids = stats["page_ids"]
            assert isinstance(page_ids, list)
            page_ids.append(result.get("page_id", ""))
        except Exception as e:
            logger.error(f"Error upserting review item: {e}")
            # Продолжаем обработку остальных элементов
            continue

    return stats


def enqueue(items: list[dict], meeting_page_id: str) -> list[str]:
    """
    Добавляет элементы в очередь на ревью (старая версия без дедупликации).
    DEPRECATED: Используйте enqueue_with_upsert() для новой логики с дедупликацией.

    Args:
        items: Список элементов для ревью
        meeting_page_id: ID страницы встречи в Notion

    Returns:
        Список ID созданных страниц
    """
    if not items:
        return []

    ids: list[str] = []
    client = _create_client()

    try:
        for item in items:
            props = _props_review(item, meeting_page_id)
            response = client.post(
                f"{NOTION_API}/pages",
                json={"parent": {"database_id": settings.review_db_id}, "properties": props},
            )
            if response.status_code != 200:
                logger.error(f"Review API Error {response.status_code}: {response.text}")
                logger.error(
                    f"Review Payload: {{'parent': {{'database_id': '{settings.review_db_id}'}}, 'properties': {props}}}"
                )
            response.raise_for_status()
            ids.append(response.json()["id"])

    except Exception as e:
        print(f"Error in enqueue: {type(e).__name__}: {e}")
        raise
    finally:
        client.close()

    return ids


def set_status(page_id: str, status: str, *, linked_commit_id: str | None = None) -> None:
    """
    Обновляет статус элемента в очереди ревью.

    Args:
        page_id: ID страницы в Notion
        status: Новый статус (pending, resolved, dropped)
        linked_commit_id: ID связанного коммита (для resolved статуса)
    """
    from datetime import datetime
    
    client = _create_client()

    try:
        props: dict[str, Any] = {
            "Status": {"select": {"name": status}},
        }
        
        # Добавляем Resolved At для закрытых статусов
        if status in {"resolved", "dropped"}:
            props["Resolved At"] = {
                "date": {"start": datetime.now(UTC).isoformat()}
            }
        
        # Добавляем связь с коммитом для resolved
        if linked_commit_id and status == "resolved":
            props["Linked Commit"] = {"relation": [{"id": linked_commit_id}]}
        
        response = client.patch(
            f"{NOTION_API}/pages/{page_id}",
            json={"properties": props},
        )
        response.raise_for_status()

    except Exception as e:
        logger.error(f"Error in set_status: {type(e).__name__}: {e}")
        raise
    finally:
        client.close()


def archive(page_id: str) -> None:
    """
    Архивирует страницу Review (soft-удаление).
    
    Args:
        page_id: ID страницы в Notion
    """
    client = _create_client()

    try:
        response = client.patch(
            f"{NOTION_API}/pages/{page_id}",
            json={"archived": True},
        )
        response.raise_for_status()
        logger.info(f"Archived review page: {page_id}")

    except Exception as e:
        logger.error(f"Error in archive: {type(e).__name__}: {e}")
        raise
    finally:
        client.close()


# ====== НОВЫЕ МЕТОДЫ ДЛЯ УПРАВЛЕНИЯ REVIEW QUEUE ======


def _short_id(page_id: str) -> str:
    """Возвращает короткий ID (последние 6 символов)."""
    return page_id.replace("-", "")[-6:]


def _parse_rich_text(prop: dict | None) -> str:
    """Парсит Notion rich_text property."""
    if not prop or prop.get("type") != "rich_text":
        return ""
    parts = prop.get("rich_text", [])
    return "".join(p.get("plain_text", "") for p in parts).strip()


def _parse_select(prop: dict | None) -> str | None:
    """Парсит Notion select property."""
    if not prop or prop.get("type") != "select":
        return None
    sel = prop.get("select") or {}
    return sel.get("name")


def _parse_multi_select(prop: dict | None) -> list[str]:
    """Парсит Notion multi_select property."""
    if not prop or prop.get("type") != "multi_select":
        return []
    return [x.get("name", "") for x in prop.get("multi_select", []) if x.get("name")]


def _parse_date(prop: dict | None) -> str | None:
    """Парсит Notion date property."""
    if not prop or prop.get("type") != "date":
        return None
    dt = prop.get("date") or {}
    return dt.get("start")


def _parse_number(prop: dict | None) -> float | None:
    """Парсит Notion number property."""
    if not prop or prop.get("type") != "number":
        return None
    return prop.get("number")


def _parse_relation_id(prop: dict | None) -> str | None:
    """Парсит Notion relation property и возвращает первый ID."""
    if not prop or prop.get("type") != "relation":
        return None
    rel = prop.get("relation") or []
    return rel[0]["id"] if rel else None


def list_pending(limit: int = 5) -> list[dict]:
    """
    Возвращает список открытых элементов из Review queue.
    Показывает только элементы со статусом 'pending' или 'needs-review'.

    Args:
        limit: Максимальное количество элементов

    Returns:
        Список словарей с данными элементов
    """
    # Открытые статусы (не resolved/dropped)
    OPEN_STATUSES = ["pending", "needs-review"]
    
    client = _create_client()

    try:
        # Фильтруем только открытые статусы
        payload = {
            "filter": {
                "or": [
                    {"property": "Status", "select": {"equals": status}}
                    for status in OPEN_STATUSES
                ]
            },
            "page_size": limit,
            "sorts": [{"timestamp": "last_edited_time", "direction": "descending"}],
        }
        response = client.post(
            f"{NOTION_API}/databases/{settings.review_db_id}/query",
            json=payload,
        )
        response.raise_for_status()

        results = []
        for item in response.json().get("results", []):
            page_id = item["id"]
            props = item["properties"]

            results.append(
                {
                    "page_id": page_id,
                    "short_id": _short_id(page_id),
                    "text": _parse_rich_text(props.get("Commit text")),
                    "direction": _parse_select(props.get("Direction")),
                    "assignees": _parse_multi_select(props.get("Assignee")),
                    "due_iso": _parse_date(props.get("Due")),
                    "confidence": _parse_number(props.get("Confidence")),
                    "reasons": _parse_multi_select(props.get("Reason")),
                    "context": _parse_rich_text(props.get("Context")),
                    "meeting_page_id": _parse_relation_id(props.get("Meeting")),
                }
            )

        # Fallback: если 0 записей, попробуем без фильтра (диагностика)
        if not results:
            logger.warning("No pending items found, trying fallback query without filter")
            fallback_response = client.post(
                f"{NOTION_API}/databases/{settings.review_db_id}/query",
                json={
                    "page_size": limit,
                    "sorts": [{"timestamp": "last_edited_time", "direction": "descending"}],
                },
            )
            fallback_response.raise_for_status()
            fallback_data = fallback_response.json()

            logger.info(f"Fallback query found {len(fallback_data.get('results', []))} total items")
            for item in fallback_data.get("results", [])[:3]:
                status = _parse_select(item["properties"].get("Status"))
                logger.info(f"Item status: '{status}'")

        return results

    except Exception as e:
        logger.error(f"Error in list_pending: {type(e).__name__}: {e}")
        raise
    finally:
        client.close()


def get_by_short_id(short_id: str) -> dict | None:
    """
    Находит элемент по короткому ID с поддержкой пагинации.

    Args:
        short_id: Короткий ID (последние 6 символов page_id)

    Returns:
        Словарь с данными элемента или None
    """
    short_id = short_id.lower()
    client = _create_client()

    try:
        cursor: str | None = None
        while True:
            payload = {
                "filter": {"property": "Status", "select": {"equals": REVIEW_STATUS_PENDING}},
                "sorts": [{"timestamp": "last_edited_time", "direction": "descending"}],
                "page_size": 50,
            }
            if cursor:
                payload["start_cursor"] = cursor

            response = client.post(
                f"{NOTION_API}/databases/{settings.review_db_id}/query", json=payload
            )
            response.raise_for_status()
            data = response.json()

            # Ищем в текущей странице
            for item in data.get("results", []):
                page_id = item["id"]
                if _short_id(page_id).lower() == short_id:
                    props = item["properties"]
                    return {
                        "page_id": page_id,
                        "short_id": _short_id(page_id),
                        "text": _parse_rich_text(props.get("Commit text")),
                        "direction": _parse_select(props.get("Direction")),
                        "assignees": _parse_multi_select(props.get("Assignee")),
                        "due_iso": _parse_date(props.get("Due")),
                        "confidence": _parse_number(props.get("Confidence")),
                        "reasons": _parse_multi_select(props.get("Reason")),
                        "context": _parse_rich_text(props.get("Context")),
                        "meeting_page_id": _parse_relation_id(props.get("Meeting")),
                    }

            # Проверяем, есть ли еще страницы
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")

        return None

    except Exception as e:
        logger.error(f"Error in get_by_short_id: {type(e).__name__}: {e}")
        raise
    finally:
        client.close()


def update_fields(
    page_id: str,
    *,
    direction: str | None = None,
    assignees: list[str] | None = None,
    due_iso: str | None = None,
) -> bool:
    """
    Обновляет поля элемента в Review queue.

    Args:
        page_id: ID страницы в Notion
        direction: Новое направление (mine/theirs)
        assignees: Новый список исполнителей
        due_iso: Новая дата дедлайна в ISO формате

    Returns:
        True если успешно обновлено
    """
    props: dict[str, Any] = {}

    if direction:
        props["Direction"] = {"select": {"name": direction}}

    if assignees is not None:
        props["Assignee"] = {"multi_select": [{"name": a} for a in assignees]}

    if due_iso is not None:
        props["Due"] = {"date": {"start": due_iso}} if due_iso else {"date": None}

    if not props:
        return True  # Нечего обновлять

    client = _create_client()

    try:
        response = client.patch(f"{NOTION_API}/pages/{page_id}", json={"properties": props})
        response.raise_for_status()
        return True

    except Exception as e:
        logger.error(f"Error in update_fields: {type(e).__name__}: {e}")
        return False
    finally:
        client.close()
