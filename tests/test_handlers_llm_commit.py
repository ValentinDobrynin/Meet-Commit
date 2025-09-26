"""
Тесты для LLM commit handler.
"""

from unittest.mock import AsyncMock, Mock, patch

import pytest
from aiogram.types import Message, User

from app.bot.handlers_llm_commit import _get_user_name, llm_commit_handler


class TestGetUserName:
    """Тесты получения имени пользователя."""

    def test_get_user_name_full_name(self):
        """Тест получения полного имени."""
        user = User(id=123, is_bot=False, first_name="Valya", last_name="Dobrynin")
        message = Mock(spec=Message)
        message.from_user = user

        result = _get_user_name(message)
        assert result == "Valya Dobrynin"

    def test_get_user_name_username(self):
        """Тест получения username."""
        user = User(id=123, is_bot=False, first_name="Valya", username="valya_d")
        message = Mock(spec=Message)
        message.from_user = user

        result = _get_user_name(message)
        assert result == "Valya"  # first_name приоритетнее username

    def test_get_user_name_id_fallback(self):
        """Тест fallback к ID."""
        user = User(id=123, is_bot=False, first_name="")
        message = Mock(spec=Message)
        message.from_user = user

        result = _get_user_name(message)
        assert result == "User_123"

    def test_get_user_name_no_user(self):
        """Тест без пользователя."""
        message = Mock(spec=Message)
        message.from_user = None

        result = _get_user_name(message)
        assert result == "Unknown User"


class TestLLMCommitHandler:
    """Тесты LLM commit handler."""

    @pytest.fixture
    def mock_message(self):
        """Создает мок сообщения."""
        user = User(id=123, is_bot=False, first_name="Valya", last_name="Dobrynin")
        message = Mock(spec=Message)
        message.from_user = user
        message.answer = AsyncMock()
        return message

    @pytest.mark.asyncio
    async def test_llm_commit_no_text(self, mock_message):
        """Тест команды без текста."""
        mock_message.text = "/llm"

        await llm_commit_handler(mock_message)

        mock_message.answer.assert_called_once()
        args = mock_message.answer.call_args[0]
        assert "Укажите текст коммита" in args[0]

    @pytest.mark.asyncio
    async def test_llm_commit_empty_text(self, mock_message):
        """Тест команды с пустым текстом."""
        mock_message.text = "/llm   "

        await llm_commit_handler(mock_message)

        mock_message.answer.assert_called_once()
        args = mock_message.answer.call_args[0]
        assert "Укажите текст коммита" in args[0]

    @pytest.mark.asyncio
    async def test_llm_commit_no_message_text(self, mock_message):
        """Тест когда message.text is None."""
        mock_message.text = None

        await llm_commit_handler(mock_message)

        mock_message.answer.assert_called_once()
        args = mock_message.answer.call_args[0]
        assert "Ошибка: отсутствует текст команды" in args[0]

    @pytest.mark.asyncio
    @patch("app.bot.handlers_llm_commit.parse_commit_text")
    @patch("app.bot.handlers_llm_commit._save_commit_to_notion")
    @patch("app.bot.handlers_llm_commit.format_commit_card")
    async def test_llm_commit_success(self, mock_format, mock_save, mock_parse, mock_message):
        """Тест успешного создания LLM коммита."""
        mock_message.text = "/llm Саша сделает отчет"

        # Настраиваем моки
        mock_parse.return_value = {
            "text": "сделать отчет",
            "assignees": ["Sasha"],
            "from_person": ["Valya"],
            "due_iso": "2025-10-05",
        }

        mock_save.return_value = {"id": "test-id", "short_id": "12345678", "title": "Test Title"}

        mock_format.return_value = "📋 Test Card"

        # Мокаем processing message
        processing_msg = Mock()
        processing_msg.edit_text = AsyncMock()
        mock_message.answer.return_value = processing_msg

        await llm_commit_handler(mock_message)

        # Проверяем вызовы
        mock_parse.assert_called_once_with("Саша сделает отчет", "Valya Dobrynin")
        mock_save.assert_called_once()
        mock_format.assert_called_once()

        # Проверяем финальное сообщение
        processing_msg.edit_text.assert_called()
        final_call = processing_msg.edit_text.call_args_list[-1]
        assert "LLM коммит создан" in final_call[0][0]

    @pytest.mark.asyncio
    @patch("app.bot.handlers_llm_commit.parse_commit_text")
    async def test_llm_commit_validation_error(self, mock_parse, mock_message):
        """Тест ошибки валидации."""
        mock_message.text = "/llm пустой текст"
        mock_parse.side_effect = ValueError("Текст слишком короткий")

        processing_msg = Mock()
        processing_msg.edit_text = AsyncMock()
        mock_message.answer.return_value = processing_msg

        await llm_commit_handler(mock_message)

        # Проверяем что показана ошибка валидации
        processing_msg.edit_text.assert_called()
        error_call = processing_msg.edit_text.call_args_list[-1]
        assert "Ошибка валидации" in error_call[0][0]
        assert "Текст слишком короткий" in error_call[0][0]

    @pytest.mark.asyncio
    @patch("app.bot.handlers_llm_commit.parse_commit_text")
    async def test_llm_commit_runtime_error(self, mock_parse, mock_message):
        """Тест ошибки LLM или Notion."""
        mock_message.text = "/llm тестовый текст"
        mock_parse.side_effect = RuntimeError("LLM API недоступен")

        processing_msg = Mock()
        processing_msg.edit_text = AsyncMock()
        mock_message.answer.return_value = processing_msg

        await llm_commit_handler(mock_message)

        # Проверяем что показана ошибка обработки
        processing_msg.edit_text.assert_called()
        error_call = processing_msg.edit_text.call_args_list[-1]
        assert "Ошибка обработки" in error_call[0][0]
        assert "LLM API недоступен" in error_call[0][0]

    @pytest.mark.asyncio
    @patch("app.bot.handlers_llm_commit.parse_commit_text")
    async def test_llm_commit_handler_exception(self, mock_parse, mock_message):
        """Тест критической ошибки в handler."""
        mock_message.text = "/llm тест"
        # Имитируем неожиданную ошибку
        mock_parse.side_effect = Exception("Unexpected error")

        processing_msg = Mock()
        processing_msg.edit_text = AsyncMock()
        mock_message.answer.return_value = processing_msg

        await llm_commit_handler(mock_message)

        # Проверяем что показана неожиданная ошибка
        processing_msg.edit_text.assert_called()
        error_call = processing_msg.edit_text.call_args_list[-1]
        assert "Неожиданная ошибка" in error_call[0][0]


class TestIntegration:
    """Интеграционные тесты."""

    def test_all_functions_importable(self):
        """Тест что все функции можно импортировать."""
        from app.bot.handlers_llm_commit import (
            _create_direct_meeting,
            _get_user_name,
            _save_commit_to_notion,
            llm_commit_handler,
        )

        # Проверяем что функции существуют
        assert callable(_get_user_name)
        assert callable(_create_direct_meeting)
        assert callable(_save_commit_to_notion)
        assert callable(llm_commit_handler)
