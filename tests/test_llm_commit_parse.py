"""
Тесты для LLM парсинга коммитов.
"""

from pathlib import Path
from unittest.mock import patch

import pytest

from app.core.llm_commit_parse import (
    _apply_role_fallbacks,
    _build_full_commit,
    _create_fallback_commit,
    parse_commit_text,
)


class TestRoleFallbacks:
    """Тесты логики fallback для ролей."""

    def test_both_specified(self):
        """Тест когда указаны и исполнитель и заказчик."""
        llm_result = {"assignee": "Sasha", "from_person": "Daniil"}
        assignee, from_person, direction = _apply_role_fallbacks(llm_result, "Valya")

        assert assignee == "Sasha"
        assert from_person == "Daniil"
        assert direction == "theirs"  # Исполнитель не пользователь

    def test_only_assignee(self):
        """Тест когда указан только исполнитель."""
        llm_result = {"assignee": "Sasha", "from_person": None}
        assignee, from_person, direction = _apply_role_fallbacks(llm_result, "Valya")

        assert assignee == "Sasha"
        assert from_person == "Valya"  # Fallback к пользователю
        assert direction == "theirs"

    def test_only_from_person(self):
        """Тест когда указан только заказчик."""
        llm_result = {"assignee": None, "from_person": "Sasha"}
        assignee, from_person, direction = _apply_role_fallbacks(llm_result, "Valya")

        assert assignee == "Valya"  # Fallback к пользователю
        assert from_person == "Sasha"
        assert direction == "mine"  # Пользователь исполнитель

    def test_nothing_specified(self):
        """Тест когда ничего не указано."""
        llm_result = {"assignee": None, "from_person": None}
        assignee, from_person, direction = _apply_role_fallbacks(llm_result, "Valya")

        assert assignee == "Valya"  # Fallback к пользователю
        assert from_person == "Valya"  # Fallback к пользователю
        assert direction == "mine"  # Пользователь и исполнитель и заказчик

    def test_user_as_assignee(self):
        """Тест когда пользователь указан как исполнитель."""
        llm_result = {"assignee": "Valya", "from_person": "Sasha"}
        assignee, from_person, direction = _apply_role_fallbacks(llm_result, "Valya")

        assert assignee == "Valya"
        assert from_person == "Sasha"
        assert direction == "mine"  # Пользователь исполнитель


class TestBuildFullCommit:
    """Тесты построения полного коммита."""

    @patch("app.core.commit_normalize.build_title")
    @patch("app.core.commit_normalize.build_key")
    @patch("app.core.tags.tag_text")
    def test_build_full_commit_complete(self, mock_tag_text, mock_build_key, mock_build_title):
        """Тест построения полного коммита со всеми полями."""
        # Настраиваем моки
        mock_build_title.return_value = "Test Title"
        mock_build_key.return_value = "test_key_123"
        mock_tag_text.return_value = ["Topic/Test"]

        llm_result = {"text": "подготовить отчет", "due": "2025-10-05", "confidence": 0.9}

        result = _build_full_commit(llm_result, "Valya", "Sasha", "Daniil", "theirs")

        assert result["title"] == "Test Title"
        assert result["text"] == "подготовить отчет"
        assert result["direction"] == "theirs"
        assert result["assignees"] == ["Sasha"]
        assert result["from_person"] == ["Daniil"]
        assert result["due_iso"] == "2025-10-05"
        assert result["confidence"] == 0.9
        assert result["flags"] == ["direct", "llm"]
        assert result["key"] == "test_key_123"
        assert result["tags"] == ["Topic/Test"]
        assert result["status"] == "open"

    @patch("app.core.commit_normalize.build_title")
    @patch("app.core.commit_normalize.build_key")
    @patch("app.core.tags.tag_text")
    def test_build_full_commit_minimal(self, mock_tag_text, mock_build_key, mock_build_title):
        """Тест построения коммита с минимальными данными."""
        mock_build_title.return_value = "Minimal Title"
        mock_build_key.return_value = "minimal_key"
        mock_tag_text.return_value = []

        llm_result = {"text": "сделать задачу"}

        result = _build_full_commit(llm_result, "Valya", "Valya", "Valya", "mine")

        assert result["text"] == "сделать задачу"
        assert result["direction"] == "mine"
        assert result["assignees"] == ["Valya"]
        assert result["from_person"] == ["Valya"]
        assert result["due_iso"] is None
        assert result["confidence"] == 0.7  # Default
        assert result["tags"] == []

    def test_build_full_commit_empty_text(self):
        """Тест ошибки при пустом тексте."""
        llm_result = {"text": ""}

        with pytest.raises(ValueError, match="Текст задачи не может быть пустым"):
            _build_full_commit(llm_result, "Valya", "Sasha", "Daniil", "theirs")


