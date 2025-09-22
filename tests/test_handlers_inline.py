"""Тесты для inline кнопок Review Queue."""

from unittest.mock import AsyncMock, patch

import pytest
from aiogram.types import CallbackQuery, Message

from app.bot.handlers_inline import (
    build_main_menu_kb,
    build_review_item_kb,
    cb_main_new_file,
    cb_main_review,
    cb_review_assign,
    cb_review_confirm,
    cb_review_confirm_all,
    cb_review_delete,
    cb_review_flip,
)


class TestInlineButtons:
    """Тесты для inline кнопок."""

    def test_build_main_menu_kb(self):
        """Тест создания клавиатуры главного меню."""
        kb = build_main_menu_kb()

        assert kb.inline_keyboard is not None
        assert len(kb.inline_keyboard) == 1  # Одна строка кнопок
        assert len(kb.inline_keyboard[0]) == 2  # Две кнопки в строке

        # Проверяем текст и callback_data кнопок
        buttons = kb.inline_keyboard[0]
        assert buttons[0].text == "📄 Новый файл"
        assert buttons[0].callback_data == "main_new_file"
        assert buttons[1].text == "🔍 Review"
        assert buttons[1].callback_data == "main_review"

    def test_build_review_item_kb(self):
        """Тест создания клавиатуры для элемента Review."""
        short_id = "abc123"
        kb = build_review_item_kb(short_id)

        assert kb.inline_keyboard is not None
        assert len(kb.inline_keyboard) == 2  # Две строки кнопок
        assert len(kb.inline_keyboard[0]) == 2  # Две кнопки в первой строке
        assert len(kb.inline_keyboard[1]) == 2  # Две кнопки во второй строке

        # Проверяем callback_data
        buttons_row1 = kb.inline_keyboard[0]
        buttons_row2 = kb.inline_keyboard[1]

        assert buttons_row1[0].callback_data == f"review_confirm:{short_id}"
        assert buttons_row1[1].callback_data == f"review_flip:{short_id}"
        assert buttons_row2[0].callback_data == f"review_delete:{short_id}"
        assert buttons_row2[1].callback_data == f"review_assign:{short_id}"


class TestMainMenuCallbacks:
    """Тесты для callback'ов главного меню."""

    @pytest.fixture
    def mock_callback(self):
        """Создает mock объект CallbackQuery."""
        callback = AsyncMock(spec=CallbackQuery)
        callback.answer = AsyncMock()
        callback.message = AsyncMock(spec=Message)
        callback.message.answer = AsyncMock()
        return callback

    @pytest.mark.asyncio
    async def test_cb_main_new_file(self, mock_callback):
        """Тест кнопки 'Обработать новый файл'."""
        await cb_main_new_file(mock_callback)

        mock_callback.answer.assert_called_once()
        mock_callback.message.answer.assert_called_once()

        # Проверяем что сообщение содержит информацию о форматах
        call_args = mock_callback.message.answer.call_args[0][0]
        assert "Поддерживаемые форматы:" in call_args
        assert ".txt" in call_args
        assert ".pdf" in call_args
        assert ".docx" in call_args
        assert ".vtt" in call_args
        # Убеждаемся что НЕ упоминаем неподдерживаемые форматы
        assert ".mp3" not in call_args
        assert ".mp4" not in call_args

    @patch("app.bot.handlers_inline.list_open_reviews")
    @pytest.mark.asyncio
    async def test_cb_main_review_success(self, mock_list_pending, mock_callback):
        """Тест кнопки 'Review Commits' с элементами."""
        mock_list_pending.return_value = [
            {
                "short_id": "abc123",
                "text": "Test commit",
                "direction": "mine",
                "assignees": ["John"],
                "due_iso": "2025-01-15",
                "confidence": 0.75,
            }
        ]

        await cb_main_review(mock_callback)

        mock_callback.answer.assert_called_once()
        assert mock_callback.message.answer.call_count == 2  # Заголовок + элемент

    @patch("app.bot.handlers_inline.list_open_reviews")
    @pytest.mark.asyncio
    async def test_cb_main_review_empty(self, mock_list_pending, mock_callback):
        """Тест кнопки 'Review Commits' без элементов."""
        mock_list_pending.return_value = []

        await cb_main_review(mock_callback)

        mock_callback.answer.assert_called_once()
        # Проверяем, что вызывается новая функция с улучшенным сообщением и кнопкой
        mock_callback.message.answer.assert_called_once()
        call_args = mock_callback.message.answer.call_args
        assert "📋 Review queue пуста." in call_args[0][0]
        assert "💡" in call_args[0][0]  # Проверяем наличие улучшенного текста
        assert call_args[1]["reply_markup"] is not None  # Проверяем наличие клавиатуры


