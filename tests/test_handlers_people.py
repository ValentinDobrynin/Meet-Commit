"""Тесты для обработчиков people miner."""

import json
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, Message, User

from app.bot.handlers_people import (
    _format_candidate_message,
    _pick_next_candidate,
    _validate_en_name,
    people_miner_start,
    people_reset_handler,
    people_stats_handler,
    pm_add_handler,
    pm_delete_handler,
    pm_skip_handler,
    pm_stats_handler,
    set_en_name_handler,
)


@pytest.fixture
def mock_message():
    """Фикстура для создания mock сообщения."""
    message = AsyncMock(spec=Message)
    message.from_user = MagicMock(spec=User)
    message.from_user.id = 123456789
    message.answer = AsyncMock()
    return message


@pytest.fixture
def mock_callback():
    """Фикстура для создания mock callback query."""
    callback = AsyncMock(spec=CallbackQuery)
    callback.from_user = MagicMock(spec=User)
    callback.from_user.id = 123456789
    callback.message = AsyncMock()
    callback.message.edit_text = AsyncMock()
    callback.message.answer = AsyncMock()
    callback.answer = AsyncMock()
    callback.data = "test_data"
    return callback


@pytest.fixture
def mock_fsm_context():
    """Фикстура для создания mock FSM context."""
    context = AsyncMock(spec=FSMContext)
    context.set_state = AsyncMock()
    context.get_data = AsyncMock()
    context.update_data = AsyncMock()
    context.clear = AsyncMock()
    return context


@pytest.fixture
def temp_candidates_file():
    """Фикстура для создания временного файла кандидатов."""
    test_candidates = [
        {
            "id": "abc12345",
            "alias": "Иван Петров",
            "context": "Встреча с Иван Петровым по проекту",
            "freq": 5,
            "source": "meeting",
        },
        {
            "id": "def67890",
            "alias": "Мария Сидорова",
            "context": "Мария Сидорова подтвердила план",
            "freq": 3,
            "source": "meeting",
        },
    ]

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(test_candidates, f, ensure_ascii=False, indent=2)
        temp_path = Path(f.name)

    # Патчим пути к файлам
    with patch("app.core.people_store.CAND", temp_path):
        yield temp_path, test_candidates

    # Удаляем временный файл
    if temp_path.exists():
        temp_path.unlink()


@pytest.fixture
def temp_people_file():
    """Фикстура для создания временного файла людей."""
    test_people = [
        {
            "name_en": "Sasha Katanov",
            "aliases": ["Саша Катанов", "Катанов"],
            "role": "Developer",
            "org": "Company",
        }
    ]

    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False, encoding="utf-8") as f:
        json.dump(test_people, f, ensure_ascii=False, indent=2)
        temp_path = Path(f.name)

    # Патчим пути к файлам
    with patch("app.core.people_store.PEOPLE", temp_path):
        yield temp_path, test_people

    # Удаляем временный файл
    if temp_path.exists():
        temp_path.unlink()


class TestUtilityFunctions:
    """Тесты утилитарных функций."""

    def test_validate_en_name(self):
        """Тест валидации английских имен."""
        assert _validate_en_name("Sasha Katanov") is True
        assert _validate_en_name("John Doe") is True
        assert _validate_en_name("Maria Garcia") is True
        assert _validate_en_name("Sasha Katanov123") is False
        assert _validate_en_name("Саша Катанов") is False
        assert _validate_en_name("Sasha-Katanov") is False
        assert _validate_en_name("") is False
        assert _validate_en_name("   ") is False

    def test_format_candidate_message(self):
        """Тест форматирования сообщения о кандидате."""
        candidate = {
            "alias": "Иван Петров",
            "freq": 5,
            "context": "Встреча с Иваном",
            "id": "abc12345",
            "source": "meeting",
        }

        message = _format_candidate_message(candidate, 1, 3)

        assert "Кандидат 1/3" in message
        assert "Иван Петров" in message
        assert "5" in message and "Частота" in message
        assert "Встреча с Иваном" in message
        assert "abc12345" in message

    def test_pick_next_candidate(self, temp_candidates_file):
        """Тест выбора следующего кандидата."""
        temp_path, test_candidates = temp_candidates_file

        candidate, index, total = _pick_next_candidate()

        assert candidate is not None
        assert candidate["alias"] == "Иван Петров"  # Самый частый
        assert index == 1
        assert total == 2

    def test_pick_next_candidate_empty(self):
        """Тест выбора кандидата при пустом списке."""
        with patch("app.bot.handlers_people.load_candidates_raw", return_value=[]):
            candidate, index, total = _pick_next_candidate()

            assert candidate is None
            assert index == 0
            assert total == 0