class TestFallbackCommit:
    """Тесты fallback коммита."""

    @patch("app.core.commit_normalize.build_title")
    @patch("app.core.commit_normalize.build_key")
    @patch("app.core.tags.tag_text")
    def test_create_fallback_commit(self, mock_tag_text, mock_build_key, mock_build_title):
        """Тест создания fallback коммита."""
        mock_build_title.return_value = "Fallback Title"
        mock_build_key.return_value = "fallback_key"
        mock_tag_text.return_value = ["Topic/Fallback"]

        result = _create_fallback_commit("сделать что-то", "Valya")

        assert result["text"] == "сделать что-то"
        assert result["direction"] == "mine"
        assert result["assignees"] == ["Valya"]
        assert result["from_person"] == ["Valya"]
        assert result["confidence"] == 0.3
        assert result["flags"] == ["direct", "llm", "fallback"]


class TestLLMIntegration:
    """Интеграционные тесты LLM парсинга."""

    @patch("app.core.llm_commit_parse._call_llm_parse")
    @patch("app.core.commit_normalize.build_title")
    @patch("app.core.commit_normalize.build_key")
    @patch("app.core.tags.tag_text")
    def test_parse_commit_text_success(
        self, mock_tag_text, mock_build_key, mock_build_title, mock_llm
    ):
        """Тест успешного парсинга коммита."""
        # Настраиваем моки
        mock_llm.return_value = {
            "text": "подготовить презентацию",
            "assignee": "Sasha",
            "from_person": None,
            "due": "2025-10-05",
            "confidence": 0.9,
        }
        mock_build_title.return_value = "Test Title"
        mock_build_key.return_value = "test_key"
        mock_tag_text.return_value = ["Topic/Presentation"]

        result = parse_commit_text("Саша подготовит презентацию к 5 октября", "Valya")

        assert result["text"] == "подготовить презентацию"
        assert result["assignees"] == ["Sasha"]
        assert result["from_person"] == ["Valya"]  # Fallback
        assert result["direction"] == "theirs"
        assert result["due_iso"] == "2025-10-05"
        assert result["confidence"] == 0.9

    @patch("app.core.llm_commit_parse._call_llm_parse")
    @patch("app.core.llm_commit_parse._create_fallback_commit")
    def test_parse_commit_text_llm_error(self, mock_fallback, mock_llm):
        """Тест fallback при ошибке LLM."""
        # LLM возвращает ошибку
        mock_llm.side_effect = RuntimeError("LLM API error")
        mock_fallback.return_value = {"text": "fallback", "confidence": 0.3}

        result = parse_commit_text("сделать что-то", "Valya")

        # Должен вызваться fallback
        mock_fallback.assert_called_once_with("сделать что-то", "Valya")
        assert result["text"] == "fallback"

    def test_parse_commit_text_empty_input(self):
        """Тест ошибки при пустом вводе."""
        with pytest.raises(ValueError, match="Текст коммита не может быть пустым"):
            parse_commit_text("", "Valya")

        with pytest.raises(ValueError, match="Текст коммита не может быть пустым"):
            parse_commit_text("   ", "Valya")


class TestEdgeCases:
    """Тесты граничных случаев."""

    def test_role_fallbacks_with_empty_strings(self):
        """Тест fallback с пустыми строками."""
        llm_result = {"assignee": "", "from_person": ""}
        assignee, from_person, direction = _apply_role_fallbacks(llm_result, "Valya")

        assert assignee == "Valya"  # Пустая строка → fallback
        assert from_person == "Valya"
        assert direction == "mine"

    @patch("app.core.commit_normalize.build_title")
    @patch("app.core.commit_normalize.build_key")
    @patch("app.core.tags.tag_text")
    def test_build_commit_with_none_values(self, mock_tag_text, mock_build_key, mock_build_title):
        """Тест построения коммита с None значениями."""
        mock_build_title.return_value = "Title"
        mock_build_key.return_value = "key"
        mock_tag_text.return_value = []

        llm_result = {"text": "задача", "due": None, "confidence": None}

        result = _build_full_commit(llm_result, "Valya", "", "", "mine")

        assert result["assignees"] == []  # Пустой исполнитель
        assert result["from_person"] == []  # Пустой заказчик
        assert result["due_iso"] is None
        assert result["confidence"] == 0.7  # Default


class TestPromptLoading:
    """Тесты загрузки промпта."""

    def test_prompt_file_exists(self):
        """Тест что файл промпта существует."""
        prompt_path = Path("prompts/commits/llm_parse_ru.md")
        assert prompt_path.exists(), f"Промпт не найден: {prompt_path}"

        content = prompt_path.read_text(encoding="utf-8")
        assert len(content) > 100, "Промпт слишком короткий"
        assert "text" in content, "Промпт должен содержать описание поля 'text'"
        assert "assignee" in content, "Промпт должен содержать описание поля 'assignee'"
        assert "from_person" in content, "Промпт должен содержать описание поля 'from_person'"
