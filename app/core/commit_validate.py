# app/core/commit_validate.py
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date
from typing import Literal

from app.core.commit_normalize import NormalizedCommit
from app.core.tags import merge_meeting_and_commit_tags

Level = Literal["HIGH", "MEDIUM", "LOW", "UNCLEAR"]


@dataclass
class ValidationNotes:
    """
    Результат семантической валидации коммита.

    Содержит скорректированные параметры и причины для принятия решений.
    """

    adjusted_confidence: float
    flags: list[str]
    notes: list[str]
    level: Level
    reason_for_review: list[str]  # только если LOW/UNCLEAR


def validate_structure(commit: NormalizedCommit) -> tuple[bool, list[str]]:
    """
    Валидирует структурную корректность коммита.

    Args:
        commit: Нормализованный коммит для проверки

    Returns:
        Tuple (is_valid, error_list)

    Проверяет:
        - Минимальная длина текста (8 символов)
        - Корректность direction
        - Валидность confidence
    """
    errors: list[str] = []

    # Проверка текста
    if not commit.text or len(commit.text.strip()) < 8:
        errors.append("text_too_short")

    # Проверка direction
    if commit.direction not in ("mine", "theirs"):
        errors.append("bad_direction")

    # Проверка confidence
    if commit.confidence is None or not (0.0 <= commit.confidence <= 1.0):
        errors.append("bad_confidence")

    return (len(errors) == 0, errors)


def validate_semantics(
    commit: NormalizedCommit,
    *,
    attendees_en: Iterable[str],
    meeting_date_iso: str,
) -> ValidationNotes:
    """
    Выполняет семантическую валидацию коммита с корректировкой confidence.

    Args:
        commit: Нормализованный коммит для проверки
        attendees_en: Список участников встречи
        meeting_date_iso: Дата встречи в формате YYYY-MM-DD

    Returns:
        ValidationNotes с результатами валидации

    Проверки и штрафы:
        - Исполнители не из списка участников: -0.1
        - theirs без исполнителей: -0.15
        - Дедлайн раньше встречи: -0.2
        - Условные формулировки: -0.1
        - Пассивный залог: -0.08
        - Слишком общий текст: -0.08
        - Отсутствие дедлайна: -0.05
    """
    flags = list(commit.flags or [])
    notes: list[str] = []
    confidence = float(commit.confidence or 0.5)

    attendees_set = {a.strip() for a in attendees_en}
    meeting_date = date.fromisoformat(meeting_date_iso)

    # 1) Валидация исполнителей
    if commit.direction == "theirs" and not commit.assignees:
        flags.append("ambiguous_assignee")
        notes.append("theirs_without_assignee")
        confidence -= 0.15

    # Проверяем, что все исполнители участвовали во встрече
    invalid_assignees = [a for a in commit.assignees if a not in attendees_set]
    if invalid_assignees:
        flags.append("assignee_not_in_attendees")
        notes.append(f"assignee_outside_meeting: {', '.join(invalid_assignees)}")
        confidence -= 0.1

    # 2) Валидация дедлайна
    if commit.due_iso:
        try:
            due_date = date.fromisoformat(commit.due_iso)
            # Дедлайн раньше даты встречи - подозрительно
            if due_date < meeting_date:
                flags.append("due_before_meeting")
                notes.append("due_in_past_vs_meeting")
                confidence -= 0.2
        except ValueError:
            flags.append("bad_due_format")
            notes.append("invalid_due_date_format")
            confidence -= 0.2
    else:
        # Легкий штраф за отсутствие срока
        flags.append("no_due")
        confidence -= 0.05

    # 3) Эвристики качества текста
    text_lower = (commit.text or "").lower()

    # Условные формулировки снижают уверенность
    conditional_phrases = [
        "если получится",
        "возможно",
        "попробуем",
        "при случае",
        "если будет время",
    ]
    if any(phrase in text_lower for phrase in conditional_phrases):
        flags.append("conditional_wording")
        notes.append("contains_conditional_language")
        confidence -= 0.1

    # Пассивный залог менее конкретен
    passive_phrases = ["будет отправлено", "будет сделано", "должно быть", "планируется"]
    if any(phrase in text_lower for phrase in passive_phrases):
        flags.append("passive_voice")
        notes.append("passive_voice_detected")
        confidence -= 0.08

    # Слишком короткий или общий текст
    if len(text_lower) < 20:
        flags.append("too_generic")
        notes.append("text_too_short_for_clarity")
        confidence -= 0.08

    # Проверка на слишком общие формулировки
    generic_phrases = ["сделать задачу", "выполнить работу", "решить вопрос", "разобраться"]
    if any(phrase in text_lower for phrase in generic_phrases):
        flags.append("too_generic")
        notes.append("generic_task_description")
        confidence -= 0.08

    # 4) Ограничиваем confidence в допустимых пределах
    confidence = max(0.0, min(1.0, confidence))

    # 5) Определяем уровень для маршрутизации
    reason_for_review: list[str] = []

    if confidence >= 0.8:
        level: Level = "HIGH"
    elif confidence >= 0.6:
        level = "MEDIUM"
    elif confidence >= 0.4:
        level = "LOW"
        reason_for_review = ["low_confidence"]
    else:
        level = "UNCLEAR"
        reason_for_review = ["unclear_commitment"]

    # Дополнительные причины для ревью
    if "ambiguous_assignee" in flags:
        reason_for_review.append("unclear_assignee")
    if "due_before_meeting" in flags:
        reason_for_review.append("suspicious_due_date")
    if "conditional_wording" in flags:
        reason_for_review.append("conditional_language")

    return ValidationNotes(
        adjusted_confidence=confidence,
        flags=sorted(set(flags)),
        notes=notes,
        level=level,
        reason_for_review=list(set(reason_for_review)),
    )


