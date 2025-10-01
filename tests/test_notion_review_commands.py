"""Тесты для команд Review queue в Telegram боте."""

from unittest.mock import AsyncMock, patch

import pytest
from aiogram.types import Message

from app.bot.handlers import (
    cmd_assign_manual,
    cmd_confirm,
    cmd_delete,
    cmd_flip,
    cmd_review,
    cmd_review_fallback,
)


class TestReviewCommands:
    """Тесты для команд управления Review queue."""

    @pytest.fixture
    def mock_message(self):
        """Создает mock объект Message."""
        msg = AsyncMock(spec=Message)
        msg.answer = AsyncMock()
        return msg

    @pytest.fixture
    def sample_review_item(self):
        """Образец элемента Review queue."""
        return {
            "page_id": "12345678-1234-1234-1234-123456789012",
            "short_id": "789012",
            "text": "Подготовить отчет по продажам",
            "direction": "theirs",
            "assignees": ["Daniil"],
            "due_iso": "2025-10-15",
            "confidence": 0.8,
            "reasons": ["unclear_assignee"],
            "context": "Обсуждение на встрече",
            "meeting_page_id": "87654321-4321-4321-4321-210987654321",
        }

    @patch("app.bot.handlers.list_open_reviews")  # Правильный путь для новой логики
    @pytest.mark.asyncio
    async def test_cmd_review_success(self, mock_list_pending, mock_message, sample_review_item):
        """Тест успешного выполнения команды /review."""
        mock_message.text = "/review"
        mock_list_pending.return_value = [sample_review_item]

        await cmd_review(mock_message)

        mock_list_pending.assert_called_once_with(limit=5)
        # Теперь отправляется 2 сообщения: заголовок + элемент
        assert mock_message.answer.call_count == 2

        # Проверяем содержимое первого сообщения (заголовок)
        first_call_args = mock_message.answer.call_args_list[0][0][0]
        assert "📋 <b>Review Queue" in first_call_args

    @patch("app.bot.handlers.list_open_reviews")
    @pytest.mark.asyncio
    async def test_cmd_review_empty(self, mock_list_pending, mock_message):
        """Тест команды /review с пустой очередью."""
        mock_message.text = "/review"
        mock_list_pending.return_value = []

        await cmd_review(mock_message)

        # Проверяем, что вызывается новая функция с улучшенным сообщением и кнопками
        mock_message.answer.assert_called_once()
        call_args = mock_message.answer.call_args
        assert "📋 Review queue пуста." in call_args[0][0]
        assert "💡" in call_args[0][0]  # Проверяем наличие улучшенного текста
        assert call_args[1]["reply_markup"] is not None  # Проверяем наличие клавиатуры

    @patch("app.bot.handlers.list_open_reviews")  # Правильный путь
    @pytest.mark.asyncio
    async def test_cmd_review_with_limit(self, mock_list_pending, mock_message, sample_review_item):
        """Тест команды /review с указанием лимита."""
        mock_message.text = "/review 10"
        mock_list_pending.return_value = [sample_review_item]

        await cmd_review(mock_message)

        mock_list_pending.assert_called_once_with(limit=10)

    @patch("app.bot.handlers.get_by_short_id")
    @patch("app.bot.handlers.update_fields")
    @pytest.mark.asyncio
    async def test_cmd_flip_success(
        self, mock_update_fields, mock_get_by_short_id, mock_message, sample_review_item
    ):
        """Тест успешного выполнения команды /flip."""
        mock_message.text = "/flip 789012"
        mock_get_by_short_id.return_value = sample_review_item
        mock_update_fields.return_value = True

        await cmd_flip(mock_message)

        mock_get_by_short_id.assert_called_once_with("789012")
        mock_update_fields.assert_called_once_with(sample_review_item["page_id"], direction="mine")
        mock_message.answer.assert_called_once_with("✅ [789012] Direction → mine")

    @patch("app.bot.handlers.get_by_short_id")
    @pytest.mark.asyncio
    async def test_cmd_flip_not_found(self, mock_get_by_short_id, mock_message):
        """Тест команды /flip с несуществующим ID."""
        mock_message.text = "/flip abc123"
        mock_get_by_short_id.return_value = None

        await cmd_flip(mock_message)

        mock_message.answer.assert_called_once_with(
            "❌ Карточка [abc123] не найдена. Проверьте /review."
        )

    @pytest.mark.asyncio
    async def test_cmd_confirm_wrong_syntax_too_many_args(self, mock_message):
        """Тест команды /confirm с лишними аргументами."""
        mock_message.text = "/confirm 123456 Daniil"

        await cmd_confirm(mock_message)

        expected_msg = (
            "❌ Команда /confirm принимает только ID карточки.\n"
            "Синтаксис: /confirm <short_id>\n"
            "Возможно, вы хотели: /assign 123456 Daniil"
        )
        mock_message.answer.assert_called_once_with(expected_msg)

    @pytest.mark.asyncio
    async def test_cmd_confirm_wrong_syntax_no_args(self, mock_message):
        """Тест команды /confirm без аргументов."""
        mock_message.text = "/confirm"

        await cmd_confirm(mock_message)

        mock_message.answer.assert_called_once_with("❌ Синтаксис: /confirm <short_id>")

    @pytest.mark.asyncio
    async def test_cmd_review_fallback_review(self, mock_message):
        """Тест fallback для неправильной команды /review."""
        mock_message.text = "/review abc def"

        await cmd_review_fallback(mock_message)

        mock_message.answer.assert_called_once_with(
            "❌ Неправильный синтаксис.\nИспользуйте: /review [количество]"
        )

    @pytest.mark.asyncio
    async def test_cmd_review_fallback_confirm(self, mock_message):
        """Тест fallback для неправильной команды /confirm."""
        mock_message.text = "/confirm"

        await cmd_review_fallback(mock_message)

        mock_message.answer.assert_called_once_with(
            "❌ Неправильный синтаксис.\nИспользуйте: /confirm <short_id>"
        )

    @patch("app.bot.handlers.get_by_short_id")
    @patch("app.bot.handlers.normalize_assignees")
    @patch("app.bot.handlers.update_fields")
    @pytest.mark.asyncio
    async def test_cmd_assign_success(
        self,
        mock_update_fields,
        mock_normalize_assignees,
        mock_get_by_short_id,
        mock_message,
        sample_review_item,
    ):
        """Тест успешного выполнения команды /assign."""
        mock_message.text = "/assign 789012 Valentin"
        mock_get_by_short_id.return_value = sample_review_item
        mock_normalize_assignees.return_value = ["Valentin"]
        mock_update_fields.return_value = True

        await cmd_assign_manual(mock_message)

        mock_get_by_short_id.assert_called_once_with("789012")
        mock_normalize_assignees.assert_called_once_with(["Valentin"], attendees_en=[])
        mock_update_fields.assert_called_once_with(
            sample_review_item["page_id"], assignees=["Valentin"]
        )
        mock_message.answer.assert_called_once_with("✅ [789012] Assignee → Valentin")

    @patch("app.bot.handlers.get_by_short_id")
    @patch("app.bot.handlers.normalize_assignees")
    @pytest.mark.asyncio
    async def test_cmd_assign_unknown_person(
        self, mock_normalize_assignees, mock_get_by_short_id, mock_message, sample_review_item
    ):
        """Тест команды /assign с неизвестным человеком."""
        mock_message.text = "/assign 789012 UnknownPerson"
        mock_get_by_short_id.return_value = sample_review_item
        mock_normalize_assignees.return_value = []

        await cmd_assign_manual(mock_message)

        mock_message.answer.assert_called_once_with(
            "❌ Не удалось распознать исполнителя(ей): UnknownPerson"
        )

    @patch("app.bot.handlers.get_by_short_id")
    @patch("app.bot.handlers.set_status")
    @pytest.mark.asyncio
    async def test_cmd_delete_success(
        self, mock_set_status, mock_get_by_short_id, mock_message, sample_review_item
    ):
        """Тест успешного выполнения команды /delete."""
        mock_message.text = "/delete 789012"
        mock_get_by_short_id.return_value = sample_review_item

        await cmd_delete(mock_message)

        mock_get_by_short_id.assert_called_once_with("789012")
        mock_set_status.assert_called_once_with(sample_review_item["page_id"], "dropped")
        mock_message.answer.assert_called_once_with("✅ [789012] Удалено (dropped).")

    @patch("app.bot.handlers.get_by_short_id")
    @patch("app.bot.handlers.build_title")
    @patch("app.bot.handlers.build_key")
    @patch("app.bot.handlers.upsert_commits")
    @patch("app.bot.handlers.set_status")
    @pytest.mark.asyncio
    async def test_cmd_confirm_success(
        self,
        mock_set_status,
        mock_upsert_commits,
        mock_build_key,
        mock_build_title,
        mock_get_by_short_id,
        mock_message,
        sample_review_item,
    ):
        """Тест успешного выполнения команды /confirm."""
        mock_message.text = "/confirm 789012"
        mock_get_by_short_id.return_value = sample_review_item
        mock_build_title.return_value = "Daniil: Подготовить отчет по продажам [due 2025-10-15]"
        mock_build_key.return_value = "test_key_hash"
        mock_upsert_commits.return_value = {"created": ["new_commit_id"], "updated": []}

        await cmd_confirm(mock_message)

        mock_get_by_short_id.assert_called_once_with("789012")
        mock_build_title.assert_called_once_with(
            "theirs", "Подготовить отчет по продажам", ["Daniil"], "2025-10-15"
        )
        mock_build_key.assert_called_once_with(
            "Подготовить отчет по продажам", ["Daniil"], "2025-10-15"
        )

        # Проверяем вызов upsert_commits
        mock_upsert_commits.assert_called_once()
        commit_call_args = mock_upsert_commits.call_args
        assert commit_call_args[0][0] == sample_review_item["meeting_page_id"]
        commit_item = commit_call_args[0][1][0]
        assert commit_item["text"] == "Подготовить отчет по продажам"
        assert commit_item["direction"] == "theirs"
        assert commit_item["assignees"] == ["Daniil"]

        mock_set_status.assert_called_once_with(
            sample_review_item["page_id"], "resolved", linked_commit_id="new_commit_id"
        )
        # Проверяем, что ответ содержит основную информацию
        mock_message.answer.assert_called_once()
        call_args = mock_message.answer.call_args[0][0]
        assert "✅ <b>[789012] Коммит подтвержден</b>" in call_args  # Новый формат подтверждения
        assert "ℹ️ <b>Review Status:</b> resolved" in call_args  # Новый формат статуса

    @patch("app.bot.handlers.get_by_short_id")
    @pytest.mark.asyncio
    async def test_cmd_confirm_no_meeting_id(
        self, mock_get_by_short_id, mock_message, sample_review_item
    ):
        """Тест команды /confirm без meeting_page_id."""
        mock_message.text = "/confirm 789012"
        sample_review_item["meeting_page_id"] = None
        mock_get_by_short_id.return_value = sample_review_item

        await cmd_confirm(mock_message)

        mock_message.answer.assert_called_once_with("❌ [789012] Не найден meeting_page_id.")


class TestReviewCommandsErrorHandling:
    """Тесты обработки ошибок в командах Review queue."""

    @pytest.fixture
    def mock_message(self):
        """Создает mock объект Message."""
        msg = AsyncMock(spec=Message)
        msg.answer = AsyncMock()
        return msg

    @patch("app.bot.handlers.list_open_reviews")  # Правильный путь
    @pytest.mark.asyncio
    async def test_cmd_review_exception(self, mock_list_pending, mock_message):
        """Тест обработки исключения в команде /review."""
        mock_message.text = "/review"
        mock_list_pending.side_effect = Exception("Database error")

        await cmd_review(mock_message)

        mock_message.answer.assert_called_once_with("❌ Ошибка при получении списка review.")

    @patch("app.bot.handlers.get_by_short_id")
    @pytest.mark.asyncio
    async def test_cmd_flip_exception(self, mock_get_by_short_id, mock_message):
        """Тест обработки исключения в команде /flip."""
        mock_message.text = "/flip 789012"
        mock_get_by_short_id.side_effect = Exception("API error")

        await cmd_flip(mock_message)

        mock_message.answer.assert_called_once_with("❌ Ошибка при выполнении flip.")
