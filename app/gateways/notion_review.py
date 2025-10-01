"""Gateway для работы с базой Review Queue в Notion."""

from __future__ import annotations

import logging
from typing import Any

from app.core.clients import get_notion_http_client
from app.core.constants import (
    REVIEW_STATUS_PENDING,
)
from app.gateways.error_handling import notion_create, notion_query, notion_update
from app.gateways.notion_parsers import (
    parse_date,
    parse_multi_select,
    parse_number,
    parse_relation_single,
    parse_rich_text,
    parse_select,
)
from app.settings import settings

logger = logging.getLogger(__name__)

NOTION_API = "https://api.notion.com/v1"


# Удалено: используем единый клиент из app.core.clients


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
        "From": {"multi_select": [{"name": f} for f in (item.get("from_person") or [])]},
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


@notion_query("find_pending_by_key", fallback=None)  # Graceful fallback для стабильности
def find_pending_by_key(key: str) -> dict | None:
    """
    Ищет pending элемент в Review Queue по ключу.

    Args:
        key: Ключ для поиска

    Returns:
        Словарь с page_id и properties если найден, иначе None (graceful fallback при ошибках)
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

    with get_notion_http_client() as client:
        response = client.post(f"{NOTION_API}/databases/{settings.review_db_id}/query", json=body)
        response.raise_for_status()
        results = response.json().get("results", [])

        if not results:
            return None

        item = results[0]
        return {"page_id": item["id"], "properties": item["properties"]}


@notion_create("upsert_review")  # Strict handling для целостности данных
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

    client = get_notion_http_client()
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


@notion_create("enqueue_review_items")  # Strict handling для целостности данных
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
    client = get_notion_http_client()

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


@notion_update("set_review_status")  # Strict handling для целостности данных
def set_status(page_id: str, status: str, *, linked_commit_id: str | None = None) -> None:
    """
    Обновляет статус элемента в очереди ревью.

    Args:
        page_id: ID страницы в Notion
        status: Новый статус (pending, resolved, dropped)
        linked_commit_id: ID связанного коммита (для resolved статуса)
    """

    client = get_notion_http_client()

    try:
        # Маппинг новых статусов на старые для обратной совместимости
        status_mapping = {
            "resolved": "confirmed",  # resolved → confirmed
            "dropped": "rejected",  # dropped → rejected
            "pending": "pending",  # pending остается
        }

        mapped_status = status_mapping.get(status, status)

        props: dict[str, Any] = {
            "Status": {"select": {"name": mapped_status}},
        }

        # Добавляем Resolved At для закрытых статусов (временно отключено для диагностики)
        # if status in {"resolved", "dropped"}:
        #     props["Resolved At"] = {"date": {"start": datetime.now(UTC).isoformat()}}

        # Добавляем связь с коммитом для resolved (временно отключено для диагностики)
        # if linked_commit_id and status == "resolved":
        #     props["Linked Commit"] = {"relation": [{"id": linked_commit_id}]}

        logger.debug(f"Updating page {page_id} with props: {props}")

        response = client.patch(
            f"{NOTION_API}/pages/{page_id}",
            json={"properties": props},
        )

        if response.status_code != 200:
            logger.error(f"Set status API Error {response.status_code}: {response.text}")
            logger.error(f"Props payload: {props}")

        response.raise_for_status()

    except Exception as e:
        logger.error(f"Error in set_status: {type(e).__name__}: {e}")
        raise
    finally:
        client.close()


@notion_update("archive_review")  # Strict handling для целостности данных
def archive(page_id: str) -> None:
    """
    Архивирует страницу Review (soft-удаление).

    Args:
        page_id: ID страницы в Notion
    """
    client = get_notion_http_client()

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


# Используем общие парсеры из notion_parsers.py


@notion_query("list_pending", fallback=[])  # Graceful fallback для стабильности UI
def list_pending(limit: int = 5) -> list[dict]:
    """
    Возвращает список открытых элементов из Review queue.
    Показывает только элементы со статусом 'pending' или 'needs-review'.

    Args:
        limit: Максимальное количество элементов

    Returns:
        Список словарей с данными элементов (graceful fallback на [] при ошибках)
    """
    # Открытые статусы (не confirmed/rejected)
    OPEN_STATUSES = ["pending", "needs-review"]

    with get_notion_http_client() as client:
        # Фильтруем только открытые статусы
        payload = {
            "filter": {
                "or": [
                    {"property": "Status", "select": {"equals": status}} for status in OPEN_STATUSES
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
                    "text": parse_rich_text(props.get("Commit text")),
                    "direction": parse_select(props.get("Direction")),
                    "assignees": parse_multi_select(props.get("Assignee")),
                    "due_iso": parse_date(props.get("Due")),
                    "confidence": parse_number(props.get("Confidence")),
                    "reasons": parse_multi_select(props.get("Reason")),
                    "context": parse_rich_text(props.get("Context")),
                    "meeting_page_id": parse_relation_single(props.get("Meeting")),
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
                status = parse_select(item["properties"].get("Status"))
                logger.info(f"Item status: '{status}'")

        return results


@notion_query("get_by_short_id", fallback=None)  # Graceful fallback для стабильности
def get_by_short_id(short_id: str) -> dict | None:
    """
    Находит элемент по короткому ID с поддержкой пагинации.

    Args:
        short_id: Короткий ID (последние 6 символов page_id)

    Returns:
        Словарь с данными элемента или None (graceful fallback при ошибках)
    """
    short_id = short_id.lower()

    with get_notion_http_client() as client:
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
                        "text": parse_rich_text(props.get("Commit text")),
                        "direction": parse_select(props.get("Direction")),
                        "assignees": parse_multi_select(props.get("Assignee")),
                        "due_iso": parse_date(props.get("Due")),
                        "confidence": parse_number(props.get("Confidence")),
                        "reasons": parse_multi_select(props.get("Reason")),
                        "context": parse_rich_text(props.get("Context")),
                        "meeting_page_id": parse_relation_single(props.get("Meeting")),
                    }

            # Проверяем, есть ли еще страницы
            if not data.get("has_more"):
                break
            cursor = data.get("next_cursor")

        return None


@notion_update("update_review_fields")  # Strict handling для целостности данных
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

    Raises:
        NotionAPIError: При ошибках API (strict handling для целостности данных)
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

    with get_notion_http_client() as client:
        response = client.patch(f"{NOTION_API}/pages/{page_id}", json={"properties": props})
        response.raise_for_status()
        return True


# ====== FUNCTIONS FOR REVIEW CLEANUP ======


@notion_query("fetch_all_reviews", fallback=[])  # Graceful fallback для стабильности
def fetch_all_reviews(status_filter: list[str] | None = None) -> list[dict[str, Any]]:
    """
    Получает все записи Review Queue с опциональным фильтром по статусу.

    Args:
        status_filter: Список статусов для фильтрации, если None - все записи

    Returns:
        Список всех записей Review Queue
    """
    if not settings.review_db_id:
        logger.warning("REVIEW_DB_ID не настроен, возвращаем пустой список")
        return []

    try:
        with get_notion_http_client() as client:
            all_results = []
            has_more = True
            next_cursor = None

            while has_more:
                # Подготавливаем payload
                payload: dict[str, Any] = {"page_size": 100}

                if next_cursor:
                    payload["start_cursor"] = next_cursor  # type: ignore[unreachable]

                # Добавляем фильтр по статусу если указан
                if status_filter:
                    if len(status_filter) == 1:
                        payload["filter"] = {
                            "property": "Status",
                            "select": {"equals": status_filter[0]},
                        }
                    else:
                        payload["filter"] = {
                            "or": [
                                {"property": "Status", "select": {"equals": status}}
                                for status in status_filter
                            ]
                        }

                # Сортировка по дате последнего редактирования
                payload["sorts"] = [{"timestamp": "last_edited_time", "direction": "descending"}]

                # Выполняем запрос
                response = client.post(
                    f"{NOTION_API}/databases/{settings.review_db_id}/query", json=payload
                )
                response.raise_for_status()

                data = response.json()
                results = data.get("results", [])

                # Преобразуем в стандартный формат
                for item in results:
                    page_id = item["id"]
                    props = item["properties"]

                    review_item = {
                        "id": page_id,
                        "text": parse_rich_text(props.get("Commit text")),
                        "status": parse_select(props.get("Status")),
                        "direction": parse_select(props.get("Direction")),
                        "assignees": parse_multi_select(props.get("Assignee")),
                        "confidence": parse_number(props.get("Confidence")),
                        "due_iso": parse_date(props.get("Due")),
                        "context": parse_rich_text(props.get("Context")),
                        "key": parse_rich_text(props.get("Key")),
                        "meeting_page_id": parse_relation_single(props.get("Meeting")),
                        "last_edited_time": item.get("last_edited_time"),
                        "created_time": item.get("created_time"),
                    }

                    all_results.append(review_item)

                # Проверяем есть ли еще страницы
                has_more = data.get("has_more", False)
                next_cursor = data.get("next_cursor")

            logger.debug(f"Fetched {len(all_results)} reviews from Notion")
            return all_results

    except Exception as e:
        logger.error(f"Error fetching all reviews: {e}")
        return []


@notion_update("bulk_update_status")  # Strict handling для целостности данных
def bulk_update_status(page_ids: list[str], new_status: str) -> dict[str, int]:
    """
    Массово обновляет статус записей Review Queue.

    Args:
        page_ids: Список ID страниц для обновления
        new_status: Новый статус для установки

    Returns:
        Словарь со статистикой: {"updated": int, "errors": int}

    Raises:
        RuntimeError: При критических ошибках API
    """
    if not page_ids:
        return {"updated": 0, "errors": 0}

    if not settings.review_db_id:
        raise RuntimeError("REVIEW_DB_ID не настроен")

    updated_count = 0
    error_count = 0

    try:
        with get_notion_http_client() as client:
            # Обновляем каждую страницу отдельно для надежности
            for page_id in page_ids:
                try:
                    # Подготавливаем properties для обновления
                    properties = {"Status": {"select": {"name": new_status}}}

                    # Обновляем страницу
                    response = client.patch(
                        f"{NOTION_API}/pages/{page_id}", json={"properties": properties}
                    )

                    if response.status_code == 200:
                        updated_count += 1
                        logger.debug(f"Updated review {page_id} to status '{new_status}'")
                    else:
                        error_count += 1
                        logger.error(
                            f"Failed to update review {page_id}: "
                            f"HTTP {response.status_code} - {response.text}"
                        )

                except Exception as e:
                    error_count += 1
                    logger.error(f"Error updating review {page_id}: {e}")

            logger.info(
                f"Bulk status update completed: {updated_count} updated, {error_count} errors"
            )

            return {"updated": updated_count, "errors": error_count}

    except Exception as e:
        logger.error(f"Critical error in bulk_update_status: {e}")
        raise RuntimeError(f"Failed to bulk update status: {e}") from e


@notion_update("archive_review")  # Strict handling для целостности данных
def archive_review(page_id: str) -> bool:
    """
    Архивирует одну запись Review Queue.

    Args:
        page_id: ID страницы для архивирования

    Returns:
        True если успешно архивировано

    Raises:
        RuntimeError: При ошибках API
    """
    try:
        result = bulk_update_status([page_id], "archived")
        return bool(result["updated"] > 0)

    except Exception as e:
        logger.error(f"Error archiving review {page_id}: {e}")
        raise RuntimeError(f"Failed to archive review: {e}") from e
