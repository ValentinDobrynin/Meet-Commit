from __future__ import annotations

import json
import logging
import re
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

DICT_DIR = Path(__file__).resolve().parent.parent / "dictionaries"
TAGS_PATH = DICT_DIR / "tags.json"
LEGACY_SYNONYMS_PATH = DICT_DIR / "tag_synonyms.json"


def _normalize_token(w: str) -> str:
    """Нормализация токена: нижний регистр + отсечение типовых русских окончаний."""
    w = w.lower()
    # Убираем все кроме букв, цифр и дефисов
    w = re.sub(r"[^\w\-]+", "", w, flags=re.UNICODE)

    # Мини-стемминг для русских существительных/глаголов
    # Сортируем по длине (длинные первыми) для правильного отсечения
    suffixes = [
        "ание",
        "ения",
        "ении",
        "ением",
        "ованием",
        "ирование",
        "ирования",
        "ированием",
        "ами",
        "ями",
        "ием",
        "ией",
        "ах",
        "ях",
        "ую",
        "ем",
        "ам",
        "ям",
        "ета",
        "ете",
        "ов",
        "ев",
        "ые",
        "ий",
        "ой",
        "ый",
        "ая",
        "ия",
        "ся",
        "ть",
        "ти",
        "ет",
        "ла",
        "ли",
        "ло",
        "л",
        "а",
        "е",
        "и",
        "о",
        "у",
        "ы",
        "я",
    ]

    for suffix in suffixes:
        if w.endswith(suffix) and len(w) - len(suffix) >= 3:
            w = w[: -len(suffix)]
            break

    return w


def _load_tags() -> dict[str, list[str]]:
    """Загружает новый формат тегов (канонический тег → список синонимов)."""
    if not TAGS_PATH.exists():
        logger.warning(f"Tags file not found: {TAGS_PATH}")
        return {}

    try:
        with open(TAGS_PATH, encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
            else:
                logger.error(f"Invalid tags.json format: expected dict, got {type(data)}")
                return {}
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"Failed to load tags.json: {e}")
        return {}


def _load_legacy_synonyms() -> dict[str, str]:
    """Загружает старый формат синонимов для обратной совместимости."""
    if not LEGACY_SYNONYMS_PATH.exists():
        return {}

    try:
        with open(LEGACY_SYNONYMS_PATH, encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError) as e:
        logger.warning(f"Failed to load legacy synonyms: {e}")
        return {}


def _build_index(tags_map: dict[str, list[str]]) -> dict[str, str]:
    """Строит индекс: нормализованный синоним → канонический тег."""
    idx: dict[str, str] = {}

    for canonical_tag, synonyms in tags_map.items():
        for synonym in synonyms:
            if not isinstance(synonym, str):
                continue  # type: ignore[unreachable]

            normalized_key = _normalize_token(synonym)
            if normalized_key:
                if normalized_key in idx:
                    logger.debug(
                        f"Duplicate synonym '{synonym}' -> '{normalized_key}' for tags '{idx[normalized_key]}' and '{canonical_tag}'"
                    )
                idx[normalized_key] = canonical_tag

    logger.debug(f"Built index with {len(idx)} normalized synonyms")
    return idx


def _token_counts(text: str) -> dict[str, int]:
    """Подсчитывает частоту нормализованных токенов в тексте."""
    # Извлекаем все слова (буквы, цифры, дефисы)
    tokens = re.findall(r"[A-Za-zА-Яа-яЁё0-9\-]+", text)
    counts: dict[str, int] = {}

    for token in tokens:
        normalized = _normalize_token(token)
        if not normalized or len(normalized) < 2:  # Пропускаем слишком короткие
            continue
        counts[normalized] = counts.get(normalized, 0) + 1

    return counts


def run(summary_md: str, meta: dict, *, threshold: int = 1) -> list[str]:
    """
    v2 tagger: улучшенное тегирование с нормализацией и порогами.

    Args:
        summary_md: Текст саммари для анализа
        meta: Метаданные (title, attendees, etc.)
        threshold: Минимальное количество совпадений для тега

    Returns:
        Отсортированный список канонических тегов
    """
    # Загружаем новый формат тегов
    tags_map = _load_tags()

    # Если новый формат пуст, используем legacy
    if not tags_map:
        logger.info("Using legacy tagger format")
        return _run_legacy(summary_md, meta)

    # Строим индекс синонимов
    synonym_index = _build_index(tags_map)

    # Подсчитываем токены в тексте
    full_text = summary_md + " " + meta.get("title", "")
    token_counts = _token_counts(full_text)

    # Находим теги по порогу
    found_tags: set[str] = set()
    for token, count in token_counts.items():
        if token in synonym_index and count >= threshold:
            found_tags.add(synonym_index[token])
            logger.debug(f"Tag found: {token} ({count}x) → {synonym_index[token]}")

    # Добавляем person/* теги из участников
    for person_en in meta.get("attendees", []):
        slug = person_en.strip().lower().replace(" ", "_")
        if slug:
            found_tags.add(f"person/{slug}")

    result = sorted(found_tags)
    logger.info(f"Found {len(result)} tags with threshold={threshold}")
    return result


def _run_legacy(summary_md: str, meta: dict) -> list[str]:
    """Fallback к старому формату тегирования."""
    legacy_synonyms = _load_legacy_synonyms()
    tags = set()
    low = summary_md.lower()

    # Существующий маппинг через legacy SYNONYMS
    for key, mapped_tag in legacy_synonyms.items():
        if key in low or key in meta.get("title", "").lower():
            tags.add(mapped_tag)

    # person/* из английских имён
    for person_en in meta.get("attendees", []):
        slug = person_en.strip().lower()
        if slug:
            tags.add(f"person/{slug}")

    logger.info(f"Legacy tagger found {len(tags)} tags")
    return sorted(tags)


# CLI
if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python -m app.core.tagger 'текст'")
        sys.exit(1)
    text = sys.argv[1]
    tags = run(summary_md=text, meta={"title": "cli-test"})
    print("Теги:", tags)
