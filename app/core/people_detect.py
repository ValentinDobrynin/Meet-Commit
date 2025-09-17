from __future__ import annotations

import logging
import re

from app.core.people_store import load_people, load_stopwords

logger = logging.getLogger(__name__)

# Паттерны для поиска имен
# Латинские имена: "John", "John Smith", "Mary Johnson"
PAT_LAT = re.compile(r"\b([A-Z][a-z]{2,15})(?:\s+([A-Z][a-z]{2,20}))?\b")

# Кириллические имена: "Иван", "Иван Петров", "Мария Иванова"
PAT_CYR = re.compile(r"\b([А-ЯЁ][а-яё]{2,15})(?:\s+([А-ЯЁ][а-яё]{2,20}))?\b")

# Дополнительные паттерны для сложных случаев
PAT_LAT_HYPHEN = re.compile(r"\b([A-Z][a-z]+-[A-Z][a-z]+)\b")  # "Mary-Jane"
PAT_CYR_HYPHEN = re.compile(r"\b([А-ЯЁ][а-яё]+-[А-ЯЁ][а-яё]+)\b")  # "Анна-Мария"

# Паттерн для инициалов
PAT_INIT = re.compile(r"\b([А-ЯЁA-Z])\.\s*([А-ЯЁA-Z][а-яёa-z]{2,20})\b")  # "А. Петров", "A. Petrov"

# Исключения - паттерны, которые точно НЕ являются именами
EXCLUDE_PATTERNS = [
    re.compile(r"\b[A-Z]{2,}\b"),  # Аббревиатуры типа "API", "CEO"
    re.compile(r"\b\d+\b"),  # Числа
    re.compile(r"\b[A-Z][a-z]+\d+\b"),  # "Version1", "Test2"
    re.compile(r"\b\S+@\S+\b"),  # Email адреса
    re.compile(r"https?://\S+"),  # URL
    re.compile(r"\b[А-ЯA-Z][\w-]*\d+\b"),  # "Слово№1", "Word123"
]


def _known_aliases_lower() -> set[str]:
    """Возвращает множество всех известных алиасов в нижнем регистре."""
    known = set()
    for person in load_people():
        # Добавляем все алиасы
        for alias in person.get("aliases", []):
            if alias:
                known.add(alias.lower())
        
        # Добавляем каноническое английское имя
        name_en = (person.get("name_en") or "").strip()
        if name_en:
            known.add(name_en.lower())
    
    logger.debug(f"Loaded {len(known)} known aliases")
    return known


def _translit_ru_en(s: str) -> str:
    """
    Упрощенная транслитерация с русского на английский по ГОСТ.
    Поддерживает сохранение регистра.
    """
    # Расширенная таблица транслитерации
    table = {
        "А": "A", "Б": "B", "В": "V", "Г": "G", "Д": "D", "Е": "E", "Ё": "E", 
        "Ж": "Zh", "З": "Z", "И": "I", "Й": "Y", "К": "K", "Л": "L", "М": "M", 
        "Н": "N", "О": "O", "П": "P", "Р": "R", "С": "S", "Т": "T", "У": "U", 
        "Ф": "F", "Х": "Kh", "Ц": "Ts", "Ч": "Ch", "Ш": "Sh", "Щ": "Sch", 
        "Ы": "Y", "Э": "E", "Ю": "Yu", "Я": "Ya", "Ь": "", "Ъ": ""
    }
    
    result = []
    for char in s:
        upper_char = char.upper()
        if upper_char in table:
            transliterated = table[upper_char]
            # Сохраняем регистр
            if char.islower() and transliterated:
                transliterated = transliterated.lower()
            result.append(transliterated)
        else:
            result.append(char)
    
    return "".join(result)


