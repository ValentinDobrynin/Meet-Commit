"""Gateway для работы с базой Agendas в Notion.

Обеспечивает создание и управление повестками для встреч, людей и тегов.
"""

from __future__ import annotations

import logging
from typing import Any, Literal

from app.core.clients import get_notion_http_client
from app.core.metrics import timer
from app.gateways.error_handling import notion_create, notion_query
from app.settings import settings

logger = logging.getLogger(__name__)

NOTION_API = "https://api.notion.com/v1"

# Типы контекста для повесток
ContextType = Literal["Meeting", "Person", "Tag"]


# Удалено: используем единый клиент из app.core.clients


def _build_agenda_properties(
    name: str,
    date_iso: str,
    context_type: ContextType,
    context_key: str,
    summary_md: str,
    tags: list[str],
    people: list[str],
    raw_hash: str,
    commit_ids: list[str] | None = None,
) -> dict[str, Any]:
    """Создает properties для страницы Agenda."""

    properties = {
        "Name": {"title": [{"text": {"content": name}}]},
        "Date": {"date": {"start": date_iso}},
        "Context type": {"select": {"name": context_type}},
        "Context key": {"rich_text": [{"text": {"content": context_key}}]},
        "Summary MD": {"rich_text": [{"text": {"content": summary_md[:2000]}}]},  # Лимит Notion
        "Tags": {"multi_select": [{"name": tag} for tag in tags]},
        "People": {"multi_select": [{"name": person} for person in people]},
        "Raw hash": {"rich_text": [{"text": {"content": raw_hash}}]},
    }

    # Добавляем связанные коммиты если указаны
    if commit_ids:
        properties["Commits linked"] = {"relation": [{"id": commit_id} for commit_id in commit_ids]}

    return properties


@notion_query("find_agenda_by_hash", fallback=None)  # Graceful fallback для стабильности
def find_agenda_by_hash(raw_hash: str) -> dict[str, Any] | None:
    """
    Ищет существующую повестку по хэшу для дедупликации.

    Args:
        raw_hash: Хэш исходных данных

    Returns:
        Данные страницы если найдена, иначе None (graceful fallback при ошибках API)
    """
    client = get_notion_http_client()

    try:
        payload = {
            "filter": {"property": "Raw hash", "rich_text": {"equals": raw_hash}},
            "page_size": 1,
        }

        response = client.post(
            f"{NOTION_API}/databases/{settings.agendas_db_id}/query", json=payload
        )
        response.raise_for_status()

        results = response.json().get("results", [])
        if results:
            logger.debug(f"Found existing agenda with hash: {raw_hash}")
            return results[0]  # type: ignore[no-any-return]
        else:
            logger.debug(f"No existing agenda found for hash: {raw_hash}")
            return None

    except Exception as e:
        logger.error(f"Error in find_agenda_by_hash: {e}")
        return None
    finally:
        client.close()


@notion_create("create_agenda")  # Strict handling для целостности данных
def create_agenda(
    name: str,
    date_iso: str,
    context_type: ContextType,
    context_key: str,
    summary_md: str,
    tags: list[str],
    people: list[str],
    raw_hash: str,
    commit_ids: list[str] | None = None,
) -> str:
    """
    Создает новую повестку в Notion.

    Args:
        name: Название повестки (Agenda — <контекст>)
        date_iso: Дата в формате YYYY-MM-DD
        context_type: Тип контекста (Meeting/Person/Tag)
        context_key: Ключ контекста (ID встречи или имя/тег)
        summary_md: Готовая повестка в Markdown
        tags: Список тегов
        people: Список участников
        raw_hash: Хэш для дедупликации
        commit_ids: ID связанных коммитов

    Returns:
        ID созданной страницы
    """
    with timer("notion.create_agenda"):
        # Проверяем дедупликацию
        existing = find_agenda_by_hash(raw_hash)
        if existing:
            logger.info(f"Agenda already exists for hash {raw_hash}, skipping creation")
            return str(existing["id"])

        client = get_notion_http_client()

        try:
            properties = _build_agenda_properties(
                name,
                date_iso,
                context_type,
                context_key,
                summary_md,
                tags,
                people,
                raw_hash,
                commit_ids,
            )

            payload = {"parent": {"database_id": settings.agendas_db_id}, "properties": properties}

            logger.info(
                f"Creating agenda: '{name}' ({context_type}) with {len(tags)} tags, {len(people)} people"
            )

            response = client.post(f"{NOTION_API}/pages", json=payload)

            if response.status_code == 200:
                page_id = response.json()["id"]
                logger.info(f"Agenda created successfully: {page_id}")
                return str(page_id)
            else:
                logger.error(f"Failed to create agenda: {response.status_code} - {response.text}")
                raise RuntimeError(f"Notion API error: {response.status_code}")

        except Exception as e:
            logger.error(f"Error creating agenda: {e}")
            raise
        finally:
            client.close()


