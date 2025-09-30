"""
Тесты для улучшенной agenda системы.
Проверяют новую логику кнопок, Other People пагинацию и admin команды.
"""

from unittest.mock import AsyncMock, patch

import pytest

from app.bot.handlers_agenda import (
    _build_fallback_people_keyboard,
    _build_people_keyboard,
    _show_other_people_page,
)


class TestImprovedPeopleKeyboard:
    """Тесты улучшенной клавиатуры людей."""

    @patch("app.core.people_activity.get_top_people_by_activity")
    @patch("app.core.people_activity.get_other_people")
    def test_build_people_keyboard_with_top_people(self, mock_other, mock_top):
        """Тест создания клавиатуры с топ людьми."""
        # Мокаем топ людей
        mock_top.return_value = ["Valya Dobrynin", "Nodari Kezua", "Sergey Lompa"]
        mock_other.return_value = ["Vlad Sklyanov", "Sasha Katanov"]

        keyboard = _build_people_keyboard()

        # Проверяем структуру клавиатуры
        assert keyboard is not None
        assert hasattr(keyboard, "inline_keyboard")
        assert len(keyboard.inline_keyboard) > 0

        # Собираем все тексты кнопок
        all_button_texts = []
        for row in keyboard.inline_keyboard:
            for button in row:
                all_button_texts.append(button.text)

        # Проверяем что есть кнопки с топ людьми
        assert any("Valya Dobrynin" in text for text in all_button_texts)
        assert any("Nodari Kezua" in text for text in all_button_texts)
        assert any("Sergey Lompa" in text for text in all_button_texts)

        # Проверяем что есть кнопка "Other people"
        assert any("Other people" in text for text in all_button_texts)

        # Проверяем что есть кнопка "Назад"
        assert any("Назад" in text for text in all_button_texts)

        # Проверяем что НЕТ кнопки "Ввести вручную"
        assert not any("вручную" in text.lower() for text in all_button_texts)

    @patch("app.core.people_activity.get_top_people_by_activity")
    @patch("app.core.people_activity.get_other_people")
    def test_build_people_keyboard_no_other_people(self, mock_other, mock_top):
        """Тест клавиатуры когда нет других людей."""
        mock_top.return_value = ["Valya Dobrynin", "Nodari Kezua"]
        mock_other.return_value = []  # Нет других людей

        keyboard = _build_people_keyboard()

        # Собираем тексты кнопок
        all_button_texts = []
        for row in keyboard.inline_keyboard:
            for button in row:
                all_button_texts.append(button.text)

        # Не должно быть кнопки "Other people"
        assert not any("Other people" in text for text in all_button_texts)

    def test_build_fallback_people_keyboard(self):
        """Тест fallback клавиатуры людей."""
        keyboard = _build_fallback_people_keyboard()

        assert keyboard is not None
        assert len(keyboard.inline_keyboard) > 0

        # Должны быть кнопки с fallback людьми
        all_button_texts = []
        for row in keyboard.inline_keyboard:
            for button in row:
                all_button_texts.append(button.text)

        # Проверяем fallback людей (используем реальные данные)
        expected_people = [
            "Nodari Kezua",
            "Sergey Lompa",
            "Vlad Sklyanov",
            "Sasha Katanov",
            "Daniil",
        ]
        assert any(person in text for person in expected_people for text in all_button_texts)
        assert any("Nodari Kezua" in text for text in all_button_texts)


class TestOtherPeoplePagination:
    """Тесты пагинации других людей."""

    @pytest.mark.asyncio
    @patch("app.core.people_activity.get_top_people_by_activity")
    @patch("app.core.people_activity.get_other_people")
    async def test_show_other_people_first_page(self, mock_other, mock_top):
        """Тест показа первой страницы других людей."""
        # Мокаем данные
        mock_top.return_value = ["Top Person 1", "Top Person 2"]
        mock_other.return_value = [f"Other Person {i:02d}" for i in range(20)]  # 20 других людей

        # Мокаем callback
        mock_callback = AsyncMock()
        mock_message = AsyncMock()
        mock_callback.message = mock_message
        mock_callback.answer = AsyncMock()

        # Вызываем функцию
        await _show_other_people_page(mock_callback, page=0)

        # Проверяем что сообщение обновлено
        mock_message.edit_text.assert_called_once()
        call_args = mock_message.edit_text.call_args

        # Проверяем текст сообщения
        message_text = call_args[0][0]
        assert "Other people" in message_text
        assert "страница 1/" in message_text

        # Проверяем клавиатуру
        keyboard = call_args[1]["reply_markup"]
        assert keyboard is not None

    @pytest.mark.asyncio
    @patch("app.core.people_activity.get_top_people_by_activity")
    @patch("app.core.people_activity.get_other_people")
    async def test_show_other_people_empty_list(self, mock_other, mock_top):
        """Тест когда нет других людей."""
        mock_top.return_value = ["Top Person"]
        mock_other.return_value = []  # Нет других людей

        mock_callback = AsyncMock()
        mock_callback.answer = AsyncMock()

        await _show_other_people_page(mock_callback, page=0)

        # Должно показать предупреждение
        mock_callback.answer.assert_called_once()
        call_args = mock_callback.answer.call_args
        # Проверяем что вызван с alert
        if len(call_args) > 1 and isinstance(call_args[1], dict):
            assert call_args[1]["show_alert"] is True
        # Проверяем текст предупреждения
        alert_text = call_args[0][0] if call_args[0] else ""
        assert "Нет других людей" in alert_text

    @pytest.mark.asyncio
    @patch("app.core.people_activity.get_top_people_by_activity")
    @patch("app.core.people_activity.get_other_people")
    async def test_pagination_navigation(self, mock_other, mock_top):
        """Тест навигации по страницам."""
        mock_top.return_value = []
        mock_other.return_value = [
            f"Person {i:02d}" for i in range(25)
        ]  # 25 людей = 4 страницы по 8

        mock_callback = AsyncMock()
        mock_message = AsyncMock()
        mock_callback.message = mock_message
        mock_callback.answer = AsyncMock()

        # Тест первой страницы
        await _show_other_people_page(mock_callback, page=0)

        call_args = mock_message.edit_text.call_args
        keyboard = call_args[1]["reply_markup"]

        # Должны быть кнопки навигации
        nav_buttons = []
        for row in keyboard.inline_keyboard:
            for button in row:
                if any(word in button.text for word in ["←", "→", "/"]):
                    nav_buttons.append(button.text)

        # На первой странице должна быть кнопка "Вперед"
        assert any("→" in text for text in nav_buttons)
        assert any("1/" in text for text in nav_buttons)  # Индикатор страницы


