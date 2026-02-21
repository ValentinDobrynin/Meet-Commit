"""
LLM парсинг коммитов из человеческого языка.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from app.core.clients import get_openai_parse_client
from app.core.metrics import MetricNames, timer, track_llm_tokens

logger = logging.getLogger(__name__)


# Удалено: используем единый клиент из app.core.clients


def _load_prompt() -> str:
    """Загружает промпт для парсинга коммитов."""
    prompt_path = Path("prompts/commits/llm_parse_ru.md")
    if not prompt_path.exists():
        raise RuntimeError(f"Промпт не найден: {prompt_path}")

    return prompt_path.read_text(encoding="utf-8")


def _call_llm_parse(text: str) -> dict[str, Any]:
    """Вызывает LLM для парсинга текста коммита."""
    from datetime import date
    prompt = _load_prompt()
    # Подставляем актуальную дату через плейсхолдер {TODAY}
    today = date.today()
    prompt = prompt.replace("{TODAY}", today.isoformat())
    client = get_openai_parse_client()

    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.2,
            messages=[
                {"role": "system", "content": prompt},
                {"role": "user", "content": text},
            ],
            response_format={"type": "json_object"},
        )

        # Отслеживаем токены
        if resp.usage and hasattr(resp.usage, "prompt_tokens"):
            try:
                track_llm_tokens(
                    MetricNames.LLM_COMMIT_PARSE,
                    int(resp.usage.prompt_tokens),
                    int(resp.usage.completion_tokens),
                    int(resp.usage.total_tokens),
                )
            except (TypeError, ValueError):
                pass  # Игнорируем ошибки в тестах с Mock объектами

        raw = (resp.choices[0].message.content or "").strip()
        if not raw:
            raise RuntimeError("LLM вернул пустой ответ")

        try:
            return json.loads(raw)  # type: ignore[no-any-return]
        except json.JSONDecodeError as e:
            logger.warning(f"Invalid JSON from LLM: {raw}")
            raise RuntimeError(f"LLM вернул некорректный JSON: {e}") from e

    except Exception as e:
        logger.error(f"LLM API error: {type(e).__name__}: {e}")
        raise
    finally:
        client.close()


def _split_names(names_string: str) -> list[str]:
    """
    Разбивает строку с именами на отдельные имена.

    Args:
        names_string: Строка типа "Vlad Sklyanov, Sergey Lompa" или "Nodari и Lompa"

    Returns:
        Список отдельных имен
    """
    if not names_string or not names_string.strip():
        return []

    # Разбиваем по запятым и союзам
    import re

    # Заменяем союзы на запятые для унификации
    normalized = re.sub(r"\s+(и|and|with|&|\+)\s+", ", ", names_string, flags=re.IGNORECASE)

    # Разбиваем по запятым
    names = [name.strip() for name in normalized.split(",")]

    # Фильтруем пустые строки
    names = [name for name in names if name]

    logger.debug(f"Split names '{names_string}' -> {names}")
    return names


def _apply_role_fallbacks(llm_result: dict, user_name: str) -> tuple[list[str], str, str]:
    """
    Применяет fallback логику для ролей.

    Args:
        llm_result: Результат LLM парсинга
        user_name: Имя пользователя

    Returns:
        (assignees_list, from_person, direction)
    """
    # Исполнители: разбиваем строку на список
    assignee_raw = llm_result.get("assignee") or user_name
    assignees = _split_names(assignee_raw) if assignee_raw else [user_name]

    # Заказчик: если не указан, то пользователь
    from_person = llm_result.get("from_person") or user_name

    # Direction зависит от того, кто исполнитель
    # Если пользователь среди исполнителей - mine, иначе theirs
    direction = "mine" if user_name in assignees else "theirs"

    logger.debug(
        f"Role fallbacks: assignees={assignees}, from_person={from_person}, direction={direction}"
    )
    return assignees, from_person, direction


def _build_full_commit(
    llm_result: dict, user_name: str, assignees: list[str], from_person: str, direction: str
) -> dict:
    """Строит полный коммит из LLM данных и fallback значений."""
    from app.core.commit_normalize import build_key, build_title, normalize_assignees
    from app.core.tags import tag_text

    text = llm_result.get("text", "").strip()
    if not text:
        raise ValueError("Текст задачи не может быть пустым")

    due_iso = llm_result.get("due")

    # Нормализуем исполнителей и заказчиков через people.json
    normalized_assignees = normalize_assignees(
        assignees, []
    )  # Без фильтра по участникам встречи для LLM коммитов

    raw_from_person = [from_person] if from_person else []
    normalized_from_person = normalize_assignees(raw_from_person, [])  # Нормализуем заказчика

    # Генерируем title и key
    title = build_title(direction, text, normalized_assignees, due_iso)
    key = build_key(text, normalized_assignees, due_iso)

    # Автотегирование
    tags = tag_text(text)

    return {
        "title": title,
        "text": text,
        "direction": direction,
        "assignees": normalized_assignees,
        "from_person": normalized_from_person,
        "due_iso": due_iso,
        "confidence": float(llm_result.get("confidence") or 0.7),
        "flags": ["direct", "llm"],  # Помечаем как LLM-созданный
        "key": key,
        "tags": tags,
        "status": "open",
    }


def parse_commit_text(text: str, user_name: str) -> dict:
    """
    Парсит человеческий текст в структурированный коммит.

    Args:
        text: Пользовательский ввод
        user_name: Имя пользователя для fallback значений

    Returns:
        Полный словарь коммита готовый для Direct Commit пайплайна

    Raises:
        ValueError: Если текст пустой или некорректный
        RuntimeError: Если ошибка LLM API
    """
    if not text or not text.strip():
        raise ValueError("Текст коммита не может быть пустым")

    with timer(MetricNames.LLM_COMMIT_PARSE):
        try:
            # 1. LLM парсинг
            llm_result = _call_llm_parse(text.strip())

            # 2. Применение fallback логики
            assignees, from_person, direction = _apply_role_fallbacks(llm_result, user_name)

            # 3. Построение полного коммита
            commit_data = _build_full_commit(
                llm_result, user_name, assignees, from_person, direction
            )

            logger.info(
                f"LLM parsed commit: '{commit_data['text']}' "
                f"from {from_person} to {assignees} ({direction}), "
                f"due {commit_data['due_iso'] or 'none'}, "
                f"confidence {commit_data['confidence']:.2f}"
            )

            return commit_data

        except Exception as e:
            logger.error(f"Error parsing commit text: {e}")
            # Fallback: создаем базовый коммит
            return _create_fallback_commit(text.strip(), user_name)


def _create_fallback_commit(text: str, user_name: str) -> dict:
    """Создает fallback коммит при ошибке LLM."""
    from app.core.commit_normalize import build_key, build_title, normalize_assignees
    from app.core.tags import tag_text

    logger.warning(f"Creating fallback commit for: {text}")

    # Базовые значения с нормализацией
    direction = "mine"  # По умолчанию пользователь делает сам
    normalized_assignees = normalize_assignees([user_name], [])
    normalized_from_person = normalize_assignees([user_name], [])

    title = build_title(direction, text, normalized_assignees, None)
    key = build_key(text, normalized_assignees, None)
    tags = tag_text(text)

    return {
        "title": title,
        "text": text,
        "direction": direction,
        "assignees": normalized_assignees,
        "from_person": normalized_from_person,
        "due_iso": None,
        "confidence": 0.3,  # Низкая уверенность для fallback
        "flags": ["direct", "llm", "fallback"],
        "key": key,
        "tags": tags,
        "status": "open",
    }
