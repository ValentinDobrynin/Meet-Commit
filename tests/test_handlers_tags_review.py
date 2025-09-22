"""Тесты для интерактивного ревью тегов."""

from __future__ import annotations

import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, User

from app.bot.handlers_tags_review import (
    TagReviewSession,
    _build_tags_keyboard,
    _format_tags_message,
    _validate_tag_format,
    cancel_handler,
    custom_tag_handler,
    drop_tag_handler,
    save_handler,
    start_tags_review,
    undo_handler,
)
from app.bot.states.tags_review_states import TagsReviewStates


@pytest.fixture
def mock_message():
    """Создает мок сообщения."""
    message = AsyncMock(spec=Message)
    message.from_user = MagicMock(spec=User)
    message.from_user.id = 50929545
    message.answer = AsyncMock()
    message.edit_text = AsyncMock()
    return message


@pytest.fixture
def mock_callback():
    """Создает мок callback query."""
    callback = AsyncMock(spec=CallbackQuery)
    callback.from_user = MagicMock(spec=User)
    callback.from_user.id = 50929545
    callback.message = AsyncMock()
    callback.message.edit_text = AsyncMock()
    callback.answer = AsyncMock()
    return callback


@pytest.fixture
def mock_fsm_context():
    """Создает мок FSM контекста."""
    context = AsyncMock(spec=FSMContext)
    context.get_data = AsyncMock(return_value={})
    context.update_data = AsyncMock()
    context.set_state = AsyncMock()
    context.clear = AsyncMock()
    return context


@pytest.fixture
def sample_session():
    """Создает образец сессии для тестов."""
    return TagReviewSession(
        meeting_id="deadbeef12345678",
        owner_user_id=50929545,
        started_at=time.time(),
        original_tags=["Finance/IFRS", "Business/Lavka"],
        working_tags=["Finance/IFRS", "Business/Lavka"],
    )


class TestTagReviewSession:
    """Тесты для класса TagReviewSession."""

    def test_session_creation(self):
        """Тест создания сессии."""
        session = TagReviewSession(
            meeting_id="test123",
            owner_user_id=12345,
            started_at=time.time(),
            original_tags=["Finance/IFRS"],
            working_tags=["Finance/IFRS"],
        )

        assert session.meeting_id == "test123"
        assert session.owner_user_id == 12345
        assert not session.is_expired
        assert session.can_edit(12345)
        assert not session.can_edit(99999)

    def test_session_expiration(self):
        """Тест истечения сессии."""
        session = TagReviewSession(
            meeting_id="test123",
            owner_user_id=12345,
            started_at=time.time() - 1000,  # 1000 секунд назад
            original_tags=[],
            working_tags=[],
        )

        assert session.is_expired

    def test_admin_can_edit(self):
        """Тест что админ может редактировать любую сессию."""
        session = TagReviewSession(
            meeting_id="test123",
            owner_user_id=12345,
            started_at=time.time(),
            original_tags=[],
            working_tags=[],
        )

        # Мокаем _admin_ids_set
        with patch("app.bot.handlers_tags_review._admin_ids_set", {50929545}):
            assert session.can_edit(50929545)  # админ
            assert session.can_edit(12345)  # владелец
            assert not session.can_edit(99999)  # чужой

    def test_changes_summary(self):
        """Тест подсчета изменений."""
        session = TagReviewSession(
            meeting_id="test123",
            owner_user_id=12345,
            started_at=time.time(),
            original_tags=["Finance/IFRS", "Business/Lavka"],
            working_tags=["Finance/IFRS", "Projects/Mobile"],
        )

        summary = session.get_changes_summary()
        assert "+1 добавлено" in summary
        assert "-1 удалено" in summary