@dataclass
class PartitionResult:
    """
    Результат разделения коммитов на категории для хранения.

    to_commits: Коммиты высокого качества для прямого сохранения
    to_review: Коммиты низкого качества для ручной проверки
    """

    to_commits: list[NormalizedCommit]
    to_review: list[dict]  # элементы для очереди ревью


def partition_for_storage(
    items: list[NormalizedCommit],
    *,
    attendees_en: list[str],
    meeting_date_iso: str,
) -> PartitionResult:
    """
    Разделяет коммиты на категории для хранения.

    Args:
        items: Список нормализованных коммитов
        attendees_en: Список участников встречи
        meeting_date_iso: Дата встречи в формате YYYY-MM-DD

    Returns:
        PartitionResult с разделенными коммитами

    Логика маршрутизации:
        - HIGH/MEDIUM confidence → прямо в Commits
        - LOW/UNCLEAR confidence → в Review Queue для ручной проверки
        - Структурные ошибки → в Review Queue с низким confidence
    """
    good_commits: list[NormalizedCommit] = []
    review_items: list[dict] = []

    for commit in items:
        # Сначала проверяем структурную корректность
        is_valid, struct_errors = validate_structure(commit)

        if not is_valid:
            # Структурно некорректные коммиты идут в ревью
            review_items.append(
                {
                    "text": commit.text,
                    "direction": commit.direction,
                    "assignees": commit.assignees,
                    "from_person": getattr(commit, "from_person", []) or ["System"],  # Заказчик
                    "due_iso": commit.due_iso,
                    "confidence": 0.3,  # низкий confidence для структурных ошибок
                    "reasons": ["structure_error"] + struct_errors,
                    "context": commit.context,
                    "status": "pending",
                }
            )
            continue

        # Семантическая валидация для структурно корректных коммитов
        validation = validate_semantics(
            commit, attendees_en=attendees_en, meeting_date_iso=meeting_date_iso
        )

        # Обновляем коммит с результатами валидации
        commit.confidence = validation.adjusted_confidence
        commit.flags = validation.flags

        # Маршрутизация по уровню качества
        if validation.level in ("HIGH", "MEDIUM"):
            good_commits.append(commit)
        else:
            # LOW/UNCLEAR коммиты идут в ревью
            review_items.append(
                {
                    "text": commit.text,
                    "direction": commit.direction,
                    "assignees": commit.assignees,
                    "from_person": getattr(commit, "from_person", []) or ["System"],  # Заказчик
                    "due_iso": commit.due_iso,
                    "confidence": validation.adjusted_confidence,
                    "reasons": validation.reason_for_review or ["needs_review"],
                    "context": commit.context,
                    "status": "pending",
                }
            )

    return PartitionResult(to_commits=good_commits, to_review=review_items)


def validate_and_partition(
    items: list[NormalizedCommit],
    *,
    attendees_en: list[str],
    meeting_date_iso: str,
    meeting_tags: list[str],
) -> PartitionResult:
    """
    Комплексная функция валидации и разделения коммитов.

    Выполняет валидацию, добавляет теги встречи и разделяет на категории.

    Args:
        items: Список нормализованных коммитов
        attendees_en: Список участников встречи
        meeting_date_iso: Дата встречи
        meeting_tags: Теги встречи для наследования

    Returns:
        PartitionResult с обработанными коммитами
    """
    # Сначала разделяем по качеству
    result = partition_for_storage(
        items,
        attendees_en=attendees_en,
        meeting_date_iso=meeting_date_iso,
    )

    # Добавляем теги встречи к коммитам высокого качества
    for commit in result.to_commits:
        # Объединяем теги встречи с собственными тегами коммита
        commit.tags = merge_meeting_and_commit_tags(meeting_tags, commit.tags)

    return result
