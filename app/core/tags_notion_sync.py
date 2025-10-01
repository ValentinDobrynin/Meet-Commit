"""Сервис синхронизации правил тегирования между Notion Tag Catalog и локальным тэггером.

Обеспечивает гибридную архитектуру:
- Primary source: Notion Tag Catalog (если доступен)
- Fallback source: локальный YAML файл
- Кэширование для быстрого старта
- Graceful degradation при ошибках
"""

from __future__ import annotations

import json
import logging
import time
from pathlib import Path
from typing import Any

from app.gateways.notion_tag_catalog import fetch_tag_catalog, validate_tag_catalog_access
from app.settings import settings

logger = logging.getLogger(__name__)

# Путь к кэшу правил
CACHE_DIR = Path("cache")
RULES_CACHE_PATH = CACHE_DIR / "tag_rules.json"
SYNC_METADATA_PATH = CACHE_DIR / "sync_metadata.json"


class TagsSyncResult:
    """Результат синхронизации правил тегирования."""

    def __init__(
        self,
        success: bool,
        source: str,
        rules_count: int,
        kind_breakdown: dict[str, int] | None = None,
        error: str | None = None,
        cache_updated: bool = False,
    ):
        self.success = success
        self.source = source  # "notion", "yaml", "cache"
        self.rules_count = rules_count
        self.kind_breakdown = kind_breakdown or {}
        self.error = error
        self.cache_updated = cache_updated
        self.timestamp = time.time()

    def to_dict(self) -> dict[str, Any]:
        """Конвертирует результат в словарь."""
        return {
            "success": self.success,
            "source": self.source,
            "rules_count": self.rules_count,
            "kind_breakdown": self.kind_breakdown,
            "error": self.error,
            "cache_updated": self.cache_updated,
            "timestamp": self.timestamp,
        }


def _ensure_cache_dir() -> None:
    """Создает директорию для кэша если не существует."""
    CACHE_DIR.mkdir(parents=True, exist_ok=True)


def _save_rules_cache(rules: list[dict[str, Any]]) -> None:
    """Сохраняет правила в локальный кэш."""
    try:
        _ensure_cache_dir()

        with open(RULES_CACHE_PATH, "w", encoding="utf-8") as f:
            json.dump(rules, f, ensure_ascii=False, indent=2)

        logger.debug(f"Saved {len(rules)} rules to cache: {RULES_CACHE_PATH}")

    except Exception as e:
        logger.warning(f"Failed to save rules cache: {e}")


def _load_rules_cache() -> list[dict[str, Any]] | None:
    """Загружает правила из локального кэша."""
    try:
        if not RULES_CACHE_PATH.exists():
            return None

        with open(RULES_CACHE_PATH, encoding="utf-8") as f:
            rules = json.load(f)

        if isinstance(rules, list):
            logger.debug(f"Loaded {len(rules)} rules from cache")
            return rules
        else:
            logger.warning("Invalid cache format, expected list")
            return None

    except Exception as e:
        logger.warning(f"Failed to load rules cache: {e}")
        return None


def _save_sync_metadata(result: TagsSyncResult) -> None:
    """Сохраняет метаданные последней синхронизации."""
    try:
        _ensure_cache_dir()

        with open(SYNC_METADATA_PATH, "w", encoding="utf-8") as f:
            json.dump(result.to_dict(), f, ensure_ascii=False, indent=2)

    except Exception as e:
        logger.warning(f"Failed to save sync metadata: {e}")


def _load_sync_metadata() -> dict[str, Any] | None:
    """Загружает метаданные последней синхронизации."""
    try:
        if not SYNC_METADATA_PATH.exists():
            return None

        with open(SYNC_METADATA_PATH, encoding="utf-8") as f:
            return json.load(f)

    except Exception as e:
        logger.warning(f"Failed to load sync metadata: {e}")
        return None


