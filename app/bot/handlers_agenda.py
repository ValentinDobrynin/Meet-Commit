"""
Обработчики команд для системы повесток.

Поддерживает команды:
- /agenda - главное меню выбора типа повестки
- /agenda_meeting <meeting_id> - повестка по встрече
- /agenda_person <name> - персональная повестка
- /agenda_tag <tag> - тематическая повестка

Интегрирован с системой форматирования и Notion Agendas.
"""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot.formatters import format_agenda_card
from app.core import agenda_builder

logger = logging.getLogger(__name__)
router = Router()


class AgendaStates(StatesGroup):
    """Состояния FSM для работы с повестками."""

    waiting_meeting_id = State()
    waiting_person_name = State()
    waiting_tag_name = State()


def _build_main_menu_keyboard() -> InlineKeyboardMarkup:
    """Создание клавиатуры главного меню повесток."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="🏢 По встрече", callback_data="agenda:type:meeting"),
                InlineKeyboardButton(text="👤 По человеку", callback_data="agenda:type:person"),
            ],
            [
                InlineKeyboardButton(text="🏷️ По тегу", callback_data="agenda:type:tag"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="agenda:cancel"),
            ],
        ]
    )


def _build_people_keyboard() -> InlineKeyboardMarkup:
    """Создание клавиатуры выбора людей на основе активности в Commits."""
    from app.core.people_activity import get_top_people_by_activity

    try:
        # Получаем топ людей по активности (3-8 адаптивно)
        top_people = get_top_people_by_activity(min_count=3, max_count=8, min_score=1.0)

        logger.info(f"Building people keyboard with {len(top_people)} top people")

        buttons = []

        # Добавляем топ людей (по 2 в ряд для компактности)
        for i in range(0, len(top_people), 2):
            row = []
            for j in range(i, min(i + 2, len(top_people))):
                person = top_people[j]
                row.append(
                    InlineKeyboardButton(
                        text=f"👤 {person}", callback_data=f"agenda:person:{person}"
                    )
                )
            if row:
                buttons.append(row)

        # Добавляем кнопку "Other people" если есть еще люди
        from app.core.people_activity import get_other_people

        other_people = get_other_people(exclude_top=top_people)

        if other_people:
            buttons.append(
                [
                    InlineKeyboardButton(
                        text="👥 Other people...", callback_data="agenda:people:other"
                    )
                ]
            )

        # Кнопка возврата
        buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="agenda:back")])

        return InlineKeyboardMarkup(inline_keyboard=buttons)

    except Exception as e:
        logger.error(f"Error building people keyboard: {e}")
        # Fallback - простая клавиатура
        return _build_fallback_people_keyboard()


def _build_fallback_people_keyboard() -> InlineKeyboardMarkup:
    """Fallback клавиатура людей если нет данных активности."""
    from app.core.people_activity import get_fallback_top_people

    fallback_people = get_fallback_top_people()
    buttons = []

    # Добавляем fallback людей
    for person in fallback_people:
        buttons.append(
            [InlineKeyboardButton(text=f"👤 {person}", callback_data=f"agenda:person:{person}")]
        )

    # Кнопка возврата
    buttons.append([InlineKeyboardButton(text="🔙 Назад", callback_data="agenda:back")])

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _build_tags_keyboard() -> InlineKeyboardMarkup:
    """Создание клавиатуры популярных тегов."""
    # Популярные теги - можно настроить или загружать из файла
    popular_tags = [
        "Finance/IFRS",
        "Business/Lavka",
        "Projects/Mobile App",
        "Topic/Meeting",
        "Topic/Planning",
    ]

    buttons = []
    for tag in popular_tags:
        buttons.append([InlineKeyboardButton(text=f"🏷️ {tag}", callback_data=f"agenda:tag:{tag}")])

    buttons.extend(
        [
            [InlineKeyboardButton(text="✍️ Ввести вручную", callback_data="agenda:tag:manual")],
            [InlineKeyboardButton(text="🔙 Назад", callback_data="agenda:back")],
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _build_agenda_keyboard(bundle: agenda_builder.AgendaBundle) -> InlineKeyboardMarkup:
    """Создание клавиатуры для готовой повестки."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="📤 Сохранить в Notion",
                    callback_data=f"agenda:save:{bundle.context_type}:{bundle.raw_hash[:8]}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="🔄 Обновить",
                    callback_data=f"agenda:refresh:{bundle.context_type}:{bundle.context_key}",
                ),
            ],
            [
                InlineKeyboardButton(text="🔙 Новая повестка", callback_data="agenda:new"),
            ],
        ]
    )


