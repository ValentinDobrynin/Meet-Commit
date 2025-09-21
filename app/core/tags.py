"""Унифицированная система тегирования с каноническими схемами тегов.

Единая точка входа: tag_text(text, *, kind="meeting|commit", meta: dict|None)

Канонические схемы тегов:
- People/<NameEn> - люди
- Finance/<Topic> - финансы
- Business/<Unit> - бизнес-единицы
- Projects/<Code> - проекты
- Topic/<Theme> - темы

Режимы работы:
- v0: только старый тэггер (с маппингом в канон)
- v1: только новый тэггер (уже в каноне)
- both: объединяет результаты с приоритетом v1
"""

from __future__ import annotations

import logging
import time
from functools import lru_cache
from typing import Any

from app.core.tagger import run as tagger_v0
from app.core.tagger_v1 import clear_cache as reload_rules_v1
from app.core.tagger_v1 import tag_text as tagger_v1
from app.settings import settings

logger = logging.getLogger(__name__)

# Валидные режимы и типы
VALID_MODES = {"v0", "v1", "both"}
VALID_KINDS = {"meeting", "commit"}

# Статистика использования
_stats: dict[str, Any] = {
    "calls_by_mode": {"v0": 0, "v1": 0, "both": 0},
    "calls_by_kind": {"meeting": 0, "commit": 0},
    "cache_hits": 0,
    "cache_misses": 0,
    "last_reload": None,
}


def _canonicalize_tag(tag: str) -> str:
    """Канонизирует тег: нормализует пробелы, приводит к стандартному формату."""
    return " ".join(tag.strip().split())


def _normalize_for_comparison(tag: str) -> str:
    """Нормализует тег для сравнения (lowercase, collapse spaces)."""
    return _canonicalize_tag(tag).lower().replace("_", " ").replace("-", " ")


# Маппинг v0 → v1 канон
V0_TO_V1_MAPPING = {
    # People mapping
    "person/sasha_katanov": "People/Sasha Katanov",
    "person/valentin_dobrynin": "People/Valentin Dobrynin",
    "person/daniil": "People/Daniil",
    # Finance mapping
    "area/ifrs": "Finance/IFRS",
    "area/audit": "Finance/Audit",
    "area/budget": "Finance/Budget",
    "project/budgets": "Finance/Budget",
    # Business mapping
    "area/lavka": "Business/Lavka",
    "area/kovcheg": "Business/Kovcheg",
    "area/alaska": "Business/Alaska",
    # Projects mapping
    "project/evm": "Projects/EVM",
    "project/integration": "Projects/Integration",
    # Topic mapping
    "topic/meeting": "Topic/Meeting",
    "topic/planning": "Topic/Planning",
    "topic/risk": "Topic/Risk",
    "topic/decision": "Topic/Decision",
    "topic/review": "Topic/Review",
    "topic/deadline": "Topic/Deadline",
}


def _map_v0_to_v1(tags_v0: set[str]) -> set[str]:
    """Маппит теги v0 в канонический формат v1."""
    mapped_tags: set[str] = set()

    for tag in tags_v0:
        # Прямой маппинг если есть
        if tag in V0_TO_V1_MAPPING:
            mapped_tags.add(V0_TO_V1_MAPPING[tag])
            logger.debug(f"Mapped v0 tag: {tag} → {V0_TO_V1_MAPPING[tag]}")
        else:
            # Попытка маппинга по префиксам
            if tag.startswith("person/"):
                # person/sasha_katanov → People/Sasha Katanov
                name_part = tag[7:].replace("_", " ").title()
                mapped_tags.add(f"People/{name_part}")
            elif tag.startswith("area/"):
                # area/ifrs → Finance/IFRS (если не маппится в Business)
                area_part = tag[5:].upper()
                if area_part in ["IFRS", "AUDIT", "BUDGET"]:
                    mapped_tags.add(f"Finance/{area_part}")
                else:
                    mapped_tags.add(f"Topic/{area_part.title()}")
            elif tag.startswith("project/"):
                # project/budgets → Finance/Budget
                project_part = tag[8:].title()
                mapped_tags.add(f"Projects/{project_part}")
            elif tag.startswith("topic/"):
                # topic/meeting → Topic/Meeting
                topic_part = tag[6:].title()
                mapped_tags.add(f"Topic/{topic_part}")
            else:
                # Fallback: добавляем как есть, но канонизируем
                mapped_tags.add(_canonicalize_tag(tag))

    return mapped_tags


