"""
Модуль для вычисления стабильных хэшей транскриптов встреч.

Нормализует текст для получения одинакового хэша для:
- Одного и того же транскрипта с разными именами файлов
- Текста с незначительными отличиями в форматировании
- Контента с разными временными метками

Используется для дедупликации встреч в базе данных Meetings.
"""

from __future__ import annotations

import hashlib
import re
import unicodedata
from functools import lru_cache

# Регулярные выражения для очистки текста
_TIMESTAMP_PATTERN = re.compile(r"\b\d{1,2}:\d{2}(:\d{2})?\b")  # 12:34 или 1:02:03
_SPEAKER_PATTERN = re.compile(
    r"^\s*(\d{1,2}:\d{2}\s+)?.*?(speaker|спикер|говорящий|участник)\s*[:#-].*?[:#-]\s*|^\s*(\d{1,2}:\d{2}\s+)?(valentin|валентин|sasha|саша)\s*[:#-]\s*",
    re.IGNORECASE,
)
_WHITESPACE_PATTERN = re.compile(r"\s+")
_EMOJI_PATTERN = re.compile(
    r"[\U0001F600-\U0001F64F\U0001F300-\U0001F5FF\U0001F680-\U0001F6FF\U0001F1E0-\U0001F1FF\U00002702-\U000027B0\U000024C2-\U0001F251]+"
)


def _normalize_for_hash(text: str) -> str:
    """
    Нормализует текст для стабильного хэширования.

    Применяет следующие преобразования:
    1. Unicode нормализация (NFC)
    2. Удаление временных меток (12:34, 1:02:03)
    3. Удаление строк с метками спикеров
    4. Удаление эмодзи
    5. Нормализация пробелов
    6. Приведение к нижнему регистру

    Args:
        text: Исходный текст транскрипта

    Returns:
        Нормализованный текст для хэширования
    """
    if not text:
        return ""

    # Unicode нормализация
    normalized = unicodedata.normalize("NFC", text)

    # Удаляем временные метки
    normalized = _TIMESTAMP_PATTERN.sub("", normalized)

    # Удаляем метки спикеров более простым способом
    # Удаляем паттерны "Имя:" в начале строк
    normalized = re.sub(
        r"^\s*(Валентин|Валя|Sasha|Саша|Speaker|Спикер|Говорящий|Участник).*?:\s*",
        "",
        normalized,
        flags=re.MULTILINE | re.IGNORECASE,
    )
    # Удаляем паттерны "Участник - Имя:"
    normalized = re.sub(
        r"^\s*Участник\s*-\s*\w+\s*:\s*", "", normalized, flags=re.MULTILINE | re.IGNORECASE
    )

    # Удаляем эмодзи
    normalized = _EMOJI_PATTERN.sub("", normalized)

    # Нормализуем пробелы и приводим к нижнему регистру
    normalized = _WHITESPACE_PATTERN.sub(" ", normalized).strip().lower()

    return normalized


@lru_cache(maxsize=128)
def compute_raw_hash(text: str) -> str:
    """
    Вычисляет стабильный хэш для текста транскрипта.

    Использует нормализацию для получения одинакового хэша
    для семантически идентичных транскриптов.

    Args:
        text: Текст транскрипта встречи

    Returns:
        SHA-256 хэш нормализованного текста (64 символа)

    Examples:
        >>> compute_raw_hash("Валентин: Привет! 12:30")
        'a1b2c3d4e5f6...'

        >>> compute_raw_hash("Привет! 15:45")  # Другое время, тот же контент
        'a1b2c3d4e5f6...'  # Тот же хэш
    """
    normalized = _normalize_for_hash(text)
    hash_bytes = hashlib.sha256(normalized.encode("utf-8", errors="ignore"))
    return hash_bytes.hexdigest()


def compute_short_hash(text: str, length: int = 16) -> str:
    """
    Вычисляет короткий хэш для отображения в UI.

    Args:
        text: Текст для хэширования
        length: Длина результирующего хэша (по умолчанию 16)

    Returns:
        Первые N символов полного хэша
    """
    full_hash = compute_raw_hash(text)
    return full_hash[:length]


def is_similar_content(text1: str, text2: str) -> bool:
    """
    Проверяет, являются ли два текста семантически похожими.

    Args:
        text1: Первый текст
        text2: Второй текст

    Returns:
        True если тексты имеют одинаковый нормализованный хэш
    """
    return compute_raw_hash(text1) == compute_raw_hash(text2)


# Для отладки и тестирования
def debug_normalization(text: str) -> dict[str, str]:
    """
    Возвращает промежуточные этапы нормализации для отладки.

    Args:
        text: Исходный текст

    Returns:
        Словарь с этапами нормализации
    """
    steps = {
        "original": text,
        "unicode_normalized": unicodedata.normalize("NFC", text),
    }

    # Удаление временных меток
    no_timestamps = _TIMESTAMP_PATTERN.sub("", steps["unicode_normalized"])
    steps["no_timestamps"] = no_timestamps

    # Удаление меток спикеров (но оставляем содержимое)
    lines = no_timestamps.splitlines()
    cleaned_lines = []
    for line in lines:
        stripped_line = line.strip()
        match = _SPEAKER_PATTERN.match(stripped_line)
        if match:
            content_start = match.end()
            remaining_content = stripped_line[content_start:].strip()
            if remaining_content:
                cleaned_lines.append(remaining_content)
        else:
            cleaned_lines.append(line)

    no_speakers = "\n".join(cleaned_lines)
    steps["no_speakers"] = no_speakers

    # Удаление эмодзи
    no_emoji = _EMOJI_PATTERN.sub("", no_speakers)
    steps["no_emoji"] = no_emoji

    # Финальная нормализация
    final = _WHITESPACE_PATTERN.sub(" ", no_emoji).strip().lower()
    steps["final_normalized"] = final

    steps["hash"] = hashlib.sha256(final.encode("utf-8", errors="ignore")).hexdigest()

    return steps
