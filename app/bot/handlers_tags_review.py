"""Обработчики для интерактивного ревью тегов встреч.

Позволяет пользователям интерактивно редактировать автоматически сгенерированные теги
через инлайн-кнопки сразу после создания встречи.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot.states.tags_review_states import TagsReviewStates
from app.gateways.notion_meetings import update_meeting_tags
from app.settings import _admin_ids_set, settings

logger = logging.getLogger(__name__)

router = Router()


async def _show_review_queue_after_tags(callback: CallbackQuery) -> None:
    """Показывает Review Queue после завершения ревью тегов."""
    try:
        from app.bot.formatters import format_review_card
        from app.bot.handlers_inline import build_review_item_kb
        from app.core.review_queue import list_open_reviews

        # Проверяем наличие элементов в Review Queue
        items = list_open_reviews(limit=5)

        if not items:
            # Если очереди нет, показываем главное меню
            from app.bot.handlers_inline import build_main_menu_kb

            await callback.message.answer(
                "🎯 <b>Что дальше?</b>", reply_markup=build_main_menu_kb()
            )
            return

        # Показываем заголовок с кнопкой "Confirm All"
        confirm_all_kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="✅ Confirm All", callback_data="review_confirm_all"),
                    InlineKeyboardButton(text="🔄 Обновить", callback_data="main_review"),
                ]
            ]
        )

        await callback.message.answer(
            f"📋 <b>Review Queue ({len(items)} элементов):</b>\n\n"
            f"💡 <i>Проверьте и подтвердите коммиты:</i>",
            reply_markup=confirm_all_kb,
        )

        # Показываем каждый элемент с кнопками
        for item in items:
            short_id = item["short_id"]
            formatted_card = format_review_card(item)

            await callback.message.answer(
                formatted_card, parse_mode="HTML", reply_markup=build_review_item_kb(short_id)
            )

        logger.info(f"Showed {len(items)} review items after tags review")

    except Exception as e:
        logger.error(f"Error showing review queue after tags: {e}")
        # Fallback к главному меню
        from app.bot.handlers_inline import build_main_menu_kb

        await callback.message.answer("🎯 <b>Что дальше?</b>", reply_markup=build_main_menu_kb())


@dataclass
class TagReviewSession:
    """Сессия интерактивного ревью тегов."""

    meeting_id: str
    owner_user_id: int
    started_at: float
    original_tags: list[str]
    working_tags: list[str]
    history: list[tuple[str, str]] = field(default_factory=list)  # (action, tag)

    @property
    def is_expired(self) -> bool:
        """Проверяет, истекла ли сессия."""
        return (time.time() - self.started_at) > settings.tags_review_ttl_sec

    def can_edit(self, user_id: int | None) -> bool:
        """Проверяет, может ли пользователь редактировать теги."""
        if user_id is None:
            return False
        return user_id == self.owner_user_id or user_id in _admin_ids_set

    def get_changes_summary(self) -> str:
        """Возвращает краткую сводку изменений."""
        added = [tag for tag in self.working_tags if tag not in self.original_tags]
        removed = [tag for tag in self.original_tags if tag not in self.working_tags]

        if not added and not removed:
            return "Изменений нет"

        summary = []
        if added:
            summary.append(f"+{len(added)} добавлено")
        if removed:
            summary.append(f"-{len(removed)} удалено")

        return ", ".join(summary)


def _build_tags_keyboard(session: TagReviewSession) -> InlineKeyboardMarkup:
    """Создает клавиатуру для ревью тегов."""
    rows = []

    # Показываем первые 8 тегов (чтобы не переполнить интерфейс)
    visible_tags = session.working_tags[:8]

    for i, tag in enumerate(visible_tags):
        # Делаем кнопку тега на всю ширину для лучшей читаемости
        display_tag = tag if len(tag) <= 45 else f"{tag[:42]}..."
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"❌ {i+1}. {display_tag}",
                    callback_data=f"tagrev:drop:{session.meeting_id}:{i}",
                ),
            ]
        )

    # Если тегов больше 8, показываем информацию
    if len(session.working_tags) > 8:
        rows.append(
            [
                InlineKeyboardButton(
                    text=f"📋 ... и еще {len(session.working_tags) - 8} тегов", callback_data="noop"
                )
            ]
        )

    # Управляющие кнопки
    control_row1 = [
        InlineKeyboardButton(
            text="✅ Принять все", callback_data=f"tagrev:accept:{session.meeting_id}"
        ),
        InlineKeyboardButton(
            text="🗑 Удалить все", callback_data=f"tagrev:clear:{session.meeting_id}"
        ),
    ]

    control_row2 = [
        InlineKeyboardButton(text="➕ Добавить", callback_data=f"tagrev:add:{session.meeting_id}"),
        InlineKeyboardButton(text="↩️ Отменить", callback_data=f"tagrev:undo:{session.meeting_id}"),
    ]

    control_row3 = [
        InlineKeyboardButton(
            text="💾 Сохранить", callback_data=f"tagrev:save:{session.meeting_id}"
        ),
        InlineKeyboardButton(
            text="❌ Отменить ревью", callback_data=f"tagrev:cancel:{session.meeting_id}"
        ),
    ]

    rows.extend([control_row1, control_row2, control_row3])

    return InlineKeyboardMarkup(inline_keyboard=rows)


def _format_tags_message(session: TagReviewSession) -> str:
    """Форматирует сообщение с тегами для ревью."""
    header = "🏷️ <b>Ревью тегов встречи</b>\n"
    header += f"📝 <b>ID:</b> <code>...{session.meeting_id[-8:]}</code>\n\n"

    if not session.working_tags:
        return header + "📋 <i>Тегов нет</i>\n\n💡 Используйте кнопку 'Добавить' для создания тегов"

    # Показываем первые 8 тегов
    visible_tags = session.working_tags[:8]
    tags_text = "\n".join(f"{i+1}. <code>{tag}</code>" for i, tag in enumerate(visible_tags))

    if len(session.working_tags) > 8:
        tags_text += f"\n<i>... и еще {len(session.working_tags) - 8} тегов</i>"

    # Показываем изменения
    changes = session.get_changes_summary()
    changes_text = f"\n\n📊 <b>Изменения:</b> {changes}" if changes != "Изменений нет" else ""

    return header + tags_text + changes_text


async def _get_session(
    callback: CallbackQuery, meeting_id: str, state: FSMContext
) -> TagReviewSession | None:
    """Получает и валидирует сессию ревью тегов."""
    data = await state.get_data()
    session_key = f"tagrev:{meeting_id}"
    session = data.get(session_key)  # type: ignore[assignment]

    if not session:
        await callback.answer("❌ Сессия ревью не найдена", show_alert=True)
        return None

    if session.is_expired:
        await callback.answer("⏰ Сессия ревью истекла", show_alert=True)
        # Очищаем устаревшую сессию
        await state.update_data(**{session_key: None})
        return None

    user_id = callback.from_user.id if callback.from_user else None
    if not session.can_edit(user_id):
        await callback.answer("❌ У вас нет прав на редактирование", show_alert=True)
        return None

    return session


async def _update_session(session: TagReviewSession, state: FSMContext) -> None:
    """Обновляет сессию в FSM."""
    session_key = f"tagrev:{session.meeting_id}"
    await state.update_data(**{session_key: session})  # type: ignore[arg-type]


async def start_tags_review(
    meeting_id: str, original_tags: list[str], user_id: int, message: Message, state: FSMContext
) -> None:
    """
    Запускает интерактивное ревью тегов.

    Args:
        meeting_id: ID встречи
        original_tags: Исходные автоматически сгенерированные теги
        user_id: ID пользователя, который загрузил встречу
        message: Сообщение для отправки интерфейса
        state: FSM контекст
    """
    if not settings.tags_review_enabled:
        logger.debug("Tags review disabled, skipping")
        return

    session = TagReviewSession(
        meeting_id=meeting_id,
        owner_user_id=user_id,
        started_at=time.time(),
        original_tags=list(original_tags),
        working_tags=list(original_tags),
    )

    session_key = f"tagrev:{meeting_id}"
    await state.update_data(**{session_key: session})
    await state.set_state(TagsReviewStates.reviewing)

    message_text = _format_tags_message(session)
    keyboard = _build_tags_keyboard(session)

    await message.answer(message_text, reply_markup=keyboard)
    logger.info(f"Started tags review for meeting {meeting_id} by user {user_id}")


@router.callback_query(F.data.regexp(r"^tagrev:drop:([0-9a-f\-]{10,}):(\d+)$"))
async def drop_tag_handler(callback: CallbackQuery, state: FSMContext) -> None:
    """Обработчик удаления конкретного тега."""
    try:
        match = callback.data.split(":")
        meeting_id = match[2]
        tag_index = int(match[3])

        session = await _get_session(callback, meeting_id, state)
        if not session:
            return

        if 0 <= tag_index < len(session.working_tags):
            removed_tag = session.working_tags.pop(tag_index)
            session.history.append(("drop", removed_tag))

            await _update_session(session, state)

            # Обновляем сообщение
            message_text = _format_tags_message(session)
            keyboard = _build_tags_keyboard(session)

            await callback.message.edit_text(message_text, reply_markup=keyboard)
            await callback.answer(f"🗑 Удален: {removed_tag}")
        else:
            await callback.answer("❌ Тег не найден", show_alert=True)

    except Exception as e:
        logger.error(f"Error in drop_tag_handler: {e}")
        await callback.answer("❌ Ошибка при удалении тега", show_alert=True)


@router.callback_query(F.data.regexp(r"^tagrev:accept:([0-9a-f\-]{10,})$"))
async def accept_all_handler(callback: CallbackQuery, state: FSMContext) -> None:
    """Обработчик принятия всех тегов."""
    try:
        meeting_id = callback.data.split(":")[2]

        session = await _get_session(callback, meeting_id, state)
        if not session:
            return

        # Принимаем все текущие теги
        for tag in session.working_tags:
            if ("keep", tag) not in session.history:
                session.history.append(("keep", tag))

        await _finalize_review(session, callback, state, "✅ Все теги приняты")

    except Exception as e:
        logger.error(f"Error in accept_all_handler: {e}")
        await callback.answer("❌ Ошибка при принятии тегов", show_alert=True)


@router.callback_query(F.data.regexp(r"^tagrev:clear:([0-9a-f\-]{10,})$"))
async def clear_all_handler(callback: CallbackQuery, state: FSMContext) -> None:
    """Обработчик удаления всех тегов."""
    try:
        meeting_id = callback.data.split(":")[2]

        session = await _get_session(callback, meeting_id, state)
        if not session:
            return

        # Удаляем все теги
        for tag in list(session.working_tags):
            session.history.append(("drop", tag))
        session.working_tags.clear()

        await _update_session(session, state)

        # Обновляем интерфейс
        message_text = _format_tags_message(session)
        keyboard = _build_tags_keyboard(session)

        await callback.message.edit_text(message_text, reply_markup=keyboard)
        await callback.answer("🗑 Все теги удалены")

    except Exception as e:
        logger.error(f"Error in clear_all_handler: {e}")
        await callback.answer("❌ Ошибка при удалении тегов", show_alert=True)


@router.callback_query(F.data.regexp(r"^tagrev:add:([0-9a-f\-]{10,})$"))
async def add_tag_handler(callback: CallbackQuery, state: FSMContext) -> None:
    """Обработчик запроса добавления нового тега."""
    try:
        meeting_id = callback.data.split(":")[2]

        session = await _get_session(callback, meeting_id, state)
        if not session:
            return

        await state.set_state(TagsReviewStates.waiting_custom_tag)

        await callback.message.answer(
            "➕ <b>Добавление тега</b>\n\n"
            "Введите тег в каноническом формате:\n"
            "• <code>Finance/IFRS</code>\n"
            "• <code>Business/Lavka</code>\n"
            "• <code>People/Ivan Petrov</code>\n"
            "• <code>Projects/Mobile App</code>\n\n"
            "💡 Или отправьте /cancel для отмены"
        )
        await callback.answer()

    except Exception as e:
        logger.error(f"Error in add_tag_handler: {e}")
        await callback.answer("❌ Ошибка при добавлении тега", show_alert=True)


@router.message(TagsReviewStates.waiting_custom_tag, F.text)
async def custom_tag_handler(message: Message, state: FSMContext) -> None:
    """Обработчик ввода кастомного тега."""
    try:
        if message.text == "/cancel":
            await state.set_state(TagsReviewStates.reviewing)
            await message.answer("❌ Добавление тега отменено")
            return

        tag = message.text.strip()

        # Валидация формата тега
        if not _validate_tag_format(tag):
            await message.answer(
                "❌ <b>Неправильный формат тега</b>\n\n"
                "Используйте формат: <code>Категория/Название</code>\n"
                "Доступные категории: Finance, Business, People, Projects, Topic"
            )
            return

        # Ищем активную сессию
        data = await state.get_data()
        session = None
        for key, value in data.items():
            if key.startswith("tagrev:") and isinstance(value, TagReviewSession):
                session = value
                break

        if not session or session.is_expired:
            await message.answer("❌ Сессия ревью не найдена или истекла")
            await state.clear()
            return

        if not session.can_edit(message.from_user.id if message.from_user else None):
            await message.answer("❌ У вас нет прав на редактирование")
            return

        # Добавляем тег если его еще нет
        if tag not in session.working_tags:
            session.working_tags.append(tag)
            session.history.append(("add", tag))

            await _update_session(session, state)
            await state.set_state(TagsReviewStates.reviewing)

            await message.answer(f"✅ Добавлен тег: <code>{tag}</code>")
        else:
            await message.answer(f"⚠️ Тег уже существует: <code>{tag}</code>")

    except Exception as e:
        logger.error(f"Error in custom_tag_handler: {e}")
        await message.answer("❌ Ошибка при добавлении тега")


@router.callback_query(F.data.regexp(r"^tagrev:undo:([0-9a-f\-]{10,})$"))
async def undo_handler(callback: CallbackQuery, state: FSMContext) -> None:
    """Обработчик отмены последнего действия."""
    try:
        meeting_id = callback.data.split(":")[2]

        session = await _get_session(callback, meeting_id, state)
        if not session:
            return

        if not session.history:
            await callback.answer("❌ История действий пуста")
            return

        # Отменяем последнее действие
        last_action, last_tag = session.history.pop()

        if last_action == "drop":
            # Восстанавливаем удаленный тег
            if last_tag not in session.working_tags:
                session.working_tags.append(last_tag)
        elif last_action == "add":
            # Удаляем добавленный тег
            if last_tag in session.working_tags:
                session.working_tags.remove(last_tag)

        await _update_session(session, state)

        # Обновляем интерфейс
        message_text = _format_tags_message(session)
        keyboard = _build_tags_keyboard(session)

        await callback.message.edit_text(message_text, reply_markup=keyboard)
        await callback.answer(f"↩️ Отменено: {last_action} '{last_tag}'")

    except Exception as e:
        logger.error(f"Error in undo_handler: {e}")
        await callback.answer("❌ Ошибка при отмене действия", show_alert=True)


@router.callback_query(F.data.regexp(r"^tagrev:save:([0-9a-f\-]{10,})$"))
async def save_handler(callback: CallbackQuery, state: FSMContext) -> None:
    """Обработчик сохранения изменений в Notion."""
    try:
        meeting_id = callback.data.split(":")[2]

        session = await _get_session(callback, meeting_id, state)
        if not session:
            return

        await _finalize_review(session, callback, state, "💾 Теги сохранены в Notion")

    except Exception as e:
        logger.error(f"Error in save_handler: {e}")
        await callback.answer("❌ Ошибка при сохранении", show_alert=True)


@router.callback_query(F.data.regexp(r"^tagrev:cancel:([0-9a-f\-]{10,})$"))
async def cancel_handler(callback: CallbackQuery, state: FSMContext) -> None:
    """Обработчик отмены ревью."""
    try:
        meeting_id = callback.data.split(":")[2]

        session = await _get_session(callback, meeting_id, state)
        if not session:
            return

        # Очищаем сессию без сохранения
        session_key = f"tagrev:{meeting_id}"
        await state.update_data(**{session_key: None})
        await state.clear()

        await callback.message.edit_text(
            "❌ <b>Ревью тегов отменен</b>\n\n"
            "Изменения не сохранены. Теги остались без изменений.",
            reply_markup=None,
        )
        await callback.answer("❌ Ревью отменен")

        logger.info(f"Tags review cancelled for meeting {meeting_id}")

    except Exception as e:
        logger.error(f"Error in cancel_handler: {e}")
        await callback.answer("❌ Ошибка при отмене", show_alert=True)


async def _finalize_review(
    session: TagReviewSession, callback: CallbackQuery, state: FSMContext, success_message: str
) -> None:
    """Завершает ревью и сохраняет изменения в Notion."""
    try:
        # Обновляем теги в Notion
        update_meeting_tags(session.meeting_id, session.working_tags)

        # Логируем изменения если включено
        if settings.enable_tag_edit_log:
            _log_tag_changes(session, callback.from_user.id if callback.from_user else None)

        # Очищаем сессию
        session_key = f"tagrev:{session.meeting_id}"
        await state.update_data(**{session_key: None})
        await state.clear()

        # Показываем результат
        changes_summary = session.get_changes_summary()
        final_message = (
            f"{success_message}\n\n"
            f"📊 <b>Изменения:</b> {changes_summary}\n"
            f"🏷️ <b>Итого тегов:</b> {len(session.working_tags)}"
        )

        await callback.message.edit_text(final_message, reply_markup=None)
        await callback.answer()

        logger.info(
            f"Tags review completed for meeting {session.meeting_id}: "
            f"{len(session.original_tags)} → {len(session.working_tags)} tags"
        )

        # Показываем Review Queue если есть элементы
        await _show_review_queue_after_tags(callback)

    except Exception as e:
        logger.error(f"Error finalizing review for meeting {session.meeting_id}: {e}")
        await callback.answer("❌ Ошибка при сохранении в Notion", show_alert=True)


def _validate_tag_format(tag: str) -> bool:
    """Валидирует формат тега."""
    if not tag or "/" not in tag:
        return False

    # Проверяем, что есть только один слэш
    if tag.count("/") != 1:
        return False

    parts = tag.split("/", 1)
    if len(parts) != 2:
        return False

    category, name = parts

    # Проверяем допустимые категории
    allowed_categories = {"Finance", "Business", "People", "Projects", "Topic", "Area"}
    if category not in allowed_categories:
        return False

    # Проверяем, что название не пустое
    return bool(name.strip())


def _log_tag_changes(session: TagReviewSession, user_id: int | None) -> None:
    """Логирует изменения тегов (пока только в лог, Notion база опциональна)."""
    if not session.history:
        return

    logger.info(
        f"Tag changes for meeting {session.meeting_id} by user {user_id}: "
        f"{len(session.history)} actions"
    )

    for action, tag in session.history:
        logger.info(f"  {action.upper()}: {tag}")


# Обработчик для noop callbacks (предотвращает ошибки)
@router.callback_query(F.data == "noop")
async def noop_handler(callback: CallbackQuery) -> None:
    """Обработчик для неактивных кнопок."""
    await callback.answer("ℹ️ Это информационная кнопка", show_alert=False)