def _merge_tags_with_priority(tags_v0: set[str], tags_v1: set[str]) -> list[str]:
    """Объединяет теги с приоритетом v1 и фильтрацией по префиксам."""
    # Маппим v0 теги в канон
    mapped_v0 = _map_v0_to_v1(tags_v0)

    # Строим индекс для сравнения
    v1_index: dict[str, str] = {}
    v0_index: dict[str, str] = {}

    # Индексируем v1 теги (приоритет)
    for tag in tags_v1:
        normalized = _normalize_for_comparison(tag)
        v1_index[normalized] = tag

    # Индексируем маппированные v0 теги
    for tag in mapped_v0:
        normalized = _normalize_for_comparison(tag)
        if normalized not in v1_index:  # Только если нет конфликта
            v0_index[normalized] = tag

    # Объединяем с фильтрацией
    result_tags: set[str] = set()

    # Добавляем все v1 теги
    result_tags.update(v1_index.values())

    # Добавляем v0 теги (People/* всегда, остальные по уникальности)
    for normalized, tag in v0_index.items():
        if tag.startswith("People/"):
            # People теги всегда добавляем
            result_tags.add(tag)
        elif normalized not in v1_index:
            # Остальные только если нет конфликта
            result_tags.add(tag)

    result = sorted(result_tags)
    logger.debug(
        f"Merge: v0={len(tags_v0)}→{len(mapped_v0)}, v1={len(tags_v1)}, result={len(result)}"
    )
    return result


def _validate_mode(mode: str) -> str:
    """Валидирует режим тегирования."""
    normalized = mode.lower().strip()
    if normalized not in VALID_MODES:
        logger.warning(f"Invalid tags mode '{mode}', using 'both'. Valid modes: {VALID_MODES}")
        return "both"
    return normalized


def _validate_kind(kind: str) -> str:
    """Валидирует тип тегирования."""
    normalized = kind.lower().strip()
    if normalized not in VALID_KINDS:
        logger.warning(f"Invalid tags kind '{kind}', using 'meeting'. Valid kinds: {VALID_KINDS}")
        return "meeting"
    return normalized


@lru_cache(maxsize=256)
def _tag_cached(mode: str, kind: str, text_hash: str, text: str) -> list[str]:
    """Кэшированная функция тегирования."""
    if not text or not text.strip():
        return []

    # Подготавливаем метаданные в зависимости от типа
    meta: dict[str, Any] = {"title": "", "attendees": []}

    try:
        if mode == "v0":
            # Только старый тэггер с маппингом в канон
            raw_tags = tagger_v0(text, meta)
            mapped_tags = _map_v0_to_v1(set(raw_tags))
            result = sorted(mapped_tags)
            logger.debug(f"v0 mode: {len(raw_tags)} raw → {len(result)} canonical tags")
            return result

        elif mode == "v1":
            # Только новый тэггер (уже в каноне)
            result = tagger_v1(text)
            logger.debug(f"v1 mode: found {len(result)} canonical tags")
            return result

        else:  # mode == "both"
            # Объединяем оба тэггера с приоритетом v1
            tags_v0 = set(tagger_v0(text, meta))
            tags_v1 = set(tagger_v1(text))

            result = _merge_tags_with_priority(tags_v0, tags_v1)
            logger.debug(f"both mode: v0={len(tags_v0)}, v1={len(tags_v1)}, merged={len(result)}")
            return result

    except Exception as e:
        logger.error(f"Error in _tag_cached with mode '{mode}', kind '{kind}': {e}")
        # Fallback к v0 при ошибках
        try:
            raw_tags = tagger_v0(text, meta)
            fallback_result = sorted(_map_v0_to_v1(set(raw_tags)))
            logger.warning(f"Fallback to v0 mode due to error, found {len(fallback_result)} tags")
            return fallback_result
        except Exception as fallback_error:
            logger.error(f"Fallback also failed: {fallback_error}")
            return []


def tag_text(text: str, *, kind: str = "meeting", meta: dict | None = None) -> list[str]:
    """Единая точка входа для тегирования."""
    if not text or not text.strip():
        return []

    # Валидируем параметры
    mode = _validate_mode(settings.tags_mode)
    kind = _validate_kind(kind)

    # Обновляем статистику
    _stats["calls_by_mode"][mode] += 1
    _stats["calls_by_kind"][kind] += 1

    # Создаем хеш для кэширования
    text_hash = str(hash((mode, kind, text)))

    # Проверяем кэш
    try:
        result = _tag_cached(mode, kind, text_hash, text)
        _stats["cache_hits"] += 1
        logger.debug(f"Cache hit for {mode}/{kind}, {len(result)} tags")
        return result
    except Exception:
        _stats["cache_misses"] += 1
        logger.debug(f"Cache miss for {mode}/{kind}")
        # Fallback без кэша
        return []


