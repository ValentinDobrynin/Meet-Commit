from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from pathlib import Path

logger = logging.getLogger(__name__)

DICT_DIR = Path(__file__).resolve().parent.parent / "dictionaries"
PEOPLE = DICT_DIR / "people.json"
CAND = DICT_DIR / "people_candidates.json"
STOPS = DICT_DIR / "people_stopwords.json"


def _load_json(p: Path, fallback: dict) -> dict:
    """Загружает JSON файл с fallback значением при отсутствии файла."""
    if not p.exists():
        logger.debug(f"File {p} does not exist, using fallback")
        return fallback
    try:
        with open(p, encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else fallback
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"Failed to load {p}: {e}")
        return fallback


def _save_json(p: Path, data: dict) -> None:
    """Сохраняет данные в JSON файл."""
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.debug(f"Saved data to {p}")
    except OSError as e:
        logger.error(f"Failed to save {p}: {e}")
        raise


def load_people() -> list[dict]:
    """Загружает список людей из основного словаря."""
    data = _load_json(PEOPLE, {"people": []})
    people = data.get("people", [])
    return people if isinstance(people, list) else []


def save_people(items: list[dict]) -> None:
    """Сохраняет список людей в основной словарь."""
    data = {"people": items}
    _save_json(PEOPLE, data)
    logger.info(f"Saved {len(items)} people to {PEOPLE}")


def load_candidates() -> dict[str, int]:
    """Загружает словарь кандидатов с частотами."""
    data = _load_json(CAND, {"candidates": {}})
    candidates = data.get("candidates", {})
    return candidates if isinstance(candidates, dict) else {}


def bump_candidates(aliases: Iterable[str | None]) -> None:
    """Увеличивает счетчики кандидатов для переданных алиасов."""
    data = _load_json(CAND, {"candidates": {}})
    cand: dict[str, int] = data.get("candidates", {})
    
    added_count = 0
    for raw_alias in aliases:
        if raw_alias is None:
            continue
        alias = raw_alias.strip()
        if not alias:
            continue
        old_count = cand.get(alias, 0)
        cand[alias] = old_count + 1
        if old_count == 0:
            added_count += 1
    
    data["candidates"] = cand
    _save_json(CAND, data)
    
    if added_count > 0:
        logger.info(f"Added {added_count} new candidates, updated counts for existing ones")


def load_stopwords() -> set[str]:
    """Загружает множество стоп-слов."""
    data = _load_json(STOPS, {"stop": []})
    stop_list = data.get("stop", [])
    return {word.lower() for word in stop_list if word}


def clear_candidates() -> None:
    """Очищает словарь кандидатов."""
    data: dict = {"candidates": {}}
    _save_json(CAND, data)
    logger.info("Cleared candidates dictionary")


def remove_candidate(alias: str) -> bool:
    """Удаляет кандидата из словаря. Возвращает True если кандидат был найден и удален."""
    data: dict = _load_json(CAND, {"candidates": {}})
    cand: dict[str, int] = data.get("candidates", {})
    
    if alias in cand:
        del cand[alias]
        data["candidates"] = cand
        _save_json(CAND, data)
        logger.info(f"Removed candidate: {alias}")
        return True
    return False


def get_candidate_stats() -> dict[str, int | float]:
    """Возвращает статистику по кандидатам."""
    candidates = load_candidates()
    if not candidates:
        return {"total": 0, "max_count": 0, "min_count": 0}
    
    counts = list(candidates.values())
    return {
        "total": len(candidates),
        "max_count": max(counts),
        "min_count": min(counts),
        "avg_count": sum(counts) / len(counts),
    }
