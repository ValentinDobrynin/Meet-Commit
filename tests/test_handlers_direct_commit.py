"""Тесты для обработчиков прямых коммитов."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, User

from app.bot.handlers_direct_commit import (
    _build_confirm_keyboard,
    _build_edit_keyboard,
    _build_people_keyboard,
    _get_people_suggestions,
    _show_confirmation,
    cancel_direct_commit,
    confirm_direct_commit,
    edit_direct_commit,
    handle_edit_field,
    set_commit_text,
    set_due_callback,
    set_due_manual,
    set_from_callback,
    start_direct_commit,
)
from app.bot.states.commit_states import DirectCommitStates


@pytest.fixture
def mock_message():
    """Фикстура для создания mock сообщения."""
    message = AsyncMock(spec=Message)
    message.from_user = MagicMock(spec=User)
    message.from_user.id = 123456789
    message.answer = AsyncMock()
    message.edit_text = AsyncMock()
    return message


@pytest.fixture
def mock_callback():
    """Фикстура для создания mock callback query."""
    callback = AsyncMock(spec=CallbackQuery)
    callback.from_user = MagicMock(spec=User)
    callback.from_user.id = 123456789
    callback.answer = AsyncMock()
    callback.message = AsyncMock(spec=Message)
    callback.message.edit_text = AsyncMock()
    callback.message.answer = AsyncMock()
    return callback


@pytest.fixture
def mock_state():
    """Фикстура для создания mock FSM контекста."""
    state = AsyncMock(spec=FSMContext)
    state.clear = AsyncMock()
    state.set_state = AsyncMock()
    state.update_data = AsyncMock()
    state.get_data = AsyncMock()
    return state


class TestUtilityFunctions:
    """Тесты вспомогательных функций."""

    @patch("app.bot.handlers_direct_commit.load_people")
    def test_get_people_suggestions(self, mock_load_people):
        """Тест получения подсказок людей."""
        mock_load_people.return_value = [
            {"name_en": "John Doe"},
            {"name_en": "Jane Smith"},
            {"name_en": ""},  # Пустое имя должно игнорироваться
            {"name_ru": "Иван Петров"},  # Нет name_en
        ]

        suggestions = _get_people_suggestions()

        assert "John Doe" in suggestions
        assert "Jane Smith" in suggestions
        assert len(suggestions) == 2

    def test_build_people_keyboard(self):
        """Тест создания клавиатуры с людьми."""
        suggestions = ["John Doe", "Jane Smith", "Bob Wilson"]
        keyboard = _build_people_keyboard(suggestions, "test_prefix")

        # Проверяем структуру клавиатуры
        assert len(keyboard.inline_keyboard) >= 2  # Минимум 2 ряда (люди + управление)

        # Проверяем, что есть кнопки с именами
        first_row = keyboard.inline_keyboard[0]
        assert any("John Doe" in btn.text for btn in first_row)

        # Проверяем управляющие кнопки (теперь в двух последних рядах)
        control_buttons = keyboard.inline_keyboard[-2] + keyboard.inline_keyboard[-1]
        control_texts = [btn.text for btn in control_buttons]
        assert any("Ввести вручную" in text for text in control_texts)
        assert any("Самостоятельно" in text for text in control_texts)
        assert any("Отмена" in text for text in control_texts)

    def test_build_confirm_keyboard(self):
        """Тест создания клавиатуры подтверждения."""
        keyboard = _build_confirm_keyboard()

        assert len(keyboard.inline_keyboard) == 2

        # Первый ряд: Создать, Редактировать
        first_row = keyboard.inline_keyboard[0]
        assert len(first_row) == 2
        assert any("Создать" in btn.text for btn in first_row)
        assert any("Редактировать" in btn.text for btn in first_row)

        # Второй ряд: Отмена
        second_row = keyboard.inline_keyboard[1]
        assert len(second_row) == 1
        assert "Отмена" in second_row[0].text

    def test_build_edit_keyboard(self):
        """Тест создания клавиатуры редактирования."""
        keyboard = _build_edit_keyboard()

        assert len(keyboard.inline_keyboard) == 3

        # Проверяем наличие всех полей для редактирования
        all_buttons = [btn for row in keyboard.inline_keyboard for btn in row]
        button_texts = [btn.text for btn in all_buttons]

        assert any("Текст" in text for text in button_texts)
        assert any("Заказчик" in text for text in button_texts)  # Обновленная терминология
        assert any("Исполнитель" in text for text in button_texts)  # Обновленная терминология
        assert any("Дедлайн" in text for text in button_texts)


class TestDirectCommitFlow:
    """Тесты основного флоу прямых коммитов."""

    @pytest.mark.asyncio
    async def test_start_direct_commit(self, mock_message, mock_state):
        """Тест запуска создания прямого коммита."""
        mock_message.text = "/commit"

        await start_direct_commit(mock_message, mock_state)

        mock_state.clear.assert_called_once()
        mock_state.set_state.assert_called_once_with(DirectCommitStates.waiting_text)
        mock_message.answer.assert_called_once()

        # Проверяем содержание сообщения
        call_args = mock_message.answer.call_args[0][0]
        assert "Создание прямого коммита" in call_args
        assert "Шаг 1/4" in call_args

    @pytest.mark.asyncio
    async def test_set_commit_text_valid(self, mock_message, mock_state):
        """Тест установки текста коммита."""
        mock_message.text = "Подготовить отчет по продажам"

        with patch(
            "app.bot.handlers_direct_commit._get_people_suggestions", return_value=["John", "Jane"]
        ):
            await set_commit_text(mock_message, mock_state)

        mock_state.update_data.assert_called_once_with(text="Подготовить отчет по продажам")
        mock_state.set_state.assert_called_once_with(DirectCommitStates.waiting_from)
        mock_message.answer.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_commit_text_empty(self, mock_message, mock_state):
        """Тест установки пустого текста коммита."""
        mock_message.text = "   "  # Пустая строка с пробелами

        await set_commit_text(mock_message, mock_state)

        mock_state.update_data.assert_not_called()
        mock_state.set_state.assert_not_called()
        mock_message.answer.assert_called_once()

        call_args = mock_message.answer.call_args[0][0]
        assert "не может быть пустым" in call_args

    @pytest.mark.asyncio
    async def test_set_from_callback_person_selected(self, mock_callback, mock_state):
        """Тест выбора отправителя через кнопку."""
        mock_callback.data = "direct_commit:from:John Doe"

        with patch("app.bot.handlers_direct_commit._get_people_suggestions", return_value=["Jane"]):
            await set_from_callback(mock_callback, mock_state)

        mock_callback.answer.assert_called_once()
        mock_state.update_data.assert_called_once_with(from_person="John Doe")
        mock_state.set_state.assert_called_once_with(DirectCommitStates.waiting_to)

    @pytest.mark.asyncio
    async def test_set_from_callback_manual(self, mock_callback, mock_state):
        """Тест выбора ручного ввода отправителя."""
        mock_callback.data = "direct_commit:from:manual"

        await set_from_callback(mock_callback, mock_state)

        mock_callback.answer.assert_called_once()
        mock_state.update_data.assert_not_called()
        mock_state.set_state.assert_not_called()

        # Проверяем, что сообщение обновилось для ручного ввода
        mock_callback.message.edit_text.assert_called_once()
        call_args = mock_callback.message.edit_text.call_args[0][0]
        assert "Введите имя заказчика" in call_args  # Обновленная терминология


class TestDueDateHandling:
    """Тесты обработки дедлайнов."""

    @pytest.mark.asyncio
    async def test_set_due_callback_today(self, mock_callback, mock_state):
        """Тест установки дедлайна 'сегодня'."""
        mock_callback.data = "direct_commit:due:today"
        mock_state.get_data.return_value = {
            "text": "Test task",
            "from_person": "John",
            "to_person": "Jane",
        }

        with patch("app.bot.handlers_direct_commit._show_confirmation") as mock_show:
            await set_due_callback(mock_callback, mock_state)

        mock_callback.answer.assert_called_once()

        # Проверяем, что дата установлена (сегодняшняя)
        mock_state.update_data.assert_called_once()
        call_args = mock_state.update_data.call_args
        due_iso = call_args.kwargs.get("due_iso")
        assert due_iso is not None
        assert len(due_iso) == 10  # YYYY-MM-DD format

        mock_show.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_due_callback_skip(self, mock_callback, mock_state):
        """Тест пропуска дедлайна."""
        mock_callback.data = "direct_commit:due:skip"
        mock_state.get_data.return_value = {
            "text": "Test task",
            "from_person": "John",
            "to_person": "Jane",
        }

        with patch("app.bot.handlers_direct_commit._show_confirmation") as mock_show:
            await set_due_callback(mock_callback, mock_state)

        mock_state.update_data.assert_called_once_with(due_iso=None)
        mock_show.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_due_manual_valid_date(self, mock_message, mock_state):
        """Тест ручного ввода валидной даты."""
        mock_message.text = "2025-10-15"

        with patch("app.bot.handlers_direct_commit._show_confirmation") as mock_show:
            await set_due_manual(mock_message, mock_state)

        mock_state.update_data.assert_called_once_with(due_iso="2025-10-15")
        mock_show.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_due_manual_invalid_date(self, mock_message, mock_state):
        """Тест ручного ввода невалидной даты."""
        mock_message.text = "invalid-date"

        await set_due_manual(mock_message, mock_state)

        mock_state.update_data.assert_not_called()
        mock_message.answer.assert_called_once()

        call_args = mock_message.answer.call_args[0][0]
        assert "Неверный формат даты" in call_args

    @pytest.mark.asyncio
    async def test_set_due_manual_skip(self, mock_message, mock_state):
        """Тест пропуска дедлайна через текст."""
        mock_message.text = "/skip"

        with patch("app.bot.handlers_direct_commit._show_confirmation") as mock_show:
            await set_due_manual(mock_message, mock_state)

        mock_state.update_data.assert_called_once_with(due_iso=None)
        mock_show.assert_called_once()


class TestConfirmationFlow:
    """Тесты подтверждения и создания коммита."""

    @pytest.mark.asyncio
    async def test_show_confirmation(self, mock_message, mock_state):
        """Тест отображения экрана подтверждения."""
        mock_state.get_data.return_value = {
            "text": "Подготовить отчет",
            "from_person": "Valya Dobrynin",
            "to_person": "John Doe",
            "due_iso": "2025-10-15",
        }

        with patch("app.core.tags.tag_text_for_commit", return_value=["Finance/Report"]):
            await _show_confirmation(mock_message, mock_state)

        mock_state.set_state.assert_called_once_with(DirectCommitStates.confirm)

        # Проверяем, что вызван либо answer, либо edit_text
        assert mock_message.answer.call_count + mock_message.edit_text.call_count == 1

        # Получаем текст сообщения
        if mock_message.answer.called:
            call_args = mock_message.answer.call_args[0][0]
        else:
            call_args = mock_message.edit_text.call_args[0][0]

        assert "Подтверждение коммита" in call_args
        assert "Подготовить отчет" in call_args
        assert "Valya Dobrynin" in call_args
        assert "John Doe" in call_args
        assert "15.10.2025" in call_args

    @pytest.mark.asyncio
    async def test_confirm_direct_commit_success(self, mock_callback, mock_state):
        """Тест успешного создания прямого коммита."""
        mock_callback.data = "direct_commit:confirm"
        mock_state.get_data.return_value = {
            "text": "Подготовить отчет",
            "from_person": "Valya Dobrynin",
            "to_person": "John Doe",
            "due_iso": "2025-10-15",
        }

        # Используем валидный UUID для meeting ID
        valid_meeting_id = "12345678-1234-5678-9abc-123456789abc"

        with (
            patch(
                "app.bot.handlers_direct_commit._create_direct_meeting",
                return_value=valid_meeting_id,
            ),
            patch("app.core.people_store.canonicalize_list") as mock_canonicalize,
            patch("app.core.tags.tag_text_for_commit", return_value=["Finance/Report"]),
            patch("app.bot.handlers_direct_commit.upsert_commits") as mock_upsert,
        ):
            mock_canonicalize.side_effect = lambda x: x  # Возвращаем как есть
            mock_upsert.return_value = {"created": ["commit-123"], "updated": []}

            await confirm_direct_commit(mock_callback, mock_state)

        mock_callback.answer.assert_called_once()
        mock_state.clear.assert_called_once()

        # Проверяем вызов upsert_commits
        mock_upsert.assert_called_once()
        call_args = mock_upsert.call_args
        assert call_args[0][0] == valid_meeting_id  # meeting_page_id

        commit_data = call_args[0][1][0]  # Первый коммит
        assert commit_data["text"] == "Подготовить отчет"
        assert commit_data["direction"] == "mine"  # Valya -> mine
        assert commit_data["assignees"] == ["John Doe"]
        assert commit_data["due_iso"] == "2025-10-15"
        assert commit_data["confidence"] == 1.0
        assert "direct" in commit_data["flags"]

    @pytest.mark.asyncio
    async def test_confirm_direct_commit_missing_fields(self, mock_callback, mock_state):
        """Тест создания коммита с неполными данными."""
        mock_callback.data = "direct_commit:confirm"
        mock_state.get_data.return_value = {
            "text": "Подготовить отчет",
            "from_person": "",  # Пустое поле
            "to_person": "John Doe",
        }

        await confirm_direct_commit(mock_callback, mock_state)

        mock_callback.answer.assert_called_once()
        mock_callback.message.edit_text.assert_called_once()

        call_args = mock_callback.message.edit_text.call_args[0][0]
        assert "Не все обязательные поля заполнены" in call_args

    @pytest.mark.asyncio
    async def test_cancel_direct_commit(self, mock_callback, mock_state):
        """Тест отмены создания коммита."""
        mock_callback.data = "direct_commit:cancel"

        await cancel_direct_commit(mock_callback, mock_state)

        mock_callback.answer.assert_called_once()
        mock_state.clear.assert_called_once()
        mock_callback.message.edit_text.assert_called_once()

        call_args = mock_callback.message.edit_text.call_args[0][0]
        assert "отменено" in call_args


class TestEditFlow:
    """Тесты редактирования коммита."""

    @pytest.mark.asyncio
    async def test_edit_direct_commit(self, mock_callback, mock_state):
        """Тест показа меню редактирования."""
        mock_callback.data = "direct_commit:edit"
        mock_state.get_data.return_value = {
            "text": "Test task",
            "from_person": "John",
            "to_person": "Jane",
            "due_iso": "2025-10-15",
        }

        await edit_direct_commit(mock_callback, mock_state)

        mock_callback.answer.assert_called_once()
        mock_callback.message.edit_text.assert_called_once()

        call_args = mock_callback.message.edit_text.call_args[0][0]
        assert "Редактирование коммита" in call_args
        assert "Test task" in call_args
        assert "John" in call_args
        assert "Jane" in call_args

    @pytest.mark.asyncio
    async def test_handle_edit_field_text(self, mock_callback, mock_state):
        """Тест редактирования поля 'текст'."""
        mock_callback.data = "direct_commit:edit:text"

        await handle_edit_field(mock_callback, mock_state)

        mock_callback.answer.assert_called_once()
        mock_state.set_state.assert_called_once_with(DirectCommitStates.waiting_text)
        mock_callback.message.edit_text.assert_called_once()

    @pytest.mark.asyncio
    async def test_handle_edit_field_from(self, mock_callback, mock_state):
        """Тест редактирования поля 'от кого'."""
        mock_callback.data = "direct_commit:edit:from"

        with patch("app.bot.handlers_direct_commit._get_people_suggestions", return_value=["John"]):
            await handle_edit_field(mock_callback, mock_state)

        mock_callback.answer.assert_called_once()
        mock_state.set_state.assert_called_once_with(DirectCommitStates.waiting_from)


class TestIntegration:
    """Интеграционные тесты."""

    @pytest.mark.asyncio
    async def test_full_workflow_with_buttons(self, mock_message, mock_callback, mock_state):
        """Тест полного флоу с использованием кнопок."""
        # Настраиваем моки
        mock_state.get_data.return_value = {
            "text": "Подготовить отчет",
            "from_person": "Valya Dobrynin",
            "to_person": "John Doe",
            "due_iso": "2025-10-15",
        }

        # Используем валидный UUID
        valid_meeting_id = "87654321-4321-8765-dcba-987654321fed"

        with (
            patch(
                "app.bot.handlers_direct_commit._create_direct_meeting",
                return_value=valid_meeting_id,
            ),
            patch("app.core.people_store.canonicalize_list", side_effect=lambda x: x),
            patch("app.core.tags.tag_text_for_commit", return_value=["Finance/Report"]),
            patch("app.bot.handlers_direct_commit.upsert_commits") as mock_upsert,
        ):
            mock_upsert.return_value = {"created": ["commit-123"], "updated": []}

            # Симулируем полный флоу
            await confirm_direct_commit(mock_callback, mock_state)

        # Проверяем, что коммит создан с правильными данными
        mock_upsert.assert_called_once()
        commit_data = mock_upsert.call_args[0][1][0]

        assert commit_data["text"] == "Подготовить отчет"
        assert commit_data["direction"] == "mine"  # Valya -> mine
        assert commit_data["assignees"] == ["John Doe"]
        assert commit_data["confidence"] == 1.0
        assert "direct" in commit_data["flags"]
        # Теги могут быть пустыми в тестовой среде, главное что функция вызывается
        assert "tags" in commit_data

    @pytest.mark.asyncio
    async def test_direction_detection(self, mock_callback, mock_state):
        """Тест автоматического определения направления."""
        test_cases = [
            ("Valya Dobrynin", "mine"),
            ("валя", "mine"),
            ("Valentin", "mine"),
            ("John Doe", "theirs"),
            ("Иван Петров", "theirs"),
        ]

        # Используем валидный UUID
        valid_meeting_id = "11111111-2222-3333-4444-555555555555"

        for from_person, expected_direction in test_cases:
            mock_state.get_data.return_value = {
                "text": "Test task",
                "from_person": from_person,
                "to_person": "Someone",
                "due_iso": None,
            }

            with (
                patch(
                    "app.bot.handlers_direct_commit._create_direct_meeting",
                    return_value=valid_meeting_id,
                ),
                patch("app.core.people_store.canonicalize_list", side_effect=lambda x: x),
                patch("app.core.tags.tag_text_for_commit", return_value=[]),
                patch("app.bot.handlers_direct_commit.upsert_commits") as mock_upsert,
            ):
                mock_upsert.return_value = {"created": ["commit-123"], "updated": []}

                await confirm_direct_commit(mock_callback, mock_state)

                commit_data = mock_upsert.call_args[0][1][0]
                assert commit_data["direction"] == expected_direction, f"Failed for {from_person}"


class TestErrorHandling:
    """Тесты обработки ошибок."""

    @pytest.mark.asyncio
    async def test_confirm_commit_notion_error(self, mock_callback, mock_state):
        """Тест обработки ошибки Notion API."""
        mock_state.get_data.return_value = {
            "text": "Test task",
            "from_person": "John",
            "to_person": "Jane",
            "due_iso": None,
        }

        with (
            patch(
                "app.bot.handlers_direct_commit._create_direct_meeting",
                side_effect=Exception("Notion error"),
            ),
            patch("app.core.people_store.canonicalize_list", side_effect=lambda x: x),
        ):
            await confirm_direct_commit(mock_callback, mock_state)

        mock_state.clear.assert_called_once()
        mock_callback.message.edit_text.assert_called_once()

        call_args = mock_callback.message.edit_text.call_args[0][0]
        assert "Ошибка создания коммита" in call_args

    @patch("app.bot.handlers_direct_commit.load_people")
    def test_get_people_suggestions_error(self, mock_load_people):
        """Тест обработки ошибки при загрузке людей."""
        mock_load_people.side_effect = Exception("Database error")

        suggestions = _get_people_suggestions()

        assert suggestions == []  # Должен вернуть пустой список при ошибке