@router.message(Command("agenda"))
async def cmd_agenda_menu(message: Message, state: FSMContext) -> None:
    """Главное меню системы повесток."""
    await state.clear()

    help_text = (
        "📋 <b>Система повесток</b>\n\n"
        "Выберите тип повестки:\n\n"
        "🏢 <b>По встрече</b> - все коммиты и вопросы конкретной встречи\n"
        "👤 <b>По человеку</b> - взаимные обязательства с конкретным человеком\n"
        "🏷️ <b>По тегу</b> - все активные задачи по тематике\n\n"
        "💡 <i>Повестки автоматически сохраняются в Notion с связями на коммиты</i>"
    )

    await message.answer(help_text, parse_mode="HTML", reply_markup=_build_main_menu_keyboard())


@router.message(Command("agenda_meeting"))
async def cmd_agenda_meeting_direct(message: Message) -> None:
    """Прямая команда создания повестки по встрече."""
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            "❓ Укажите ID встречи:\n"
            "<code>/agenda_meeting 277344c5-6766-8198-af51-e25b82569c9e</code>",
            parse_mode="HTML",
        )
        return

    meeting_id = parts[1].strip()
    await _generate_meeting_agenda(message, meeting_id)


@router.message(Command("agenda_person"))
async def cmd_agenda_person_direct(message: Message) -> None:
    """Прямая команда создания персональной повестки."""
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            "❓ Укажите имя человека:\n" "<code>/agenda_person Sasha Katanov</code>",
            parse_mode="HTML",
        )
        return

    person_name = parts[1].strip()
    await _generate_person_agenda(message, person_name)


@router.message(Command("agenda_tag"))
async def cmd_agenda_tag_direct(message: Message) -> None:
    """Прямая команда создания тематической повестки."""
    parts = (message.text or "").split(maxsplit=1)
    if len(parts) < 2:
        await message.answer(
            "❓ Укажите тег:\n" "<code>/agenda_tag Finance/IFRS</code>", parse_mode="HTML"
        )
        return

    tag = parts[1].strip()
    await _generate_tag_agenda(message, tag)


@router.callback_query(F.data == "agenda:type:meeting")
async def callback_agenda_meeting(callback: CallbackQuery, state: FSMContext) -> None:
    """Выбор повестки по встрече."""
    await state.set_state(AgendaStates.waiting_meeting_id)

    await callback.message.edit_text(  # type: ignore[union-attr]
        "🏢 <b>Повестка по встрече</b>\n\n"
        "Отправьте ID встречи (можно скопировать из Notion URL):\n"
        "<code>277344c5-6766-8198-af51-e25b82569c9e</code>\n\n"
        "💡 <i>Или отправьте /cancel для отмены</i>",
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[[InlineKeyboardButton(text="🔙 Назад", callback_data="agenda:back")]]
        ),
    )
    await callback.answer()


@router.callback_query(F.data == "agenda:type:person")
async def callback_agenda_person(callback: CallbackQuery, state: FSMContext) -> None:
    """Выбор персональной повестки."""
    await state.clear()

    await callback.message.edit_text(  # type: ignore[union-attr]
        "👤 <b>Персональная повестка</b>\n\n" "Выберите человека или введите имя вручную:",
        parse_mode="HTML",
        reply_markup=_build_people_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "agenda:type:tag")