class TestUtilityFunctions:
    """Тесты для вспомогательных функций."""

    def test_validate_tag_format_valid(self):
        """Тест валидации правильных тегов."""
        assert _validate_tag_format("Finance/IFRS")
        assert _validate_tag_format("Business/Lavka")
        assert _validate_tag_format("People/Ivan Petrov")
        assert _validate_tag_format("Projects/Mobile App")

    def test_validate_tag_format_invalid(self):
        """Тест валидации неправильных тегов."""
        assert not _validate_tag_format("InvalidCategory/Test")
        assert not _validate_tag_format("Finance")  # нет слэша
        assert not _validate_tag_format("Finance/")  # пустое название
        assert not _validate_tag_format("")  # пустая строка
        assert not _validate_tag_format("Finance/Test/Extra")  # лишний слэш

    def test_format_tags_message(self, sample_session):
        """Тест форматирования сообщения."""
        message = _format_tags_message(sample_session)

        assert "Ревью тегов встречи" in message
        assert "Finance/IFRS" in message
        assert "Business/Lavka" in message
        # Изменений нет только если есть изменения, иначе секция не показывается

    def test_format_tags_message_empty(self):
        """Тест форматирования сообщения без тегов."""
        session = TagReviewSession(
            meeting_id="test123",
            owner_user_id=12345,
            started_at=time.time(),
            original_tags=[],
            working_tags=[],
        )

        message = _format_tags_message(session)
        assert "Тегов нет" in message

    def test_build_tags_keyboard(self, sample_session):
        """Тест создания клавиатуры."""
        keyboard = _build_tags_keyboard(sample_session)

        assert keyboard.inline_keyboard
        # Проверяем наличие управляющих кнопок
        buttons_text = str(keyboard.inline_keyboard)
        assert "Принять все" in buttons_text
        assert "Удалить все" in buttons_text
        assert "Добавить" in buttons_text
        assert "Сохранить" in buttons_text


