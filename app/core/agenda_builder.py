"""
Система сборки повесток из коммитов и задач на ревью.

Поддерживает три режима:
- Meeting: повестка по конкретной встрече
- Person: персональная повестка (входящие и исходящие коммиты)
- Tag: тематическая повестка по тегу

Интегрирована с системой метрик и существующими gateway.
"""

from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from app.core.clients import get_notion_http_client
from app.core.metrics import timer
from app.gateways.notion_commits import _map_commit_page
from app.settings import settings

logger = logging.getLogger(__name__)

NOTION_API = "https://api.notion.com/v1"


@dataclass
class AgendaBundle:
    """Структура данных для повестки."""

    context_type: str  # Meeting/Person/Tag
    context_key: str  # meeting_id или People/Name или tag
    debts_mine: list[dict[str, Any]]  # Мои обязательства
    debts_theirs: list[dict[str, Any]]  # Их обязательства
    review_open: list[dict[str, Any]]  # Открытые вопросы на ревью
    recent_done: list[dict[str, Any]]  # Недавно выполненные
    commits_linked: list[str]  # ID коммитов для relation
    summary_md: str  # Markdown содержимое
    tags: list[str]  # Теги для повестки
    people: list[str]  # Участники
    raw_hash: str  # Хеш для дедупликации


def _query_commits(
    filter_: dict[str, Any], sorts: list[dict] | None = None, page_size: int = 50
) -> list[dict[str, Any]]:
    """Запрос коммитов из Notion с использованием существующего паттерна."""
    if not settings.commits_db_id:
        return []  # Graceful fallback если база Commits не настроена

    client = get_notion_http_client()
    try:
        payload: dict[str, Any] = {
            "page_size": page_size,
            "filter": filter_,
        }

        if sorts:
            payload["sorts"] = sorts
        else:
            payload["sorts"] = [{"property": "Due", "direction": "ascending"}]

        response = client.post(
            f"{NOTION_API}/databases/{settings.commits_db_id}/query", json=payload
        )
        response.raise_for_status()

        results = response.json().get("results", [])
        return [_map_commit_page(page) for page in results]

    except Exception as e:
        # Логируем ошибку, но не прерываем работу
        import logging

        logger = logging.getLogger(__name__)
        logger.warning(f"Commits database query failed: {e}. Returning empty results.")
        return []

    finally:
        client.close()


def _query_review(filter_: dict[str, Any], page_size: int = 50) -> list[dict[str, Any]]:
    """Запрос элементов ревью из Notion."""
    if not settings.review_db_id:
        return []  # Graceful fallback если база Review не настроена

    client = get_notion_http_client()
    try:
        payload = {
            "page_size": page_size,
            "filter": filter_,
            "sorts": [{"timestamp": "last_edited_time", "direction": "descending"}],
        }

        response = client.post(
            f"{NOTION_API}/databases/{settings.review_db_id}/query", json=payload
        )
        response.raise_for_status()

        results = response.json().get("results", [])
        return [_map_review_page(page) for page in results]

    except Exception as e:
        # Логируем ошибку, но не прерываем работу
        import logging

        logger = logging.getLogger(__name__)
        logger.warning(f"Review database query failed: {e}. Continuing without review data.")
        return []

    finally:
        client.close()


def _map_review_page(page: dict[str, Any]) -> dict[str, Any]:
    """Преобразование страницы ревью в стандартный формат."""
    props = page["properties"]

    def _extract_field(field_name: str, field_type: str) -> Any:
        field = props.get(field_name, {})
        if field_type == "rich_text":
            return "".join(item.get("plain_text", "") for item in field.get("rich_text", []))
        elif field_type == "select":
            select_value = field.get("select")
            return select_value.get("name") if select_value else None
        elif field_type == "multi_select":
            return [item["name"] for item in field.get("multi_select", [])]
        elif field_type == "relation":
            return [item["id"] for item in field.get("relation", [])]
        return field.get(field_type)

    return {
        "id": page["id"],
        "url": page.get("url", ""),
        "text": _extract_field("Commit text", "rich_text"),
        "reason": _extract_field("Reason", "rich_text"),  # В Review это rich_text, не multi_select
        "tags": [],  # В Review нет поля Tags, оставляем пустым
        "status": _extract_field("Status", "select"),
        "meeting_ids": _extract_field("Meeting", "relation"),
        "context": _extract_field("Context", "rich_text"),  # Добавляем Context
    }


