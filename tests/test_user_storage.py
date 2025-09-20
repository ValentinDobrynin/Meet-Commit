"""Тесты для модуля user_storage."""

import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

from app.bot.user_storage import (
    add_user,
    cleanup_old_users,
    get_all_active_users,
    get_user_chat_ids,
    get_users_count,
    remove_user,
)


@pytest.fixture
def temp_users_file():
    """Создает временный файл для тестов."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        temp_path = Path(f.name)

    # Патчим путь к файлу пользователей
    with patch("app.bot.user_storage.USERS_FILE", temp_path):
        yield temp_path

    # Удаляем временный файл
    if temp_path.exists():
        temp_path.unlink()


class TestUserStorage:
    """Тесты для системы хранения пользователей."""

    def test_add_new_user(self, temp_users_file):
        """Тест добавления нового пользователя."""
        chat_id = 123456789
        username = "testuser"
        first_name = "Test"

        # Добавляем нового пользователя
        is_new = add_user(chat_id, username, first_name)

        assert is_new is True

        # Проверяем, что пользователь сохранился
        users = get_all_active_users()
        assert len(users) == 1

        user = users[0]
        assert user["chat_id"] == chat_id
        assert user["username"] == username
        assert user["first_name"] == first_name
        assert "first_seen" in user
        assert "last_activity" in user

    def test_update_existing_user(self, temp_users_file):
        """Тест обновления существующего пользователя."""
        chat_id = 123456789

        # Добавляем пользователя
        add_user(chat_id, "oldname", "OldFirst")

        # Обновляем пользователя
        is_new = add_user(chat_id, "newname", "NewFirst")

        assert is_new is False

        # Проверяем, что данные обновились
        users = get_all_active_users()
        assert len(users) == 1

        user = users[0]
        assert user["chat_id"] == chat_id
        assert user["username"] == "newname"
        assert user["first_name"] == "NewFirst"

    def test_get_user_chat_ids(self, temp_users_file):
        """Тест получения списка chat_id."""
        # Добавляем несколько пользователей
        add_user(111, "user1", "First1")
        add_user(222, "user2", "First2")
        add_user(333, "user3", "First3")

        chat_ids = get_user_chat_ids()

        assert len(chat_ids) == 3
        assert 111 in chat_ids
        assert 222 in chat_ids
        assert 333 in chat_ids

    def test_get_users_count(self, temp_users_file):
        """Тест подсчета пользователей."""
        assert get_users_count() == 0

        add_user(111, "user1", "First1")
        assert get_users_count() == 1

        add_user(222, "user2", "First2")
        assert get_users_count() == 2

    def test_remove_user(self, temp_users_file):
        """Тест удаления пользователя."""
        chat_id = 123456789

        # Добавляем пользователя
        add_user(chat_id, "testuser", "Test")
        assert get_users_count() == 1

        # Удаляем пользователя
        removed = remove_user(chat_id)
        assert removed is True
        assert get_users_count() == 0

        # Пытаемся удалить несуществующего пользователя
        removed = remove_user(999999)
        assert removed is False

    def test_cleanup_old_users(self, temp_users_file):
        """Тест очистки старых пользователей."""
        # Создаем пользователей с разными датами активности
        old_date = (datetime.now() - timedelta(days=40)).isoformat()
        recent_date = (datetime.now() - timedelta(days=10)).isoformat()

        # Добавляем пользователей
        add_user(111, "user1", "First1")
        add_user(222, "user2", "First2")

        # Вручную устанавливаем старую дату для первого пользователя
        users = get_all_active_users()
        users[0]["last_activity"] = old_date
        users[1]["last_activity"] = recent_date

        # Сохраняем измененные данные
        data = {"active_users": users}
        with open(temp_users_file, "w", encoding="utf-8") as f:
            json.dump(data, f)

        # Очищаем пользователей старше 30 дней
        removed_count = cleanup_old_users(days=30)

        assert removed_count == 1
        assert get_users_count() == 1

        # Проверяем, что остался только недавний пользователь
        remaining_users = get_all_active_users()
        assert len(remaining_users) == 1
        assert remaining_users[0]["chat_id"] == 222

    def test_empty_file_handling(self, temp_users_file):
        """Тест обработки пустого/несуществующего файла."""
        # Удаляем файл
        temp_users_file.unlink()

        # Должны получить пустой список
        users = get_all_active_users()
        assert users == []
        assert get_users_count() == 0
        assert get_user_chat_ids() == []

        # Добавление пользователя должно создать файл
        add_user(123, "test", "Test")
        assert temp_users_file.exists()
        assert get_users_count() == 1

    def test_invalid_json_handling(self, temp_users_file):
        """Тест обработки поврежденного JSON файла."""
        # Записываем некорректный JSON
        temp_users_file.write_text("invalid json content", encoding="utf-8")

        # Должны получить пустой список
        users = get_all_active_users()
        assert users == []

        # Добавление пользователя должно перезаписать файл
        add_user(123, "test", "Test")
        assert get_users_count() == 1
