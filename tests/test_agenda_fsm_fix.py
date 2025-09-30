"""
Тест исправления FSM проблемы в agenda системе.
Проверяет что текстовый ввод в состояниях agenda обрабатывается корректно.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.bot.handlers import handle_text_with_fsm_check
from app.bot.handlers_agenda import AgendaStates


class TestAgendaFSMFix:
    """Тесты исправления FSM проблемы в agenda."""

    @pytest.mark.asyncio
    async def test_person_name_input_in_agenda_state(self):
        """Тест что ввод имени человека в состоянии agenda обрабатывается корректно."""

        # Мокаем сообщение с именем человека
        mock_message = AsyncMock()
        mock_message.text = "Valya Dobrynin"
        mock_message.answer = AsyncMock()

        # Мокаем состояние FSM
        mock_state = AsyncMock()
        mock_state.get_state.return_value = AgendaStates.waiting_person_name

        # Мокаем обработчик agenda
        with patch("app.bot.handlers_agenda.handle_person_name_input") as mock_handler:
            mock_handler.return_value = None

            # Вызываем новый обработчик текста с FSM проверкой
            from app.bot.handlers import handle_text_with_fsm_check

            await handle_text_with_fsm_check(mock_message, mock_state)

            # Проверяем что вызван правильный обработчик agenda
            mock_handler.assert_called_once_with(mock_message, mock_state)

            # Проверяем что НЕ была запущена суммаризация
            mock_state.update_data.assert_not_called()
            mock_state.set_state.assert_not_called()

    @pytest.mark.asyncio
    async def test_meeting_id_input_in_agenda_state(self):
        """Тест что ввод ID встречи в состоянии agenda обрабатывается корректно."""

        # Мокаем сообщение с ID встречи
        mock_message = AsyncMock()
        mock_message.text = "27c344c5-6766-81bd-a378-f4912a023598"
        mock_message.answer = AsyncMock()

        # Мокаем состояние FSM
        mock_state = AsyncMock()
        mock_state.get_state.return_value = AgendaStates.waiting_meeting_id

        # Мокаем обработчик agenda
        with patch("app.bot.handlers_agenda.handle_meeting_id_input") as mock_handler:
            mock_handler.return_value = None

            # Вызываем новый обработчик текста с FSM проверкой
            from app.bot.handlers import handle_text_with_fsm_check

            await handle_text_with_fsm_check(mock_message, mock_state)

            # Проверяем что вызван правильный обработчик agenda
            mock_handler.assert_called_once_with(mock_message, mock_state)

            # Проверяем что НЕ была запущена суммаризация
            mock_state.update_data.assert_not_called()
            mock_state.set_state.assert_not_called()

    @pytest.mark.asyncio
    async def test_tag_name_input_in_agenda_state(self):
        """Тест что ввод тега в состоянии agenda обрабатывается корректно."""

        # Мокаем сообщение с тегом
        mock_message = AsyncMock()
        mock_message.text = "Finance/IFRS"
        mock_message.answer = AsyncMock()

        # Мокаем состояние FSM
        mock_state = AsyncMock()
        mock_state.get_state.return_value = AgendaStates.waiting_tag_name

        # Мокаем обработчик agenda
        with patch("app.bot.handlers_agenda.handle_tag_name_input") as mock_handler:
            mock_handler.return_value = None

            # Вызываем новый обработчик текста с FSM проверкой
            from app.bot.handlers import handle_text_with_fsm_check

            await handle_text_with_fsm_check(mock_message, mock_state)

            # Проверяем что вызван правильный обработчик agenda
            mock_handler.assert_called_once_with(mock_message, mock_state)

            # Проверяем что НЕ была запущена суммаризация
            mock_state.update_data.assert_not_called()
            mock_state.set_state.assert_not_called()

    @pytest.mark.asyncio
    async def test_normal_text_still_goes_to_summarization(self):
        """Тест что обычный текст все еще идет на суммаризацию."""

        # Мокаем сообщение с обычным текстом
        mock_message = AsyncMock()
        mock_message.text = "Обычный текст для суммаризации"
        mock_message.answer = AsyncMock()
        mock_message.document = None

        # Мокаем состояние FSM (нет активного состояния)
        mock_state = AsyncMock()
        mock_state.get_state.return_value = None

        # Вызываем новый обработчик текста с FSM проверкой
        await handle_text_with_fsm_check(mock_message, mock_state)

        # Проверяем что запущена суммаризация
        mock_state.update_data.assert_called_once()
        mock_state.set_state.assert_called_once()
        mock_message.answer.assert_called()

        # Проверяем содержимое вызова
        call_args = mock_state.update_data.call_args[1]
        assert call_args["text"] == "Обычный текст для суммаризации"
        assert call_args["raw_bytes"] is None
        assert call_args["filename"] == "message.txt"

    @pytest.mark.asyncio
    async def test_fsm_state_logging(self):
        """Тест что FSM состояния логируются для отладки."""

        # Мокаем сообщение
        mock_message = AsyncMock()
        mock_message.text = "test"
        mock_message.answer = AsyncMock()
        mock_message.document = None

        # Мокаем состояние FSM
        mock_state = AsyncMock()
        mock_state.get_state.return_value = AgendaStates.waiting_person_name

        # Мокаем логгер
        with patch("app.bot.handlers.logger") as mock_logger:
            with patch("app.bot.handlers_agenda.handle_person_name_input") as mock_handler:
                mock_handler.return_value = None

                # Вызываем обработчик
                await handle_text_with_fsm_check(mock_message, mock_state)

                # Проверяем что состояние залогировано
                mock_logger.debug.assert_called_with(
                    f"Text input 'test' in state: {AgendaStates.waiting_person_name}"
                )


class TestAgendaFSMIntegration:
    """Интеграционные тесты FSM agenda с реальными обработчиками."""

    @pytest.mark.asyncio
    @patch("app.bot.handlers_agenda._generate_person_agenda")
    async def test_person_name_processing_integration(self, mock_generate):
        """Интеграционный тест обработки имени человека."""

        # Мокаем генерацию повестки
        mock_generate.return_value = None

        # Мокаем сообщение
        mock_message = AsyncMock()
        mock_message.text = "Valya Dobrynin"
        mock_message.answer = AsyncMock()

        # Мокаем состояние
        mock_state = AsyncMock()
        mock_state.clear = AsyncMock()

        # Импортируем и вызываем реальный обработчик
        from app.bot.handlers_agenda import handle_person_name_input

        await handle_person_name_input(mock_message, mock_state)

        # Проверяем что состояние очищено
        mock_state.clear.assert_called_once()

        # Проверяем что вызвана генерация повестки
        mock_generate.assert_called_once_with(mock_message, "Valya Dobrynin")

    @pytest.mark.asyncio
    @patch("app.bot.handlers_agenda._generate_meeting_agenda")
    async def test_meeting_id_processing_integration(self, mock_generate):
        """Интеграционный тест обработки ID встречи."""

        # Мокаем генерацию повестки
        mock_generate.return_value = None

        # Мокаем сообщение
        mock_message = AsyncMock()
        mock_message.text = "27c344c5-6766-81bd-a378-f4912a023598"
        mock_message.answer = AsyncMock()

        # Мокаем состояние
        mock_state = AsyncMock()
        mock_state.clear = AsyncMock()

        # Импортируем и вызываем реальный обработчик
        from app.bot.handlers_agenda import handle_meeting_id_input

        await handle_meeting_id_input(mock_message, mock_state)

        # Проверяем что состояние очищено
        mock_state.clear.assert_called_once()

        # Проверяем что вызвана генерация повестки
        mock_generate.assert_called_once_with(mock_message, "27c344c5-6766-81bd-a378-f4912a023598")

    @pytest.mark.asyncio
    @patch("app.bot.handlers_agenda._generate_tag_agenda")
    async def test_tag_name_processing_integration(self, mock_generate):
        """Интеграционный тест обработки тега."""

        # Мокаем генерацию повестки
        mock_generate.return_value = None

        # Мокаем сообщение
        mock_message = AsyncMock()
        mock_message.text = "Finance/IFRS"
        mock_message.answer = AsyncMock()

        # Мокаем состояние
        mock_state = AsyncMock()
        mock_state.clear = AsyncMock()

        # Импортируем и вызываем реальный обработчик
        from app.bot.handlers_agenda import handle_tag_name_input

        await handle_tag_name_input(mock_message, mock_state)

        # Проверяем что состояние очищено
        mock_state.clear.assert_called_once()

        # Проверяем что вызвана генерация повестки
        mock_generate.assert_called_once_with(mock_message, "Finance/IFRS")
