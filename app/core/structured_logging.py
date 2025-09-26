"""
Структурированное логирование для Meet-Commit.

Обеспечивает консистентное и машиночитаемое логирование
всех операций с контекстной информацией.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Literal

from app.core.types import CommitData, MeetingData

logger = logging.getLogger(__name__)

# Типы событий
EventType = Literal[
    "commit_created",
    "commit_updated", 
    "commit_extracted",
    "meeting_created",
    "meeting_updated",
    "review_created",
    "review_updated",
    "llm_request",
    "llm_response",
    "notion_request",
    "notion_response",
    "user_action",
    "pipeline_start",
    "pipeline_end",
    "error",
]


class StructuredLogger:
    """Структурированный логгер с контекстом."""
    
    def __init__(self, name: str):
        self.logger = logging.getLogger(name)
        self.context: dict[str, Any] = {}
    
    def with_context(self, **context: Any) -> StructuredLogger:
        """Создает новый логгер с дополнительным контекстом."""
        new_logger = StructuredLogger(self.logger.name)
        new_logger.context = {**self.context, **context}
        return new_logger
    
    def _log(self, level: int, event_type: EventType, message: str, **extra: Any) -> None:
        """Базовый метод логирования."""
        log_data = {
            "event_type": event_type,
            "message": message,
            "context": self.context,
            **extra,
        }
        
        # Удаляем None значения для чистоты
        log_data = {k: v for k, v in log_data.items() if v is not None}
        
        # Логируем как JSON для машинной обработки + читаемое сообщение
        json_str = json.dumps(log_data, ensure_ascii=False, separators=(',', ':'))
        readable_msg = f"[{event_type}] {message}"
        
        self.logger.log(level, f"{readable_msg} | {json_str}")
    
    def info(self, event_type: EventType, message: str, **extra: Any) -> None:
        """Информационное сообщение."""
        self._log(logging.INFO, event_type, message, **extra)
    
    def warning(self, event_type: EventType, message: str, **extra: Any) -> None:
        """Предупреждение."""
        self._log(logging.WARNING, event_type, message, **extra)
    
    def error(self, event_type: EventType, message: str, **extra: Any) -> None:
        """Ошибка."""
        self._log(logging.ERROR, event_type, message, **extra)
    
    def debug(self, event_type: EventType, message: str, **extra: Any) -> None:
        """Отладочное сообщение."""
        self._log(logging.DEBUG, event_type, message, **extra)


# =============== СПЕЦИАЛИЗИРОВАННЫЕ ЛОГГЕРЫ ===============


def get_commit_logger(user_id: int | None = None, commit_id: str | None = None) -> StructuredLogger:
    """Создает логгер для операций с коммитами."""
    context = {}
    if user_id:
        context["user_id"] = user_id
    if commit_id:
        context["commit_id"] = commit_id
    
    return StructuredLogger("app.commits").with_context(**context)


def get_meeting_logger(meeting_id: str | None = None, user_id: int | None = None) -> StructuredLogger:
    """Создает логгер для операций со встречами."""
    context = {}
    if meeting_id:
        context["meeting_id"] = meeting_id
    if user_id:
        context["user_id"] = user_id
    
    return StructuredLogger("app.meetings").with_context(**context)


def get_llm_logger(operation: str, user_id: int | None = None) -> StructuredLogger:
    """Создает логгер для LLM операций."""
    context = {"operation": operation}
    if user_id:
        context["user_id"] = user_id
    
    return StructuredLogger("app.llm").with_context(**context)


def get_notion_logger(operation: str, database: str | None = None) -> StructuredLogger:
    """Создает логгер для Notion API операций."""
    context = {"operation": operation}
    if database:
        context["database"] = database
    
    return StructuredLogger("app.notion").with_context(**context)


def get_user_logger(user_id: int, username: str | None = None) -> StructuredLogger:
    """Создает логгер для пользовательских действий."""
    context = {"user_id": user_id}
    if username:
        context["username"] = username
    
    return StructuredLogger("app.users").with_context(**context)


# =============== УДОБНЫЕ ФУНКЦИИ ЛОГИРОВАНИЯ ===============


def log_commit_operation(
    operation: Literal["created", "updated", "extracted"],
    commit: CommitData,
    user_id: int | None = None,
    duration_ms: float | None = None,
) -> None:
    """Логирует операцию с коммитом."""
    logger = get_commit_logger(user_id, commit.get("key"))
    
    extra = {
        "commit_title": commit.get("title"),
        "commit_direction": commit.get("direction"),
        "commit_assignees": commit.get("assignees"),
        "commit_tags_count": len(commit.get("tags", [])),
    }
    
    if duration_ms:
        extra["duration_ms"] = duration_ms
    
    logger.info(f"commit_{operation}", f"Commit {operation}: {commit.get('title', 'Unknown')}", **extra)


def log_meeting_operation(
    operation: Literal["created", "updated"],
    meeting: MeetingData,
    user_id: int | None = None,
    duration_ms: float | None = None,
) -> None:
    """Логирует операцию со встречей."""
    logger = get_meeting_logger(meeting.get("raw_hash"), user_id)
    
    extra = {
        "meeting_title": meeting.get("title"),
        "meeting_attendees_count": len(meeting.get("attendees", [])),
        "meeting_tags_count": len(meeting.get("tags", [])),
    }
    
    if duration_ms:
        extra["duration_ms"] = duration_ms
    
    logger.info(f"meeting_{operation}", f"Meeting {operation}: {meeting.get('title', 'Unknown')}", **extra)


def log_llm_request(
    operation: str,
    model: str,
    prompt_length: int,
    user_id: int | None = None,
) -> None:
    """Логирует LLM запрос."""
    logger = get_llm_logger(operation, user_id)
    
    logger.info(
        "llm_request",
        f"LLM request: {operation}",
        model=model,
        prompt_length=prompt_length,
    )


def log_llm_response(
    operation: str,
    response_length: int,
    tokens_used: dict[str, int] | None = None,
    duration_ms: float | None = None,
    user_id: int | None = None,
) -> None:
    """Логирует LLM ответ."""
    logger = get_llm_logger(operation, user_id)
    
    extra = {"response_length": response_length}
    if tokens_used:
        extra.update(tokens_used)
    if duration_ms:
        extra["duration_ms"] = duration_ms
    
    logger.info("llm_response", f"LLM response: {operation}", **extra)


def log_notion_request(
    operation: str,
    database: str,
    filter_params: dict[str, Any] | None = None,
    page_size: int | None = None,
) -> None:
    """Логирует Notion API запрос."""
    logger = get_notion_logger(operation, database)
    
    extra = {}
    if filter_params:
        extra["filter"] = filter_params
    if page_size:
        extra["page_size"] = page_size
    
    logger.info("notion_request", f"Notion request: {operation}", **extra)


def log_notion_response(
    operation: str,
    database: str,
    results_count: int,
    duration_ms: float | None = None,
    error: str | None = None,
) -> None:
    """Логирует Notion API ответ."""
    logger = get_notion_logger(operation, database)
    
    extra = {"results_count": results_count}
    if duration_ms:
        extra["duration_ms"] = duration_ms
    
    if error:
        logger.error("notion_response", f"Notion error: {operation}", error=error, **extra)
    else:
        logger.info("notion_response", f"Notion response: {operation}", **extra)


def log_user_action(
    user_id: int,
    action: str,
    details: dict[str, Any] | None = None,
    username: str | None = None,
) -> None:
    """Логирует действие пользователя."""
    logger = get_user_logger(user_id, username)
    
    extra = details or {}
    logger.info("user_action", f"User action: {action}", **extra)


def log_pipeline_stage(
    stage: str,
    duration_ms: float | None = None,
    items_processed: int | None = None,
    **extra: Any,
) -> None:
    """Логирует этап пайплайна."""
    logger = StructuredLogger("app.pipeline")
    
    log_extra = {}
    if duration_ms:
        log_extra["duration_ms"] = duration_ms
    if items_processed:
        log_extra["items_processed"] = items_processed
    log_extra.update(extra)
    
    logger.info("pipeline_stage", f"Pipeline stage: {stage}", **log_extra)
