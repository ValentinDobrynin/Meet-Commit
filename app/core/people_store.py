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
    if not PEOPLE.exists():
        logger.debug(f"File {PEOPLE} does not exist")
        return []

    try:
        with open(PEOPLE, encoding="utf-8") as f:
            data = json.load(f)

        # Поддерживаем оба формата: новый [dict, ...] и старый {"people": [dict, ...]}
        if isinstance(data, list):
            return data  # Новый формат (текущий)
        elif isinstance(data, dict) and "people" in data:
            people_data = data["people"]
            return people_data if isinstance(people_data, list) else []  # Старый формат
        else:
            logger.warning(f"Invalid format in {PEOPLE}: expected list or dict with 'people' key")
            return []

    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"Failed to load {PEOPLE}: {e}")
        return []


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


def _build_alias_index() -> dict[str, str]:
    """
    Строит индекс alias/lower -> name_en для канонизации имен.

    Returns:
        Словарь, где ключи - lowercase алиасы, значения - канонические EN имена
    """
    idx: dict[str, str] = {}
    for p in load_people():
        name_en = (p.get("name_en") or "").strip()
        if not name_en:
            continue  # Пропускаем записи с пустым name_en
        idx[name_en.lower()] = name_en
        for alias in p.get("aliases", []):
            if alias and alias.strip():
                idx[alias.lower()] = name_en
    return idx


def canonicalize_list(raw_names: list[str]) -> list[str]:
    """
    Превращает сырые имена в канонические EN из словаря people.json.
    Удаляет дубли и игнорирует неизвестных.

    Args:
        raw_names: Список сырых имен (могут быть русские, алиасы, с опечатками)

    Returns:
        Список канонических EN имен без дубликатов

    Example:
        ["Валентин", "Daniil", "валентин"] -> ["Valentin", "Daniil"]
    """
    idx = _build_alias_index()
    seen: set[str] = set()
    out: list[str] = []

    for raw_name in raw_names or []:
        key = (raw_name or "").strip().lower()
        if not key:
            continue

        name_en = idx.get(key)
        if not name_en:
            # Если имя не найдено в словаре, используем исходное имя с капитализацией
            name_en = raw_name.strip()
            logger.debug(f"Unknown person '{raw_name}' kept as-is (not in people.json)")

        if name_en.lower() in seen:
            continue

        seen.add(name_en.lower())
        out.append(name_en)

    return out


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


# === People Miner утилиты ===


def load_people_raw() -> list[dict]:
    """Загружает основной словарь людей как список dict."""
    if not PEOPLE.exists():
        return []
    try:
        data = json.loads(PEOPLE.read_text(encoding="utf-8") or "[]")
        # Поддерживаем как старый формат {"people": [...]}, так и новый [...]
        if isinstance(data, dict) and "people" in data:
            return data["people"] if isinstance(data["people"], list) else []
        elif isinstance(data, list):
            return data
        else:
            return []
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"Error loading people.json: {e}")
        return []


def save_people_raw(items: list[dict]) -> None:
    """Сохраняет основной словарь людей в новом формате (прямой массив)."""
    try:
        # Сохраняем в новом формате как прямой массив
        PEOPLE.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"Saved {len(items)} people to {PEOPLE}")
    except OSError as e:
        logger.error(f"Error saving people.json: {e}")
        raise


def load_candidates_raw() -> list[dict]:
    """Загружает словарь кандидатов как список dict."""
    if not CAND.exists():
        return []
    try:
        data = json.loads(CAND.read_text(encoding="utf-8") or "[]")
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"Error loading people_candidates.json: {e}")
        return []


def save_candidates_raw(items: list[dict]) -> None:
    """Сохраняет словарь кандидатов."""
    try:
        CAND.write_text(json.dumps(items, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info(f"Saved {len(items)} candidates to {CAND}")
    except OSError as e:
        logger.error(f"Error saving people_candidates.json: {e}")
        raise


def delete_candidate_by_id(cid: str) -> bool:
    """Удаляет кандидата по ID. Возвращает True если удален."""
    items = load_candidates_raw()
    original_count = len(items)
    items = [x for x in items if x.get("id") != cid]

    if len(items) < original_count:
        save_candidates_raw(items)
        logger.info(f"Deleted candidate with id {cid}")
        return True
    return False


def get_candidate_by_id(cid: str) -> dict | None:
    """Получает кандидата по ID."""
    items = load_candidates_raw()
    return next((x for x in items if x.get("id") == cid), None)


def upsert_candidate(alias: str, context: str = "", freq: int = 1, source: str = "miner") -> None:
    """Добавляет или обновляет кандидата."""
    import hashlib

    # Создаем ID из alias (не для безопасности, только для идентификации)
    cid = hashlib.sha1(alias.strip().lower().encode("utf-8"), usedforsecurity=False).hexdigest()[:8]

    items = load_candidates_raw()
    found = next((x for x in items if x.get("id") == cid), None)

    if found:
        # Обновляем существующего
        found["freq"] = int(found.get("freq", 0)) + freq
        if context and not found.get("context"):
            found["context"] = context[:400]
        found["source"] = source
        logger.debug(f"Updated candidate {cid}: {alias}")
    else:
        # Добавляем нового
        items.append(
            {
                "id": cid,
                "alias": alias.strip(),
                "context": context[:400] if context else "",
                "freq": freq,
                "source": source,
            }
        )
        logger.info(f"Added new candidate {cid}: {alias}")

    save_candidates_raw(items)
