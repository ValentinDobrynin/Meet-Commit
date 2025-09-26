"""
Асинхронная версия LLM извлечения коммитов.

Устраняет необходимость в run_in_executor для LLM операций.
"""

from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Any, Literal

from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel, Field, ValidationError, field_validator

from app.core.clients import get_async_openai_client
from app.core.metrics import MetricNames, async_timer, track_llm_tokens

logger = logging.getLogger(__name__)

# Переиспользуем модели из синхронной версии
Direction = Literal["mine", "theirs"]


class ExtractedCommit(BaseModel):
    text: str = Field(..., min_length=8)
    direction: Direction
    assignees: list[str] = Field(default_factory=list)
    due_iso: str | None = None
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    flags: list[str] = Field(default_factory=list)
    context: str | None = None
    reasoning: str | None = None

    @field_validator("assignees")
    @classmethod
    def _strip_assignees(cls, v: list[str]) -> list[str]:
        return [a.strip() for a in v if a and a.strip()]

    @field_validator("direction")
    @classmethod
    def _dir_ok(cls, v: str) -> str:
        if v not in {"mine", "theirs"}:
            raise ValueError("direction must be 'mine' or 'theirs'")
        return v


# Константы
PROMPT_PATH = Path("prompts/extraction/commits_extract_ru.md")


def _load_prompt() -> str:
    """Загружает промпт для извлечения коммитов."""
    if not PROMPT_PATH.exists():
        raise FileNotFoundError(f"Промпт не найден: {PROMPT_PATH}")
    return PROMPT_PATH.read_text(encoding="utf-8")


def _build_messages(text: str, attendees_en: list[str], meeting_date_iso: str) -> list[ChatCompletionMessageParam]:
    """Строит сообщения для LLM."""
    prompt = _load_prompt()
    
    # Контекст для LLM
    context = f"""
Участники встречи: {', '.join(attendees_en) if attendees_en else 'не указаны'}
Дата встречи: {meeting_date_iso}
"""
    
    system_msg: ChatCompletionMessageParam = {
        "role": "system", 
        "content": f"{prompt}\n\nКонтекст:\n{context}"
    }
    user_msg: ChatCompletionMessageParam = {
        "role": "user", 
        "content": text
    }
    
    return [system_msg, user_msg]


def _extract_json(raw_response: str) -> dict[str, Any]:
    """Извлекает JSON из ответа LLM."""
    # Попытка извлечь JSON из markdown блока
    json_match = re.search(r'```json\s*\n(.*?)\n```', raw_response, re.DOTALL)
    if json_match:
        json_str = json_match.group(1)
    else:
        json_str = raw_response.strip()
    
    try:
        return json.loads(json_str)
    except json.JSONDecodeError as e:
        logger.warning(f"Failed to parse JSON: {json_str[:200]}...")
        raise RuntimeError(f"Некорректный JSON от LLM: {e}") from e


def _to_models(payload: dict[str, Any]) -> list[ExtractedCommit]:
    """Преобразует ответ LLM в модели ExtractedCommit."""
    commits_data = payload.get("commits", [])
    if not isinstance(commits_data, list):
        raise RuntimeError("LLM вернул некорректную структуру: ожидался список commits")

    out: list[ExtractedCommit] = []
    for i, item in enumerate(commits_data):
        try:
            commit = ExtractedCommit.model_validate(item)
            out.append(commit)
        except ValidationError as e:
            logger.warning(f"Skipping invalid commit {i}: {item}, error: {e}")
            continue
    
    return out


async def extract_commits_async(
    text: str,
    attendees_en: list[str],
    meeting_date_iso: str,
    *,
    model: str | None = None,
    temperature: float = 0.1,
) -> list[ExtractedCommit]:
    """
    Асинхронная версия извлечения коммитов через LLM.
    
    Args:
        text: Текст встречи для анализа
        attendees_en: Список участников (канонические EN имена)
        meeting_date_iso: Дата встречи в формате YYYY-MM-DD
        model: Модель LLM (по умолчанию gpt-4o-mini)
        temperature: Температура для LLM
        
    Returns:
        Список извлеченных коммитов
    """
    async with async_timer(MetricNames.LLM_EXTRACT_COMMITS):
        mdl = model or "gpt-4o-mini"
        messages = _build_messages(text, attendees_en, meeting_date_iso)

        client = await get_async_openai_client()
        try:
            # Попытка №1 с response_format
            try:
                resp = await client.chat.completions.create(
                    model=mdl,
                    messages=messages,
                    temperature=temperature,
                    response_format={"type": "json_object"},
                )
            except Exception as e:
                logger.warning(f"JSON format failed, falling back to text: {e}")
                # Fallback без response_format
                resp = await client.chat.completions.create(
                    model=mdl,
                    messages=messages,
                    temperature=temperature,
                )

            # Отслеживаем токены
            if resp.usage and hasattr(resp.usage, "prompt_tokens"):
                try:
                    track_llm_tokens(
                        MetricNames.LLM_EXTRACT_COMMITS,
                        int(resp.usage.prompt_tokens),
                        int(resp.usage.completion_tokens),
                        int(resp.usage.total_tokens),
                    )
                except (TypeError, ValueError):
                    pass  # Игнорируем ошибки в тестах с Mock объектами

            raw = (resp.choices[0].message.content or "").strip()
            if not raw:
                raise RuntimeError("LLM вернул пустой ответ")

            # Парсим JSON и преобразуем в модели
            payload = _extract_json(raw)
            commits = _to_models(payload)
            
            logger.info(f"Extracted {len(commits)} commits from LLM (async)")
            return commits

        except Exception as e:
            logger.error(f"LLM extraction error: {type(e).__name__}: {e}")
            raise
        finally:
            await client.close()
