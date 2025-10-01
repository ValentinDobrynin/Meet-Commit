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

from app.core.metrics import MetricNames, integrate_with_tags_stats, timer
from app.core.tagger import run as tagger_v0
from app.core.tagger_v1_scored import reload_rules
from app.core.tagger_v1_scored import tag_text as tagger_v1
from app.core.tagger_v1_scored import tag_text_scored as tagger_v1_scored
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
    "total_calls": 0,
    "start_time": time.time(),
    "performance": {
        "avg_response_time": 0.0,
        "total_response_time": 0.0,
        "call_count": 0,
    },
    "top_tags": {},  # tag -> count
    "deduplication": {
        "v0_tags_total": 0,
        "v1_tags_total": 0,
        "merged_tags_total": 0,
        "duplicates_removed": 0,
        "people_tags_preserved": 0,
        "v1_priority_wins": 0,
    },
    "inheritance": {
        "meeting_tags_total": 0,
        "commit_tags_total": 0,
        "inherited_tags": 0,
        "duplicates_removed": 0,
        "people_inherited": 0,
        "business_inherited": 0,
        "projects_inherited": 0,
        "finance_inherited": 0,
        "topic_inherited": 0,
    },
}


def _canonicalize_tag(tag: str) -> str:
    """Канонизирует тег: нормализует пробелы, приводит к стандартному формату."""
    return " ".join(tag.strip().split())