def _format_commit_line(commit: dict[str, Any], *, show_requester: bool = False) -> str:
    """Форматирование строки коммита для повестки."""
    assignees = commit.get("assignees", [])
    from_person = commit.get("from_person", [])

    # Определяем кого показывать
    if show_requester:
        who = ", ".join(from_person) if from_person else "—"
        who_emoji = "💼"  # Заказчик
    else:
        who = ", ".join(assignees) if assignees else "—"
        who_emoji = "👤"  # Исполнитель

    due = commit.get("due_date") or "—"
    status_emoji = {"open": "🟥", "done": "✅", "dropped": "❌"}.get(
        commit.get("status", "open"), "⬜"
    )

    return f"{status_emoji} {commit['text']} — {who_emoji} {who} | ⏳ {due}"


def _format_review_line(review: dict[str, Any]) -> str:
    """Форматирование строки ревью для повестки."""
    reason = review.get("reason", "")
    reason_text = f" ({reason})" if reason else ""
    return f"❓ {review['text']}{reason_text}"


def _extract_tags_and_people(
    commits: list[dict[str, Any]], reviews: list[dict[str, Any]]
) -> tuple[list[str], list[str]]:
    """Извлечение тегов и участников из коммитов и ревью."""
    tags = set()
    people = set()

    for commit in commits:
        tags.update(commit.get("tags", []))
        people.update(commit.get("assignees", []))

    for review in reviews:
        tags.update(review.get("tags", []))

    return sorted(list(tags)), sorted(list(people))


def _generate_hash(
    context_type: str, context_key: str, commits: list[dict], reviews: list[dict]
) -> str:
    """Генерация хеша для дедупликации повесток."""
    content = f"{context_type}:{context_key}"
    commit_ids = sorted([c["id"] for c in commits])
    review_ids = sorted([r["id"] for r in reviews])
    content += f":{','.join(commit_ids)}:{','.join(review_ids)}"

    return hashlib.sha256(content.encode()).hexdigest()[:16]


@timer("agenda.build_meeting")
def build_for_meeting(meeting_id: str) -> AgendaBundle:
    """Построение повестки для встречи."""
    # Коммиты связанные с встречей
    commits_filter = {"property": "Meeting", "relation": {"contains": meeting_id}}
    commits = _query_commits(commits_filter)

    # Ревью связанные с встречей
    review_filter = {"property": "Meeting", "relation": {"contains": meeting_id}}
    reviews = _query_review(review_filter)

    # Формирование содержимого
    md_parts = []
    if commits:
        md_parts.append("🧾 <b>Коммиты встречи</b>")
        md_parts.extend(_format_commit_line(c) for c in commits)

    if reviews:
        md_parts.append("\n❓ <b>Открытые вопросы</b>")
        md_parts.extend(_format_review_line(r) for r in reviews)

    tags, people = _extract_tags_and_people(commits, reviews)
    linked_ids = [c["id"] for c in commits]
    raw_hash = _generate_hash("Meeting", meeting_id, commits, reviews)

    return AgendaBundle(
        context_type="Meeting",
        context_key=meeting_id,
        debts_mine=commits,
        debts_theirs=[],
        review_open=reviews,
        recent_done=[],
        commits_linked=linked_ids,
        summary_md="\n".join(md_parts) if md_parts else "📋 Повестка пуста",
        tags=tags,
        people=people,
        raw_hash=raw_hash,
    )


