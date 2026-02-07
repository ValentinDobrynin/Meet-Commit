"""
Тесты исправления извлечения и отображения дат в LLM коммитах.
"""

from unittest.mock import patch

import pytest

from app.bot.formatters import format_commit_card
from app.core.agenda_builder import _format_commit_line
from app.core.llm_commit_parse import parse_commit_text


class TestLLMDatesExtraction:
    """Тесты извлечения дат в LLM парсинге."""

    @patch("app.core.llm_commit_parse._call_llm_parse")
    def test_llm_extracts_relative_dates(self, mock_llm):
        """LLM извлекает относительные даты."""
        test_cases = [
            {
                "input": "Саша сделает отчет до конца недели",
                "llm_response": {
                    "text": "сделать отчет до конца недели",
                    "assignee": "Sasha",
                    "from_person": None,
                    "due": "2025-09-30",
                    "confidence": 0.9,
                },
                "expected_due": "2025-09-30",
            },
            {
                "input": "Подготовить презентацию до конца октября",
                "llm_response": {
                    "text": "подготовить презентацию до конца октября",
                    "assignee": None,
                    "from_person": None,
                    "due": "2025-10-31",
                    "confidence": 0.8,
                },
                "expected_due": "2025-10-31",
            },
            {
                "input": "Сделать анализ до пятницы",
                "llm_response": {
                    "text": "сделать анализ до пятницы",
                    "assignee": None,
                    "from_person": None,
                    "due": "2025-09-27",
                    "confidence": 0.9,
                },
                "expected_due": "2025-09-27",
            },
        ]

        for case in test_cases:
            mock_llm.return_value = case["llm_response"]

            result = parse_commit_text(case["input"], "Valentin Dobrynin")

            assert result["due_iso"] == case["expected_due"], f"Failed for: {case['input']}"
            assert result["text"] == case["llm_response"]["text"]

    @patch("app.core.llm_commit_parse._call_llm_parse")
    def test_llm_handles_no_date(self, mock_llm):
        """LLM корректно обрабатывает отсутствие даты."""
        mock_llm.return_value = {
            "text": "подготовить документы",
            "assignee": "Sasha",
            "from_person": None,
            "due": None,
            "confidence": 0.7,
        }

        result = parse_commit_text("Саша подготовит документы", "Valentin Dobrynin")

        assert result["due_iso"] is None
        assert result["text"] == "подготовить документы"


class TestDateDisplayInUI:
    """Тесты отображения дат в UI."""

    def test_agenda_format_commit_line_with_date(self):
        """Agenda корректно отображает дату из due_iso."""
        commit = {
            "text": "подготовить отчет",
            "assignees": ["Sasha"],
            "from_person": ["Valya Dobrynin"],
            "due_iso": "2025-10-31",
            "status": "open",
        }

        result = _format_commit_line(commit)

        # Должна быть дата в формате due_iso
        assert "2025-10-31" in result
        assert "подготовить отчет" in result
        assert "Sasha" in result

    def test_agenda_format_commit_line_without_date(self):
        """Agenda корректно обрабатывает отсутствие даты."""
        commit = {
            "text": "подготовить отчет",
            "assignees": ["Sasha"],
            "from_person": ["Valya Dobrynin"],
            "due_iso": None,
            "status": "open",
        }

        result = _format_commit_line(commit)

        # Должен быть прочерк для отсутствующей даты
        assert "—" in result
        assert "подготовить отчет" in result

    def test_commit_card_formats_date(self):
        """Карточка коммита правильно форматирует дату."""
        commit = {
            "text": "подготовить презентацию",
            "assignees": ["Sasha Katanov"],
            "from_person": ["Valya Dobrynin"],
            "due_iso": "2025-10-31",
            "status": "open",
            "direction": "theirs",
            "short_id": "abc123",
        }

        result = format_commit_card(commit)

        # Дата должна быть отформатирована как DD.MM.YYYY
        assert "31.10.2025" in result
        assert "Срок:" in result
        assert "подготовить презентацию" in result

    def test_commit_card_handles_no_date(self):
        """Карточка коммита обрабатывает отсутствие даты."""
        commit = {
            "text": "подготовить документы",
            "assignees": ["Sasha"],
            "due_iso": None,
            "status": "open",
            "direction": "theirs",
        }

        result = format_commit_card(commit)

        # Должен быть прочерк для отсутствующей даты
        assert "—" in result
        assert "Срок:" in result


class TestDateFieldMappingFix:
    """Тесты исправления маппинга полей дат."""

    def test_agenda_uses_due_iso_not_due_date(self):
        """Проверяем что agenda использует due_iso, а не due_date."""
        # Тестируем что _format_commit_line использует правильное поле
        commit_with_due_iso = {
            "text": "задача с due_iso",
            "assignees": ["Test"],
            "due_iso": "2025-10-31",  # Правильное поле
            "due_date": "wrong_date",  # Неправильное поле (если есть)
            "status": "open",
        }

        result = _format_commit_line(commit_with_due_iso)

        # Должна использоваться дата из due_iso
        assert "2025-10-31" in result
        assert "wrong_date" not in result

    def test_integration_llm_to_agenda_display(self):
        """Интеграционный тест: от LLM парсинга до отображения в agenda."""
        # Мокаем LLM ответ с датой
        with patch("app.core.llm_commit_parse._call_llm_parse") as mock_llm:
            mock_llm.return_value = {
                "text": "подготовить квартальный отчет до конца октября",
                "assignee": "Sasha Katanov",
                "from_person": None,
                "due": "2025-10-31",
                "confidence": 0.9,
            }

            # 1. LLM парсинг
            commit_data = parse_commit_text(
                "Саша Катанов подготовит квартальный отчет до конца октября", "Valentin Dobrynin"
            )

            # 2. Проверяем что дата извлечена
            assert commit_data["due_iso"] == "2025-10-31"

            # 3. Проверяем отображение в agenda
            agenda_line = _format_commit_line(commit_data)
            assert "2025-10-31" in agenda_line

            # 4. Проверяем отображение в карточке
            card = format_commit_card(commit_data)
            assert "31.10.2025" in card  # Форматированная дата


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


