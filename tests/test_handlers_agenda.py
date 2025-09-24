"""
Тесты для обработчиков команд повесток в Telegram.
"""

from unittest.mock import AsyncMock, Mock, patch

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, User

from app.bot.handlers_agenda import (
    AgendaStates,
    _build_agenda_keyboard,
    _build_main_menu_keyboard,
    _build_people_keyboard,
    _build_tags_keyboard,
    _generate_meeting_agenda,
    _generate_person_agenda,
    _generate_tag_agenda,
    callback_agenda_back,
    callback_agenda_cancel,
    callback_agenda_meeting,
    callback_agenda_person,
    callback_agenda_tag,
    callback_person_selected,
    callback_tag_selected,
    cmd_agenda_meeting_direct,
    cmd_agenda_menu,
    cmd_agenda_person_direct,
    cmd_agenda_tag_direct,
    handle_meeting_id_input,
    handle_person_name_input,
    handle_tag_name_input,
)
from app.core.agenda_builder import AgendaBundle


class TestKeyboards:
    """Тесты для функций создания клавиатур."""

    def test_build_main_menu_keyboard(self):
        """Тест создания главного меню."""
        keyboard = _build_main_menu_keyboard()

        assert keyboard.inline_keyboard is not None
        assert len(keyboard.inline_keyboard) == 2  # 2 ряда кнопок

        # Первый ряд: встреча и человек
        first_row = keyboard.inline_keyboard[0]
        assert len(first_row) == 2
        assert first_row[0].text == "🏢 По встрече"
        assert first_row[0].callback_data == "agenda:type:meeting"
        assert first_row[1].text == "👤 По человеку"
        assert first_row[1].callback_data == "agenda:type:person"

        # Второй ряд: тег и отмена
        second_row = keyboard.inline_keyboard[1]
        assert len(second_row) == 2
        assert second_row[0].text == "🏷️ По тегу"
        assert second_row[0].callback_data == "agenda:type:tag"
        assert second_row[1].text == "❌ Отмена"
        assert second_row[1].callback_data == "agenda:cancel"

    @patch("app.bot.handlers_agenda.load_people")
    def test_build_people_keyboard(self, mock_load_people):
        """Тест создания клавиатуры людей."""
        mock_load_people.return_value = [
            {"name_en": "Valya Dobrynin", "aliases": ["Valya", "Валентин"]},
            {"name_en": "Sasha Katanov", "aliases": ["Sasha", "Александр"]},
            {"name_en": "Ivan Petrov", "aliases": ["Ivan", "Иван"]},
        ]

        keyboard = _build_people_keyboard()

        assert keyboard.inline_keyboard is not None
        # Проверяем, что есть кнопки для популярных людей
        found_people = []
        for row in keyboard.inline_keyboard[:-2]:  # Исключаем последние 2 ряда (manual + back)
            for button in row:
                if button.text.startswith("👤"):
                    found_people.append(button.text)

        assert len(found_people) > 0

        # Проверяем последние кнопки
        manual_row = keyboard.inline_keyboard[-2]
        assert manual_row[0].text == "✍️ Ввести вручную"
        assert manual_row[0].callback_data == "agenda:person:manual"

        back_row = keyboard.inline_keyboard[-1]
        assert back_row[0].text == "🔙 Назад"
        assert back_row[0].callback_data == "agenda:back"

    def test_build_tags_keyboard(self):
        """Тест создания клавиатуры тегов."""
        keyboard = _build_tags_keyboard()

        assert keyboard.inline_keyboard is not None

        # Проверяем, что есть кнопки для популярных тегов
        found_tags = []
        for row in keyboard.inline_keyboard[:-2]:  # Исключаем последние 2 ряда
            for button in row:
                if button.text.startswith("🏷️"):
                    found_tags.append(button.text)

        assert len(found_tags) > 0
        assert any("Finance/IFRS" in tag for tag in found_tags)

    def test_build_agenda_keyboard(self):
        """Тест создания клавиатуры для готовой повестки."""
        bundle = AgendaBundle(
            context_type="Meeting",
            context_key="test-meeting",
            debts_mine=[],
            debts_theirs=[],
            review_open=[],
            recent_done=[],
            commits_linked=[],
            summary_md="Test",
            tags=[],
            people=[],
            raw_hash="abcd1234",
        )

        keyboard = _build_agenda_keyboard(bundle)

        assert keyboard.inline_keyboard is not None
        assert len(keyboard.inline_keyboard) == 3  # 3 ряда кнопок

        # Проверяем кнопки
        save_button = keyboard.inline_keyboard[0][0]
        assert save_button.text == "📤 Сохранить в Notion"
        assert save_button.callback_data.startswith("agenda:save:Meeting:")

        refresh_button = keyboard.inline_keyboard[1][0]
        assert refresh_button.text == "🔄 Обновить"
        assert refresh_button.callback_data == "agenda:refresh:Meeting:test-meeting"

        new_button = keyboard.inline_keyboard[2][0]
        assert new_button.text == "🔙 Новая повестка"
        assert new_button.callback_data == "agenda:new"


