"""
Тесты для модуля валидации коммитов app.core.commit_validate
"""

from app.core.commit_normalize import NormalizedCommit
from app.core.commit_validate import (
    PartitionResult,
    partition_for_storage,
    validate_and_partition,
    validate_semantics,
    validate_structure,
)


class TestStructuralValidation:
    """Тесты структурной валидации коммитов."""

    def test_validate_structure_valid_commit(self):
        """Тест валидации корректного коммита."""
        commit = NormalizedCommit(
            text="Подготовить отчет по IFRS",
            direction="theirs",
            assignees=["Daniil"],
            due_iso="2024-12-31",
            confidence=0.8,
            flags=[],
            context=None,
            reasoning=None,
            title="Daniil: Подготовить отчет по IFRS [due 2024-12-31]",
            key="test_key",
            tags=[],
        )

        is_valid, errors = validate_structure(commit)
        assert is_valid is True
        assert errors == []

    def test_validate_structure_short_text(self):
        """Тест валидации коммита с коротким текстом."""
        commit = NormalizedCommit(
            text="Тест",  # менее 8 символов
            direction="mine",
            assignees=[],
            due_iso=None,
            confidence=0.5,
            flags=[],
            context=None,
            reasoning=None,
            title="Test title",
            key="test_key",
            tags=[],
        )

        is_valid, errors = validate_structure(commit)
        assert is_valid is False
        assert "text_too_short" in errors

    def test_validate_structure_bad_direction(self):
        """Тест валидации коммита с неправильным direction."""
        commit = NormalizedCommit(
            text="Выполнить задачу",
            direction="invalid",  # неправильное значение
            assignees=[],
            due_iso=None,
            confidence=0.5,
            flags=[],
            context=None,
            reasoning=None,
            title="Test title",
            key="test_key",
            tags=[],
        )

        is_valid, errors = validate_structure(commit)
        assert is_valid is False
        assert "bad_direction" in errors

    def test_validate_structure_bad_confidence(self):
        """Тест валидации коммита с неправильным confidence."""
        commit = NormalizedCommit(
            text="Выполнить задачу",
            direction="mine",
            assignees=[],
            due_iso=None,
            confidence=1.5,  # вне диапазона 0-1
            flags=[],
            context=None,
            reasoning=None,
            title="Test title",
            key="test_key",
            tags=[],
        )

        is_valid, errors = validate_structure(commit)
        assert is_valid is False
        assert "bad_confidence" in errors

    def test_validate_structure_multiple_errors(self):
        """Тест валидации коммита с множественными ошибками."""
        commit = NormalizedCommit(
            text="",  # пустой текст
            direction="wrong",  # неправильное значение
            assignees=[],
            due_iso=None,
            confidence=-0.1,  # отрицательное значение
            flags=[],
            context=None,
            reasoning=None,
            title="Test title",
            key="test_key",
            tags=[],
        )

        is_valid, errors = validate_structure(commit)
        assert is_valid is False
        assert "text_too_short" in errors
        assert "bad_direction" in errors
        assert "bad_confidence" in errors


