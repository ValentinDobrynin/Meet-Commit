"""Обработчики команд для быстрых запросов к коммитам."""

from __future__ import annotations

import logging
import time
from typing import Any

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, Message

from app.bot.formatters import format_commit_card, format_error_card, format_success_card
from app.bot.keyboards import (
    build_commit_action_keyboard,
    build_pagination_keyboard,
    build_query_help_keyboard,
)
from app.gateways.notion_commits import (
    query_commits_by_assignee,
    query_commits_by_tag,
    query_commits_due_today,
    query_commits_due_within,
    query_commits_mine,
    query_commits_mine_active,
    query_commits_recent,
    query_commits_theirs,
    update_commit_status,
)

logger = logging.getLogger(__name__)

router = Router()

# Rate limiting (простая реализация)
_last_query_time: dict[int, float] = {}
RATE_LIMIT_SECONDS = 2


def _check_rate_limit(user_id: int) -> bool:
    """Проверяет rate limit для пользователя."""
    now = time.time()
    last_time = _last_query_time.get(user_id, 0)

    if now - last_time < RATE_LIMIT_SECONDS:
        return False

    _last_query_time[user_id] = now
    return True


async def _send_commits_list(
    message: Message,
    commits: list[dict[str, Any]],
    query_type: str,
    query_description: str,
    *,
    extra_params: str = "",
    show_actions: bool = True,
) -> None:
    """
    Отправляет список коммитов с красивым форматированием.

    Args:
        message: Сообщение для ответа
        commits: Список коммитов
        query_type: Тип запроса для пагинации
        query_description: Описание запроса для заголовка
        extra_params: Дополнительные параметры (например, тег)
        show_actions: Показывать ли кнопки действий
    """
    if not commits:
        await message.answer(
            f"📭 <b>{query_description}</b>\n\n" "💡 <i>Ничего не найдено</i>", parse_mode="HTML"
        )
        return

    # Заголовок с количеством и пагинацией
    header_text = f"📋 <b>{query_description}</b>\n\n📊 <b>Найдено:</b> {len(commits)} коммитов"

    # Простая пагинация (v1 - без настоящих страниц)
    current_page = 1
    total_pages = 1

    pagination_kb = build_pagination_keyboard(
        query_type, current_page, total_pages, len(commits), extra_params=extra_params
    )

    await message.answer(header_text, reply_markup=pagination_kb, parse_mode="HTML")

    # Отправляем каждый коммит как отдельную карточку
    for commit in commits:
        try:
            # Используем красивое форматирование
            card_text = format_commit_card(commit)

            # Добавляем кнопки действий только для активных коммитов
            reply_markup = None
            commit_status = commit.get("status", "open")
            if show_actions and commit_status not in ("done", "dropped", "cancelled"):
                reply_markup = build_commit_action_keyboard(commit.get("id", ""))

            await message.answer(card_text, parse_mode="HTML", reply_markup=reply_markup)

        except Exception as e:
            logger.error(f"Error formatting commit {commit.get('id', 'unknown')}: {e}")
            continue


@router.message(Command("commits"))
async def cmd_commits(message: Message) -> None:
    """Показывает последние коммиты."""
    user_id = message.from_user.id if message.from_user else 0

    if not _check_rate_limit(user_id):
        await message.answer("⏳ Подождите немного перед следующим запросом")
        return

    try:
        commits = query_commits_recent(limit=10)
        await _send_commits_list(message, commits, "recent", "Последние коммиты")

        logger.info(f"User {user_id} queried recent commits: {len(commits)} found")

    except Exception as e:
        logger.error(f"Error in cmd_commits: {e}")
        error_message = format_error_card("Ошибка получения коммитов", str(e))
        await message.answer(error_message, parse_mode="HTML")


@router.message(Command("mine"))
async def cmd_mine(message: Message) -> None:
    """Показывает мои задачи (все: активные + выполненные)."""
    user_id = message.from_user.id if message.from_user else 0

    if not _check_rate_limit(user_id):
        await message.answer("⏳ Подождите немного перед следующим запросом")
        return

    try:
        commits = query_commits_mine(limit=10)
        await _send_commits_list(message, commits, "mine", "Мои задачи (все)")

        logger.info(f"User {user_id} queried mine commits: {len(commits)} found")

    except Exception as e:
        logger.error(f"Error in cmd_mine: {e}")
        error_message = format_error_card("Ошибка получения моих задач", str(e))
        await message.answer(error_message, parse_mode="HTML")