class TestCommands:
    """Тесты для команд повесток."""

    @pytest.mark.asyncio
    async def test_cmd_agenda_menu(self):
        """Тест команды /agenda."""
        mock_message = Mock(spec=Message)
        mock_message.answer = AsyncMock()
        mock_state = Mock(spec=FSMContext)
        mock_state.clear = AsyncMock()

        await cmd_agenda_menu(mock_message, mock_state)

        mock_state.clear.assert_called_once()
        mock_message.answer.assert_called_once()

        # Проверяем содержимое сообщения
        call_args = mock_message.answer.call_args
        message_text = call_args[0][0]
        assert "📋 <b>Система повесток</b>" in message_text
        assert "🏢 <b>По встрече</b>" in message_text
        assert "👤 <b>По человеку</b>" in message_text
        assert "🏷️ <b>По тегу</b>" in message_text

    @pytest.mark.asyncio
    @patch("app.bot.handlers_agenda._generate_meeting_agenda")
    async def test_cmd_agenda_meeting_direct_with_id(self, mock_generate):
        """Тест прямой команды /agenda_meeting с ID."""
        mock_message = Mock(spec=Message)
        mock_message.text = "/agenda_meeting 277344c5-6766-8198-af51-e25b82569c9e"
        mock_generate.return_value = None

        await cmd_agenda_meeting_direct(mock_message)

        mock_generate.assert_called_once_with(mock_message, "277344c5-6766-8198-af51-e25b82569c9e")

    @pytest.mark.asyncio
    async def test_cmd_agenda_meeting_direct_no_id(self):
        """Тест прямой команды /agenda_meeting без ID."""
        mock_message = Mock(spec=Message)
        mock_message.text = "/agenda_meeting"
        mock_message.answer = AsyncMock()

        await cmd_agenda_meeting_direct(mock_message)

        mock_message.answer.assert_called_once()
        call_args = mock_message.answer.call_args
        message_text = call_args[0][0]
        assert "❓ Укажите ID встречи:" in message_text

    @pytest.mark.asyncio
    @patch("app.bot.handlers_agenda._generate_person_agenda")
    async def test_cmd_agenda_person_direct_with_name(self, mock_generate):
        """Тест прямой команды /agenda_person с именем."""
        mock_message = Mock(spec=Message)
        mock_message.text = "/agenda_person Sasha Katanov"
        mock_generate.return_value = None

        await cmd_agenda_person_direct(mock_message)

        mock_generate.assert_called_once_with(mock_message, "Sasha Katanov")

    @pytest.mark.asyncio
    async def test_cmd_agenda_person_direct_no_name(self):
        """Тест прямой команды /agenda_person без имени."""
        mock_message = Mock(spec=Message)
        mock_message.text = "/agenda_person"
        mock_message.answer = AsyncMock()

        await cmd_agenda_person_direct(mock_message)

        mock_message.answer.assert_called_once()
        call_args = mock_message.answer.call_args
        message_text = call_args[0][0]
        assert "❓ Укажите имя человека:" in message_text

    @pytest.mark.asyncio
    @patch("app.bot.handlers_agenda._generate_tag_agenda")
    async def test_cmd_agenda_tag_direct_with_tag(self, mock_generate):
        """Тест прямой команды /agenda_tag с тегом."""
        mock_message = Mock(spec=Message)
        mock_message.text = "/agenda_tag Finance/IFRS"
        mock_generate.return_value = None

        await cmd_agenda_tag_direct(mock_message)

        mock_generate.assert_called_once_with(mock_message, "Finance/IFRS")