def _normalize_for_comparison(tag: str) -> str:
    """Улучшенная нормализация тега для сравнения.

    Приводит теги к единому формату для дедупликации:
    - Убирает префиксы (person/, area/, project/, topic/)
    - Нормализует разделители (/, -, _ → пробел)
    - Приводит к lowercase
    - Убирает лишние пробелы
    """
    # Убираем префиксы для сравнения
    normalized = tag.lower()
    for prefix in [
        "person/",
        "area/",
        "project/",
        "topic/",
        "people/",
        "finance/",
        "business/",
        "projects/",
    ]:
        if normalized.startswith(prefix):
            normalized = normalized[len(prefix) :]
            break

    # Нормализуем разделители
    normalized = normalized.replace("/", " ").replace("-", " ").replace("_", " ")

    # Убираем лишние пробелы
    return " ".join(normalized.split())


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
    """
    Объединение тегов с использованием нового dedup_fuse модуля.

    Заменяет старую логику на новую детерминированную систему дедупликации
    с улучшенными метриками и специальной обработкой People/* тегов.
    """
    from app.core.tags_dedup import dedup_fuse

    # Маппим v0 теги в канон для совместимости
    mapped_v0 = _map_v0_to_v1(tags_v0)

    # Используем новую систему дедупликации
    result, metrics = dedup_fuse(mapped_v0, tags_v1)

    # Обновляем существующие метрики для обратной совместимости
    _stats["deduplication"]["v0_tags_total"] += metrics.total_v0
    _stats["deduplication"]["v1_tags_total"] += metrics.total_v1
    _stats["deduplication"]["merged_tags_total"] += metrics.unique_result
    _stats["deduplication"]["duplicates_removed"] += metrics.conflicts_resolved
    _stats["deduplication"]["people_tags_preserved"] += metrics.people_tags_preserved
    _stats["deduplication"]["v1_priority_wins"] += metrics.v1_priority_wins

    # Логируем детальные метрики новой системы
    logger.debug(f"New dedup system metrics: {metrics.as_dict()}")

    # Логируем совместимость со старой системой
    logger.info(
        f"Smart dedup: v0={len(tags_v0)}→{len(mapped_v0)}, v1={len(tags_v1)}, "
        f"result={len(result)}, conflicts_resolved={metrics.conflicts_resolved}, "
        f"people_preserved={metrics.people_tags_preserved}, v1_wins={metrics.v1_priority_wins}"
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
def _tag_cached(
    mode: str, kind: str, text_hash: str, text: str, meta_json: str = "{}"
) -> list[str]:
    """Кэшированная функция тегирования."""
    if not text or not text.strip():
        return []

    # Восстанавливаем метаданные из JSON
    import json

    try:
        meta: dict[str, Any] = json.loads(meta_json)
    except (json.JSONDecodeError, TypeError):
        meta = {"title": "", "attendees": []}

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


def tag_text(
    text: str, *, kind: str = "meeting", meta: dict | None = None, mode: str | None = None
) -> list[str]:
    """
    Единая точка входа для тегирования.

    Args:
        text: Текст для анализа
        kind: Тип контента ("meeting" или "commit")
        meta: Метаданные (опционально)
        mode: Режим тегирования ("v0", "v1", "both"), если None - берется из настроек

    Returns:
        Список канонических тегов
    """
    if not text or not text.strip():
        return []

    with timer(MetricNames.TAGGING_TAG_TEXT):
        start_time = time.time()

        # Валидируем параметры
        mode = _validate_mode(mode or settings.tags_mode)
        kind = _validate_kind(kind)

        # Обновляем статистику
        _stats["calls_by_mode"][mode] += 1
        _stats["calls_by_kind"][kind] += 1
        _stats["total_calls"] += 1

        # Подготавливаем meta для кэширования
        import json

        meta_to_use = meta or {"title": "", "attendees": []}
        meta_json = json.dumps(meta_to_use, sort_keys=True, ensure_ascii=False)

        # Создаем хеш для кэширования (включая meta)
        text_hash = str(hash((mode, kind, text, meta_json)))

        # Проверяем кэш
        try:
            result = _tag_cached(mode, kind, text_hash, text, meta_json)
            _stats["cache_hits"] += 1

            # Обновляем статистику топ тегов
            for tag in result:
                _stats["top_tags"][tag] = _stats["top_tags"].get(tag, 0) + 1

            # Обновляем производительность
            response_time = time.time() - start_time
            _stats["performance"]["total_response_time"] += response_time
            _stats["performance"]["call_count"] += 1
            _stats["performance"]["avg_response_time"] = (
                _stats["performance"]["total_response_time"] / _stats["performance"]["call_count"]
            )

            # Интегрируем с новой системой метрик
            integrate_with_tags_stats(_stats)

            logger.debug(
                f"Cache hit for {mode}/{kind}, {len(result)} tags, {response_time*1000:.1f}ms"
            )
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


def tag_text_scored(text: str, *, kind: str = "meeting") -> list[tuple[str, float]]:
    """
    Возвращает теги с оценками уверенности.

    Args:
        text: Текст для анализа
        kind: Тип контента ("meeting" или "commit")

    Returns:
        Список кортежей (tag, score), отсортированный по убыванию score

    Example:
        >>> tag_text_scored("Обсудили IFRS аудит дважды")
        [("Finance/IFRS", 2.4), ("Finance/Audit", 1.0)]
    """
    if not text or not text.strip():
        return []

    # Валидируем параметры
    mode = _validate_mode(settings.tags_mode)
    kind = _validate_kind(kind)

    # Обновляем статистику
    _stats["calls_by_mode"][mode] += 1
    _stats["calls_by_kind"][kind] += 1

    try:
        if mode == "v1" or mode == "both":
            # Используем scored версию v1 тэггера
            return tagger_v1_scored(text)
        else:
            # Для v0 режима возвращаем теги с score=1.0
            tags_v0 = tagger_v0(text, {"title": "", "attendees": []})
            mapped_tags = _map_v0_to_v1(set(tags_v0))
            return [(tag, 1.0) for tag in sorted(mapped_tags)]

    except Exception as e:
        logger.error(f"Error in tag_text_scored: {e}")
        return []


def merge_meeting_and_commit_tags(meeting_tags: list[str], commit_tags: list[str]) -> list[str]:
    """Улучшенное объединение тегов встречи и коммита с умной дедупликацией и наследованием."""
    if not meeting_tags and not commit_tags:
        return []

    # Счетчики для метрик
    inherited_tags = 0
    duplicates_removed = 0
    people_inherited = 0
    business_inherited = 0
    projects_inherited = 0
    finance_inherited = 0
    topic_inherited = 0

    # Строим индекс для дедупликации
    result_index: dict[str, str] = {}

    # 1) Добавляем теги коммита (приоритет)
    for tag in commit_tags:
        normalized = _normalize_for_comparison(tag)
        result_index[normalized] = tag

    # 2) Добавляем теги встречи с умной логикой наследования
    for tag in meeting_tags:
        normalized = _normalize_for_comparison(tag)

        if normalized in result_index:
            # Дубликат: коммит имеет приоритет
            duplicates_removed += 1
            logger.debug(f"Commit priority: '{tag}' → '{result_index[normalized]}'")
        else:
            # Нет дубликата, проверяем логику наследования
            should_inherit = False

            if tag.startswith("People/"):
                # People теги: наследуем только если у коммита нет People тегов
                has_people_in_commit = any(t.startswith("People/") for t in commit_tags)
                if not has_people_in_commit:
                    should_inherit = True
                    people_inherited += 1
                    logger.debug(f"People inherited: '{tag}'")
            elif tag.startswith("Business/") or tag.startswith("Projects/"):
                # Business/Projects теги: всегда наследуем
                should_inherit = True
                if tag.startswith("Business/"):
                    business_inherited += 1
                else:
                    projects_inherited += 1
                logger.debug(f"Business/Projects inherited: '{tag}'")
            elif tag.startswith("Finance/") or tag.startswith("Topic/"):
                # Finance/Topic теги: наследуем с приоритетом коммита
                should_inherit = True
                if tag.startswith("Finance/"):
                    finance_inherited += 1
                else:
                    topic_inherited += 1
                logger.debug(f"Finance/Topic inherited: '{tag}'")

            if should_inherit:
                result_index[normalized] = tag
                inherited_tags += 1

    # Обновляем метрики наследования
    _stats["inheritance"]["meeting_tags_total"] += len(meeting_tags)
    _stats["inheritance"]["commit_tags_total"] += len(commit_tags)
    _stats["inheritance"]["inherited_tags"] += inherited_tags
    _stats["inheritance"]["duplicates_removed"] += duplicates_removed
    _stats["inheritance"]["people_inherited"] += people_inherited
    _stats["inheritance"]["business_inherited"] += business_inherited
    _stats["inheritance"]["projects_inherited"] += projects_inherited
    _stats["inheritance"]["finance_inherited"] += finance_inherited
    _stats["inheritance"]["topic_inherited"] += topic_inherited

    result = sorted(result_index.values())
    logger.info(
        f"Smart inheritance: meeting={len(meeting_tags)}, commit={len(commit_tags)}, "
        f"result={len(result)}, inherited={inherited_tags}, duplicates_removed={duplicates_removed}, "
        f"people={people_inherited}, business={business_inherited}, projects={projects_inherited}"
    )
    return result


def reload_tags_rules() -> int:
    """Перезагружает правила тегирования в runtime."""
    try:
        # Очищаем кэш
        _tag_cached.cache_clear()

        # Перезагружаем правила v1 (scored)
        from app.core.tagger_v1_scored import clear_cache as clear_v1_cache

        clear_v1_cache()
        rules_count = reload_rules()

        # Обновляем статистику
        _stats["last_reload"] = time.time()

        logger.info(f"Tags rules reloaded successfully: {rules_count} rules")
        return rules_count
    except Exception as e:
        logger.error(f"Failed to reload tags rules: {e}")
        return 0


def get_tagging_stats() -> dict[str, Any]:
    """Возвращает статистику системы тегирования."""
    try:
        from app.core.tagger_v1_scored import get_rules_stats as get_v1_stats

        v1_stats = get_v1_stats()
        cache_info = _tag_cached.cache_info()

        # Вычисляем uptime
        uptime_seconds = time.time() - _stats["start_time"]
        uptime_hours = uptime_seconds / 3600

        # Топ-10 тегов
        top_tags = sorted(_stats["top_tags"].items(), key=lambda x: x[1], reverse=True)[:10]

        # Cache hit rate
        total_cache_calls = cache_info.hits + cache_info.misses
        hit_rate = (cache_info.hits / total_cache_calls * 100) if total_cache_calls > 0 else 0

        # Метрики дедупликации
        dedup_stats = _stats["deduplication"]
        dedup_efficiency = 0.0
        if dedup_stats["v0_tags_total"] + dedup_stats["v1_tags_total"] > 0:
            total_input_tags = dedup_stats["v0_tags_total"] + dedup_stats["v1_tags_total"]
            dedup_efficiency = dedup_stats["duplicates_removed"] / total_input_tags

        # Метрики наследования
        inheritance_stats = _stats["inheritance"]
        inheritance_efficiency = 0.0
        if inheritance_stats["meeting_tags_total"] > 0:
            inheritance_efficiency = (
                inheritance_stats["inherited_tags"] / inheritance_stats["meeting_tags_total"]
            )

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
                "hit_rate_percent": round(hit_rate, 1),
            },
            "performance": {
                "uptime_hours": round(uptime_hours, 2),
                "calls_per_hour": round(_stats["total_calls"] / uptime_hours, 1)
                if uptime_hours > 0
                else 0,
                "avg_response_time_ms": round(_stats["performance"]["avg_response_time"] * 1000, 2),
            },
            "top_tags": top_tags,
            "v1_stats": v1_stats,
            "v1_scored_enabled": True,
            "tags_min_score": settings.tags_min_score,
            "mapping_rules": len(V0_TO_V1_MAPPING),
            "deduplication": {
                "v0_tags_total": dedup_stats["v0_tags_total"],
                "v1_tags_total": dedup_stats["v1_tags_total"],
                "merged_tags_total": dedup_stats["merged_tags_total"],
                "duplicates_removed": dedup_stats["duplicates_removed"],
                "people_tags_preserved": dedup_stats["people_tags_preserved"],
                "v1_priority_wins": dedup_stats["v1_priority_wins"],
                "efficiency_percent": round(dedup_efficiency * 100, 1),
            },
            "inheritance": {
                "meeting_tags_total": inheritance_stats["meeting_tags_total"],
                "commit_tags_total": inheritance_stats["commit_tags_total"],
                "inherited_tags": inheritance_stats["inherited_tags"],
                "duplicates_removed": inheritance_stats["duplicates_removed"],
                "people_inherited": inheritance_stats["people_inherited"],
                "business_inherited": inheritance_stats["business_inherited"],
                "projects_inherited": inheritance_stats["projects_inherited"],
                "finance_inherited": inheritance_stats["finance_inherited"],
                "topic_inherited": inheritance_stats["topic_inherited"],
                "efficiency_percent": round(inheritance_efficiency * 100, 1),
            },
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