@timer("agenda.build_person")
def build_for_person(person_name_en: str) -> AgendaBundle:
    """Построение персональной повестки."""
    # Мои обязательства перед этим человеком (задачи, которые я взял)
    mine_filter = {
        "and": [
            {
                "property": "From",
                "multi_select": {"contains": person_name_en},
            },  # Заказчик = этот человек
            {"property": "Status", "select": {"does_not_equal": "done"}},
            {"property": "Status", "select": {"does_not_equal": "dropped"}},
        ]
    }
    debts_mine = _query_commits(mine_filter)

    # Их обязательства (задачи, которые должен выполнить этот человек)
    theirs_filter = {
        "and": [
            {
                "property": "Assignee",
                "multi_select": {"contains": person_name_en},
            },  # Исполнитель = этот человек
            {"property": "Status", "select": {"does_not_equal": "done"}},
            {"property": "Status", "select": {"does_not_equal": "dropped"}},
        ]
    }
    debts_theirs = _query_commits(theirs_filter)

    # Ревью связанные с этим человеком (через Assignee)
    review_filter = {"property": "Assignee", "multi_select": {"contains": person_name_en}}
    reviews = _query_review(review_filter)

    # Недавно выполненные (последние 7 дней)
    since_date = (datetime.now(UTC) - timedelta(days=7)).date().isoformat()
    done_filter = {
        "and": [
            {
                "or": [
                    {"property": "Assignee", "multi_select": {"contains": person_name_en}},
                    {"property": "Tags", "multi_select": {"contains": f"People/{person_name_en}"}},
                ]
            },
            {"property": "Status", "select": {"equals": "done"}},
            {"timestamp": "last_edited_time", "last_edited_time": {"on_or_after": since_date}},
        ]
    }
    recent_done = _query_commits(
        done_filter, sorts=[{"timestamp": "last_edited_time", "direction": "descending"}]
    )

    # Формирование содержимого
    md_parts = []

    if debts_mine:
        md_parts.append(f"📋 <b>Задачи от {person_name_en} (заказчик)</b>")
        md_parts.extend(_format_commit_line(c) for c in debts_mine)

    if debts_theirs:
        md_parts.append(f"\n📤 <b>Задачи для {person_name_en} (исполнитель)</b>")
        md_parts.extend(_format_commit_line(c, show_requester=True) for c in debts_theirs)

    if reviews:
        md_parts.append("\n❓ <b>Открытые вопросы</b>")
        md_parts.extend(_format_review_line(r) for r in reviews)

    if recent_done:
        md_parts.append("\n✅ <b>Выполнено за неделю</b>")
        md_parts.extend(_format_commit_line(c) for c in recent_done[:5])  # Ограничиваем до 5

    all_commits = debts_mine + debts_theirs + recent_done
    tags, people = _extract_tags_and_people(all_commits, reviews)
    linked_ids = [c["id"] for c in debts_mine + debts_theirs]
    raw_hash = _generate_hash("Person", f"People/{person_name_en}", all_commits, reviews)

    return AgendaBundle(
        context_type="Person",
        context_key=f"People/{person_name_en}",
        debts_mine=debts_mine,
        debts_theirs=debts_theirs,
        review_open=reviews,
        recent_done=recent_done,
        commits_linked=linked_ids,
        summary_md="\n".join(md_parts) if md_parts else "📋 Повестка пуста",
        tags=tags,
        people=people,
        raw_hash=raw_hash,
    )


@timer("agenda.build_tag")
def build_for_tag(tag: str) -> AgendaBundle:
    """Построение тематической повестки по тегу."""
    # Активные коммиты по тегу
    commits_filter = {
        "and": [
            {"property": "Tags", "multi_select": {"contains": tag}},
            {"property": "Status", "select": {"does_not_equal": "done"}},
            {"property": "Status", "select": {"does_not_equal": "dropped"}},
        ]
    }
    commits = _query_commits(commits_filter)

    # Ревью по тегу - используем Context field для поиска упоминаний тега
    review_filter = {"property": "Context", "rich_text": {"contains": tag}}
    reviews = _query_review(review_filter)

    # Недавно выполненные по тегу
    since_date = (datetime.now(UTC) - timedelta(days=7)).date().isoformat()
    done_filter = {
        "and": [
            {"property": "Tags", "multi_select": {"contains": tag}},
            {"property": "Status", "select": {"equals": "done"}},
            {"timestamp": "last_edited_time", "last_edited_time": {"on_or_after": since_date}},
        ]
    }
    recent_done = _query_commits(
        done_filter, sorts=[{"timestamp": "last_edited_time", "direction": "descending"}]
    )

    # Формирование содержимого
    md_parts = []

    if commits:
        md_parts.append(f"🏷️ <b>Активные задачи по {tag}</b>")
        md_parts.extend(_format_commit_line(c) for c in commits)

    if reviews:
        md_parts.append("\n❓ <b>Открытые вопросы</b>")
        md_parts.extend(_format_review_line(r) for r in reviews)

    if recent_done:
        md_parts.append("\n✅ <b>Выполнено за неделю</b>")
        md_parts.extend(_format_commit_line(c) for c in recent_done[:10])  # Больше для тематических

    all_commits = commits + recent_done
    tags, people = _extract_tags_and_people(all_commits, reviews)
    linked_ids = [c["id"] for c in commits]
    raw_hash = _generate_hash("Tag", tag, all_commits, reviews)

    return AgendaBundle(
        context_type="Tag",
        context_key=tag,
        debts_mine=commits,
        debts_theirs=[],
        review_open=reviews,
        recent_done=recent_done,
        commits_linked=linked_ids,
        summary_md="\n".join(md_parts) if md_parts else "📋 Повестка пуста",
        tags=tags,
        people=people,
        raw_hash=raw_hash,
    )