class TestCallbacks:
    """Тесты для callback обработчиков."""

    @pytest.mark.asyncio
    async def test_callback_agenda_meeting(self):
        """Тест callback выбора повестки по встрече."""
        mock_callback = Mock(spec=CallbackQuery)
        mock_callback.data = "agenda:type:meeting"
        mock_callback.message = Mock()
        mock_callback.message.edit_text = AsyncMock()
        mock_callback.answer = AsyncMock()

        mock_state = Mock(spec=FSMContext)
        mock_state.set_state = AsyncMock()

        await callback_agenda_meeting(mock_callback, mock_state)

        mock_state.set_state.assert_called_once_with(AgendaStates.waiting_meeting_id)
        mock_callback.message.edit_text.assert_called_once()
        mock_callback.answer.assert_called_once()

        # Проверяем содержимое сообщения
        call_args = mock_callback.message.edit_text.call_args
        message_text = call_args[0][0]
        assert "🏢 <b>Повестка по встрече</b>" in message_text

    @pytest.mark.asyncio
    async def test_callback_agenda_person(self):
        """Тест callback выбора персональной повестки."""
        mock_callback = Mock(spec=CallbackQuery)
        mock_callback.data = "agenda:type:person"
        mock_callback.message = Mock()
        mock_callback.message.edit_text = AsyncMock()
        mock_callback.answer = AsyncMock()

        mock_state = Mock(spec=FSMContext)
        mock_state.clear = AsyncMock()

        await callback_agenda_person(mock_callback, mock_state)

        mock_state.clear.assert_called_once()
        mock_callback.message.edit_text.assert_called_once()
        mock_callback.answer.assert_called_once()

    @pytest.mark.asyncio
    async def test_callback_agenda_tag(self):
        """Тест callback выбора тематической повестки."""
        mock_callback = Mock(spec=CallbackQuery)
        mock_callback.data = "agenda:type:tag"
        mock_callback.message = Mock()
        mock_callback.message.edit_text = AsyncMock()
        mock_callback.answer = AsyncMock()

        mock_state = Mock(spec=FSMContext)
        mock_state.clear = AsyncMock()

        await callback_agenda_tag(mock_callback, mock_state)

        mock_state.clear.assert_called_once()
        mock_callback.message.edit_text.assert_called_once()
        mock_callback.answer.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.bot.handlers_agenda._generate_person_agenda")
    async def test_callback_person_selected_specific(self, mock_generate):
        """Тест выбора конкретного человека."""
        mock_callback = Mock(spec=CallbackQuery)
        mock_callback.data = "agenda:person:Sasha Katanov"
        mock_callback.message = Mock()
        mock_callback.answer = AsyncMock()
        mock_generate.return_value = None

        await callback_person_selected(mock_callback)

        mock_generate.assert_called_once_with(mock_callback.message, "Sasha Katanov")
        mock_callback.answer.assert_called_once()

    @pytest.mark.asyncio
    async def test_callback_person_selected_manual(self):
        """Тест выбора ручного ввода имени."""
        mock_callback = Mock(spec=CallbackQuery)
        mock_callback.data = "agenda:person:manual"
        mock_callback.message = Mock()
        mock_callback.message.edit_text = AsyncMock()
        mock_callback.answer = AsyncMock()

        await callback_person_selected(mock_callback)

        mock_callback.message.edit_text.assert_called_once()
        mock_callback.answer.assert_called_once()

        # Проверяем содержимое сообщения
        call_args = mock_callback.message.edit_text.call_args
        message_text = call_args[0][0]
        assert "Введите имя человека" in message_text

    @pytest.mark.asyncio
    @patch("app.bot.handlers_agenda._generate_tag_agenda")
    async def test_callback_tag_selected_specific(self, mock_generate):
        """Тест выбора конкретного тега."""
        mock_callback = Mock(spec=CallbackQuery)
        mock_callback.data = "agenda:tag:Finance/IFRS"
        mock_callback.message = Mock()
        mock_callback.answer = AsyncMock()
        mock_generate.return_value = None

        await callback_tag_selected(mock_callback)

        mock_generate.assert_called_once_with(mock_callback.message, "Finance/IFRS")
        mock_callback.answer.assert_called_once()

    @pytest.mark.asyncio
    async def test_callback_agenda_back(self):
        """Тест возврата к главному меню."""
        mock_callback = Mock(spec=CallbackQuery)
        mock_callback.data = "agenda:back"
        mock_callback.message = Mock()
        mock_callback.message.edit_text = AsyncMock()
        mock_callback.answer = AsyncMock()

        mock_state = Mock(spec=FSMContext)
        mock_state.clear = AsyncMock()

        await callback_agenda_back(mock_callback, mock_state)

        mock_state.clear.assert_called_once()
        mock_callback.message.edit_text.assert_called_once()
        mock_callback.answer.assert_called_once()

    @pytest.mark.asyncio
    async def test_callback_agenda_cancel(self):
        """Тест отмены создания повестки."""
        mock_callback = Mock(spec=CallbackQuery)
        mock_callback.data = "agenda:cancel"
        mock_callback.message = Mock()
        mock_callback.message.edit_text = AsyncMock()
        mock_callback.answer = AsyncMock()

        mock_state = Mock(spec=FSMContext)
        mock_state.clear = AsyncMock()

        await callback_agenda_cancel(mock_callback, mock_state)

        mock_state.clear.assert_called_once()
        mock_callback.message.edit_text.assert_called_once()
        mock_callback.answer.assert_called_once()

        # Проверяем содержимое сообщения
        call_args = mock_callback.message.edit_text.call_args
        message_text = call_args[0][0]
        assert "❌ Создание повестки отменено" in message_text


