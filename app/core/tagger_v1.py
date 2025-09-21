"""Улучшенный тэггер v1 с YAML правилами и регулярными выражениями."""

from __future__ import annotations

import logging
import re
from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml

from app.core.people_store import load_people
from app.settings import settings

logger = logging.getLogger(__name__)


@lru_cache(maxsize=1)
def _load_rules() -> dict[str, list[str]]:
    """
    Загружает правила тегирования из YAML файла с кэшированием.

    Returns:
        Словарь правил: {тег: [список паттернов]}
    """
    rules_path = Path(settings.tagger_v1_rules_file)

    # Если путь относительный, делаем его относительно корня проекта
    if not rules_path.is_absolute():
        project_root = Path(__file__).parent.parent.parent
        rules_path = project_root / rules_path

    if not rules_path.exists():
        logger.warning(f"Tagger v1 rules file not found: {rules_path}")
        return {}

    try:
        with open(rules_path, encoding="utf-8") as f:
            data = yaml.safe_load(f)
            if not isinstance(data, dict):
                logger.error(
                    f"Invalid YAML format in {rules_path}: expected dict, got {type(data)}"
                )
                return {}

            # Валидируем структуру
            validated_rules: dict[str, list[str]] = {}
            for tag, patterns in data.items():
                if not isinstance(tag, str):
                    logger.warning(f"Skipping non-string tag: {tag}")
                    continue

                if not isinstance(patterns, list):
                    logger.warning(
                        f"Skipping tag {tag}: patterns must be a list, got {type(patterns)}"
                    )
                    continue

                # Фильтруем только строковые паттерны
                valid_patterns = [p for p in patterns if isinstance(p, str) and p.strip()]
                if valid_patterns:
                    validated_rules[tag] = valid_patterns
                else:
                    logger.warning(f"Tag {tag} has no valid patterns")

            logger.info(f"Loaded {len(validated_rules)} tag rules from {rules_path}")
            return validated_rules

    except yaml.YAMLError as e:
        logger.error(f"YAML parsing error in {rules_path}: {e}")
        return {}
    except (OSError, UnicodeDecodeError) as e:
        logger.error(f"Failed to read rules file {rules_path}: {e}")
        return {}


def _compile_patterns(rules: dict[str, list[str]]) -> dict[str, list[re.Pattern[str]]]:
    """
    Компилирует регулярные выражения для всех правил.

    Args:
        rules: Словарь правил с паттернами

    Returns:
        Словарь скомпилированных regex паттернов
    """
    compiled: dict[str, list[re.Pattern[str]]] = {}

    for tag, patterns in rules.items():
        compiled_patterns: list[re.Pattern[str]] = []

        for pattern in patterns:
            try:
                # Компилируем с флагами case-insensitive и unicode
                compiled_pattern = re.compile(pattern, flags=re.IGNORECASE | re.UNICODE)
                compiled_patterns.append(compiled_pattern)
            except re.error as e:
                logger.warning(f"Invalid regex pattern '{pattern}' for tag {tag}: {e}")
                continue

        if compiled_patterns:
            compiled[tag] = compiled_patterns

    logger.debug(f"Compiled patterns for {len(compiled)} tags")
    return compiled


@lru_cache(maxsize=1)
def _get_compiled_rules() -> dict[str, list[re.Pattern[str]]]:
    """Возвращает скомпилированные правила с кэшированием."""
    rules = _load_rules()
    return _compile_patterns(rules)


def _extract_people_tags(text: str) -> set[str]:
    """
    Извлекает теги людей из текста на основе словаря people.json.

    Args:
        text: Текст для анализа

    Returns:
        Множество тегов вида "People/Name En"
    """
    if not text:
        return set()

    text_lower = text.lower()
    people_tags: set[str] = set()
    seen_people: set[str] = set()  # Избегаем дубликатов

    for person in load_people():
        name_en = person.get("name_en", "").strip()
        if not name_en or name_en.lower() in seen_people:
            continue

        # Проверяем все алиасы этого человека
        found = False
        for alias in person.get("aliases", []):
            if alias and alias.strip():
                alias_clean = alias.strip().lower()
                if alias_clean in text_lower:
                    people_tags.add(f"People/{name_en}")
                    seen_people.add(name_en.lower())
                    found = True
                    break

        # Если не нашли по алиасам, проверяем каноническое имя
        if not found and name_en.lower() in text_lower:
            people_tags.add(f"People/{name_en}")
            seen_people.add(name_en.lower())

    logger.debug(f"Found {len(people_tags)} people tags in text")
    return people_tags


