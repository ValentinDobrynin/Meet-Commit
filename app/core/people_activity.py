"""
Анализ активности людей в системе коммитов.
Используется для ранжирования в agenda и других функциях.
"""

from __future__ import annotations

import logging
from collections import defaultdict
from typing import Any

from app.core.smart_caching import lru_cache_with_ttl
from app.gateways.notion_commits import query_commits_all

logger = logging.getLogger(__name__)


def _extract_people_from_commits(commits: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    """
    Извлекает статистику людей из коммитов с нормализацией имен.

    Args:
        commits: Список коммитов из Notion

    Returns:
        Словарь: {normalized_person_name: {"assignee": count, "from_person": count}}
    """
    from app.core.commit_normalize import normalize_assignees

    people_stats: dict[str, dict[str, int]] = defaultdict(lambda: {"assignee": 0, "from_person": 0})

    for commit in commits:
        # Обрабатываем исполнителей с нормализацией
        assignees = commit.get("assignees", [])
        if isinstance(assignees, list):
            # Нормализуем все имена исполнителей
            normalized_assignees = normalize_assignees(assignees, [])
            for assignee in normalized_assignees:
                if assignee and isinstance(assignee, str):
                    people_stats[assignee]["assignee"] += 1

        # Обрабатываем заказчиков с нормализацией
        from_persons = commit.get("from_person", [])
        if isinstance(from_persons, list):
            # Нормализуем все имена заказчиков
            normalized_from_persons = normalize_assignees(from_persons, [])
            for from_person in normalized_from_persons:
                if from_person and isinstance(from_person, str):
                    people_stats[from_person]["from_person"] += 1

    return dict(people_stats)


def calculate_person_score(person: str, stats: dict[str, int]) -> float:
    """
    Вычисляет score активности человека.

    Args:
        person: Имя человека
        stats: Статистика {"assignee": count, "from_person": count}

    Returns:
        Score активности (чем больше, тем активнее)
    """
    assignee_count = stats.get("assignee", 0) or 0
    from_person_count = stats.get("from_person", 0) or 0

    # Защита от некорректных типов
    try:
        assignee_count = int(assignee_count)
        from_person_count = int(from_person_count)
    except (ValueError, TypeError):
        assignee_count = 0
        from_person_count = 0

    # Умный алгоритм с весами
    score = (
        assignee_count * 2.0  # Исполнители важнее (делают работу)
        + from_person_count * 1.5  # Заказчики тоже важны (ставят задачи)
    )

    return score


@lru_cache_with_ttl(maxsize=1, ttl_seconds=86400)  # 24 часа кэш
def get_people_activity_stats() -> dict[str, dict[str, int]]:
    """
    Получает статистику активности всех людей (кэшированная).

    Returns:
        Словарь: {person_name: {"assignee": count, "from_person": count}}
    """
    try:
        logger.info("Calculating people activity stats from Commits database")

        # Получаем все коммиты
        all_commits = query_commits_all()

        # Извлекаем статистику людей
        people_stats = _extract_people_from_commits(all_commits)

        logger.info(f"People activity calculated: {len(people_stats)} people found")
        return people_stats

    except Exception as e:
        logger.error(f"Error calculating people activity: {e}")
        # Fallback - пустая статистика
        return {}


def get_top_people_by_activity(
    min_count: int = 3, max_count: int = 8, min_score: float = 1.0
) -> list[str]:
    """
    Получает топ людей по активности с адаптивным количеством.

    Args:
        min_count: Минимальное количество людей для показа
        max_count: Максимальное количество людей для показа
        min_score: Минимальный score для включения в топ

    Returns:
        Список имен людей, отсортированный по активности (убывание)
    """
    try:
        people_stats = get_people_activity_stats()

        if not people_stats:
            logger.warning("No people activity data, using fallback")
            return get_fallback_top_people()

        # Вычисляем scores для всех людей
        people_scores = []
        excluded_system_names = {"System", "Unknown", "Bot", "Auto", ""}
        excluded_owner_names = {
            "Valya Dobrynin",
            "Valentin Dobrynin",
            "Valentin",
            "Валентин",
            "Валя",
            "Val",
        }

        for person, stats in people_stats.items():
            # Фильтруем системные имена
            if person in excluded_system_names:
                continue

            # Фильтруем владельца (для него есть /mine команда)
            if person in excluded_owner_names:
                continue

            score = calculate_person_score(person, stats)
            if score >= min_score:  # Фильтруем по минимальному score
                people_scores.append((person, score))

        # Сортируем по score (убывание)
        people_scores.sort(key=lambda x: x[1], reverse=True)

        # Применяем адаптивные лимиты
        actual_count = len(people_scores)
        if actual_count < min_count:
            # Если людей меньше min_count, используем fallback
            logger.warning(f"Only {actual_count} people found, using fallback")
            return get_fallback_top_people()[:min_count]

        count = min(max_count, actual_count)
        top_people = [person for person, score in people_scores[:count]]

        logger.info(
            f"Top people selected: {len(top_people)} from {len(people_scores)} active people"
        )
        return top_people

    except Exception as e:
        logger.error(f"Error getting top people: {e}")
        return get_fallback_top_people()


def get_other_people(exclude_top: list[str]) -> list[str]:
    """
    Получает всех остальных людей из Commits (кроме топа).

    Args:
        exclude_top: Список людей для исключения (уже показанные в топе)

    Returns:
        Алфавитно отсортированный список остальных людей
    """
    try:
        people_stats = get_people_activity_stats()

        # Фильтруем людей с активностью > 0, исключая топ и владельца
        other_people = []
        exclude_set = set(exclude_top)
        excluded_owner_names = {
            "Valya Dobrynin",
            "Valentin Dobrynin",
            "Valentin",
            "Валентин",
            "Валя",
            "Val",
        }

        for person, stats in people_stats.items():
            if person not in exclude_set and person not in excluded_owner_names:
                total_activity = stats.get("assignee", 0) + stats.get("from_person", 0)
                if total_activity > 0:
                    other_people.append(person)

        # Алфавитная сортировка
        other_people.sort()

        logger.info(
            f"Other people found: {len(other_people)} (excluding {len(exclude_top)} top people)"
        )
        return other_people

    except Exception as e:
        logger.error(f"Error getting other people: {e}")
        return []


def get_fallback_top_people() -> list[str]:
    """
    Fallback список топ людей если нет статистики.
    Исключает владельца (Valya Dobrynin) - для него есть /mine команда.

    Returns:
        Базовый список активных людей
    """
    return ["Nodari Kezua", "Sergey Lompa", "Vlad Sklyanov", "Sasha Katanov", "Daniil"]


def get_person_activity_summary(person: str) -> dict[str, Any]:
    """
    Получает детальную сводку активности человека.

    Args:
        person: Имя человека

    Returns:
        Словарь с детальной статистикой
    """
    try:
        people_stats = get_people_activity_stats()
        stats = people_stats.get(person, {"assignee": 0, "from_person": 0})

        score = calculate_person_score(person, stats)
        total_activity = stats["assignee"] + stats["from_person"]

        return {
            "person": person,
            "assignee_count": stats["assignee"],
            "from_person_count": stats["from_person"],
            "total_activity": total_activity,
            "activity_score": score,
            "rank": _get_person_rank(person),
        }

    except Exception as e:
        logger.error(f"Error getting activity summary for {person}: {e}")
        return {
            "person": person,
            "assignee_count": 0,
            "from_person_count": 0,
            "total_activity": 0,
            "activity_score": 0.0,
            "rank": "unknown",
        }


def _get_person_rank(person: str) -> int:
    """Получает ранг человека в общем рейтинге."""
    try:
        top_people = get_top_people_by_activity(min_count=1, max_count=100, min_score=0)
        if person in top_people:
            return top_people.index(person) + 1
        return len(top_people) + 1
    except Exception:
        return 0


def clear_people_activity_cache() -> None:
    """Очищает кэш активности людей."""
    get_people_activity_stats.cache_clear()
    logger.info("People activity cache cleared")


def get_cache_info() -> dict[str, Any]:
    """Получает информацию о кэше активности людей."""
    try:
        cache_info = get_people_activity_stats.cache_info()
        return {
            "hits": cache_info.get("hits", 0),
            "misses": cache_info.get("misses", 0),
            "size": cache_info.get("size", 0),
            "ttl_seconds": 86400,  # 24 часа
        }
    except Exception:
        return {"status": "no_cache_info"}


__all__ = [
    "get_people_activity_stats",
    "get_top_people_by_activity",
    "get_other_people",
    "get_fallback_top_people",
    "get_person_activity_summary",
    "calculate_person_score",
    "clear_people_activity_cache",
    "get_cache_info",
]
