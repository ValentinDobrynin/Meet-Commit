"""Модуль для хранения и управления активными пользователями бота."""

from __future__ import annotations

import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Путь к файлу с пользователями
USERS_FILE = Path(__file__).resolve().parent.parent / "dictionaries" / "active_users.json"


def _load_users_data() -> dict[str, Any]:
    """Загружает данные пользователей из JSON файла."""
    if not USERS_FILE.exists():
        return {"active_users": []}

    try:
        with open(USERS_FILE, encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {"active_users": []}
    except (json.JSONDecodeError, OSError) as e:
        logger.error(f"Failed to load users data: {e}")
        return {"active_users": []}


def _save_users_data(data: dict[str, Any]) -> None:
    """Сохраняет данные пользователей в JSON файл."""
    try:
        USERS_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(USERS_FILE, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        logger.debug(f"Saved users data to {USERS_FILE}")
    except OSError as e:
        logger.error(f"Failed to save users data: {e}")
        raise


def add_user(chat_id: int, username: str | None = None, first_name: str | None = None) -> bool:
    """
    Добавляет пользователя в список активных или обновляет время последней активности.

    Args:
        chat_id: ID чата пользователя
        username: Имя пользователя (может быть None)
        first_name: Имя пользователя (может быть None)

    Returns:
        True если пользователь был добавлен, False если уже существовал
    """
    data = _load_users_data()
    users = data.get("active_users", [])

    # Ищем существующего пользователя
    for user in users:
        if user.get("chat_id") == chat_id:
            # Обновляем данные существующего пользователя
            user["last_activity"] = datetime.now().isoformat()
            if username:
                user["username"] = username
            if first_name:
                user["first_name"] = first_name
            _save_users_data(data)
            logger.debug(f"Updated existing user {chat_id}")
            return False

    # Добавляем нового пользователя
    new_user = {
        "chat_id": chat_id,
        "username": username,
        "first_name": first_name,
        "first_seen": datetime.now().isoformat(),
        "last_activity": datetime.now().isoformat(),
    }
    users.append(new_user)
    data["active_users"] = users
    _save_users_data(data)

    logger.info(f"Added new user {chat_id} (username: {username}, name: {first_name})")
    return True


def get_all_active_users() -> list[dict[str, Any]]:
    """
    Возвращает список всех активных пользователей.

    Returns:
        Список словарей с данными пользователей
    """
    data = _load_users_data()
    users = data.get("active_users", [])
    logger.debug(f"Retrieved {len(users)} active users")
    # Убеждаемся, что возвращаем правильный тип
    return users if isinstance(users, list) else []


def get_user_chat_ids() -> list[int]:
    """
    Возвращает список chat_id всех активных пользователей.

    Returns:
        Список chat_id для отправки сообщений
    """
    users = get_all_active_users()
    chat_ids = [user["chat_id"] for user in users if "chat_id" in user]
    logger.debug(f"Retrieved {len(chat_ids)} chat IDs")
    return chat_ids


def get_users_count() -> int:
    """
    Возвращает количество активных пользователей.

    Returns:
        Количество пользователей
    """
    return len(get_all_active_users())


def remove_user(chat_id: int) -> bool:
    """
    Удаляет пользователя из списка активных.

    Args:
        chat_id: ID чата пользователя для удаления

    Returns:
        True если пользователь был удален, False если не найден
    """
    data = _load_users_data()
    users = data.get("active_users", [])

    original_count = len(users)
    users = [user for user in users if user.get("chat_id") != chat_id]

    if len(users) < original_count:
        data["active_users"] = users
        _save_users_data(data)
        logger.info(f"Removed user {chat_id}")
        return True

    logger.debug(f"User {chat_id} not found for removal")
    return False


def cleanup_old_users(days: int = 30) -> int:
    """
    Удаляет пользователей, неактивных более указанного количества дней.

    Args:
        days: Количество дней неактивности для удаления

    Returns:
        Количество удаленных пользователей
    """
    from datetime import timedelta

    data = _load_users_data()
    users = data.get("active_users", [])
    cutoff_date = datetime.now() - timedelta(days=days)

    active_users = []
    removed_count = 0

    for user in users:
        try:
            last_activity = datetime.fromisoformat(user.get("last_activity", ""))
            if last_activity > cutoff_date:
                active_users.append(user)
            else:
                removed_count += 1
        except (ValueError, TypeError):
            # Если дата некорректна, оставляем пользователя
            active_users.append(user)

    if removed_count > 0:
        data["active_users"] = active_users
        _save_users_data(data)
        logger.info(f"Cleaned up {removed_count} inactive users (>{days} days)")

    return removed_count