class TestPeopleMinerStart:
    """Тесты запуска people miner."""

    @pytest.mark.asyncio
    async def test_people_miner_start_with_candidates(
        self, mock_message, mock_fsm_context, temp_candidates_file
    ):
        """Тест запуска miner с кандидатами."""
        await people_miner_start(mock_message, mock_fsm_context)

        mock_fsm_context.set_state.assert_called_once()
        mock_message.answer.assert_called_once()

        # Проверяем, что сообщение содержит информацию о кандидате
        call_args = mock_message.answer.call_args
        assert "Иван Петров" in call_args[0][0]
        assert "5" in call_args[0][0] and "Частота" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_people_miner_start_no_candidates(self, mock_message, mock_fsm_context):
        """Тест запуска miner без кандидатов."""
        with patch("app.bot.handlers_people.load_candidates_raw", return_value=[]):
            await people_miner_start(mock_message, mock_fsm_context)

            mock_fsm_context.set_state.assert_called()
            mock_message.answer.assert_called_once()

            call_args = mock_message.answer.call_args
            assert "Кандидатов для обработки нет" in call_args[0][0]


class TestCallbackHandlers:
    """Тесты обработчиков callback запросов."""

    # Тест pm_next_handler удален, так как функция была удалена

    @pytest.mark.asyncio
    async def test_pm_delete_handler(self, mock_callback, mock_fsm_context, temp_candidates_file):
        """Тест удаления кандидата."""
        mock_callback.data = "pm_del:abc12345"

        await pm_delete_handler(mock_callback, mock_fsm_context)

        # Проверяем, что answer был вызван (может быть с разными сообщениями)
        mock_callback.answer.assert_called()
        mock_callback.message.edit_text.assert_called()

    @pytest.mark.asyncio
    async def test_pm_skip_handler(self, mock_callback, mock_fsm_context):
        """Тест пропуска кандидата."""
        mock_callback.data = "pm_skip:abc12345"

        await pm_skip_handler(mock_callback, mock_fsm_context)

        # Проверяем, что answer был вызван
        mock_callback.answer.assert_called()

    @pytest.mark.asyncio
    async def test_pm_add_handler(self, mock_callback, mock_fsm_context, temp_candidates_file):
        """Тест добавления кандидата."""
        mock_callback.data = "pm_add:abc12345"

        await pm_add_handler(mock_callback, mock_fsm_context)

        mock_fsm_context.update_data.assert_called_once()
        mock_fsm_context.set_state.assert_called_once()
        mock_callback.message.answer.assert_called_once()
        mock_callback.answer.assert_called_once()

        call_args = mock_callback.message.answer.call_args
        assert "Введите каноническое английское имя" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_pm_stats_handler(self, mock_callback, temp_candidates_file):
        """Тест показа статистики."""
        mock_callback.data = "pm_stats"

        with patch("app.bot.handlers_people.load_people_raw", return_value=[]):
            await pm_stats_handler(mock_callback, mock_fsm_context)

            mock_callback.answer.assert_called_once()
            mock_callback.message.answer.assert_called_once()

            call_args = mock_callback.message.answer.call_args
            assert "Статистика People Miner" in call_args[0][0]