def tag_text(text: str) -> list[str]:
    """
    Извлекает теги из текста на основе YAML правил и словаря людей.

    Args:
        text: Текст для анализа (summary, commit text, etc.)

    Returns:
        Отсортированный список найденных тегов

    Example:
        >>> tag_text("Обсудили аудит IFRS для Lavka. Саша Катанов подтвердил план.")
        ["Business/Lavka", "Finance/Audit", "Finance/IFRS", "People/Sasha Katanov"]
    """
    if not text or not text.strip():
        return []

    # Проверяем, включен ли тэггер v1
    if not settings.tagger_v1_enabled:
        logger.debug("Tagger v1 is disabled")
        return []

    tags: set[str] = set()

    try:
        # 1) Правила из YAML
        compiled_rules = _get_compiled_rules()

        for tag, patterns in compiled_rules.items():
            for pattern in patterns:
                try:
                    if pattern.search(text):
                        tags.add(tag)
                        logger.debug(f"Tag matched: {tag} (pattern: {pattern.pattern})")
                        break  # Достаточно одного совпадения для тега
                except Exception as e:
                    logger.warning(f"Error applying pattern {pattern.pattern} for tag {tag}: {e}")
                    continue

        # 2) Люди из словаря (алиасы → People/{name_en})
        people_tags = _extract_people_tags(text)
        tags.update(people_tags)

    except Exception as e:
        logger.error(f"Error in tag_text: {e}")
        # Возвращаем пустой список при критических ошибках
        return []

    result = sorted(tags)
    logger.info(f"Tagged text with {len(result)} tags: {result}")
    return result


def get_rules_stats() -> dict[str, Any]:
    """
    Возвращает статистику по загруженным правилам.

    Returns:
        Словарь со статистикой
    """
    try:
        rules = _load_rules()
        compiled_rules = _get_compiled_rules()

        total_patterns = sum(len(patterns) for patterns in rules.values())
        compiled_patterns = sum(len(patterns) for patterns in compiled_rules.values())

        categories: dict[str, int] = {}
        for tag in rules.keys():
            category = tag.split("/")[0] if "/" in tag else "Other"
            categories[category] = categories.get(category, 0) + 1

        return {
            "total_tags": len(rules),
            "total_patterns": total_patterns,
            "compiled_patterns": compiled_patterns,
            "categories": categories,
            "enabled": settings.tagger_v1_enabled,
            "rules_file": settings.tagger_v1_rules_file,
        }
    except Exception as e:
        logger.error(f"Error getting rules stats: {e}")
        return {"error": str(e)}


def clear_cache() -> None:
    """Очищает кэш загруженных правил (для тестов и hot-reload)."""
    _load_rules.cache_clear()
    _get_compiled_rules.cache_clear()
    logger.info("Tagger v1 cache cleared")


# CLI для тестирования
if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("Usage: python -m app.core.tagger_v1 'текст для анализа'")
        print("\nExample:")
        print("python -m app.core.tagger_v1 'Обсудили аудит IFRS для Lavka с Сашей Катановым'")
        sys.exit(1)

    test_text = " ".join(sys.argv[1:])
    tags = tag_text(test_text)

    print(f"\nТекст: {test_text}")
    print(f"Найденные теги ({len(tags)}):")
    for tag in tags:
        print(f"  - {tag}")

    print("\nСтатистика правил:")
    stats = get_rules_stats()
    for key, value in stats.items():
        print(f"  {key}: {value}")