class TestSemanticValidation:
    """Тесты семантической валидации коммитов."""

    def test_validate_semantics_high_quality_commit(self):
        """Тест валидации высококачественного коммита."""
        commit = NormalizedCommit(
            text="Подготовить детальный отчет по IFRS до конца месяца",
            direction="theirs",
            assignees=["Daniil"],
            due_iso="2024-12-31",
            confidence=0.9,
            flags=[],
            context=None,
            reasoning=None,
            title="Test title",
            key="test_key",
            tags=[],
        )

        validation = validate_semantics(
            commit, attendees_en=["Daniil", "Valentin"], meeting_date_iso="2024-06-15"
        )

        assert validation.level == "HIGH"
        assert validation.adjusted_confidence >= 0.8
        assert validation.reason_for_review == []

    def test_validate_semantics_theirs_without_assignee(self):
        """Тест валидации theirs коммита без исполнителя."""
        commit = NormalizedCommit(
            text="Подготовить отчет",
            direction="theirs",
            assignees=[],  # нет исполнителей
            due_iso="2024-12-31",
            confidence=0.8,
            flags=[],
            context=None,
            reasoning=None,
            title="Test title",
            key="test_key",
            tags=[],
        )

        validation = validate_semantics(
            commit, attendees_en=["Daniil", "Valentin"], meeting_date_iso="2024-06-15"
        )

        assert "ambiguous_assignee" in validation.flags
        assert "theirs_without_assignee" in validation.notes
        assert validation.adjusted_confidence < 0.8  # штраф -0.15
        assert "unclear_assignee" in validation.reason_for_review

    def test_validate_semantics_assignee_not_in_meeting(self):
        """Тест валидации коммита с исполнителем вне встречи."""
        commit = NormalizedCommit(
            text="Подготовить отчет",
            direction="theirs",
            assignees=["Unknown Person"],  # не участвовал во встрече
            due_iso="2024-12-31",
            confidence=0.8,
            flags=[],
            context=None,
            reasoning=None,
            title="Test title",
            key="test_key",
            tags=[],
        )

        validation = validate_semantics(
            commit, attendees_en=["Daniil", "Valentin"], meeting_date_iso="2024-06-15"
        )

        assert "assignee_not_in_attendees" in validation.flags
        assert "Unknown Person" in validation.notes[0]
        assert validation.adjusted_confidence < 0.8  # штраф -0.1

    def test_validate_semantics_due_before_meeting(self):
        """Тест валидации коммита с дедлайном раньше встречи."""
        commit = NormalizedCommit(
            text="Подготовить отчет",
            direction="theirs",
            assignees=["Daniil"],
            due_iso="2024-01-01",  # раньше даты встречи
            confidence=0.8,
            flags=[],
            context=None,
            reasoning=None,
            title="Test title",
            key="test_key",
            tags=[],
        )

        validation = validate_semantics(
            commit, attendees_en=["Daniil", "Valentin"], meeting_date_iso="2024-06-15"
        )

        assert "due_before_meeting" in validation.flags
        assert "due_in_past_vs_meeting" in validation.notes
        assert validation.adjusted_confidence < 0.6  # штраф -0.2
        assert "suspicious_due_date" in validation.reason_for_review

    def test_validate_semantics_invalid_due_format(self):
        """Тест валидации коммита с неправильным форматом даты."""
        commit = NormalizedCommit(
            text="Подготовить отчет",
            direction="theirs",
            assignees=["Daniil"],
            due_iso="invalid-date",  # неправильный формат
            confidence=0.8,
            flags=[],
            context=None,
            reasoning=None,
            title="Test title",
            key="test_key",
            tags=[],
        )

        validation = validate_semantics(
            commit, attendees_en=["Daniil", "Valentin"], meeting_date_iso="2024-06-15"
        )

        assert "bad_due_format" in validation.flags
        assert "invalid_due_date_format" in validation.notes
        assert validation.adjusted_confidence < 0.6  # штраф -0.2

    def test_validate_semantics_no_due_date(self):
        """Тест валидации коммита без дедлайна."""
        commit = NormalizedCommit(
            text="Подготовить отчет",
            direction="theirs",
            assignees=["Daniil"],
            due_iso=None,  # нет дедлайна
            confidence=0.8,
            flags=[],
            context=None,
            reasoning=None,
            title="Test title",
            key="test_key",
            tags=[],
        )

        validation = validate_semantics(
            commit, attendees_en=["Daniil", "Valentin"], meeting_date_iso="2024-06-15"
        )

        assert "no_due" in validation.flags
        assert validation.adjusted_confidence < 0.8  # легкий штраф -0.05

    def test_validate_semantics_conditional_wording(self):
        """Тест валидации коммита с условными формулировками."""
        commit = NormalizedCommit(
            text="Если получится, подготовлю отчет",
            direction="mine",
            assignees=["Valentin"],
            due_iso="2024-12-31",
            confidence=0.8,
            flags=[],
            context=None,
            reasoning=None,
            title="Test title",
            key="test_key",
            tags=[],
        )

        validation = validate_semantics(
            commit, attendees_en=["Daniil", "Valentin"], meeting_date_iso="2024-06-15"
        )

        assert "conditional_wording" in validation.flags
        assert "contains_conditional_language" in validation.notes
        assert validation.adjusted_confidence < 0.8  # штраф -0.1
        assert "conditional_language" in validation.reason_for_review

    def test_validate_semantics_passive_voice(self):
        """Тест валидации коммита с пассивным залогом."""
        commit = NormalizedCommit(
            text="Отчет будет сделано командой",
            direction="theirs",
            assignees=["Daniil"],
            due_iso="2024-12-31",
            confidence=0.8,
            flags=[],
            context=None,
            reasoning=None,
            title="Test title",
            key="test_key",
            tags=[],
        )

        validation = validate_semantics(
            commit, attendees_en=["Daniil", "Valentin"], meeting_date_iso="2024-06-15"
        )

        assert "passive_voice" in validation.flags
        assert "passive_voice_detected" in validation.notes
        assert validation.adjusted_confidence < 0.8  # штраф -0.08

    def test_validate_semantics_too_generic(self):
        """Тест валидации слишком общего коммита."""
        commit = NormalizedCommit(
            text="Сделать задачу",  # общая формулировка
            direction="mine",
            assignees=["Valentin"],
            due_iso="2024-12-31",
            confidence=0.8,
            flags=[],
            context=None,
            reasoning=None,
            title="Test title",
            key="test_key",
            tags=[],
        )

        validation = validate_semantics(
            commit, attendees_en=["Daniil", "Valentin"], meeting_date_iso="2024-06-15"
        )

        assert "too_generic" in validation.flags
        assert any("generic" in note for note in validation.notes)
        assert validation.adjusted_confidence < 0.8  # штраф -0.08

    def test_validate_semantics_confidence_bounds(self):
        """Тест ограничения confidence в пределах 0-1."""
        commit = NormalizedCommit(
            text="Если получится, возможно сделать задачу",  # много штрафов
            direction="theirs",
            assignees=[],  # нет исполнителей
            due_iso=None,  # нет дедлайна
            confidence=0.3,  # низкий изначальный confidence
            flags=[],
            context=None,
            reasoning=None,
            title="Test title",
            key="test_key",
            tags=[],
        )

        validation = validate_semantics(
            commit, attendees_en=["Daniil", "Valentin"], meeting_date_iso="2024-06-15"
        )

        # Confidence не может быть отрицательным
        assert 0.0 <= validation.adjusted_confidence <= 1.0
        assert validation.level == "UNCLEAR"

    def test_validate_semantics_level_thresholds(self):
        """Тест пороговых значений для уровней качества."""
        test_cases = [
            (0.9, "HIGH"),
            (0.8, "HIGH"),
            (0.7, "MEDIUM"),
            (0.6, "MEDIUM"),
            (0.5, "LOW"),
            (0.4, "LOW"),
            (0.3, "UNCLEAR"),
            (0.1, "UNCLEAR"),
        ]

        for confidence, expected_level in test_cases:
            commit = NormalizedCommit(
                text="Подготовить детальный отчет",
                direction="theirs",
                assignees=["Daniil"],
                due_iso="2024-12-31",
                confidence=confidence,
                flags=[],
                context=None,
                reasoning=None,
                title="Test title",
                key="test_key",
                tags=[],
            )

            validation = validate_semantics(
                commit, attendees_en=["Daniil", "Valentin"], meeting_date_iso="2024-06-15"
            )

            assert validation.level == expected_level