@notion_query("query_agendas_by_context", fallback=[])  # Graceful fallback для стабильности
def query_agendas_by_context(
    context_type: ContextType, context_key: str | None = None, limit: int = 10
) -> list[dict[str, Any]]:
    """
    Получает повестки по типу контекста.

    Args:
        context_type: Тип контекста (Meeting/Person/Tag)
        context_key: Конкретный ключ контекста (опционально)
        limit: Максимальное количество результатов

    Returns:
        Список повесток (graceful fallback на [] при ошибках API)
    """
    with timer("notion.query_agendas"):
        client = get_notion_http_client()

        try:
            # Базовый фильтр по типу контекста
            filter_conditions = [{"property": "Context type", "select": {"equals": context_type}}]

            # Добавляем фильтр по ключу если указан
            if context_key:
                filter_conditions.append(
                    {"property": "Context key", "rich_text": {"contains": context_key}}
                )

            payload = {
                "filter": {"and": filter_conditions}
                if len(filter_conditions) > 1
                else filter_conditions[0],
                "sorts": [{"property": "Date", "direction": "descending"}],
                "page_size": limit,
            }

            response = client.post(
                f"{NOTION_API}/databases/{settings.agendas_db_id}/query", json=payload
            )
            response.raise_for_status()

            results = response.json().get("results", [])
            logger.info(
                f"Found {len(results)} agendas for {context_type}"
                + (f"/{context_key}" if context_key else "")
            )

            return results  # type: ignore[no-any-return]

        except Exception as e:
            logger.error(f"Error querying agendas: {e}")
            return []
        finally:
            client.close()


@notion_query("get_agenda_statistics", fallback={})  # Graceful fallback для статистики
def get_agenda_statistics() -> dict[str, Any]:
    """
    Получает статистику по повесткам.

    Returns:
        Словарь со статистикой (graceful fallback на {} при ошибках API)
    """
    client = get_notion_http_client()

    try:
        # Получаем все повестки
        response = client.post(
            f"{NOTION_API}/databases/{settings.agendas_db_id}/query", json={"page_size": 100}
        )
        response.raise_for_status()

        agendas = response.json().get("results", [])

        # Анализируем статистику
        stats: dict[str, Any] = {
            "total_agendas": len(agendas),
            "by_context_type": {"Meeting": 0, "Person": 0, "Tag": 0},
            "recent_agendas": [],
            "top_tags": {},
            "top_people": {},
        }

        for agenda in agendas:
            props = agenda.get("properties", {})

            # Тип контекста
            context_type = props.get("Context type", {}).get("select", {}).get("name", "Unknown")
            if context_type in stats["by_context_type"]:
                stats["by_context_type"][context_type] += 1

            # Последние повестки (топ-5)
            recent_agendas = stats["recent_agendas"]
            if len(recent_agendas) < 5:
                name = props.get("Name", {}).get("title", [{}])[0].get("plain_text", "Untitled")
                date = props.get("Date", {}).get("date", {}).get("start", "Unknown")
                recent_agendas.append({"name": name, "date": date, "type": context_type})

            # Топ теги
            tags = props.get("Tags", {}).get("multi_select", [])
            top_tags = stats["top_tags"]
            for tag in tags:
                tag_name = tag.get("name", "")
                if tag_name:
                    top_tags[tag_name] = top_tags.get(tag_name, 0) + 1

            # Топ участники
            people = props.get("People", {}).get("multi_select", [])
            top_people = stats["top_people"]
            for person in people:
                person_name = person.get("name", "")
                if person_name:
                    top_people[person_name] = top_people.get(person_name, 0) + 1

        # Сортируем топы
        stats["top_tags"] = dict(
            sorted(stats["top_tags"].items(), key=lambda x: x[1], reverse=True)[:10]
        )
        stats["top_people"] = dict(
            sorted(stats["top_people"].items(), key=lambda x: x[1], reverse=True)[:10]
        )

        return stats

    except Exception as e:
        logger.error(f"Error getting agenda statistics: {e}")
        return {}
    finally:
        client.close()


# Константы для экспорта
__all__ = [
    "create_agenda",
    "find_agenda_by_hash",
    "query_agendas_by_context",
    "get_agenda_statistics",
    "ContextType",
]