def _is_valid_name_candidate(candidate: str) -> bool:
    """Проверяет, может ли строка быть именем человека."""
    # Проверяем исключающие паттерны
    for pattern in EXCLUDE_PATTERNS:
        if pattern.search(candidate):
            return False
    
    # Проверяем длину
    if len(candidate) < 2 or len(candidate) > 50:
        return False
    
    # Проверяем, что есть хотя бы одна буква
    if not re.search(r"[a-zA-Zа-яёА-ЯЁ]", candidate):
        return False
    
    # Проверяем, что нет слишком много цифр
    digit_count = sum(1 for c in candidate if c.isdigit())
    if digit_count > len(candidate) // 2:
        return False
    
    
    # Требуем хотя бы одно "длинное" слово в кандидате, кроме инициалов и известных коротких имен
    words = candidate.split()
    short_valid_names = {"bob", "tom", "jim", "joe", "ann", "sue", "tim", "sam", "max", "dan", "jon", "ben", "ron", "ray", "guy", "ted", "leo", "art", "ira", "eva", "amy", "joy", "зоя", "лев", "рим", "дан", "том", "боб", "ким", "рой", "гай", "тед", "лео", "арт", "ева", "эми"}
    
    if not any(len(w) >= 4 for w in words):
        # Исключения для:
        # 1. Инициалов типа "А. Петров"
        # 2. Коротких, но валидных имен
        is_initials = len(words) == 2 and len(words[0]) == 2 and words[0].endswith(".")
        has_short_valid_name = any(w.lower() in short_valid_names for w in words)
        
        if not (is_initials or has_short_valid_name):
            return False
    
    # Дополнительные проверки для русских слов
    if re.search(r"[а-яёА-ЯЁ]", candidate):
        # Исключаем очень короткие русские слова (часто служебные)
        if len(candidate) <= 3 and candidate.lower() not in {"ваня", "катя", "петя", "коля", "маша", "даша"}:
            return False
        
        # Исключаем слова, которые явно не имена по окончаниям
        if candidate.lower().endswith(("ость", "ение", "ание", "ться", "шься", "тся")):
            return False
    
    return True


def _extract_name_candidates(text: str, max_scan: int) -> set[str]:
    """Извлекает кандидатов в имена из текста."""
    hay = text[:max_scan]
    candidates = set()
    
    # Ищем латинские имена
    for match in PAT_LAT.finditer(hay):
        name_parts = [part for part in match.groups() if part]
        if name_parts:
            candidate = " ".join(name_parts)
            if _is_valid_name_candidate(candidate):
                candidates.add(candidate)
    
    # Ищем кириллические имена
    for match in PAT_CYR.finditer(hay):
        name_parts = [part for part in match.groups() if part]
        if name_parts:
            candidate = " ".join(name_parts)
            if _is_valid_name_candidate(candidate):
                candidates.add(candidate)
    
    # Ищем составные имена с дефисом
    for match in PAT_LAT_HYPHEN.finditer(hay):
        candidate = match.group(1)
        if _is_valid_name_candidate(candidate):
            candidates.add(candidate)
    
    for match in PAT_CYR_HYPHEN.finditer(hay):
        candidate = match.group(1)
        if _is_valid_name_candidate(candidate):
            candidates.add(candidate)
    
    # Ищем инициалы
    for match in PAT_INIT.finditer(hay):
        candidate = f"{match.group(1)}. {match.group(2)}"
        if _is_valid_name_candidate(candidate):
            candidates.add(candidate)
    
    return candidates


def mine_alias_candidates(text: str, max_scan: int = 12000) -> list[str]:
    """
    Извлекает кандидатов в алиасы людей из текста.
    
    Args:
        text: Текст для анализа
        max_scan: Максимальное количество символов для сканирования
    
    Returns:
        Отсортированный список уникальных кандидатов
    """
    if not text or not text.strip():
        return []
    
    # Загружаем стоп-слова и известные алиасы (нормализуем к lower один раз)
    stopwords = {w.lower() for w in load_stopwords()}
    known_aliases = _known_aliases_lower()  # уже в lower
    
    # Извлекаем кандидатов
    candidates = _extract_name_candidates(text, max_scan)
    
    # Фильтруем кандидатов с дедупликацией кир/лат
    filtered_candidates = set()
    for candidate in candidates:
        # Нормализуем пробелы и регистр для дедупликации
        norm = " ".join(candidate.split())
        candidate_lower = norm.lower()
        
        # Пропускаем уже известных
        if candidate_lower in known_aliases:
            continue
        
        # Пропускаем стоп-слова (проверяем каждое слово в кандидате и весь кандидат целиком)
        words = norm.split()
        if any(word.lower() in stopwords for word in words) or candidate_lower in stopwords:
            continue
        
        filtered_candidates.add(norm)
    
    result = sorted(filtered_candidates)
    logger.debug(f"Found {len(result)} new name candidates in text")
    return result