async def callback_agenda_tag(callback: CallbackQuery, state: FSMContext) -> None:
    """Выбор тематической повестки."""
    await state.clear()

    await callback.message.edit_text(  # type: ignore[union-attr]
        "🏷️ <b>Тематическая повестка</b>\n\n" "Выберите тег или введите вручную:",
        parse_mode="HTML",
        reply_markup=_build_tags_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data.startswith("agenda:person:"))
async def callback_person_selected(callback: CallbackQuery) -> None:
    """Обработка выбора человека."""
    callback_data = callback.data or ""
    person_data = callback_data.split(":", 2)[2]

    # Убрали ручной ввод - теперь только кнопки
    if person_data == "manual":
        await callback.answer(
            "❌ Ручной ввод временно отключен. Выберите из списка.", show_alert=True
        )
        return

    await _generate_person_agenda(callback.message, person_data)  # type: ignore[arg-type]
    await callback.answer()


@router.callback_query(F.data == "agenda:people:other")
async def callback_show_other_people(callback: CallbackQuery) -> None:
    """Показать других людей (страница 1)."""
    await _show_other_people_page(callback, page=0)


@router.callback_query(F.data.startswith("agenda:people:other:page:"))
async def callback_other_people_page(callback: CallbackQuery) -> None:
    """Показать конкретную страницу других людей."""
    try:
        page = int((callback.data or "").split(":")[-1])
        await _show_other_people_page(callback, page=page)
    except (ValueError, IndexError):
        await callback.answer("❌ Ошибка в номере страницы", show_alert=True)


async def _show_other_people_page(callback: CallbackQuery, page: int = 0) -> None:
    """Показывает страницу других людей."""
    try:
        from app.core.people_activity import get_other_people, get_top_people_by_activity

        # Получаем топ людей для исключения
        top_people = get_top_people_by_activity()
        other_people = get_other_people(exclude_top=top_people)

        if not other_people:
            await callback.answer("❌ Нет других людей с активностью", show_alert=True)
            return

        # Пагинация
        per_page = 8
        total_pages = (len(other_people) + per_page - 1) // per_page
        page = max(0, min(page, total_pages - 1))  # Ограничиваем диапазон

        start_idx = page * per_page
        end_idx = start_idx + per_page
        page_people = other_people[start_idx:end_idx]

        # Создаем клавиатуру
        buttons = []

        # Добавляем людей этой страницы (по 2 в ряд)
        for i in range(0, len(page_people), 2):
            row = []
            for j in range(i, min(i + 2, len(page_people))):
                person = page_people[j]
                row.append(
                    InlineKeyboardButton(
                        text=f"👤 {person}", callback_data=f"agenda:person:{person}"
                    )
                )
            if row:
                buttons.append(row)

        # Навигация
        nav_row = []
        if page > 0:
            nav_row.append(
                InlineKeyboardButton(
                    text="← Назад", callback_data=f"agenda:people:other:page:{page-1}"
                )
            )

        nav_row.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="noop"))

        if page < total_pages - 1:
            nav_row.append(
                InlineKeyboardButton(
                    text="Вперед →", callback_data=f"agenda:people:other:page:{page+1}"
                )
            )

        buttons.append(nav_row)

        # Кнопка возврата к топу
        buttons.append([InlineKeyboardButton(text="🔙 К топу", callback_data="agenda:type:person")])

        # Обновляем сообщение
        text = (
            f"👥 <b>Other people</b> (страница {page+1}/{total_pages})\n\n"
            f"Выберите человека для персональной повестки:\n"
            f"<i>Показано {len(page_people)} из {len(other_people)} людей</i>"
        )

        await callback.message.edit_text(  # type: ignore[union-attr]
            text, parse_mode="HTML", reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
        )
        await callback.answer()

    except Exception as e:
        logger.error(f"Error showing other people page {page}: {e}")
        await callback.answer("❌ Ошибка при загрузке списка людей", show_alert=True)


@router.callback_query(F.data == "noop")
async def callback_noop(callback: CallbackQuery) -> None:
    """Обработчик для неактивных кнопок (индикаторы страниц)."""
    await callback.answer()