class TestHandlers:
    """Тесты для обработчиков."""

    @pytest.mark.asyncio
    async def test_start_tags_review(self, mock_message, mock_fsm_context):
        """Тест запуска ревью тегов."""
        with patch("app.bot.handlers_tags_review.settings.tags_review_enabled", True):
            await start_tags_review(
                meeting_id="deadbeef12345678",
                original_tags=["Finance/IFRS", "Business/Lavka"],
                user_id=50929545,
                message=mock_message,
                state=mock_fsm_context,
            )

            # Проверяем, что сессия создана
            mock_fsm_context.update_data.assert_called_once()
            mock_fsm_context.set_state.assert_called_once_with(TagsReviewStates.reviewing)
            mock_message.answer.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_tags_review_disabled(self, mock_message, mock_fsm_context):
        """Тест что ревью не запускается если отключено."""
        with patch("app.bot.handlers_tags_review.settings.tags_review_enabled", False):
            await start_tags_review(
                meeting_id="test123",
                original_tags=["Finance/IFRS"],
                user_id=50929545,
                message=mock_message,
                state=mock_fsm_context,
            )

            # Проверяем, что ничего не вызывалось
            mock_fsm_context.update_data.assert_not_called()
            mock_message.answer.assert_not_called()

    @pytest.mark.asyncio
    async def test_drop_tag_handler(self, mock_callback, mock_fsm_context, sample_session):
        """Тест удаления тега."""
        mock_callback.data = "tagrev:drop:deadbeef12345678:0"

        # Мокаем получение сессии
        mock_fsm_context.get_data.return_value = {"tagrev:deadbeef12345678": sample_session}

        await drop_tag_handler(mock_callback, mock_fsm_context)

        # Проверяем, что тег удален
        assert len(sample_session.working_tags) == 1  # был 2, стал 1
        assert sample_session.working_tags[0] == "Business/Lavka"
        assert sample_session.history[-1] == ("drop", "Finance/IFRS")

    @pytest.mark.asyncio
    async def test_custom_tag_handler_valid(self, mock_message, mock_fsm_context, sample_session):
        """Тест добавления валидного тега."""
        mock_message.text = "Projects/Mobile App"

        # Мокаем получение сессии
        mock_fsm_context.get_data.return_value = {"tagrev:deadbeef12345678": sample_session}

        with patch("app.bot.handlers_tags_review.TagsReviewStates.waiting_custom_tag"):
            await custom_tag_handler(mock_message, mock_fsm_context)

            # Проверяем, что тег добавлен
            assert "Projects/Mobile App" in sample_session.working_tags
            assert sample_session.history[-1] == ("add", "Projects/Mobile App")

    @pytest.mark.asyncio
    async def test_custom_tag_handler_invalid(self, mock_message, mock_fsm_context):
        """Тест добавления невалидного тега."""
        mock_message.text = "InvalidFormat"

        with patch("app.bot.handlers_tags_review.TagsReviewStates.waiting_custom_tag"):
            await custom_tag_handler(mock_message, mock_fsm_context)

            # Проверяем, что показана ошибка валидации
            mock_message.answer.assert_called_once()
            call_args = mock_message.answer.call_args[0][0]
            assert "Неправильный формат" in call_args

    @pytest.mark.asyncio
    async def test_undo_handler(self, mock_callback, mock_fsm_context, sample_session):
        """Тест отмены действия."""
        # Добавляем действие в историю
        sample_session.history.append(("drop", "Finance/IFRS"))
        sample_session.working_tags.remove("Finance/IFRS")

        mock_callback.data = "tagrev:undo:deadbeef12345678"

        # Мокаем получение сессии
        mock_fsm_context.get_data.return_value = {"tagrev:deadbeef12345678": sample_session}

        await undo_handler(mock_callback, mock_fsm_context)

        # Проверяем, что действие отменено
        assert "Finance/IFRS" in sample_session.working_tags
        assert len(sample_session.history) == 0

    @pytest.mark.asyncio
    async def test_save_handler(self, mock_callback, mock_fsm_context, sample_session):
        """Тест сохранения изменений."""
        mock_callback.data = "tagrev:save:deadbeef12345678"

        # Мокаем получение сессии
        mock_fsm_context.get_data.return_value = {"tagrev:deadbeef12345678": sample_session}

        with (
            patch("app.bot.handlers_tags_review.update_meeting_tags") as mock_update,
            patch("app.bot.handlers_tags_review.settings.enable_tag_edit_log", False),
        ):
            await save_handler(mock_callback, mock_fsm_context)

            # Проверяем, что теги обновлены в Notion
            mock_update.assert_called_once_with(
                sample_session.meeting_id, sample_session.working_tags
            )

            # Проверяем, что сессия очищена
            mock_fsm_context.update_data.assert_called()
            mock_fsm_context.clear.assert_called()

    @pytest.mark.asyncio
    async def test_cancel_handler(self, mock_callback, mock_fsm_context, sample_session):
        """Тест отмены ревью."""
        mock_callback.data = "tagrev:cancel:deadbeef12345678"

        # Мокаем получение сессии
        mock_fsm_context.get_data.return_value = {"tagrev:deadbeef12345678": sample_session}

        await cancel_handler(mock_callback, mock_fsm_context)

        # Проверяем, что сессия очищена без сохранения
        mock_fsm_context.update_data.assert_called()
        mock_fsm_context.clear.assert_called()
        mock_callback.message.edit_text.assert_called_once()