def _cap_token(tok: str) -> str:
    """Улучшенная капитализация для специальных случаев."""
    if "'" in tok:
        # Обрабатываем O'Connor, D'Angelo
        p1, p2 = tok.split("'", 1)
        return f"{p1.capitalize()}'{p2.capitalize()}"
    if tok.lower().startswith("mc") and len(tok) > 2:
        # Обрабатываем McDonald, McGregor
        return "Mc" + tok[2:].capitalize()
    return tok.capitalize()


def propose_name_en(alias: str) -> str:
    """
    Предлагает каноническое английское имя для алиаса.
    
    Args:
        alias: Алиас для обработки
    
    Returns:
        Предлагаемое каноническое английское имя
    """
    if not alias or not alias.strip():
        return ""
    
    alias = alias.strip()
    
    # Обрабатываем каждое слово отдельно (может быть смесь языков)
    words = alias.split()
    result_words = []
    
    for word in words:
        if not word:
            continue
            
        # Если слово содержит только латинские буквы, нормализуем капитализацию
        if re.match(r"^[A-Za-z\-'\.]+$", word):
            # Обрабатываем дефисы правильно
            if "-" in word:
                parts = word.split("-")
                result_words.append("-".join(_cap_token(p) for p in parts if p))
            else:
                result_words.append(_cap_token(word))
        # Если содержит кириллицу, транслитерируем
        elif re.search(r"[А-Яа-яЁё]", word):
            transliterated = _translit_ru_en(word)
            if transliterated:
                result_words.append(_cap_token(transliterated))
        else:
            # Для других символов просто капитализируем
            result_words.append(_cap_token(word))
    
    return " ".join(result_words)


def validate_person_entry(person_data: dict) -> list[str]:
    """
    Валидирует запись о человеке.
    
    Args:
        person_data: Словарь с данными о человеке
    
    Returns:
        Список ошибок валидации (пустой если все ок)
    """
    errors = []
    
    # Проверяем наличие обязательных полей
    if not person_data.get("name_en"):
        errors.append("Missing required field: name_en")
    
    # Валидируем и очищаем алиасы
    raw_aliases = person_data.get("aliases")
    if raw_aliases is None:
        errors.append("Missing required field: aliases")
    elif not isinstance(raw_aliases, list):
        errors.append("Field 'aliases' must be a list")
    else:
        # Очищаем алиасы от пустых строк и приводим к строкам
        aliases = [a.strip() for a in raw_aliases if isinstance(a, str) and a.strip()]
        if not aliases:
            errors.append("Field 'aliases' cannot be empty")
        else:
            # Проверяем на дубликаты (case-insensitive)
            aliases_lower = [a.lower() for a in aliases]
            if len(set(aliases_lower)) != len(aliases_lower):
                errors.append("Aliases contain duplicates (case-insensitive)")
    
    # Проверяем формат name_en
    name_en = person_data.get("name_en", "")
    if name_en and not re.match(r"^[A-Za-z\s\-'\.]+$", name_en):
        errors.append(f"Invalid name_en format: {name_en}")
    
    # Дополнительная проверка очищенных алиасов
    if raw_aliases is not None and isinstance(raw_aliases, list):
        for i, alias in enumerate(raw_aliases):
            if not isinstance(alias, str) and alias is not None:
                errors.append(f"Alias at index {i} must be a string")
            elif isinstance(alias, str) and not alias.strip():
                errors.append(f"Alias at index {i} cannot be empty")
    
    return errors


def get_detection_stats(text: str, max_scan: int = 12000) -> dict:
    """
    Возвращает статистику детекции имен в тексте.
    
    Args:
        text: Текст для анализа
        max_scan: Максимальное количество символов для сканирования
    
    Returns:
        Словарь со статистикой
    """
    if not text:
        return {"total_candidates": 0, "known_aliases": 0, "filtered_out": 0, "new_candidates": 0}
    
    # Извлекаем всех кандидатов
    all_candidates = _extract_name_candidates(text, max_scan)
    
    # Загружаем данные для фильтрации
    stopwords = load_stopwords()
    known_aliases = _known_aliases_lower()
    
    known_count = 0
    filtered_count = 0
    
    for candidate in all_candidates:
        candidate_lower = candidate.lower()
        
        if candidate_lower in known_aliases:
            known_count += 1
        elif any(word.lower() in stopwords for word in candidate.split()):
            filtered_count += 1
    
    new_candidates = len(all_candidates) - known_count - filtered_count
    
    return {
        "total_candidates": len(all_candidates),
        "known_aliases": known_count,
        "filtered_out": filtered_count,
        "new_candidates": new_candidates,
    }