class TestSetEnNameHandler:
    """Тесты обработчика ввода английского имени."""

    @pytest.mark.asyncio
    async def test_set_en_name_valid(self, mock_message, mock_fsm_context, temp_people_file):
        """Тест ввода корректного английского имени."""
        mock_message.text = "Ivan Petrov"

        candidate_data = {
            "id": "abc12345",
            "alias": "Иван Петров",
            "freq": 5,
            "context": "Встреча с Иваном",
        }
        mock_fsm_context.get_data.return_value = {"pending_candidate": candidate_data}

        with patch("app.bot.handlers_people.load_candidates_raw", return_value=[candidate_data]):
            with patch("app.bot.handlers_people.people_miner_start") as mock_start:
                await set_en_name_handler(mock_message, mock_fsm_context)

                mock_message.answer.assert_called()
                mock_fsm_context.set_state.assert_called()
                mock_start.assert_called_once()

    @pytest.mark.asyncio
    async def test_set_en_name_invalid(self, mock_message, mock_fsm_context):
        """Тест ввода некорректного имени."""
        mock_message.text = "Иван123"

        candidate_data = {"id": "abc12345", "alias": "Иван Петров"}
        mock_fsm_context.get_data.return_value = {"pending_candidate": candidate_data}

        await set_en_name_handler(mock_message, mock_fsm_context)

        mock_message.answer.assert_called_once()
        call_args = mock_message.answer.call_args
        assert "Некорректное имя" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_set_en_name_no_candidate(self, mock_message, mock_fsm_context):
        """Тест ввода имени без кандидата в состоянии."""
        mock_message.text = "Ivan Petrov"
        mock_fsm_context.get_data.return_value = {}

        await set_en_name_handler(mock_message, mock_fsm_context)

        mock_message.answer.assert_called_once()
        call_args = mock_message.answer.call_args
        assert "Ошибка ввода" in call_args[0][0]


class TestStatsHandlers:
    """Тесты обработчиков статистики."""

    @pytest.mark.asyncio
    async def test_people_stats_handler(self, mock_message, temp_candidates_file):
        """Тест показа общей статистики."""
        with patch("app.bot.handlers_people.load_people_raw", return_value=[]):
            await people_stats_handler(mock_message)

            mock_message.answer.assert_called_once()
            call_args = mock_message.answer.call_args
            assert "Статистика людей" in call_args[0][0]
            assert "2" in call_args[0][0] and "Кандидаты" in call_args[0][0]

    @pytest.mark.asyncio
    async def test_people_reset_handler(self, mock_message, mock_fsm_context):
        """Тест сброса состояния."""
        await people_reset_handler(mock_message, mock_fsm_context)

        mock_fsm_context.clear.assert_called_once()
        mock_message.answer.assert_called_once()
        call_args = mock_message.answer.call_args
        assert "Состояние сброшено" in call_args[0][0]


class TestIntegration:
    """Интеграционные тесты."""

    @pytest.mark.asyncio
    async def test_full_workflow(
        self, mock_message, mock_fsm_context, temp_candidates_file, temp_people_file
    ):
        """Тест полного workflow добавления кандидата."""
        # 1. Запускаем miner
        await people_miner_start(mock_message, mock_fsm_context)

        # 2. Симулируем добавление кандидата
        mock_message.text = "Ivan Petrov"
        candidate_data = {
            "id": "abc12345",
            "alias": "Иван Петров",
            "freq": 5,
            "context": "Встреча с Иваном",
        }
        mock_fsm_context.get_data.return_value = {"pending_candidate": candidate_data}

        with patch("app.bot.handlers_people.load_candidates_raw", return_value=[candidate_data]):
            with patch("app.bot.handlers_people.people_miner_start") as mock_start:
                await set_en_name_handler(mock_message, mock_fsm_context)

                # Проверяем, что кандидат был добавлен и miner перезапущен
                mock_start.assert_called_once()
                mock_message.answer.assert_called()