@router.message(Command("mine_active"))
async def cmd_mine_active(message: Message) -> None:
    """Показывает только активные мои задачи."""
    user_id = message.from_user.id if message.from_user else 0

    if not _check_rate_limit(user_id):
        await message.answer("⏳ Подождите немного перед следующим запросом")
        return

    try:
        commits = query_commits_mine_active(limit=10)
        await _send_commits_list(message, commits, "mine_active", "Мои активные задачи")

        logger.info(f"User {user_id} queried mine_active commits: {len(commits)} found")

    except Exception as e:
        logger.error(f"Error in cmd_mine_active: {e}")
        error_message = format_error_card("Ошибка получения активных задач", str(e))
        await message.answer(error_message, parse_mode="HTML")


@router.message(Command("theirs"))
async def cmd_theirs(message: Message) -> None:
    """Показывает чужие коммиты (direction=theirs)."""
    user_id = message.from_user.id if message.from_user else 0

    if not _check_rate_limit(user_id):
        await message.answer("⏳ Подождите немного перед следующим запросом")
        return

    try:
        commits = query_commits_theirs(limit=10)
        await _send_commits_list(message, commits, "theirs", "Чужие задачи")

        logger.info(f"User {user_id} queried theirs commits: {len(commits)} found")

    except Exception as e:
        logger.error(f"Error in cmd_theirs: {e}")
        error_message = format_error_card("Ошибка получения чужих задач", str(e))
        await message.answer(error_message, parse_mode="HTML")


@router.message(Command("due"))
async def cmd_due(message: Message) -> None:
    """Показывает коммиты с дедлайном в ближайшую неделю."""
    user_id = message.from_user.id if message.from_user else 0

    if not _check_rate_limit(user_id):
        await message.answer("⏳ Подождите немного перед следующим запросом")
        return

    try:
        commits = query_commits_due_within(days=7, limit=10)
        await _send_commits_list(message, commits, "due", "Дедлайны на неделю")

        logger.info(f"User {user_id} queried due commits: {len(commits)} found")

    except Exception as e:
        logger.error(f"Error in cmd_due: {e}")
        error_message = format_error_card("Ошибка получения дедлайнов", str(e))
        await message.answer(error_message, parse_mode="HTML")


@router.message(Command("today"))
async def cmd_today(message: Message) -> None:
    """Показывает коммиты с дедлайном сегодня."""
    user_id = message.from_user.id if message.from_user else 0

    if not _check_rate_limit(user_id):
        await message.answer("⏳ Подождите немного перед следующим запросом")
        return

    try:
        commits = query_commits_due_today(limit=10)
        await _send_commits_list(message, commits, "today", "Горящие задачи сегодня")

        logger.info(f"User {user_id} queried today commits: {len(commits)} found")

    except Exception as e:
        logger.error(f"Error in cmd_today: {e}")
        error_message = format_error_card("Ошибка получения задач на сегодня", str(e))
        await message.answer(error_message, parse_mode="HTML")


@router.message(Command("by_tag"))
async def cmd_by_tag(message: Message) -> None:
    """Показывает коммиты по тегу."""
    user_id = message.from_user.id if message.from_user else 0

    if not _check_rate_limit(user_id):
        await message.answer("⏳ Подождите немного перед следующим запросом")
        return

    # Парсим аргумент тега
    parts = (message.text or "").strip().split(maxsplit=1)
    if len(parts) < 2:
        help_text = (
            "🏷️ <b>Поиск по тегу</b>\n\n"
            "📝 <b>Использование:</b>\n"
            "<code>/by_tag Finance/IFRS</code>\n"
            "<code>/by_tag Topic/Meeting</code>\n"
            "<code>/by_tag People/John</code>\n\n"
            "💡 <i>Поддерживается частичное совпадение</i>"
        )
        await message.answer(help_text, reply_markup=build_query_help_keyboard(), parse_mode="HTML")
        return

    tag = parts[1].strip()

    try:
        commits = query_commits_by_tag(tag, limit=10)
        await _send_commits_list(
            message, commits, "by_tag", f"Коммиты с тегом '{tag}'", extra_params=tag
        )

        logger.info(f"User {user_id} queried commits by tag '{tag}': {len(commits)} found")

    except Exception as e:
        logger.error(f"Error in cmd_by_tag: {e}")
        error_message = format_error_card("Ошибка поиска по тегу", str(e))
        await message.answer(error_message, parse_mode="HTML")


