from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Literal

from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel, Field, ValidationError, field_validator

from app.core.clients import get_openai_client
from app.core.metrics import MetricNames, timer, track_llm_tokens

# ==== Данные, которые возвращаем дальше по пайплайну ====

Direction = Literal["mine", "theirs"]


class ExtractedCommit(BaseModel):
    text: str = Field(..., min_length=8)
    direction: Direction
    assignees: list[str] = Field(default_factory=list)  # EN-имена, нормализуем на шаге 2.2
    due_iso: str | None = None  # YYYY-MM-DD или None (строгих дат нет — шаг 2.2)
    confidence: float = Field(ge=0.0, le=1.0, default=0.5)
    flags: list[str] = Field(
        default_factory=list
    )  # ["no_explicit_subject", "unclear_deadline", ...]
    context: str | None = None  # сырой фрагмент
    reasoning: str | None = None  # краткое объяснение

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


# ==== Загрузка промпта и сбор сообщения ====

PROMPT_PATH = Path("prompts/extraction/commits_extract_ru.md")


def _load_prompt() -> str:
    if PROMPT_PATH.exists():
        return PROMPT_PATH.read_text(encoding="utf-8")
    # запасной промпт, если файла нет
    return (
        "Извлеки из транскрипта все явные обязательства (коммиты). "
        "Не придумывай факты и даты. Если дедлайна нет — оставь пустым. "
        "Возвращай ТОЛЬКО JSON по схеме."
    )


def _json_schema_block() -> str:
    # описание схемы для модели
    schema = {
        "type": "object",
        "properties": {
            "commits": {
                "type": "array",
                "items": {
                    "type": "object",
                    "required": ["text", "direction", "confidence"],
                    "properties": {
                        "text": {"type": "string"},
                        "direction": {"type": "string", "enum": ["mine", "theirs"]},
                        "assignees": {"type": "array", "items": {"type": "string"}},
                        "due_iso": {"type": ["string", "null"]},
                        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                        "flags": {"type": "array", "items": {"type": "string"}},
                        "context": {"type": ["string", "null"]},
                        "reasoning": {"type": ["string", "null"]},
                    },
                },
            }
        },
        "required": ["commits"],
    }
    return json.dumps(schema, ensure_ascii=False)


def _build_user_message(text: str, attendees: list[str], meeting_date: str) -> str:
    return (
        f"Участники (EN): {', '.join(attendees) if attendees else '—'}\n"
        f"Дата встречи: {meeting_date}\n\n"
        f"Транскрипт:\n{text}"
    )


def _build_messages(
    text: str, attendees: list[str], meeting_date: str
) -> list[ChatCompletionMessageParam]:
    prompt = _load_prompt()
    # Заменяем плейсхолдеры в промпте
    prompt = prompt.replace("{ATTENDEES}", ", ".join(attendees) if attendees else "—")
    prompt = prompt.replace("{DATE}", meeting_date)

    schema_json = _json_schema_block()
    system = (
        "Ты извлекаешь коммиты из деловых транскриптов. "
        "Строго следуй фактам. Никаких домыслов. "
        "Если исполнитель не ясен — direction определяй по контексту, но confidence понижай. "
        "Если дедлайн не упомянут — оставь due_iso пустым."
    )
    instructions = (
        f"{prompt}\n\nТребования к выводу:\n"
        f"1) Только валидный JSON UTF-8 без пояснений и без Markdown-блоков.\n"
        f'2) Структура: {{"commits": [ {{...}}, ... ] }}.\n'
        f"3) JSON Schema: {schema_json}\n"
        f"4) Не придумывай даты/имена/ролей. Если неизвестно — пропусти поле или оставь null.\n"
        f"5) Для direction используй только 'mine' или 'theirs'.\n"
        f"6) confidence в диапазоне 0.0–1.0."
    )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": instructions},
        {"role": "user", "content": _build_user_message(text, attendees, meeting_date)},
    ]


# ==== Вызов LLM и разбор ответа ====

_CLEAN_FENCE = re.compile(r"^```(?:json)?|```$", re.MULTILINE)


def _extract_json(text: str) -> dict[str, Any]:
    if not text:
        raise ValueError("LLM вернул пустой ответ")
    # вырезаем возможные ```json ... ```
    cleaned = _CLEAN_FENCE.sub("", text).strip()
    return json.loads(cleaned)  # type: ignore


def _to_models(payload: dict[str, Any]) -> list[ExtractedCommit]:
    items = payload.get("commits") or []
    out: list[ExtractedCommit] = []
    for it in items:
        try:
            out.append(ExtractedCommit(**it))
        except ValidationError as e:
            # пропускаем некорректные записи в v0, логирование выше по стеку
            print(f"Skipping invalid commit: {it}, error: {e}")
            continue
    return out


# Удалено: используем единый клиент из app.core.clients


# ==== Публичный интерфейс ====


def extract_commits(
    text: str,
    attendees_en: list[str],
    meeting_date_iso: str,
    *,
    model: str | None = None,
    temperature: float = 0.1,
) -> list[ExtractedCommit]:
    """
    Возвращает список извлечённых коммитов (v0).
    Нормализация исполнителей и дедлайнов — на этапе 2.2.
    """
    with timer(MetricNames.LLM_EXTRACT_COMMITS):
        mdl = model or "gpt-4o-mini"
        messages = _build_messages(text, attendees_en, meeting_date_iso)

        client = get_openai_client()
        try:
            # попытка №1 с response_format
            resp = client.chat.completions.create(
                model=mdl,
                messages=messages,
                temperature=temperature,
                response_format={"type": "json_object"},
            )
            raw = (resp.choices[0].message.content or "").strip()

            # Отслеживаем токены от первой попытки
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

            # если по какой-то причине пришёл не JSON — повторим без response_format
            if not raw or not raw.startswith("{"):
                print("First attempt returned non-JSON, retrying without response_format...")
                resp = client.chat.completions.create(
                    model=mdl,
                    messages=messages,
                    temperature=temperature,
                )
                raw = (resp.choices[0].message.content or "").strip()

                # Отслеживаем токены от второй попытки
                if resp.usage and hasattr(resp.usage, "prompt_tokens"):
                    try:
                        track_llm_tokens(
                            f"{MetricNames.LLM_EXTRACT_COMMITS}.retry",
                            int(resp.usage.prompt_tokens),
                            int(resp.usage.completion_tokens),
                            int(resp.usage.total_tokens),
                        )
                    except (TypeError, ValueError):
                        pass  # Игнорируем ошибки в тестах с Mock объектами

            data = _extract_json(raw)
            commits = _to_models(data)
            return commits

        except Exception as e:
            print(f"Error in extract_commits: {type(e).__name__}: {e}")
            raise
        finally:
            client.close()