class TestSessionValidation:
    """Тесты для валидации сессий."""

    @pytest.mark.asyncio
    async def test_expired_session(self, mock_callback, mock_fsm_context):
        """Тест обработки истекшей сессии."""
        expired_session = TagReviewSession(
            meeting_id="test123",
            owner_user_id=12345,
            started_at=time.time() - 1000,  # истекшая
            original_tags=[],
            working_tags=[],
        )

        mock_callback.data = "tagrev:save:test123"
        mock_fsm_context.get_data.return_value = {"tagrev:test123": expired_session}

        await save_handler(mock_callback, mock_fsm_context)

        # Проверяем, что показана ошибка истечения
        mock_callback.answer.assert_called_once()
        call_args = mock_callback.answer.call_args[0][0]
        assert "истекла" in call_args

    @pytest.mark.asyncio
    async def test_unauthorized_access(self, mock_callback, mock_fsm_context, sample_session):
        """Тест несанкционированного доступа."""
        # Меняем ID пользователя на чужой
        mock_callback.from_user.id = 99999
        mock_callback.data = "tagrev:save:deadbeef12345678"

        mock_fsm_context.get_data.return_value = {"tagrev:deadbeef12345678": sample_session}

        await save_handler(mock_callback, mock_fsm_context)

        # Проверяем, что показана ошибка доступа
        mock_callback.answer.assert_called_once()
        call_args = mock_callback.answer.call_args[0][0]
        assert "нет прав" in call_args


class TestErrorHandling:
    """Тесты для обработки ошибок."""

    @pytest.mark.asyncio
    async def test_drop_tag_invalid_index(self, mock_callback, mock_fsm_context, sample_session):
        """Тест удаления тега с неправильным индексом."""
        mock_callback.data = "tagrev:drop:deadbeef12345678:999"  # неправильный индекс

        mock_fsm_context.get_data.return_value = {"tagrev:deadbeef12345678": sample_session}

        await drop_tag_handler(mock_callback, mock_fsm_context)

        # Проверяем, что показана ошибка
        mock_callback.answer.assert_called_once()
        call_args = mock_callback.answer.call_args[0][0]
        assert "не найден" in call_args

    @pytest.mark.asyncio
    async def test_undo_empty_history(self, mock_callback, mock_fsm_context, sample_session):
        """Тест отмены при пустой истории."""
        sample_session.history = []  # пустая история

        mock_callback.data = "tagrev:undo:deadbeef12345678"

        mock_fsm_context.get_data.return_value = {"tagrev:deadbeef12345678": sample_session}

        await undo_handler(mock_callback, mock_fsm_context)

        # Проверяем, что показана ошибка
        mock_callback.answer.assert_called_once()
        call_args = mock_callback.answer.call_args[0][0]
        assert "пуста" in call_args


class TestIntegration:
    """Интеграционные тесты."""

    @pytest.mark.asyncio
    async def test_full_workflow(self, mock_message, mock_fsm_context):
        """Тест полного workflow ревью тегов."""
        original_tags = ["Finance/IFRS", "Business/Lavka"]

        with patch("app.bot.handlers_tags_review.settings.tags_review_enabled", True):
            # 1. Запускаем ревью
            await start_tags_review(
                meeting_id="deadbeef12345678",
                original_tags=original_tags,
                user_id=50929545,
                message=mock_message,
                state=mock_fsm_context,
            )

            # Проверяем, что интерфейс создан
            assert mock_message.answer.call_count == 1
            assert mock_fsm_context.set_state.call_count == 1

    @pytest.mark.asyncio
    async def test_review_tags_admin_command(self):
        """Тест административной команды review_tags."""
        from app.bot.handlers_admin import review_tags_handler

        mock_message = AsyncMock()
        mock_message.text = "/review_tags deadbeef12345678"
        mock_message.from_user.id = 50929545
        mock_message.answer = AsyncMock()

        mock_state = AsyncMock()

        with (
            patch("app.bot.handlers_admin._is_admin", return_value=True),
            patch("app.gateways.notion_meetings.validate_meeting_access", return_value=True),
            patch(
                "app.gateways.notion_meetings.fetch_meeting_page",
                return_value={"current_tags": ["Finance/IFRS", "Business/Lavka"]},
            ),
            patch("app.bot.handlers_tags_review.start_tags_review") as mock_start,
        ):
            await review_tags_handler(mock_message, mock_state)

            # Проверяем, что ревью запущено
            mock_start.assert_called_once()
            assert mock_message.answer.call_count >= 1