@router.message(Command("by_assignee"))
async def cmd_by_assignee(message: Message) -> None:
    """Показывает коммиты по конкретному исполнителю."""
    user_id = message.from_user.id if message.from_user else 0

    if not _check_rate_limit(user_id):
        await message.answer("⏳ Подождите немного перед следующим запросом")
        return

    # Парсим аргумент имени исполнителя
    parts = (message.text or "").strip().split(maxsplit=1)
    if len(parts) < 2:
        help_text = (
            "👤 <b>Поиск по исполнителю</b>\n\n"
            "📝 <b>Использование:</b>\n"
            "<code>/by_assignee Valya</code>\n"
            "<code>/by_assignee John Doe</code>\n"
            "<code>/by_assignee Nodari</code>\n\n"
            "💡 <i>Поддерживаются все алиасы из people.json</i>\n"
            "🔍 <i>Показывает все коммиты (активные + выполненные)</i>"
        )
        await message.answer(help_text, parse_mode="HTML")
        return

    assignee_name = parts[1].strip()

    try:
        commits = query_commits_by_assignee(assignee_name, limit=10)
        await _send_commits_list(
            message,
            commits,
            "by_assignee",
            f"Задачи исполнителя '{assignee_name}'",
            extra_params=assignee_name,
        )

        logger.info(
            f"User {user_id} queried commits by assignee '{assignee_name}': {len(commits)} found"
        )

    except Exception as e:
        logger.error(f"Error in cmd_by_assignee: {e}")
        error_message = format_error_card("Ошибка поиска по исполнителю", str(e))
        await message.answer(error_message, parse_mode="HTML")


@router.message(Command("queries_help"))
async def cmd_queries_help(message: Message) -> None:
    """Показывает справку по командам запросов."""
    help_text = (
        "🔍 <b>Команды быстрых запросов</b>\n\n"
        "📋 <b>Основные команды:</b>\n"
        "• <code>/commits</code> - последние 10 коммитов\n"
        "• <code>/mine</code> - мои задачи (все: активные + выполненные)\n"
        "• <code>/mine_active</code> - только активные мои задачи\n"
        "• <code>/theirs</code> - чужие задачи (direction=theirs)\n"
        "• <code>/due</code> - дедлайны ближайшей недели\n"
        "• <code>/today</code> - что горит сегодня\n"
        "• <code>/by_tag &lt;тег&gt;</code> - фильтр по тегу\n"
        "• <code>/by_assignee &lt;имя&gt;</code> - задачи конкретного исполнителя\n\n"
        "🏷️ <b>Примеры поиска по тегам:</b>\n"
        "• <code>/by_tag Finance/IFRS</code>\n"
        "• <code>/by_tag Topic/Meeting</code>\n"
        "• <code>/by_tag People/John</code>\n\n"
        "👤 <b>Примеры поиска по исполнителю:</b>\n"
        "• <code>/by_assignee Valya</code>\n"
        "• <code>/by_assignee John Doe</code>\n"
        "• <code>/by_assignee Nodari</code>\n\n"
        "⚡ <b>Особенности:</b>\n"
        "• Результаты обновляются в реальном времени\n"
        "• Поддерживается частичное совпадение тегов\n"
        "• Rate limit: 1 запрос в 2 секунды\n"
        "• Быстрые действия прямо из списка"
    )

    await message.answer(help_text, reply_markup=build_query_help_keyboard(), parse_mode="HTML")


# ====== CALLBACK HANDLERS FOR PAGINATION ======


