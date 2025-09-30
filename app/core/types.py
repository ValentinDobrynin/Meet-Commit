"""
Типизированные модели данных для улучшения type safety.

Заменяет dict[str, Any] на конкретные TypedDict модели
для лучшей типизации и IDE поддержки.
"""

from __future__ import annotations

from typing import Any, Literal, TypedDict

# =============== COMMIT TYPES ===============


class CommitData(TypedDict, total=False):
    """Базовая структура данных коммита."""

    title: str
    text: str
    direction: Literal["mine", "theirs"]
    assignees: list[str]
    from_person: list[str]
    due_iso: str | None
    confidence: float
    flags: list[str]
    key: str
    tags: list[str]
    status: Literal["open", "done", "dropped", "cancelled"]


class NotionCommitData(CommitData):
    """Коммит с дополнительными Notion полями."""

    id: str
    url: str
    short_id: str
    meeting_ids: list[str]


class ExtractedCommitData(TypedDict, total=False):
    """Данные коммита извлеченного из LLM."""

    text: str
    direction: Literal["mine", "theirs"]
    assignees: list[str]
    due_iso: str | None
    confidence: float
    flags: list[str]
    context: str | None
    reasoning: str | None


# =============== MEETING TYPES ===============


class MeetingData(TypedDict, total=False):
    """Базовая структура данных встречи."""

    title: str
    date: str | None  # ISO YYYY-MM-DD
    attendees: list[str]
    source: str
    raw_hash: str
    summary_md: str
    tags: list[str]


class NotionMeetingData(MeetingData):
    """Встреча с дополнительными Notion полями."""

    id: str
    url: str
    short_id: str


# =============== REVIEW TYPES ===============


class ReviewData(TypedDict, total=False):
    """Структура данных для Review Queue."""

    text: str
    direction: Literal["mine", "theirs"]
    assignees: list[str]
    from_person: list[str]
    due_iso: str | None
    confidence: float
    reasons: list[str]
    context: str | None
    status: Literal["pending", "needs-review", "confirmed", "rejected"]
    key: str


class NotionReviewData(ReviewData):
    """Review с дополнительными Notion полями."""

    id: str
    url: str
    short_id: str
    meeting_ids: list[str]


# =============== AGENDA TYPES ===============


class AgendaContextData(TypedDict):
    """Контекст для повестки."""

    context_type: Literal["Meeting", "Person", "Tag"]
    context_key: str


class AgendaData(TypedDict, total=False):
    """Структура данных повестки."""

    name: str
    date_iso: str
    context_type: Literal["Meeting", "Person", "Tag"]
    context_key: str
    summary_md: str
    tags: list[str]
    people: list[str]
    raw_hash: str
    commit_ids: list[str]


class NotionAgendaData(AgendaData):
    """Повестка с дополнительными Notion полями."""

    id: str
    url: str


# =============== METRICS TYPES ===============


class MetricSnapshot(TypedDict):
    """Снимок метрик."""

    counters: dict[str, int]
    errors: dict[str, int]
    last_errors: dict[str, str]
    latency: dict[str, dict[str, float]]
    llm_tokens: dict[str, dict[str, int]]
    timestamp: float


class LatencyData(TypedDict):
    """Данные латентности."""

    avg: float
    p50: float
    p95: float
    p99: float
    count: int


class LLMTokenData(TypedDict):
    """Данные использования LLM токенов."""

    prompt: int
    completion: int
    total: int
    calls: int


# =============== PIPELINE TYPES ===============


class PipelineStats(TypedDict):
    """Статистика выполнения пайплайна."""

    created: int
    updated: int
    review_created: int
    review_updated: int


class NormalizationMeta(TypedDict, total=False):
    """Метаданные нормализации документа."""

    text: str
    title: str
    date: str | None
    attendees: list[str]
    sha: str
    filename: str


# =============== API RESPONSE TYPES ===============


class NotionQueryResponse(TypedDict):
    """Ответ от Notion API query."""

    results: list[dict[str, Any]]
    next_cursor: str | None
    has_more: bool


class NotionPageResponse(TypedDict):
    """Ответ от Notion API для страницы."""

    id: str
    url: str
    properties: dict[str, Any]
    created_time: str
    last_edited_time: str


class OpenAIUsageData(TypedDict):
    """Данные использования OpenAI API."""

    prompt_tokens: int
    completion_tokens: int
    total_tokens: int


class OpenAIResponse(TypedDict):
    """Ответ от OpenAI API."""

    choices: list[dict[str, Any]]
    usage: OpenAIUsageData | None


# =============== CONFIGURATION TYPES ===============


class NotionConfig(TypedDict):
    """Конфигурация Notion."""

    token_configured: bool
    meetings_db_configured: bool
    commits_db_configured: bool
    review_db_configured: bool
    agendas_db_configured: bool
    api_version: str
    timeout: float
    missing_configs: list[str]
    ready: bool


class OpenAIConfig(TypedDict):
    """Конфигурация OpenAI."""

    api_key_configured: bool
    default_model: str
    default_temperature: float
    default_timeout: float
    parse_timeout: float
    ready: bool


class ClientsInfo(TypedDict):
    """Информация о клиентах."""

    notion: NotionConfig
    openai: OpenAIConfig
    cache_info: dict[str, Any]


# =============== PEOPLE MINER TYPES ===============


class CandidateSample(TypedDict):
    """Образец контекста для кандидата."""

    meeting_id: str
    date: str
    snippet: str


class CandidateData(TypedDict, total=False):
    """Данные кандидата в People Miner v2."""

    first_seen: str
    last_seen: str
    freq: int
    meetings: int
    samples: list[CandidateSample]
    _meeting_ids: set[str]  # Внутреннее поле для отслеживания встреч


class CandidateItem(TypedDict):
    """Элемент кандидата для отображения."""

    alias: str
    freq: int
    meetings: int
    first_seen: str
    last_seen: str
    score: float
    samples: list[CandidateSample]


class CandidateStats(TypedDict):
    """Статистика кандидатов."""

    total: int
    avg_freq: float
    avg_meetings: float
    freq_distribution: dict[str, int]  # high/medium/low
    recent_candidates: int


# Для удобства использования - алиас типа
CandidateListResult = tuple[list[CandidateItem], int]