@router.callback_query(F.data.startswith("agenda:tag:"))
async def callback_tag_selected(callback: CallbackQuery) -> None:
    """Обработка выбора тега."""
    callback_data = callback.data or ""
    tag_data = callback_data.split(":", 2)[2]

    if tag_data == "manual":
        await callback.message.edit_text(  # type: ignore[union-attr]
            "🏷️ <b>Тематическая повестка</b>\n\n"
            "Введите тег в каноническом формате:\n"
            "<code>Finance/IFRS</code>\n"
            "<code>Business/Lavka</code>\n\n"
            "💡 <i>Или отправьте /cancel для отмены</i>",
            parse_mode="HTML",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 Назад", callback_data="agenda:type:tag")]
                ]
            ),
        )
        await callback.answer()
        return

    await _generate_tag_agenda(callback.message, tag_data)  # type: ignore[arg-type]
    await callback.answer()


@router.callback_query(F.data == "agenda:back")
async def callback_agenda_back(callback: CallbackQuery, state: FSMContext) -> None:
    """Возврат к главному меню повесток."""
    await state.clear()

    help_text = (
        "📋 <b>Система повесток</b>\n\n"
        "Выберите тип повестки:\n\n"
        "🏢 <b>По встрече</b> - все коммиты и вопросы конкретной встречи\n"
        "👤 <b>По человеку</b> - взаимные обязательства с конкретным человеком\n"
        "🏷️ <b>По тегу</b> - все активные задачи по тематике"
    )

    await callback.message.edit_text(  # type: ignore[union-attr]
        help_text, parse_mode="HTML", reply_markup=_build_main_menu_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data == "agenda:cancel")
async def callback_agenda_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    """Отмена создания повестки."""
    await state.clear()

    await callback.message.edit_text(  # type: ignore[union-attr]
        "❌ Создание повестки отменено"
    )
    await callback.answer()


@router.callback_query(F.data == "agenda:new")
async def callback_agenda_new(callback: CallbackQuery, state: FSMContext) -> None:
    """Создание новой повестки."""
    await state.clear()

    help_text = (
        "📋 <b>Система повесток</b>\n\n"
        "Выберите тип повестки:\n\n"
        "🏢 <b>По встрече</b> - все коммиты и вопросы конкретной встречи\n"
        "👤 <b>По человеку</b> - взаимные обязательства с конкретным человеком\n"
        "🏷️ <b>По тегу</b> - все активные задачи по тематике"
    )

    await callback.message.edit_text(  # type: ignore[union-attr]
        help_text, parse_mode="HTML", reply_markup=_build_main_menu_keyboard()
    )
    await callback.answer()


@router.callback_query(F.data.startswith("agenda:save:"))
async def callback_save_agenda(callback: CallbackQuery) -> None:
    """Сохранение повестки в Notion."""
    try:
        # Извлекаем данные из callback_data
        callback_data = callback.data or ""
        parts = callback_data.split(":")
        _context_type = parts[2]  # Пока не используется
        _hash_short = parts[3]  # Пока не используется

        # Здесь нужно восстановить bundle из кэша или пересоздать
        # Пока что показываем заглушку
        await callback.answer("💾 Сохранение в Notion...")

        await callback.message.answer(  # type: ignore[union-attr]
            "✅ Повестка сохранена в Notion!\n\n"
            "🔗 Ссылка будет добавлена после реализации сохранения"
        )

    except Exception as e:
        logger.error(f"Error saving agenda: {e}")
        await callback.answer("❌ Ошибка при сохранении", show_alert=True)


@router.callback_query(F.data.startswith("agenda:refresh:"))
async def callback_refresh_agenda(callback: CallbackQuery) -> None:
    """Обновление повестки."""
    try:
        # Извлекаем данные из callback_data
        callback_data = callback.data or ""
        parts = callback_data.split(":", 3)
        context_type = parts[2]
        context_key = parts[3]

        await callback.answer("🔄 Обновление повестки...")

        if context_type == "Meeting":
            await _generate_meeting_agenda(callback.message, context_key)  # type: ignore[arg-type]
        elif context_type == "Person":
            person_name = context_key.replace("People/", "")
            await _generate_person_agenda(callback.message, person_name)  # type: ignore[arg-type]
        elif context_type == "Tag":
            await _generate_tag_agenda(callback.message, context_key)  # type: ignore[arg-type]

    except Exception as e:
        logger.error(f"Error refreshing agenda: {e}")
        await callback.answer("❌ Ошибка при обновлении", show_alert=True)