@router.callback_query(F.data.startswith("commits:"))
async def handle_commits_pagination(callback: CallbackQuery) -> None:
    """Обрабатывает пагинацию и повторные запросы коммитов."""
    await callback.answer()

    if not callback.data or not callback.message:
        return

    user_id = callback.from_user.id if callback.from_user else 0

    # Парсим callback data: commits:query_type:page[:extra_params]
    parts = callback.data.split(":", 3)
    if len(parts) < 3:
        return

    query_type = parts[1]
    try:
        page = int(parts[2])
    except ValueError:
        page = 1

    extra_params = parts[3] if len(parts) > 3 else ""

    # Rate limiting для callback запросов
    if not _check_rate_limit(user_id):
        await callback.answer("⏳ Подождите немного", show_alert=True)
        return

    try:
        # Выполняем соответствующий запрос
        commits = []
        query_description = ""

        if query_type == "recent":
            commits = query_commits_recent(limit=10)
            query_description = "Последние коммиты"
        elif query_type == "mine":
            commits = query_commits_mine(limit=10)
            query_description = "Мои задачи (все)"
        elif query_type == "mine_active":
            commits = query_commits_mine_active(limit=10)
            query_description = "Мои активные задачи"
        elif query_type == "theirs":
            commits = query_commits_theirs(limit=10)
            query_description = "Чужие задачи"
        elif query_type == "due":
            commits = query_commits_due_within(days=7, limit=10)
            query_description = "Дедлайны на неделю"
        elif query_type == "today":
            commits = query_commits_due_today(limit=10)
            query_description = "Горящие задачи сегодня"
        elif query_type == "by_tag" and extra_params:
            commits = query_commits_by_tag(extra_params, limit=10)
            query_description = f"Коммиты с тегом '{extra_params}'"
        elif query_type == "by_assignee" and extra_params:
            commits = query_commits_by_assignee(extra_params, limit=10)
            query_description = f"Задачи исполнителя '{extra_params}'"
        elif query_type == "help_tag":
            help_text = (
                "🏷️ <b>Поиск по тегу</b>\n\n"
                "📝 <b>Введите команду:</b>\n"
                "<code>/by_tag Finance/IFRS</code>\n\n"
                "💡 <i>Или выберите быстрый запрос:</i>"
            )
            await callback.message.edit_text(  # type: ignore[union-attr]
                help_text, reply_markup=build_query_help_keyboard(), parse_mode="HTML"
            )
            return
        else:
            await callback.answer("❌ Неизвестный тип запроса", show_alert=True)
            return

        # Обновляем существующее сообщение
        if not commits:
            await callback.message.edit_text(  # type: ignore[union-attr]
                f"📭 <b>{query_description}</b>\n\n" "💡 <i>Ничего не найдено</i>",
                parse_mode="HTML",
            )
            return

        # Обновляем заголовок
        header_text = f"📋 <b>{query_description}</b>\n\n📊 <b>Найдено:</b> {len(commits)} коммитов"

        pagination_kb = build_pagination_keyboard(
            query_type,
            page,
            1,  # total_pages
            len(commits),
            extra_params=extra_params,
        )

        await callback.message.edit_text(header_text, reply_markup=pagination_kb, parse_mode="HTML")  # type: ignore[union-attr]

        # Отправляем обновленные карточки (в реальной пагинации здесь была бы логика удаления старых)
        for commit in commits[:5]:  # Показываем первые 5 для экономии места
            try:
                card_text = format_commit_card(commit)
                reply_markup = None
                commit_status = commit.get("status", "open")
                if commit_status not in ("done", "dropped", "cancelled"):
                    reply_markup = build_commit_action_keyboard(commit.get("id", ""))

                await callback.message.answer(
                    card_text, parse_mode="HTML", reply_markup=reply_markup
                )

            except Exception as e:
                logger.error(f"Error formatting commit in callback: {e}")
                continue

        logger.info(f"User {user_id} paginated {query_type} commits: {len(commits)} found")

    except Exception as e:
        logger.error(f"Error in handle_commits_pagination: {e}")
        await callback.answer("❌ Ошибка при обновлении", show_alert=True)


# ====== QUICK ACTIONS FOR COMMITS ======


@router.callback_query(F.data.startswith("commit_action:"))
async def handle_commit_action(callback: CallbackQuery) -> None:
    """Обрабатывает быстрые действия с коммитами."""
    await callback.answer()

    if not callback.data:
        return

    # Парсим callback data: commit_action:action:commit_id
    parts = callback.data.split(":", 2)
    if len(parts) < 3:
        return

    action = parts[1]
    commit_id = parts[2]

    user_id = callback.from_user.id if callback.from_user else 0

    try:
        if action == "done":
            # Обновляем статус в Notion
            if update_commit_status(commit_id, "done"):
                success_message = format_success_card(
                    "Коммит помечен как выполненный",
                    {"commit_id": commit_id[:8], "status": "✅ done"},
                )
                await callback.message.edit_reply_markup(reply_markup=None)  # type: ignore[union-attr]
                await callback.message.answer(success_message, parse_mode="HTML")  # type: ignore[union-attr]
                logger.info(f"User {user_id} marked commit {commit_id} as done")
            else:
                await callback.answer("❌ Ошибка при обновлении статуса в Notion", show_alert=True)

        elif action == "drop":
            # Обновляем статус в Notion
            if update_commit_status(commit_id, "dropped"):
                success_message = format_success_card(
                    "Коммит отменен", {"commit_id": commit_id[:8], "status": "❌ dropped"}
                )
                await callback.message.edit_reply_markup(reply_markup=None)  # type: ignore[union-attr]
                await callback.message.answer(success_message, parse_mode="HTML")  # type: ignore[union-attr]
                logger.info(f"User {user_id} dropped commit {commit_id}")
            else:
                await callback.answer("❌ Ошибка при обновлении статуса в Notion", show_alert=True)

        else:
            await callback.answer("❌ Неизвестное действие", show_alert=True)

    except Exception as e:
        logger.error(f"Error in handle_commit_action: {e}")
        await callback.answer("❌ Ошибка при выполнении действия", show_alert=True)