def tag_text_for_meeting(text: str, meta: dict[str, Any]) -> list[str]:
    """Специализированная функция для тегирования встреч."""
    return tag_text(text, kind="meeting", meta=meta)


def tag_text_for_commit(text: str) -> list[str]:
    """Специализированная функция для тегирования коммитов."""
    return tag_text(text, kind="commit")


def merge_meeting_and_commit_tags(meeting_tags: list[str], commit_tags: list[str]) -> list[str]:
    """Объединяет теги встречи и коммита с фильтрацией по префиксам."""
    if not meeting_tags and not commit_tags:
        return []

    # Разделяем теги по префиксам
    people_tags: set[str] = set()
    other_tags: set[str] = set()

    # Обрабатываем теги встречи
    for tag in meeting_tags:
        if tag.startswith("People/"):
            people_tags.add(tag)
        else:
            other_tags.add(tag)

    # Обрабатываем теги коммита
    for tag in commit_tags:
        if tag.startswith("People/"):
            people_tags.add(tag)
        else:
            other_tags.add(tag)

    # Объединяем и сортируем
    result = sorted(people_tags | other_tags)
    logger.debug(
        f"Merge tags: meeting={len(meeting_tags)}, commit={len(commit_tags)}, result={len(result)}"
    )
    return result


def reload_tags_rules() -> int:
    """Перезагружает правила тегирования в runtime."""
    try:
        # Очищаем кэш
        _tag_cached.cache_clear()

        # Перезагружаем правила v1
        reload_rules_v1()

        # Обновляем статистику
        _stats["last_reload"] = time.time()

        logger.info("Tags rules reloaded successfully")
        return 1
    except Exception as e:
        logger.error(f"Failed to reload tags rules: {e}")
        return 0


def get_tagging_stats() -> dict[str, Any]:
    """Возвращает статистику системы тегирования."""
    try:
        from app.core.tagger_v1 import get_rules_stats as get_v1_stats

        v1_stats = get_v1_stats()
        cache_info = _tag_cached.cache_info()

        return {
            "current_mode": settings.tags_mode,
            "valid_modes": list(VALID_MODES),
            "valid_kinds": list(VALID_KINDS),
            "stats": _stats.copy(),
            "cache_info": {
                "hits": cache_info.hits,
                "misses": cache_info.misses,
                "maxsize": cache_info.maxsize,
                "currsize": cache_info.currsize,
            },
            "v1_stats": v1_stats,
            "mapping_rules": len(V0_TO_V1_MAPPING),
        }
    except Exception as e:
        logger.error(f"Error getting tagging stats: {e}")
        return {
            "current_mode": settings.tags_mode,
            "valid_modes": list(VALID_MODES),
            "valid_kinds": list(VALID_KINDS),
            "stats": _stats.copy(),
            "error": str(e),
        }


def clear_cache() -> None:
    """Очищает кэш результатов тегирования."""
    _tag_cached.cache_clear()
    logger.info("Tagging cache cleared")


# CLI для тестирования
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m app.core.tags_v2 'текст для анализа' [kind]")
        print("Kind: meeting, commit (default: meeting)")
        print("\nExample:")
        print("python -m app.core.tags_v2 'Обсудили аудит IFRS для Lavka' meeting")
        sys.exit(1)

    test_text = sys.argv[1]
    test_kind = sys.argv[2] if len(sys.argv) > 2 else "meeting"

    print(f"\nТекст: {test_text}")
    print(f"Тип: {test_kind}")
    print(f"Режим: {settings.tags_mode}")

    tags = tag_text(test_text, kind=test_kind)
    print(f"Найденные теги ({len(tags)}):")
    for tag in tags:
        print(f"  - {tag}")

    print("\nСтатистика системы:")
    stats = get_tagging_stats()
    for key, value in stats.items():
        if key != "v1_stats":
            print(f"  {key}: {value}")

    if "v1_stats" in stats:
        print("  v1_stats:")
        for k, v in stats["v1_stats"].items():
            print(f"    {k}: {v}")
