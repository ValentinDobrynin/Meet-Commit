"""Тесты для контроля доступа к административным командам."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.bot.handlers_admin import _is_admin


class TestAdminAccessControl:
    """Тесты для проверки админского доступа."""

    def test_is_admin_with_admin_user(self):
        """Тест проверки админского доступа для админа."""
        # Создаем мок сообщения с админским ID
        message = MagicMock()
        message.from_user.id = 50929545

        # Мокаем _admin_ids_set
        with patch("app.settings._admin_ids_set", {50929545, 123456}):
            assert _is_admin(message) is True

    def test_is_admin_with_regular_user(self):
        """Тест проверки админского доступа для обычного пользователя."""
        # Создаем мок сообщения с обычным ID
        message = MagicMock()
        message.from_user.id = 999999

        # Мокаем _admin_ids_set
        with patch("app.settings._admin_ids_set", {50929545, 123456}):
            assert _is_admin(message) is False

    def test_is_admin_with_no_user(self):
        """Тест проверки админского доступа без пользователя."""
        # Создаем мок сообщения без пользователя
        message = MagicMock()
        message.from_user = None

        with patch("app.settings._admin_ids_set", {50929545, 123456}):
            assert _is_admin(message) is False

    @pytest.mark.asyncio
    async def test_admin_command_with_admin_user(self):
        """Тест выполнения админской команды админом."""
        from app.bot.handlers_admin import tags_stats_handler

        # Создаем мок сообщения от админа
        message = AsyncMock()
        message.from_user.id = 50929545
        message.answer = AsyncMock()

        # Мокаем функции
        with (
            patch("app.bot.handlers_admin._is_admin", return_value=True),
            patch(
                "app.bot.handlers_admin.get_tagging_stats",
                return_value={
                    "current_mode": "both",
                    "stats": {"calls_by_mode": {"both": 10}, "calls_by_kind": {"meeting": 5}},
                    "cache_info": {"hits": 8, "misses": 2, "currsize": 5, "maxsize": 100},
                    "mapping_rules": 15,
                    "tags_min_score": 0.8,
                },
            ),
        ):
            await tags_stats_handler(message)

            # Проверяем, что команда выполнилась (не было отказа в доступе)
            message.answer.assert_called_once()
            call_args = message.answer.call_args[0][0]
            assert "📊" in call_args
            assert "Статистика системы тегирования" in call_args

    @pytest.mark.asyncio
    async def test_admin_command_with_regular_user(self):
        """Тест выполнения админской команды обычным пользователем."""
        from app.bot.handlers_admin import tags_stats_handler

        # Создаем мок сообщения от обычного пользователя
        message = AsyncMock()
        message.from_user.id = 999999
        message.answer = AsyncMock()

        # Мокаем функции
        with patch("app.bot.handlers_admin._is_admin", return_value=False):
            await tags_stats_handler(message)

            # Проверяем, что был отказ в доступе
            message.answer.assert_called_once_with("❌ Команда доступна только администраторам")

    @pytest.mark.asyncio
    async def test_retag_command_with_admin_user(self):
        """Тест команды retag от админа."""
        from app.bot.handlers_admin import retag_handler

        # Создаем мок сообщения от админа
        message = AsyncMock()
        message.from_user.id = 50929545
        message.answer = AsyncMock()
        message.text = "/retag deadbeef12345678 dry-run"

        # Мокаем функции
        with (
            patch("app.bot.handlers_admin._is_admin", return_value=True),
            patch("app.gateways.notion_meetings.validate_meeting_access", return_value=True),
            patch(
                "app.gateways.notion_meetings.fetch_meeting_page",
                return_value={
                    "summary_md": "Test meeting about IFRS",
                    "current_tags": ["Business/Lavka"],
                },
            ),
            patch("app.core.tags.tag_text", return_value=["Finance/IFRS", "Business/Lavka"]),
        ):
            await retag_handler(message)

            # Проверяем, что команда выполнилась
            assert message.answer.call_count >= 1
            # Первый вызов - уведомление о начале
            first_call = message.answer.call_args_list[0][0][0]
            assert "🔍" in first_call and "dry-run" in first_call

    @pytest.mark.asyncio
    async def test_retag_command_with_regular_user(self):
        """Тест команды retag от обычного пользователя."""
        from app.bot.handlers_admin import retag_handler

        # Создаем мок сообщения от обычного пользователя
        message = AsyncMock()
        message.from_user.id = 999999
        message.answer = AsyncMock()
        message.text = "/retag deadbeef12345678"

        # Мокаем функции
        with patch("app.bot.handlers_admin._is_admin", return_value=False):
            await retag_handler(message)

            # Проверяем, что был отказ в доступе
            message.answer.assert_called_once_with("❌ Команда доступна только администраторам")

    @pytest.mark.asyncio
    async def test_tags_validate_command_with_admin_user(self):
        """Тест команды tags_validate от админа."""
        from app.bot.handlers_admin import tags_validate_handler

        # Создаем мок сообщения от админа
        message = AsyncMock()
        message.from_user.id = 50929545
        message.answer = AsyncMock()

        # Мокаем функции
        with (
            patch("app.bot.handlers_admin._is_admin", return_value=True),
            patch("app.bot.handlers_admin.validate_rules", return_value=[]),
        ):
            await tags_validate_handler(message)

            # Проверяем, что команда выполнилась
            message.answer.assert_called_once()
            call_args = message.answer.call_args[0][0]
            assert "✅" in call_args
            assert "YAML валидация пройдена" in call_args

    @pytest.mark.asyncio
    async def test_tags_validate_command_with_errors(self):
        """Тест команды tags_validate с ошибками в YAML."""
        from app.bot.handlers_admin import tags_validate_handler

        # Создаем мок сообщения от админа
        message = AsyncMock()
        message.from_user.id = 50929545
        message.answer = AsyncMock()

        # Мокаем функции с ошибками
        with (
            patch("app.bot.handlers_admin._is_admin", return_value=True),
            patch(
                "app.bot.handlers_admin.validate_rules",
                return_value=[
                    "Broken regex in tag Finance/IFRS",
                    "Empty patterns in tag Business/Test",
                ],
            ),
        ):
            await tags_validate_handler(message)

            # Проверяем, что команда выполнилась с ошибками
            message.answer.assert_called_once()
            call_args = message.answer.call_args[0][0]
            assert "❌" in call_args
            assert "Найдены ошибки в YAML" in call_args
            assert "Broken regex" in call_args

    @pytest.mark.asyncio
    async def test_admin_config_command(self):
        """Тест команды admin_config."""
        from app.bot.handlers_admin import admin_config_handler
        
        # Создаем мок сообщения от админа
        message = AsyncMock()
        message.from_user.id = 50929545
        message.answer = AsyncMock()
        
        # Мокаем функции
        mock_config = {
            "admin_ids": [50929545, 123456],
            "source": "APP_ADMIN_USER_IDS=50929545,123456",
            "count": 2,
            "env_file_exists": True,
            "recommended_setup": "Создайте .env файл с APP_ADMIN_USER_IDS=your_telegram_id"
        }
        
        with patch("app.bot.handlers_admin._is_admin", return_value=True), \
             patch("app.settings.get_admin_config_info", return_value=mock_config):
            
            await admin_config_handler(message)
            
            # Проверяем, что команда выполнилась
            message.answer.assert_called_once()
            call_args = message.answer.call_args[0][0]
            assert "🔧" in call_args
            assert "Настройки админских прав" in call_args
            assert "50929545" in call_args
            assert "APP_ADMIN_USER_IDS" in call_args