class TestFSMHandlers:
    """Тесты для обработчиков FSM состояний."""

    @pytest.mark.asyncio
    @patch("app.bot.handlers_agenda._generate_meeting_agenda")
    async def test_handle_meeting_id_input_valid(self, mock_generate):
        """Тест обработки валидного ID встречи."""
        mock_message = Mock(spec=Message)
        mock_message.text = "277344c5-6766-8198-af51-e25b82569c9e"
        mock_state = Mock(spec=FSMContext)
        mock_state.clear = AsyncMock()
        mock_generate.return_value = None

        await handle_meeting_id_input(mock_message, mock_state)

        mock_state.clear.assert_called_once()
        mock_generate.assert_called_once_with(mock_message, "277344c5-6766-8198-af51-e25b82569c9e")

    @pytest.mark.asyncio
    async def test_handle_meeting_id_input_empty(self):
        """Тест обработки пустого ID встречи."""
        mock_message = Mock(spec=Message)
        mock_message.text = "  "  # Пустая строка с пробелами
        mock_message.answer = AsyncMock()
        mock_state = Mock(spec=FSMContext)
        mock_state.clear = AsyncMock()

        await handle_meeting_id_input(mock_message, mock_state)

        mock_state.clear.assert_called_once()
        mock_message.answer.assert_called_once_with("❌ ID встречи не может быть пустым")

    @pytest.mark.asyncio
    @patch("app.bot.handlers_agenda._generate_person_agenda")
    async def test_handle_person_name_input_valid(self, mock_generate):
        """Тест обработки валидного имени человека."""
        mock_message = Mock(spec=Message)
        mock_message.text = "John Doe"
        mock_state = Mock(spec=FSMContext)
        mock_state.clear = AsyncMock()
        mock_generate.return_value = None

        await handle_person_name_input(mock_message, mock_state)

        mock_state.clear.assert_called_once()
        mock_generate.assert_called_once_with(mock_message, "John Doe")

    @pytest.mark.asyncio
    @patch("app.bot.handlers_agenda._generate_tag_agenda")
    async def test_handle_tag_name_input_valid(self, mock_generate):
        """Тест обработки валидного тега."""
        mock_message = Mock(spec=Message)
        mock_message.text = "Finance/IFRS"
        mock_state = Mock(spec=FSMContext)
        mock_state.clear = AsyncMock()
        mock_generate.return_value = None

        await handle_tag_name_input(mock_message, mock_state)

        mock_state.clear.assert_called_once()
        mock_generate.assert_called_once_with(mock_message, "Finance/IFRS")