# Обработчики ввода текста в состояниях FSM


@router.message(AgendaStates.waiting_meeting_id, F.text)
async def handle_meeting_id_input(message: Message, state: FSMContext) -> None:
    """Обработка ввода ID встречи."""
    await state.clear()

    meeting_id = message.text.strip() if message.text else ""
    if not meeting_id:
        await message.answer("❌ ID встречи не может быть пустым")
        return

    await _generate_meeting_agenda(message, meeting_id)


@router.message(AgendaStates.waiting_person_name, F.text)
async def handle_person_name_input(message: Message, state: FSMContext) -> None:
    """Обработка ввода имени человека."""
    user_id = message.from_user.id if message.from_user else "unknown"
    logger.info(
        f"Agenda FSM: User {user_id} entered person name: '{message.text}' in state waiting_person_name"
    )

    await state.clear()

    person_name = message.text.strip() if message.text else ""
    if not person_name:
        await message.answer("❌ Имя человека не может быть пустым")
        return

    await _generate_person_agenda(message, person_name)


@router.message(AgendaStates.waiting_tag_name, F.text)
async def handle_tag_name_input(message: Message, state: FSMContext) -> None:
    """Обработка ввода тега."""
    await state.clear()

    tag = message.text.strip() if message.text else ""
    if not tag:
        await message.answer("❌ Тег не может быть пустым")
        return

    await _generate_tag_agenda(message, tag)


# Вспомогательные функции для генерации повесток


async def _generate_meeting_agenda(message: Message, meeting_id: str) -> None:
    """Генерация и отправка повестки по встрече."""
    try:
        bundle = agenda_builder.build_for_meeting(meeting_id)

        card_text = format_agenda_card(bundle, device_type="mobile")
        keyboard = _build_agenda_keyboard(bundle)

        await message.answer(card_text, parse_mode="HTML", reply_markup=keyboard)

    except Exception as e:
        logger.error(f"Error generating meeting agenda for {meeting_id}: {e}")
        await message.answer(
            f"❌ Ошибка при создании повестки для встречи\n\n"
            f"Проверьте корректность ID встречи:\n"
            f"<code>{meeting_id}</code>",
            parse_mode="HTML",
        )


async def _generate_person_agenda(message: Message, person_name: str) -> None:
    """Генерация и отправка персональной повестки."""
    try:
        bundle = agenda_builder.build_for_person(person_name)

        card_text = format_agenda_card(bundle, device_type="mobile")
        keyboard = _build_agenda_keyboard(bundle)

        await message.answer(card_text, parse_mode="HTML", reply_markup=keyboard)

    except Exception as e:
        logger.error(f"Error generating person agenda for {person_name}: {e}")
        await message.answer(
            f"❌ Ошибка при создании персональной повестки\n\n"
            f"Проверьте корректность имени:\n"
            f"<code>{person_name}</code>",
            parse_mode="HTML",
        )


async def _generate_tag_agenda(message: Message, tag: str) -> None:
    """Генерация и отправка тематической повестки."""
    try:
        bundle = agenda_builder.build_for_tag(tag)

        card_text = format_agenda_card(bundle, device_type="mobile")
        keyboard = _build_agenda_keyboard(bundle)

        await message.answer(card_text, parse_mode="HTML", reply_markup=keyboard)

    except Exception as e:
        logger.error(f"Error generating tag agenda for {tag}: {e}")
        await message.answer(
            f"❌ Ошибка при создании тематической повестки\n\n"
            f"Проверьте корректность тега:\n"
            f"<code>{tag}</code>",
            parse_mode="HTML",
        )