class TestAgendaAdminCommands:
    """Тесты админских команд для agenda."""

    @pytest.mark.asyncio
    @patch("app.core.people_activity.get_people_activity_stats")
    @patch("app.core.people_activity.get_top_people_by_activity")
    async def test_people_activity_admin_command(self, mock_top, mock_stats):
        """Тест админской команды /people_activity."""
        from app.bot.handlers_admin import people_activity_handler

        # Мокаем данные
        mock_stats.return_value = {
            "Valya Dobrynin": {"assignee": 10, "from_person": 5},
            "Nodari Kezua": {"assignee": 8, "from_person": 2},
        }
        mock_top.return_value = ["Valya Dobrynin", "Nodari Kezua"]

        # Мокаем сообщение от админа
        mock_message = AsyncMock()
        mock_message.from_user.id = 12345  # Предполагаем что это админ
        mock_message.answer = AsyncMock()

        with patch("app.bot.handlers_admin._is_admin", return_value=True):
            await people_activity_handler(mock_message)

        # Проверяем что ответ отправлен
        mock_message.answer.assert_called_once()
        response_text = mock_message.answer.call_args[0][0]

        # Проверяем содержимое ответа
        assert "Рейтинг активности людей" in response_text
        assert "Valya Dobrynin" in response_text
        assert "Nodari Kezua" in response_text

    @pytest.mark.asyncio
    async def test_admin_command_access_control(self):
        """Тест контроля доступа к админским командам."""
        from app.bot.handlers_admin import people_activity_handler

        # Мокаем сообщение от не-админа
        mock_message = AsyncMock()
        mock_message.from_user.id = 99999  # Не админ
        mock_message.answer = AsyncMock()

        with patch("app.bot.handlers_admin._is_admin", return_value=False):
            await people_activity_handler(mock_message)

        # Должно быть отказано в доступе
        mock_message.answer.assert_called_once()
        response_text = mock_message.answer.call_args[0][0]
        assert "только администраторам" in response_text


class TestAgendaSystemStability:
    """Тесты стабильности улучшенной agenda системы."""

    @patch("app.core.people_activity.get_people_activity_stats")
    def test_handles_activity_calculation_errors(self, mock_stats):
        """Тест обработки ошибок в расчете активности."""
        # Мокаем ошибку
        mock_stats.side_effect = Exception("Database Error")

        # Клавиатура должна использовать fallback
        keyboard = _build_people_keyboard()

        assert keyboard is not None
        # Должна быть создана fallback клавиатура

    @pytest.mark.asyncio
    async def test_other_people_page_error_handling(self):
        """Тест обработки ошибок в пагинации других людей."""
        mock_callback = AsyncMock()
        mock_callback.answer = AsyncMock()

        # Мокаем ошибку в get_other_people
        with patch("app.core.people_activity.get_other_people", side_effect=Exception("Error")):
            await _show_other_people_page(mock_callback, page=0)

        # Должно показать ошибку
        mock_callback.answer.assert_called_once()
        call_args = mock_callback.answer.call_args
        # Проверяем что вызван с alert
        if len(call_args) > 1 and isinstance(call_args[1], dict):
            assert call_args[1]["show_alert"] is True
        # Проверяем текст ошибки
        alert_text = call_args[0][0] if call_args[0] else ""
        assert "Ошибка" in alert_text

    def test_boundary_conditions(self):
        """Тест граничных условий."""
        # Тест с пустыми данными
        with patch("app.core.people_activity.get_people_activity_stats", return_value={}):
            from app.core.people_activity import get_top_people_by_activity

            top_people = get_top_people_by_activity()
            assert isinstance(top_people, list)
            assert len(top_people) >= 3  # Должен использовать fallback

        # Тест с экстремальными параметрами
        with patch("app.core.people_activity.get_people_activity_stats") as mock_stats:
            mock_stats.return_value = {"Person": {"assignee": 1, "from_person": 0}}

            # Тест с min_count > max_count (некорректные параметры)
            result = get_top_people_by_activity(min_count=10, max_count=5)
            assert isinstance(result, list)
            assert len(result) >= 3  # Fallback должен сработать