def _convert_notion_rules_to_yaml_format(notion_rules: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Конвертирует правила из Notion формата в YAML формат для tagger_v1_scored.

    Args:
        notion_rules: Правила из Notion Tag Catalog

    Returns:
        Словарь в формате YAML для tagger_v1_scored
    """
    yaml_format = {}

    for rule in notion_rules:
        tag_name = rule.get("tag", "")
        if not tag_name:
            continue

        yaml_format[tag_name] = {
            "patterns": rule.get("patterns", []),
            "exclude": rule.get("exclude", []),
            "weight": rule.get("weight", 1.0),
        }

    return yaml_format


def _calculate_kind_breakdown(rules: list[dict[str, Any]]) -> dict[str, int]:
    """Подсчитывает количество правил по категориям."""
    breakdown = {}

    for rule in rules:
        tag = rule.get("tag", "")
        if "/" in tag:
            kind = tag.split("/", 1)[0]
            breakdown[kind] = breakdown.get(kind, 0) + 1

    return breakdown


def sync_from_notion(dry_run: bool = False) -> TagsSyncResult:
    """
    Синхронизирует правила тегирования из Notion Tag Catalog.

    Args:
        dry_run: Если True, только загружает без применения

    Returns:
        Результат синхронизации
    """
    try:
        # Проверяем доступность Notion
        if not validate_tag_catalog_access():
            raise RuntimeError("Tag Catalog not accessible")

        # Загружаем правила из Notion
        notion_rules = fetch_tag_catalog()

        if not notion_rules:
            logger.warning("No active rules found in Tag Catalog")
            return TagsSyncResult(
                success=False, source="notion", rules_count=0, error="No active rules found"
            )

        # Подсчитываем статистику
        kind_breakdown = _calculate_kind_breakdown(notion_rules)

        if dry_run:
            logger.info(f"Dry run: would sync {len(notion_rules)} rules from Notion")
            return TagsSyncResult(
                success=True,
                source="notion",
                rules_count=len(notion_rules),
                kind_breakdown=kind_breakdown,
            )

        # Конвертируем в формат для тэггера
        yaml_format = _convert_notion_rules_to_yaml_format(notion_rules)

        # Применяем правила к тэггеру
        from app.core.tagger_v1_scored import _get_tagger

        tagger = _get_tagger()
        tagger._load_and_compile_rules_from_dict(yaml_format)

        # Сохраняем в кэш
        _save_rules_cache(notion_rules)

        result = TagsSyncResult(
            success=True,
            source="notion",
            rules_count=len(notion_rules),
            kind_breakdown=kind_breakdown,
            cache_updated=True,
        )

        _save_sync_metadata(result)

        logger.info(
            f"Successfully synced {len(notion_rules)} rules from Notion Tag Catalog. "
            f"Breakdown: {kind_breakdown}"
        )

        return result

    except Exception as e:
        logger.error(f"Failed to sync from Notion: {e}")
        return TagsSyncResult(success=False, source="notion", rules_count=0, error=str(e))


def sync_from_yaml() -> TagsSyncResult:
    """
    Синхронизирует правила из локального YAML файла (fallback).

    Returns:
        Результат синхронизации
    """
    try:
        from app.core.tagger_v1_scored import _get_tagger

        tagger = _get_tagger()
        rules_count = tagger.reload_rules()

        # Получаем статистику по категориям из тэггера
        kind_breakdown: dict[str, int] = {}

        # Простой подсчет по именам тегов
        for tag_name in tagger._compiled_rules.keys():
            if "/" in tag_name:
                kind = tag_name.split("/", 1)[0]
                kind_breakdown[kind] = kind_breakdown.get(kind, 0) + 1

        result = TagsSyncResult(
            success=True, source="yaml", rules_count=rules_count, kind_breakdown=kind_breakdown
        )

        _save_sync_metadata(result)

        logger.info(
            f"Successfully synced {rules_count} rules from YAML. Breakdown: {kind_breakdown}"
        )

        return result

    except Exception as e:
        logger.error(f"Failed to sync from YAML: {e}")
        return TagsSyncResult(success=False, source="yaml", rules_count=0, error=str(e))


def sync_from_cache() -> TagsSyncResult:
    """
    Загружает правила из локального кэша (быстрый старт).

    Returns:
        Результат синхронизации
    """
    try:
        cached_rules = _load_rules_cache()

        if not cached_rules:
            return TagsSyncResult(
                success=False, source="cache", rules_count=0, error="No cached rules found"
            )

        # Конвертируем и применяем
        yaml_format = _convert_notion_rules_to_yaml_format(cached_rules)

        from app.core.tagger_v1_scored import _get_tagger

        tagger = _get_tagger()
        tagger._load_and_compile_rules_from_dict(yaml_format)

        kind_breakdown = _calculate_kind_breakdown(cached_rules)

        result = TagsSyncResult(
            success=True,
            source="cache",
            rules_count=len(cached_rules),
            kind_breakdown=kind_breakdown,
        )

        logger.info(f"Successfully loaded {len(cached_rules)} rules from cache")

        return result

    except Exception as e:
        logger.error(f"Failed to sync from cache: {e}")
        return TagsSyncResult(success=False, source="cache", rules_count=0, error=str(e))


def smart_sync(dry_run: bool = False) -> TagsSyncResult:
    """
    Умная синхронизация с автоматическим выбором источника.

    Приоритет:
    1. Notion Tag Catalog (если доступен)
    2. Локальный YAML файл
    3. Кэш (для быстрого старта)

    Args:
        dry_run: Если True, только проверяет без применения

    Returns:
        Результат синхронизации
    """
    logger.info("Starting smart tags sync...")

    # Попытка 1: Notion Tag Catalog
    if settings.notion_sync_enabled and validate_tag_catalog_access():
        logger.debug("Attempting sync from Notion Tag Catalog")
        result = sync_from_notion(dry_run)
        if result.success:
            return result
        else:
            logger.warning(f"Notion sync failed: {result.error}")

    # Попытка 2: YAML файл (если разрешен fallback)
    if settings.notion_sync_fallback_to_yaml:
        logger.debug("Falling back to YAML sync")
        result = sync_from_yaml()
        if result.success:
            return result
        else:
            logger.warning(f"YAML sync failed: {result.error}")

    # Попытка 3: Кэш (последняя надежда)
    logger.debug("Falling back to cache")
    result = sync_from_cache()
    if result.success:
        logger.warning("Using cached rules as fallback")
        return result

    # Все источники недоступны
    logger.error("All sync sources failed")
    return TagsSyncResult(
        success=False,
        source="none",
        rules_count=0,
        error="All sync sources failed (Notion, YAML, cache)",
    )


def get_sync_status() -> dict[str, Any]:
    """
    Получает статус последней синхронизации.

    Returns:
        Словарь со статусом синхронизации
    """
    metadata = _load_sync_metadata()

    if not metadata:
        return {"last_sync": None, "status": "never_synced", "source": "unknown", "rules_count": 0}

    last_sync_time = metadata.get("timestamp", 0)
    hours_since_sync = (time.time() - last_sync_time) / 3600

    return {
        "last_sync": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(last_sync_time)),
        "hours_since_sync": round(hours_since_sync, 1),
        "status": "success" if metadata.get("success") else "failed",
        "source": metadata.get("source", "unknown"),
        "rules_count": metadata.get("rules_count", 0),
        "kind_breakdown": metadata.get("kind_breakdown", {}),
        "error": metadata.get("error"),
        "cache_available": RULES_CACHE_PATH.exists(),
        "notion_accessible": validate_tag_catalog_access(),
    }


def sync_yaml_to_notion(dry_run: bool = False) -> TagsSyncResult:
    """
    Синхронизирует правила тегирования из локального YAML в Notion Tag Catalog.

    Args:
        dry_run: Если True, только показывает что будет сделано без применения

    Returns:
        TagsSyncResult с результатами синхронизации
    """
    try:
        logger.info(f"Starting YAML → Notion sync (dry_run={dry_run})")

        # Загружаем правила из YAML
        from pathlib import Path

        import yaml

        rules_path = Path(settings.tagger_v1_rules_file)
        if not rules_path.is_absolute():
            project_root = Path(__file__).parent.parent.parent
            rules_path = project_root / rules_path

        if not rules_path.exists():
            return TagsSyncResult(
                success=False,
                source="yaml",
                rules_count=0,
                error=f"YAML file not found: {rules_path}",
            )

        with open(rules_path, encoding="utf-8") as f:
            raw_data = yaml.safe_load(f) or {}

        # Конвертируем в список правил
        yaml_rules = []
        for tag_name, spec in raw_data.items():
            if isinstance(spec, list):
                # Старый формат: ["pattern1", "pattern2"]
                rule = {
                    "name": tag_name,
                    "patterns": spec,
                    "exclude": [],
                    "weight": 1.0,
                    "kind": tag_name.split("/")[0] if "/" in tag_name else "Topic",
                }
            elif isinstance(spec, dict):
                # Новый формат: {patterns: [...], exclude: [...], weight: 1.5}
                rule = {
                    "name": tag_name,
                    "patterns": spec.get("patterns", []),
                    "exclude": spec.get("exclude", []),
                    "weight": spec.get("weight", 1.0),
                    "kind": spec.get(
                        "kind", tag_name.split("/")[0] if "/" in tag_name else "Topic"
                    ),
                }
            else:
                continue

            yaml_rules.append(rule)

        if not yaml_rules:
            return TagsSyncResult(
                success=False,
                source="yaml",
                rules_count=0,
                error="No valid rules found in YAML file",
            )

        logger.info(f"Loaded {len(yaml_rules)} rules from YAML")

        # Проверяем доступ к Notion
        if not validate_tag_catalog_access():
            return TagsSyncResult(
                success=False,
                source="notion",
                rules_count=0,
                error="Notion Tag Catalog not accessible",
            )

        # Загружаем существующие правила из Notion
        from app.gateways.notion_tag_catalog import (
            create_tag_rule,
            fetch_tag_catalog,
            update_tag_rule,
        )

        existing_rules = fetch_tag_catalog()

        # Отладочная информация о структуре правил из Notion
        logger.debug(
            f"First Notion rule structure: {existing_rules[0] if existing_rules else 'None'}"
        )

        existing_by_name = {}
        for rule in existing_rules:
            # В Notion правила используют поле "tag" вместо "name"
            rule_name = rule.get("tag") or rule.get("name")
            if rule_name:
                existing_by_name[rule_name] = rule
            else:
                logger.warning(f"Notion rule missing 'tag'/'name' field: {rule}")

        logger.info(
            f"Found {len(existing_rules)} existing rules in Notion, {len(existing_by_name)} with valid names"
        )

        # Подсчитываем изменения
        to_create = []
        to_update = []
        kind_breakdown = {}

        for yaml_rule in yaml_rules:
            rule_name = yaml_rule["name"]
            rule_kind = yaml_rule.get("kind", "Unknown")

            # Подсчитываем по категориям
            kind_breakdown[rule_kind] = kind_breakdown.get(rule_kind, 0) + 1

            if rule_name in existing_by_name:
                # Проверяем нужно ли обновление
                existing_rule = existing_by_name[rule_name]
                if _rules_differ(yaml_rule, existing_rule):
                    to_update.append((yaml_rule, existing_rule))
            else:
                # Новое правило
                to_create.append(yaml_rule)

        total_changes = len(to_create) + len(to_update)

        if dry_run:
            # Dry-run режим - только показываем что будет сделано
            return TagsSyncResult(
                success=True,
                source="yaml-preview",
                rules_count=total_changes,
                kind_breakdown=kind_breakdown,
                error=f"Preview: {len(to_create)} to create, {len(to_update)} to update",
            )

        # Применяем изменения
        created_count = 0
        updated_count = 0

        # Создаем новые правила
        for rule in to_create:
            try:
                create_tag_rule(rule)
                created_count += 1
                logger.debug(f"Created rule: {rule['name']}")
            except Exception as e:
                logger.warning(f"Failed to create rule {rule['name']}: {e}")

        # Обновляем существующие правила
        for yaml_rule, existing_rule in to_update:
            try:
                update_tag_rule(existing_rule["id"], yaml_rule)
                updated_count += 1
                logger.debug(f"Updated rule: {yaml_rule['name']}")
            except Exception as e:
                logger.warning(f"Failed to update rule {yaml_rule['name']}: {e}")

        # Создаем результат для сохранения метаданных
        result_for_metadata = TagsSyncResult(
            success=True,
            source="yaml-to-notion",
            rules_count=created_count + updated_count,
            kind_breakdown=kind_breakdown,
        )
        _save_sync_metadata(result_for_metadata)

        logger.info(
            f"YAML → Notion sync completed: {created_count} created, {updated_count} updated"
        )

        return TagsSyncResult(
            success=True,
            source="yaml-to-notion",
            rules_count=created_count + updated_count,
            kind_breakdown=kind_breakdown,
            error=f"{created_count} created, {updated_count} updated"
            if total_changes > 0
            else "No changes needed",
        )

    except Exception as e:
        logger.error(f"Error in YAML → Notion sync: {e}")
        return TagsSyncResult(success=False, source="yaml-to-notion", rules_count=0, error=str(e))


def _rules_differ(yaml_rule: dict[str, Any], notion_rule: dict[str, Any]) -> bool:
    """Проверяет отличаются ли правила между YAML и Notion."""
    # Сравниваем ключевые поля
    yaml_patterns = set(yaml_rule.get("patterns", []))
    notion_patterns = set(notion_rule.get("patterns", []))

    yaml_exclude = set(yaml_rule.get("exclude", []))
    notion_exclude = set(notion_rule.get("exclude", []))

    return (
        yaml_patterns != notion_patterns
        or yaml_exclude != notion_exclude
        or yaml_rule.get("weight", 1.0) != notion_rule.get("weight", 1.0)
        or yaml_rule.get("kind", "") != notion_rule.get("kind", "")
    )