class TestAgendaGeneration:
    """Тесты для функций генерации повесток."""

    @pytest.mark.asyncio
    @patch("app.bot.handlers_agenda.agenda_builder.build_for_meeting")
    @patch("app.bot.handlers_agenda.format_agenda_card")
    async def test_generate_meeting_agenda_success(self, mock_format, mock_build):
        """Тест успешной генерации повестки встречи."""
        # Подготавливаем моки
        mock_bundle = AgendaBundle(
            context_type="Meeting",
            context_key="meeting-123",
            debts_mine=[],
            debts_theirs=[],
            review_open=[],
            recent_done=[],
            commits_linked=[],
            summary_md="Test agenda",
            tags=["Finance/IFRS"],
            people=["John Doe"],
            raw_hash="abcd1234",
        )
        mock_build.return_value = mock_bundle
        mock_format.return_value = "Formatted agenda card"

        mock_message = Mock(spec=Message)
        mock_message.answer = AsyncMock()

        # Тестируем
        await _generate_meeting_agenda(mock_message, "meeting-123")

        # Проверяем вызовы
        mock_build.assert_called_once_with("meeting-123")
        mock_format.assert_called_once_with(mock_bundle, device_type="mobile")
        mock_message.answer.assert_called_once()

        # Проверяем аргументы ответа
        call_args = mock_message.answer.call_args
        assert call_args[0][0] == "Formatted agenda card"
        assert call_args[1]["parse_mode"] == "HTML"
        assert "reply_markup" in call_args[1]

    @pytest.mark.asyncio
    @patch("app.bot.handlers_agenda.agenda_builder.build_for_meeting")
    async def test_generate_meeting_agenda_error(self, mock_build):
        """Тест обработки ошибки при генерации повестки встречи."""
        mock_build.side_effect = Exception("Test error")

        mock_message = Mock(spec=Message)
        mock_message.answer = AsyncMock()

        # Тестируем
        await _generate_meeting_agenda(mock_message, "invalid-meeting")

        # Проверяем, что отправлено сообщение об ошибке
        mock_message.answer.assert_called_once()
        call_args = mock_message.answer.call_args
        message_text = call_args[0][0]
        assert "❌ Ошибка при создании повестки для встречи" in message_text
        assert "invalid-meeting" in message_text

    @pytest.mark.asyncio
    @patch("app.bot.handlers_agenda.agenda_builder.build_for_person")
    @patch("app.bot.handlers_agenda.format_agenda_card")
    async def test_generate_person_agenda_success(self, mock_format, mock_build):
        """Тест успешной генерации персональной повестки."""
        mock_bundle = AgendaBundle(
            context_type="Person",
            context_key="People/John Doe",
            debts_mine=[{"text": "My task"}],
            debts_theirs=[{"text": "Their task"}],
            review_open=[],
            recent_done=[],
            commits_linked=["commit-1"],
            summary_md="Personal agenda",
            tags=["People/John Doe"],
            people=["John Doe"],
            raw_hash="efgh5678",
        )
        mock_build.return_value = mock_bundle
        mock_format.return_value = "Formatted personal agenda"

        mock_message = Mock(spec=Message)
        mock_message.answer = AsyncMock()

        await _generate_person_agenda(mock_message, "John Doe")

        mock_build.assert_called_once_with("John Doe")
        mock_format.assert_called_once_with(mock_bundle, device_type="mobile")
        mock_message.answer.assert_called_once()

    @pytest.mark.asyncio
    @patch("app.bot.handlers_agenda.agenda_builder.build_for_tag")
    @patch("app.bot.handlers_agenda.format_agenda_card")
    async def test_generate_tag_agenda_success(self, mock_format, mock_build):
        """Тест успешной генерации тематической повестки."""
        mock_bundle = AgendaBundle(
            context_type="Tag",
            context_key="Finance/IFRS",
            debts_mine=[{"text": "Finance task"}],
            debts_theirs=[],
            review_open=[{"text": "Review question"}],
            recent_done=[{"text": "Completed task"}],
            commits_linked=["commit-2"],
            summary_md="Tag agenda",
            tags=["Finance/IFRS"],
            people=["Finance Team"],
            raw_hash="ijkl9012",
        )
        mock_build.return_value = mock_bundle
        mock_format.return_value = "Formatted tag agenda"

        mock_message = Mock(spec=Message)
        mock_message.answer = AsyncMock()

        await _generate_tag_agenda(mock_message, "Finance/IFRS")

        mock_build.assert_called_once_with("Finance/IFRS")
        mock_format.assert_called_once_with(mock_bundle, device_type="mobile")
        mock_message.answer.assert_called_once()