class TestReviewItemCallbacks:
    """Тесты для callback'ов элементов Review."""

    @pytest.fixture
    def mock_callback(self):
        """Создает mock объект CallbackQuery."""
        callback = AsyncMock(spec=CallbackQuery)
        callback.answer = AsyncMock()
        callback.message = AsyncMock(spec=Message)
        callback.message.answer = AsyncMock()
        callback.message.edit_text = AsyncMock()
        callback.data = "review_action:abc123"
        return callback

    @pytest.fixture
    def sample_review_item(self):
        """Создает пример элемента Review."""
        return {
            "page_id": "test-page-id-123",
            "short_id": "abc123",
            "text": "Test commit text",
            "direction": "theirs",
            "assignees": ["John Doe"],
            "due_iso": "2025-01-15",
            "confidence": 0.75,
            "meeting_page_id": "meeting-123",
        }

    @patch("app.bot.handlers_inline.get_by_short_id")
    @patch("app.bot.handlers_inline.set_status")
    @pytest.mark.asyncio
    async def test_cb_review_delete_success(
        self, mock_set_status, mock_get_by_short_id, mock_callback, sample_review_item
    ):
        """Тест успешного удаления элемента Review."""
        mock_get_by_short_id.return_value = sample_review_item
        mock_set_status.return_value = True

        await cb_review_delete(mock_callback)

        mock_get_by_short_id.assert_called_once_with("abc123")
        mock_set_status.assert_called_once_with("test-page-id-123", "dropped")
        mock_callback.answer.assert_called_once_with("🗑 Удалено")
        mock_callback.message.edit_text.assert_called_once()

    @patch("app.bot.handlers_inline.get_by_short_id")
    @patch("app.bot.handlers_inline.update_fields")
    @pytest.mark.asyncio
    async def test_cb_review_flip_success(
        self, mock_update_fields, mock_get_by_short_id, mock_callback, sample_review_item
    ):
        """Тест успешного переключения direction."""
        mock_get_by_short_id.return_value = sample_review_item
        mock_update_fields.return_value = True

        await cb_review_flip(mock_callback)

        mock_get_by_short_id.assert_called_once_with("abc123")
        mock_update_fields.assert_called_once_with("test-page-id-123", direction="mine")
        mock_callback.answer.assert_called_once_with("🔄 Direction → mine")
        mock_callback.message.edit_text.assert_called_once()

    @patch("app.bot.handlers_inline.get_by_short_id")
    @pytest.mark.asyncio
    async def test_cb_review_assign_success(
        self, mock_get_by_short_id, mock_callback, sample_review_item
    ):
        """Тест кнопки Assign - показывает инструкции."""
        mock_get_by_short_id.return_value = sample_review_item

        await cb_review_assign(mock_callback)

        mock_get_by_short_id.assert_called_once_with("abc123")
        mock_callback.answer.assert_called_once()
        mock_callback.message.answer.assert_called_once()

        # Проверяем что сообщение содержит инструкции
        call_args = mock_callback.message.answer.call_args[0][0]
        assert "/assign abc123" in call_args

    @patch("app.bot.handlers_inline.get_by_short_id")
    @patch("app.bot.handlers_inline.upsert_commits")
    @patch("app.bot.handlers_inline.set_status")
    @patch("app.bot.handlers_inline.build_title")
    @patch("app.bot.handlers_inline.build_key")
    @pytest.mark.asyncio
    async def test_cb_review_confirm_success(
        self,
        mock_build_key,
        mock_build_title,
        mock_set_status,
        mock_upsert_commits,
        mock_get_by_short_id,
        mock_callback,
        sample_review_item,
    ):
        """Тест успешного подтверждения элемента Review."""
        mock_get_by_short_id.return_value = sample_review_item
        mock_build_title.return_value = "John Doe: Test commit text [due 2025-01-15]"
        mock_build_key.return_value = "test_key_hash"
        mock_upsert_commits.return_value = {"created": ["new_commit_id"], "updated": []}
        mock_set_status.return_value = True

        await cb_review_confirm(mock_callback)

        mock_get_by_short_id.assert_called_once_with("abc123")
        mock_upsert_commits.assert_called_once()
        mock_set_status.assert_called_once_with("test-page-id-123", "resolved", linked_commit_id="new_commit_id")
        mock_callback.answer.assert_called_once_with("✅ Confirmed!")
        mock_callback.message.edit_text.assert_called_once()

    @patch("app.bot.handlers_inline.get_by_short_id")
    @pytest.mark.asyncio
    async def test_cb_review_item_not_found(self, mock_get_by_short_id, mock_callback):
        """Тест обработки несуществующего элемента."""
        mock_get_by_short_id.return_value = None

        await cb_review_confirm(mock_callback)

        mock_callback.answer.assert_called_once_with("❌ Элемент не найден", show_alert=True)

    @patch("app.bot.handlers_inline.list_open_reviews")
    @patch("app.bot.handlers_inline.upsert_commits")
    @patch("app.bot.handlers_inline.set_status")
    @patch("app.bot.handlers_inline.build_title")
    @patch("app.bot.handlers_inline.build_key")
    @pytest.mark.asyncio
    async def test_cb_review_confirm_all_success(
        self,
        mock_build_key,
        mock_build_title,
        mock_set_status,
        mock_upsert_commits,
        mock_list_pending,
        mock_callback,
    ):
        """Тест массового подтверждения всех элементов Review."""
        # Настраиваем моки
        items = [
            {
                "page_id": "page-1",
                "short_id": "abc123",
                "text": "Task 1",
                "direction": "mine",
                "assignees": ["John"],
                "due_iso": None,
                "confidence": 0.7,
                "meeting_page_id": "meeting-1",
            },
            {
                "page_id": "page-2",
                "short_id": "def456",
                "text": "Task 2",
                "direction": "theirs",
                "assignees": [],
                "due_iso": "2025-01-15",
                "confidence": 0.6,
                "meeting_page_id": "meeting-1",
            },
        ]
        # Первый вызов возвращает элементы, второй - пустой список (очередь пуста после обработки)
        mock_list_pending.side_effect = [items, []]

        mock_build_title.side_effect = ["Title 1", "Title 2"]
        mock_build_key.side_effect = ["key1", "key2"]
        mock_upsert_commits.return_value = {"created": ["commit-1"], "updated": []}
        mock_set_status.return_value = True

        await cb_review_confirm_all(mock_callback)

        # Проверяем вызовы
        # Теперь list_pending вызывается дважды: сначала для получения элементов, потом для проверки пустой очереди
        assert mock_list_pending.call_count == 2
        mock_list_pending.assert_any_call(limit=50)
        mock_list_pending.assert_any_call(limit=1)  # Проверка оставшихся элементов
        assert mock_upsert_commits.call_count == 2  # По одному для каждого элемента
        assert mock_set_status.call_count == 2  # Помечаем оба как resolved
        mock_callback.answer.assert_called_once()
        # Теперь должно быть 2 сообщения: результат + сообщение о пустой очереди
        assert mock_callback.message.answer.call_count == 2

        # Проверяем сообщение о результате
        first_call_args = mock_callback.message.answer.call_args_list[0][0][0]
        assert "Подтверждено: 2 элементов" in first_call_args

        # Проверяем сообщение о пустой очереди
        second_call_args = mock_callback.message.answer.call_args_list[1]
        assert "📋 Review queue пуста." in second_call_args[0][0]
        assert "💡" in second_call_args[0][0]  # Проверяем наличие улучшенного текста
        assert second_call_args[1]["reply_markup"] is not None  # Проверяем наличие клавиатуры

    @patch("app.bot.handlers_inline.list_open_reviews")
    @pytest.mark.asyncio
    async def test_cb_review_confirm_all_empty(self, mock_list_pending, mock_callback):
        """Тест массового подтверждения при пустой очереди."""
        mock_list_pending.return_value = []

        await cb_review_confirm_all(mock_callback)

        mock_callback.answer.assert_called_once()
        # Проверяем, что вызывается новая функция с улучшенным сообщением и кнопкой
        mock_callback.message.answer.assert_called_once()
        call_args = mock_callback.message.answer.call_args
        assert "📋 Review queue пуста." in call_args[0][0]
        assert "💡" in call_args[0][0]  # Проверяем наличие улучшенного текста
        assert call_args[1]["reply_markup"] is not None  # Проверяем наличие клавиатуры
