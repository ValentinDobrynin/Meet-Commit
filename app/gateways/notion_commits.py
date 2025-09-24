"""Gateway для работы с базой Commits в Notion."""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import httpx

from app.core.metrics import MetricNames, timer, track_batch_operation
from app.settings import settings

logger = logging.getLogger(__name__)

NOTION_API = "https://api.notion.com/v1"


def _get_person_aliases(person_name: str) -> list[str]:
    """Получает все алиасы для персоны из people.json."""
    try:
        people_file = Path("app/dictionaries/people.json")
        if not people_file.exists():
            logger.warning(f"People file not found: {people_file}")
            return [person_name]

        with people_file.open("r", encoding="utf-8") as f:
            people_data = json.load(f)

        # Ищем персону по имени или алиасу
        for person in people_data:
            name_en = person.get("name_en", "")
            aliases = person.get("aliases", [])

            # Проверяем совпадение с каноническим именем или любым алиасом
            if person_name == name_en or person_name in aliases:
                # Возвращаем все алиасы + каноническое имя
                all_variants = [name_en] + aliases
                # Убираем дубликаты и пустые строки
                return list(set(filter(None, all_variants)))

        # Если не найдено в словаре, возвращаем исходное имя + базовые варианты
        logger.info(f"Person '{person_name}' not found in people.json, using fallback")
        fallback_variants = [person_name]
        if " " in person_name:
            fallback_variants.append(person_name.split()[0])  # Только имя
        return fallback_variants

    except Exception as e:
        logger.error(f"Error reading people.json: {e}")
        return [person_name]


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

    with timer(MetricNames.NOTION_UPSERT_COMMITS):
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
                    response = client.patch(
                        f"{NOTION_API}/pages/{page_id}", json={"properties": props}
                    )
                    response.raise_for_status()
                    updated.append(page_id)
                    logger.debug(f"Updated existing commit: {item.get('title', 'Unknown')}")
                else:
                    # Создаем новую страницу
                    response = client.post(
                        f"{NOTION_API}/pages",
                        json={
                            "parent": {"database_id": settings.commits_db_id},
                            "properties": props,
                        },
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

            logger.info(
                f"Commits processing completed: {len(created)} created, {len(updated)} updated"
            )

            # Отслеживаем батчевую операцию
            track_batch_operation("commits_upsert", len(commits), 0)  # duration_ms будет в timer

        except Exception as e:
            logger.error(f"Error in upsert_commits: {type(e).__name__}: {e}")
            raise
        finally:
            client.close()

        return {"created": created, "updated": updated}


# ====== QUERY FUNCTIONS FOR TG COMMANDS ======

PAGE_SIZE = 10


def _query_commits(
    filter_: dict[str, Any] | None = None,
    sorts: list[dict] | None = None,
    page_size: int = PAGE_SIZE,
) -> dict[str, Any]:
    """
    Универсальная функция для запросов к базе Commits.

    Args:
        filter_: Фильтр Notion API
        sorts: Сортировка Notion API
        page_size: Размер страницы

    Returns:
        Ответ Notion API с results
    """
    with timer(MetricNames.NOTION_QUERY_COMMITS):
        client = _create_client()

        try:
            payload: dict[str, Any] = {
                "page_size": page_size,
            }

            if filter_:
                payload["filter"] = filter_

            if sorts:
                payload["sorts"] = sorts
            else:
                # По умолчанию сортируем по дедлайну (без Created time - может не существовать)
                payload["sorts"] = [{"property": "Due", "direction": "ascending"}]

            logger.info(f"Querying commits with payload: {payload}")  # Временно INFO для отладки

            response = client.post(
                f"{NOTION_API}/databases/{settings.commits_db_id}/query", json=payload
            )
            response.raise_for_status()

            result = response.json()
            logger.info(
                f"Query result: {len(result.get('results', []))} items found"
            )  # Временно INFO для отладки

            return result  # type: ignore[no-any-return]

        except Exception as e:
            logger.error(f"Error querying commits: {e}")
            raise
        finally:
            client.close()


def _map_commit_page(page: dict[str, Any]) -> dict[str, Any]:
    """
    Преобразует страницу Notion в удобный формат для отображения.

    Args:
        page: Страница из Notion API

    Returns:
        Словарь с полями коммита
    """
    props = page.get("properties", {})

    def _extract_field(field_name: str, field_type: str) -> Any:
        """Извлекает значение поля определенного типа."""
        if field_name not in props:
            return None

        field_data = props[field_name]

        if field_type == "title":
            title_list = field_data.get("title", [])
            return "".join(item.get("plain_text", "") for item in title_list)
        elif field_type == "rich_text":
            text_list = field_data.get("rich_text", [])
            return "".join(item.get("plain_text", "") for item in text_list)
        elif field_type == "select":
            select_data = field_data.get("select")
            return select_data.get("name") if select_data else None
        elif field_type == "multi_select":
            multi_select_list = field_data.get("multi_select", [])
            return [item.get("name") for item in multi_select_list]
        elif field_type == "date":
            date_data = field_data.get("date")
            return date_data.get("start") if date_data else None
        elif field_type == "number":
            return field_data.get("number")
        elif field_type == "relation":
            relation_list = field_data.get("relation", [])
            return [item.get("id") for item in relation_list]

        return None

    # Извлекаем ID из URL для short_id
    page_id = page.get("id", "")
    short_id = page_id.replace("-", "")[-8:] if page_id else "unknown"

    return {
        "id": page.get("id"),
        "url": page.get("url"),
        "short_id": short_id,
        "title": _extract_field("Name", "title") or "Без названия",
        "text": _extract_field("Text", "rich_text") or "",
        "direction": _extract_field("Direction", "select") or "unknown",
        "assignees": _extract_field("Assignee", "multi_select") or [],
        "due_iso": _extract_field("Due", "date"),
        "confidence": _extract_field("Confidence", "number") or 0.0,
        "flags": _extract_field("Flags", "multi_select") or [],
        "status": _extract_field("Status", "select") or "open",
        "tags": _extract_field("Tags", "multi_select") or [],
        "meeting_ids": _extract_field("Meeting", "relation") or [],
    }


def query_commits_recent(limit: int = PAGE_SIZE) -> list[dict[str, Any]]:
    """Получает последние коммиты (все статусы для обзора)."""
    try:
        # Показываем все коммиты, включая выполненные, для полного обзора
        sorts = [{"property": "Due", "direction": "descending"}]

        response = _query_commits(sorts=sorts, page_size=limit)
        return [_map_commit_page(page) for page in response.get("results", [])]

    except Exception as e:
        logger.error(f"Error in query_commits_recent: {e}")
        return []


def query_commits_mine(
    me_name_en: str | None = None, limit: int = PAGE_SIZE
) -> list[dict[str, Any]]:
    """Получает мои коммиты (все статусы, сначала активные)."""
    try:
        me_name = me_name_en or settings.me_name_en

        # Получаем все алиасы из people.json
        search_variants = _get_person_aliases(me_name)

        # Фильтр: только мои коммиты (все статусы)
        filter_ = {
            "or": [
                {"property": "Assignee", "multi_select": {"contains": variant}}
                for variant in search_variants
            ]
        }

        # Сначала получаем активные коммиты
        active_filter = {
            "and": [
                filter_,
                {"property": "Status", "select": {"does_not_equal": "done"}},
                {"property": "Status", "select": {"does_not_equal": "dropped"}},
            ]
        }

        active_response = _query_commits(
            filter_=active_filter,
            sorts=[{"property": "Due", "direction": "ascending"}],
            page_size=limit,
        )
        active_commits = [_map_commit_page(page) for page in active_response.get("results", [])]

        # Если есть место, добавляем выполненные коммиты
        remaining_limit = limit - len(active_commits)
        completed_commits = []

        if remaining_limit > 0:
            completed_filter = {
                "and": [
                    filter_,
                    {
                        "or": [
                            {"property": "Status", "select": {"equals": "done"}},
                            {"property": "Status", "select": {"equals": "dropped"}},
                        ]
                    },
                ]
            }

            completed_response = _query_commits(
                filter_=completed_filter,
                sorts=[{"property": "Due", "direction": "descending"}],
                page_size=remaining_limit,
            )
            completed_commits = [
                _map_commit_page(page) for page in completed_response.get("results", [])
            ]

        # Объединяем: сначала активные, потом выполненные
        return active_commits + completed_commits

    except Exception as e:
        logger.error(f"Error in query_commits_mine: {e}")
        return []


def query_commits_mine_active(
    me_name_en: str | None = None, limit: int = PAGE_SIZE
) -> list[dict[str, Any]]:
    """Получает только активные мои коммиты (без done/dropped)."""
    try:
        me_name = me_name_en or settings.me_name_en

        # Получаем все алиасы из people.json
        search_variants = _get_person_aliases(me_name)

        # Создаем фильтр: мои коммиты + только активные
        filter_ = {
            "and": [
                {
                    "or": [
                        {"property": "Assignee", "multi_select": {"contains": variant}}
                        for variant in search_variants
                    ]
                },
                {"property": "Status", "select": {"does_not_equal": "done"}},
                {"property": "Status", "select": {"does_not_equal": "dropped"}},
            ]
        }

        sorts = [{"property": "Due", "direction": "ascending"}]

        response = _query_commits(filter_=filter_, sorts=sorts, page_size=limit)
        return [_map_commit_page(page) for page in response.get("results", [])]

    except Exception as e:
        logger.error(f"Error in query_commits_mine_active: {e}")
        return []


def query_commits_theirs(limit: int = PAGE_SIZE) -> list[dict[str, Any]]:
    """Получает чужие коммиты (direction=theirs)."""
    try:
        filter_ = {
            "and": [
                {"property": "Direction", "select": {"equals": "theirs"}},
                {"property": "Status", "select": {"does_not_equal": "done"}},
                {"property": "Status", "select": {"does_not_equal": "dropped"}},
            ]
        }

        sorts = [{"property": "Due", "direction": "ascending"}]

        response = _query_commits(filter_=filter_, sorts=sorts, page_size=limit)
        return [_map_commit_page(page) for page in response.get("results", [])]

    except Exception as e:
        logger.error(f"Error in query_commits_theirs: {e}")
        return []


def query_commits_due_within(days: int = 7, limit: int = PAGE_SIZE) -> list[dict[str, Any]]:
    """Получает коммиты с дедлайном в ближайшие N дней."""
    try:
        now = datetime.now(UTC).date()
        end_date = now + timedelta(days=days)

        filter_ = {
            "and": [
                {"property": "Due", "date": {"on_or_after": now.isoformat()}},
                {"property": "Due", "date": {"on_or_before": end_date.isoformat()}},
                {"property": "Status", "select": {"does_not_equal": "done"}},
                {"property": "Status", "select": {"does_not_equal": "dropped"}},
            ]
        }

        sorts = [{"property": "Due", "direction": "ascending"}]

        response = _query_commits(filter_=filter_, sorts=sorts, page_size=limit)
        return [_map_commit_page(page) for page in response.get("results", [])]

    except Exception as e:
        logger.error(f"Error in query_commits_due_within: {e}")
        return []


def query_commits_due_today(limit: int = PAGE_SIZE) -> list[dict[str, Any]]:
    """Получает коммиты с дедлайном сегодня."""
    try:
        today = datetime.now(UTC).date().isoformat()

        filter_ = {
            "and": [
                {"property": "Due", "date": {"equals": today}},
                {"property": "Status", "select": {"does_not_equal": "done"}},
                {"property": "Status", "select": {"does_not_equal": "dropped"}},
            ]
        }

        sorts = [{"property": "Due", "direction": "ascending"}]

        response = _query_commits(filter_=filter_, sorts=sorts, page_size=limit)
        return [_map_commit_page(page) for page in response.get("results", [])]

    except Exception as e:
        logger.error(f"Error in query_commits_due_today: {e}")
        return []


def query_commits_by_tag(tag: str, limit: int = PAGE_SIZE) -> list[dict[str, Any]]:
    """
    Получает коммиты по тегу.

    Args:
        tag: Тег для поиска (поддерживает частичное совпадение)
        limit: Максимальное количество результатов

    Returns:
        Список коммитов с указанным тегом
    """
    try:
        filter_ = {"property": "Tags", "multi_select": {"contains": tag}}

        sorts = [{"property": "Due", "direction": "ascending"}]

        response = _query_commits(filter_=filter_, sorts=sorts, page_size=limit)
        return [_map_commit_page(page) for page in response.get("results", [])]

    except Exception as e:
        logger.error(f"Error in query_commits_by_tag: {e}")
        return []


def query_commits_by_assignee(assignee_name: str, limit: int = PAGE_SIZE) -> list[dict[str, Any]]:
    """
    Получает коммиты по конкретному исполнителю.

    Args:
        assignee_name: Имя исполнителя для поиска
        limit: Максимальное количество результатов

    Returns:
        Список коммитов назначенных указанному исполнителю
    """
    try:
        # Получаем все алиасы для указанного имени
        search_variants = _get_person_aliases(assignee_name)

        # Создаем фильтр для поиска по исполнителю (все статусы)
        filter_ = {
            "or": [
                {"property": "Assignee", "multi_select": {"contains": variant}}
                for variant in search_variants
            ]
        }

        sorts = [{"property": "Due", "direction": "ascending"}]

        response = _query_commits(filter_=filter_, sorts=sorts, page_size=limit)
        return [_map_commit_page(page) for page in response.get("results", [])]

    except Exception as e:
        logger.error(f"Error in query_commits_by_assignee: {e}")
        return []


def update_commit_status(commit_id: str, status: str) -> bool:
    """
    Обновляет статус коммита в Notion.

    Args:
        commit_id: ID страницы коммита в Notion
        status: Новый статус ('done', 'dropped', 'open', etc.)

    Returns:
        True если обновление прошло успешно
    """
    with timer(MetricNames.NOTION_UPDATE_COMMIT_STATUS):
        client = _create_client()

        try:
            url = f"{NOTION_API}/pages/{commit_id}"

            # Подготавливаем payload для обновления статуса
            payload: dict[str, Any] = {"properties": {"Status": {"select": {"name": status}}}}

            logger.info(f"Updating commit {commit_id} status to '{status}'")

            response = client.patch(url, json=payload)

            if response.status_code == 200:
                logger.info(f"Successfully updated commit {commit_id} status to '{status}'")
                return True
            else:
                logger.error(
                    f"Failed to update commit status: {response.status_code} - {response.text}"
                )
                return False

        except Exception as e:
            logger.error(f"Error updating commit status: {e}")
            return False
        finally:
            client.close()