class TestErrorScenarios:
    """Тесты для сценариев с ошибками."""

    @pytest.mark.asyncio
    async def test_handle_none_text_message(self):
        """Тест обработки сообщения с None текстом."""
        mock_message = Mock(spec=Message)
        mock_message.text = None
        mock_message.answer = AsyncMock()
        mock_state = Mock(spec=FSMContext)
        mock_state.clear = AsyncMock()

        await handle_meeting_id_input(mock_message, mock_state)

        mock_state.clear.assert_called_once()
        mock_message.answer.assert_called_once_with("❌ ID встречи не может быть пустым")

    @pytest.mark.asyncio
    async def test_callback_save_agenda_error(self):
        """Тест обработки ошибки при сохранении повестки."""
        mock_callback = Mock(spec=CallbackQuery)
        mock_callback.data = "agenda:save:Meeting:abcd"
        mock_callback.answer = AsyncMock()
        mock_callback.message = Mock()
        mock_callback.message.answer = AsyncMock()

        # Импортируем и тестируем функцию с ошибкой
        from app.bot.handlers_agenda import callback_save_agenda

        # Мокаем ошибку в процессе сохранения
        with patch("app.bot.handlers_agenda.logger"):
            await callback_save_agenda(mock_callback)

            # Проверяем, что показана заглушка (пока не реализовано полное сохранение)
            mock_callback.answer.assert_called_once_with("💾 Сохранение в Notion...")
            mock_callback.message.answer.assert_called_once()


class TestIntegration:
    """Интеграционные тесты."""

    @pytest.mark.asyncio
    @patch("app.bot.handlers_agenda.agenda_builder.build_for_meeting")
    @patch("app.bot.handlers_agenda.format_agenda_card")
    async def test_full_meeting_agenda_workflow(self, mock_format, mock_build):
        """Тест полного цикла создания повестки встречи."""
        # Создаем реалистичную повестку
        mock_bundle = AgendaBundle(
            context_type="Meeting",
            context_key="277344c5-6766-8198-af51-e25b82569c9e",
            debts_mine=[
                {
                    "id": "commit-1",
                    "text": "Prepare report",
                    "assignees": ["John Doe"],
                    "due_date": "2025-10-15",
                    "status": "open",
                }
            ],
            debts_theirs=[],
            review_open=[{"id": "review-1", "text": "Need clarification", "reason": ["unclear"]}],
            recent_done=[],
            commits_linked=["commit-1"],
            summary_md="🧾 <b>Коммиты встречи</b>\n🟥 Prepare report — 👤 John Doe | ⏳ 2025-10-15\n\n❓ <b>Открытые вопросы</b>\n❓ Need clarification (unclear)",
            tags=["Finance/IFRS", "Topic/Meeting"],
            people=["John Doe"],
            raw_hash="test1234hash",
        )

        mock_build.return_value = mock_bundle
        mock_format.return_value = (
            "<b>🏢 Повестка — Встреча</b>\n"
            "📊 👤 Мои: 1 | ❓ Вопросы: 1\n"
            "🏷️ Finance/IFRS, Topic/Meeting\n"
            "👥 John Doe\n\n"
            "🧾 Коммиты встречи\n"
            "🟥 Prepare report — 👤 John Doe | ⏳ 2025-10-15\n"
            "...\n\n"
            "🕒 Сгенерировано: 24.09 12:00 UTC"
        )

        # Создаем мок сообщения
        mock_user = Mock(spec=User)
        mock_user.id = 12345
        mock_message = Mock(spec=Message)
        mock_message.from_user = mock_user
        mock_message.text = "/agenda_meeting 277344c5-6766-8198-af51-e25b82569c9e"
        mock_message.answer = AsyncMock()

        # Выполняем команду
        await cmd_agenda_meeting_direct(mock_message)

        # Проверяем результат
        mock_build.assert_called_once_with("277344c5-6766-8198-af51-e25b82569c9e")
        mock_format.assert_called_once()
        mock_message.answer.assert_called_once()

        # Проверяем содержимое ответа
        call_args = mock_message.answer.call_args
        response_text = call_args[0][0]
        assert "🏢 Повестка — Встреча" in response_text
        assert "Finance/IFRS" in response_text
        assert "John Doe" in response_text

        # Проверяем клавиатуру
        keyboard = call_args[1]["reply_markup"]
        assert keyboard is not None
        assert len(keyboard.inline_keyboard) == 3  # save, refresh, new