class TestPartitioning:
    """Тесты разделения коммитов на категории."""

    def test_partition_for_storage_high_quality_commits(self):
        """Тест разделения высококачественных коммитов."""
        commits = [
            NormalizedCommit(
                text="Подготовить детальный отчет по IFRS",
                direction="theirs",
                assignees=["Daniil"],
                due_iso="2024-12-31",
                confidence=0.9,
                flags=[],
                context=None,
                reasoning=None,
                title="Test title 1",
                key="test_key_1",
                tags=[],
            ),
            NormalizedCommit(
                text="Провести анализ финансовых показателей",
                direction="mine",
                assignees=["Valentin"],
                due_iso="2024-11-30",
                confidence=0.8,
                flags=[],
                context=None,
                reasoning=None,
                title="Test title 2",
                key="test_key_2",
                tags=[],
            ),
        ]

        result = partition_for_storage(
            commits, attendees_en=["Daniil", "Valentin"], meeting_date_iso="2024-06-15"
        )

        assert len(result.to_commits) == 2
        assert len(result.to_review) == 0
        assert all(c.confidence >= 0.6 for c in result.to_commits)

    def test_partition_for_storage_low_quality_commits(self):
        """Тест разделения низкокачественных коммитов."""
        commits = [
            NormalizedCommit(
                text="Если получится, сделать задачу",  # условная формулировка
                direction="theirs",
                assignees=[],  # нет исполнителей
                due_iso=None,  # нет дедлайна
                confidence=0.5,
                flags=[],
                context=None,
                reasoning=None,
                title="Test title",
                key="test_key",
                tags=[],
            )
        ]

        result = partition_for_storage(
            commits, attendees_en=["Daniil", "Valentin"], meeting_date_iso="2024-06-15"
        )

        assert len(result.to_commits) == 0
        assert len(result.to_review) == 1

        review_item = result.to_review[0]
        assert review_item["status"] == "pending"
        assert (
            "low_confidence" in review_item["reasons"]
            or "unclear_commitment" in review_item["reasons"]
        )

    def test_partition_for_storage_structural_errors(self):
        """Тест разделения коммитов со структурными ошибками."""
        commits = [
            NormalizedCommit(
                text="Тест",  # слишком короткий текст
                direction="mine",
                assignees=["Valentin"],
                due_iso="2024-12-31",
                confidence=0.8,
                flags=[],
                context=None,
                reasoning=None,
                title="Test title",
                key="test_key",
                tags=[],
            )
        ]

        result = partition_for_storage(
            commits, attendees_en=["Daniil", "Valentin"], meeting_date_iso="2024-06-15"
        )

        assert len(result.to_commits) == 0
        assert len(result.to_review) == 1

        review_item = result.to_review[0]
        assert review_item["confidence"] == 0.3  # низкий confidence для структурных ошибок
        assert "structure_error" in review_item["reasons"]
        assert "text_too_short" in review_item["reasons"]

    def test_partition_for_storage_mixed_quality(self):
        """Тест разделения смешанного качества коммитов."""
        commits = [
            # Высокое качество
            NormalizedCommit(
                text="Подготовить детальный отчет по IFRS",
                direction="theirs",
                assignees=["Daniil"],
                due_iso="2024-12-31",
                confidence=0.9,
                flags=[],
                context=None,
                reasoning=None,
                title="High quality",
                key="high_key",
                tags=[],
            ),
            # Низкое качество
            NormalizedCommit(
                text="Возможно, сделать что-то",
                direction="theirs",
                assignees=[],
                due_iso=None,
                confidence=0.4,
                flags=[],
                context=None,
                reasoning=None,
                title="Low quality",
                key="low_key",
                tags=[],
            ),
            # Структурная ошибка
            NormalizedCommit(
                text="",  # пустой текст
                direction="mine",
                assignees=["Valentin"],
                due_iso="2024-12-31",
                confidence=0.8,
                flags=[],
                context=None,
                reasoning=None,
                title="Structural error",
                key="error_key",
                tags=[],
            ),
        ]

        result = partition_for_storage(
            commits, attendees_en=["Daniil", "Valentin"], meeting_date_iso="2024-06-15"
        )

        assert len(result.to_commits) == 1  # только высококачественный
        assert len(result.to_review) == 2  # низкое качество + структурная ошибка

        # Проверяем качественный коммит
        assert result.to_commits[0].text == "Подготовить детальный отчет по IFRS"

        # Проверяем элементы ревью
        review_reasons = [item["reasons"] for item in result.to_review]
        assert any("structure_error" in reasons for reasons in review_reasons)
        assert any(
            "low_confidence" in reasons or "unclear_commitment" in reasons
            for reasons in review_reasons
        )


