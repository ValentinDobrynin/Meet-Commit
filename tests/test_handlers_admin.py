"""Тесты для административных команд бота."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from aiogram.types import Message, User

from app.bot.handlers_admin import (
    admin_help_handler,
    clear_cache_handler,
    reload_tags_handler,
    tags_stats_handler,
)


@pytest.fixture
def mock_message():
    """Фикстура для создания mock сообщения."""
    message = AsyncMock(spec=Message)
    message.from_user = MagicMock(spec=User)
    message.from_user.id = 123456789
    message.answer = AsyncMock()
    return message


@pytest.fixture(autouse=True)
def mock_is_admin():
    """Автоматически мокает _is_admin для всех тестов."""
    with patch("app.bot.handlers_admin._is_admin", return_value=True):
        yield


class TestReloadTagsHandler:
    """Тесты для команды /reload_tags."""

    @pytest.mark.asyncio
    async def test_reload_tags_success(self, mock_message):
        """Тест успешной перезагрузки правил."""
        with patch("app.bot.handlers_admin.reload_tags_rules", return_value=12):
            await reload_tags_handler(mock_message)

            mock_message.answer.assert_called_once()
            call_args = mock_message.answer.call_args[0][0]
            assert "♻️" in call_args
            assert "12" in call_args and "категорий" in call_args
            assert "LRU кэш очищен" in call_args

    @pytest.mark.asyncio
    async def test_reload_tags_error(self, mock_message):
        """Тест обработки ошибки при перезагрузке."""
        with patch("app.bot.handlers_admin.reload_tags_rules", side_effect=Exception("YAML error")):
            await reload_tags_handler(mock_message)

            mock_message.answer.assert_called_once()
            call_args = mock_message.answer.call_args[0][0]
            assert "❌" in call_args
            assert "Ошибка перезагрузки" in call_args
            assert "YAML error" in call_args


class TestTagsStatsHandler:
    """Тесты для команды /tags_stats."""

    @pytest.mark.asyncio
    async def test_tags_stats_success(self, mock_message):
        """Тест успешного получения статистики."""
        mock_stats = {
            "current_mode": "both",
            "valid_modes": ["v0", "v1", "both"],
            "stats": {
                "calls_by_mode": {"v0": 5, "v1": 3, "both": 10},
                "calls_by_kind": {"meeting": 15, "commit": 3},
            },
            "cache_info": {
                "hits": 45,
                "misses": 12,
                "maxsize": 256,
                "currsize": 8,
            },
            "mapping_rules": 18,
            "v1_stats": {
                "total_rules": 21,
                "total_patterns": 143,
                "total_excludes": 5,
                "average_weight": 1.1,
            },
        }

        with patch("app.bot.handlers_admin.get_tagging_stats", return_value=mock_stats):
            await tags_stats_handler(mock_message)

            mock_message.answer.assert_called_once()
            call_args = mock_message.answer.call_args[0][0]
            assert "📊" in call_args
            assert "both" in call_args
            assert "45 hits" in call_args
            assert "18" in call_args  # mapping rules
            assert "21" in call_args  # total rules

    @pytest.mark.asyncio
    async def test_tags_stats_error(self, mock_message):
        """Тест обработки ошибки при получении статистики."""
        with patch(
            "app.bot.handlers_admin.get_tagging_stats", side_effect=Exception("Stats error")
        ):
            await tags_stats_handler(mock_message)

            mock_message.answer.assert_called_once()
            call_args = mock_message.answer.call_args[0][0]
            assert "❌" in call_args
            assert "Ошибка получения статистики" in call_args
            assert "Stats error" in call_args


class TestClearCacheHandler:
    """Тесты для команды /clear_cache."""

    @pytest.mark.asyncio
    async def test_clear_cache_success(self, mock_message):
        """Тест успешной очистки кэша."""
        with patch("app.bot.handlers_admin.clear_cache") as mock_clear:
            await clear_cache_handler(mock_message)

            mock_clear.assert_called_once()
            mock_message.answer.assert_called_once()
            call_args = mock_message.answer.call_args[0][0]
            assert "🧹" in call_args
            assert "Кэш очищен" in call_args

    @pytest.mark.asyncio
    async def test_clear_cache_error(self, mock_message):
        """Тест обработки ошибки при очистке кэша."""
        with patch("app.bot.handlers_admin.clear_cache", side_effect=Exception("Cache error")):
            await clear_cache_handler(mock_message)

            mock_message.answer.assert_called_once()
            call_args = mock_message.answer.call_args[0][0]
            assert "❌" in call_args
            assert "Ошибка очистки кэша" in call_args
            assert "Cache error" in call_args


class TestAdminHelpHandler:
    """Тесты для команды /admin_help."""

    @pytest.mark.asyncio
    async def test_admin_help_success(self, mock_message):
        """Тест показа справки по админ командам."""
        await admin_help_handler(mock_message)

        mock_message.answer.assert_called_once()
        call_args = mock_message.answer.call_args[0][0]
        assert "🔧" in call_args
        assert "/reload_tags" in call_args
        assert "/tags_stats" in call_args
        assert "/clear_cache" in call_args
        assert "/admin_help" in call_args


class TestIntegration:
    """Интеграционные тесты для admin команд."""

    @pytest.mark.asyncio
    async def test_admin_commands_workflow(self, mock_message):
        """Тест полного workflow админских команд."""
        # 1. Показываем справку
        await admin_help_handler(mock_message)
        assert mock_message.answer.call_count == 1

        # 2. Получаем статистику
        mock_stats = {
            "current_mode": "both",
            "stats": {"calls_by_mode": {}, "calls_by_kind": {}},
            "cache_info": {"hits": 0, "misses": 0, "maxsize": 256, "currsize": 0},
            "mapping_rules": 18,
        }

        with patch("app.bot.handlers_admin.get_tagging_stats", return_value=mock_stats):
            await tags_stats_handler(mock_message)
            assert mock_message.answer.call_count == 2

        # 3. Очищаем кэш
        with patch("app.bot.handlers_admin.clear_cache"):
            await clear_cache_handler(mock_message)
            assert mock_message.answer.call_count == 3

        # 4. Перезагружаем правила
        with patch("app.bot.handlers_admin.reload_tags_rules", return_value=15):
            await reload_tags_handler(mock_message)
            assert mock_message.answer.call_count == 4

            # Проверяем, что сообщение содержит количество категорий
            last_call_args = mock_message.answer.call_args_list[-1][0][0]
            assert "15" in last_call_args and "категорий" in last_call_args