class TestValidateAndPartition:
    """Тесты комплексной функции валидации и разделения."""

    def test_validate_and_partition_with_tags(self):
        """Тест добавления тегов встречи к качественным коммитам."""
        commits = [
            NormalizedCommit(
                text="Подготовить отчет по IFRS",
                direction="theirs",
                assignees=["Daniil"],
                due_iso="2024-12-31",
                confidence=0.9,
                flags=[],
                context=None,
                reasoning=None,
                title="Test title",
                key="test_key",
                tags=["existing_tag"],  # уже есть тег
            )
        ]

        meeting_tags = ["Topic/Meeting", "Projects/IFRS"]

        result = validate_and_partition(
            commits,
            attendees_en=["Daniil", "Valentin"],
            meeting_date_iso="2024-06-15",
            meeting_tags=meeting_tags,
        )

        assert len(result.to_commits) == 1
        commit = result.to_commits[0]

        # Проверяем, что теги встречи добавлены согласно новой логике наследования
        # Projects теги всегда наследуются
        assert "Projects/IFRS" in commit.tags
        # Topic теги наследуются
        assert "Topic/Meeting" in commit.tags
        # Существующий тег коммита сохраняется
        assert "existing_tag" in commit.tags

    def test_validate_and_partition_no_tags_for_review(self):
        """Тест что теги не добавляются к элементам ревью."""
        commits = [
            NormalizedCommit(
                text="Возможно сделать что-то",  # низкое качество
                direction="theirs",
                assignees=[],
                due_iso=None,
                confidence=0.3,
                flags=[],
                context=None,
                reasoning=None,
                title="Test title",
                key="test_key",
                tags=[],
            )
        ]

        meeting_tags = ["meeting_tag", "project/test"]

        result = validate_and_partition(
            commits,
            attendees_en=["Daniil", "Valentin"],
            meeting_date_iso="2024-06-15",
            meeting_tags=meeting_tags,
        )

        assert len(result.to_commits) == 0
        assert len(result.to_review) == 1

        # Элементы ревью не содержат теги встречи
        review_item = result.to_review[0]
        assert "tags" not in review_item or not review_item.get("tags")

    def test_validate_and_partition_empty_input(self):
        """Тест обработки пустого списка коммитов."""
        result = validate_and_partition(
            [],
            attendees_en=["Daniil", "Valentin"],
            meeting_date_iso="2024-06-15",
            meeting_tags=["meeting_tag"],
        )

        assert len(result.to_commits) == 0
        assert len(result.to_review) == 0
        assert isinstance(result, PartitionResult)


class TestEdgeCases:
    """Тесты граничных случаев."""

    def test_empty_attendees_list(self):
        """Тест обработки пустого списка участников."""
        commit = NormalizedCommit(
            text="Подготовить отчет",
            direction="theirs",
            assignees=["Someone"],
            due_iso="2024-12-31",
            confidence=0.8,
            flags=[],
            context=None,
            reasoning=None,
            title="Test title",
            key="test_key",
            tags=[],
        )

        validation = validate_semantics(
            commit,
            attendees_en=[],  # пустой список
            meeting_date_iso="2024-06-15",
        )

        # Все исполнители будут считаться "не из встречи"
        assert "assignee_not_in_attendees" in validation.flags
        assert validation.adjusted_confidence < 0.8

    def test_future_meeting_date(self):
        """Тест обработки будущей даты встречи."""
        commit = NormalizedCommit(
            text="Подготовить отчет",
            direction="theirs",
            assignees=["Daniil"],
            due_iso="2025-01-01",  # будущая дата
            confidence=0.8,
            flags=[],
            context=None,
            reasoning=None,
            title="Test title",
            key="test_key",
            tags=[],
        )

        validation = validate_semantics(
            commit,
            attendees_en=["Daniil"],
            meeting_date_iso="2025-06-15",  # встреча в будущем
        )

        # Дедлайн раньше встречи - это подозрительно
        assert "due_before_meeting" in validation.flags
        assert validation.adjusted_confidence < 0.6

    def test_same_date_due_and_meeting(self):
        """Тест обработки одинаковой даты дедлайна и встречи."""
        commit = NormalizedCommit(
            text="Подготовить отчет",
            direction="theirs",
            assignees=["Daniil"],
            due_iso="2024-06-15",  # та же дата что и встреча
            confidence=0.8,
            flags=[],
            context=None,
            reasoning=None,
            title="Test title",
            key="test_key",
            tags=[],
        )

        validation = validate_semantics(
            commit, attendees_en=["Daniil"], meeting_date_iso="2024-06-15"
        )

        # Одинаковая дата не считается ошибкой
        assert "due_before_meeting" not in validation.flags
        assert (
            validation.adjusted_confidence >= 0.7
        )  # только штраф за отсутствие дедлайна не применяется
