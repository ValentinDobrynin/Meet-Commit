"""
Обработчики для улучшенной команды /assign с интерактивными кнопками.

Реализует интерфейс выбора исполнителей аналогично /agenda:
- Кнопки с частотными участниками
- Пагинация для "Other people"
- Сохранение ручного ввода как запасной вариант
"""

from __future__ import annotations

import logging
import re

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.gateways.notion_review import get_by_short_id, update_fields

logger = logging.getLogger(__name__)
router = Router()


class AssignStates(StatesGroup):
    """Состояния для процесса назначения исполнителя."""

    waiting_for_assignee = State()


def _clean_sid(raw_sid: str) -> str:
    """Очищает short_id от лишних символов."""
    return raw_sid.strip().lstrip("#").lower()


def _build_assignee_keyboard(short_id: str) -> InlineKeyboardMarkup:
    """Создание клавиатуры выбора исполнителей на основе активности в Commits."""
    from app.core.people_activity import get_top_people_by_activity

    try:
        # Получаем топ людей по активности (3-8 адаптивно)
        top_people = get_top_people_by_activity(min_count=3, max_count=8, min_score=1.0)

        logger.info(f"Building assignee keyboard with {len(top_people)} top people for {short_id}")

        buttons = []

        # Добавляем топ людей (по 2 в ряд для компактности)
        for i in range(0, len(top_people), 2):
            row = []
            for j in range(i, min(i + 2, len(top_people))):
                person = top_people[j]
                row.append(
                    InlineKeyboardButton(
                        text=f"👤 {person}", callback_data=f"assign:{short_id}:person:{person}"
                    )
                )
            if row:
                buttons.append(row)

        # Добавляем кнопку "Other people" если есть еще люди
        from app.core.people_activity import get_all_people_from_dictionary

        other_people = get_all_people_from_dictionary(exclude_top=top_people)

        if other_people:
            buttons.append(
                [
                    InlineKeyboardButton(
                        text="👥 Other people...", callback_data=f"assign:{short_id}:people:other"
                    )
                ]
            )

        # Кнопка ручного ввода (запасной вариант)
        buttons.append(
            [
                InlineKeyboardButton(
                    text="✏️ Ввести вручную", callback_data=f"assign:{short_id}:manual"
                )
            ]
        )

        # Кнопка отмены
        buttons.append(
            [InlineKeyboardButton(text="❌ Отмена", callback_data=f"assign:{short_id}:cancel")]
        )

        return InlineKeyboardMarkup(inline_keyboard=buttons)

    except Exception as e:
        logger.error(f"Error building assignee keyboard: {e}")
        # Fallback - простая клавиатуру с ручным вводом
        return _build_fallback_assignee_keyboard(short_id)


def _build_fallback_assignee_keyboard(short_id: str) -> InlineKeyboardMarkup:
    """Fallback клавиатура если не удалось загрузить активность людей."""
    from app.core.people_activity import get_fallback_top_people

    try:
        fallback_people = get_fallback_top_people()
        buttons = []

        # Добавляем fallback людей
        for person in fallback_people:
            buttons.append(
                [
                    InlineKeyboardButton(
                        text=f"👤 {person}", callback_data=f"assign:{short_id}:person:{person}"
                    )
                ]
            )

        # Кнопка ручного ввода
        buttons.append(
            [
                InlineKeyboardButton(
                    text="✏️ Ввести вручную", callback_data=f"assign:{short_id}:manual"
                )
            ]
        )

        # Кнопка отмены
        buttons.append(
            [InlineKeyboardButton(text="❌ Отмена", callback_data=f"assign:{short_id}:cancel")]
        )

        return InlineKeyboardMarkup(inline_keyboard=buttons)

    except Exception as e:
        logger.error(f"Error building fallback assignee keyboard: {e}")
        # Минимальная клавиатура
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="✏️ Ввести вручную", callback_data=f"assign:{short_id}:manual"
                    )
                ],
                [InlineKeyboardButton(text="❌ Отмена", callback_data=f"assign:{short_id}:cancel")],
            ]
        )


def _build_other_people_keyboard(short_id: str, page: int = 0) -> InlineKeyboardMarkup:
    """Создает клавиатуру с пагинацией для других людей."""
    try:
        from app.core.people_activity import (
            get_all_people_from_dictionary,
            get_top_people_by_activity,
        )

        # Получаем топ людей для исключения
        top_people = get_top_people_by_activity()
        other_people = get_all_people_from_dictionary(exclude_top=top_people)

        if not other_people:
            # Если нет других людей, возвращаем кнопку назад
            return InlineKeyboardMarkup(
                inline_keyboard=[
                    [InlineKeyboardButton(text="🔙 Назад", callback_data=f"assign:{short_id}:back")]
                ]
            )

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
                        text=f"👤 {person}", callback_data=f"assign:{short_id}:person:{person}"
                    )
                )
            if row:
                buttons.append(row)

        # Навигация
        nav_row = []
        if page > 0:
            nav_row.append(
                InlineKeyboardButton(
                    text="← Назад", callback_data=f"assign:{short_id}:people:other:page:{page-1}"
                )
            )

        nav_row.append(InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="noop"))

        if page < total_pages - 1:
            nav_row.append(
                InlineKeyboardButton(
                    text="Вперед →", callback_data=f"assign:{short_id}:people:other:page:{page+1}"
                )
            )

        if nav_row:
            buttons.append(nav_row)

        # Кнопка возврата к основному меню
        buttons.append(
            [
                InlineKeyboardButton(
                    text="🔙 К выбору исполнителя", callback_data=f"assign:{short_id}:back"
                )
            ]
        )

        return InlineKeyboardMarkup(inline_keyboard=buttons)

    except Exception as e:
        logger.error(f"Error building other people keyboard: {e}")
        # Fallback
        return InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔙 Назад", callback_data=f"assign:{short_id}:back")]
            ]
        )


# ====== НОВЫЙ ИНТЕРАКТИВНЫЙ ОБРАБОТЧИК /assign ======


@router.message(F.text.regexp(r"^/assign\s+\S+$", flags=re.I))
async def cmd_assign_interactive(msg: Message, state: FSMContext):
    """Интерактивная команда назначения исполнителя с кнопками."""

    try:
        parts = (msg.text or "").strip().split()
        if len(parts) != 2:
            await msg.answer(
                "❌ Неверный синтаксис\n"
                "Используйте: <code>/assign &lt;id&gt;</code>\n"
                "Для ручного ввода: <code>/assign &lt;id&gt; &lt;имя&gt;</code>",
                parse_mode="HTML",
            )
            return

        short_id = _clean_sid(parts[1])
        item = get_by_short_id(short_id)

        if not item:
            await msg.answer(f"❌ Карточка [{short_id}] не найдена. Проверьте /review.")
            return

        # Сохраняем short_id в состоянии
        await state.update_data(assign_short_id=short_id)

        # Показываем интерактивное меню выбора исполнителя
        task_text = item.get("text", "")[:100]
        if len(item.get("text", "")) > 100:
            task_text += "..."

        await msg.answer(
            f"👤 <b>Назначение исполнителя</b>\n\n"
            f"📋 <b>Задача [{short_id}]:</b>\n"
            f"<i>{task_text}</i>\n\n"
            f"Выберите исполнителя:",
            parse_mode="HTML",
            reply_markup=_build_assignee_keyboard(short_id),
        )

        logger.info(
            f"Started interactive assign for {short_id} by user {msg.from_user.id if msg.from_user else 'unknown'}"
        )

    except Exception as e:
        logger.error(f"Error in cmd_assign_interactive: {e}")
        await msg.answer("❌ Ошибка при обработке команды assign.")


# ====== ОБРАБОТЧИКИ CALLBACK'ОВ ======


@router.callback_query(F.data.startswith("assign:") & F.data.contains(":person:"))
async def callback_assign_person(callback: CallbackQuery, state: FSMContext) -> None:
    """Обработка выбора исполнителя из кнопок."""
    try:
        callback_data = callback.data or ""
        parts = callback_data.split(":")

        if len(parts) < 4:
            await callback.answer("❌ Ошибка в данных callback", show_alert=True)
            return

        short_id = parts[1]
        person_name = ":".join(parts[3:])  # На случай если в имени есть ":"

        # Проверяем что задача существует
        item = get_by_short_id(short_id)
        if not item:
            await callback.answer(f"❌ Карточка [{short_id}] не найдена", show_alert=True)
            return

        # Назначаем исполнителя
        from app.core.commit_normalize import normalize_assignees

        normalized_assignees = normalize_assignees([person_name], attendees_en=[])

        if not normalized_assignees:
            await callback.answer(
                f"❌ Не удалось распознать исполнителя: {person_name}", show_alert=True
            )
            return

        success = update_fields(item["page_id"], assignees=normalized_assignees)

        if success:
            assignees_str = ", ".join(normalized_assignees)

            # Обновляем сообщение
            await callback.message.edit_text(  # type: ignore[union-attr]
                f"✅ <b>Исполнитель назначен</b>\n\n"
                f"📋 <b>Задача [{short_id}]:</b> {item.get('text', '')[:100]}{'...' if len(item.get('text', '')) > 100 else ''}\n"
                f"👤 <b>Исполнитель:</b> {assignees_str}\n\n"
                f"💡 Теперь можете подтвердить задачу командой <code>/confirm {short_id}</code>",
                parse_mode="HTML",
            )

            await callback.answer(f"✅ Назначен: {assignees_str}")

            logger.info(f"Assigned {assignees_str} to task {short_id} via interactive button")
        else:
            await callback.answer(
                f"❌ Не удалось обновить исполнителя для [{short_id}]", show_alert=True
            )

        # Очищаем состояние
        await state.clear()

    except Exception as e:
        logger.error(f"Error in callback_assign_person: {e}")
        await callback.answer("❌ Ошибка при назначении исполнителя", show_alert=True)


@router.callback_query(F.data.startswith("assign:") & F.data.contains(":people:other"))
async def callback_assign_other_people(callback: CallbackQuery) -> None:
    """Показать других людей (страница 1)."""
    try:
        callback_data = callback.data or ""
        parts = callback_data.split(":")
        short_id = parts[1]

        await _show_other_people_page(callback, short_id, page=0)
        await callback.answer()

    except Exception as e:
        logger.error(f"Error in callback_assign_other_people: {e}")
        await callback.answer("❌ Ошибка при загрузке других людей", show_alert=True)


@router.callback_query(F.data.startswith("assign:") & F.data.contains(":people:other:page:"))
async def callback_assign_other_people_page(callback: CallbackQuery) -> None:
    """Переход на конкретную страницу других людей."""
    try:
        callback_data = callback.data or ""
        parts = callback_data.split(":")
        short_id = parts[1]
        page = int(parts[5])

        await _show_other_people_page(callback, short_id, page)
        await callback.answer()

    except (ValueError, IndexError) as e:
        logger.error(f"Error parsing page number: {e}")
        await callback.answer("❌ Ошибка в номере страницы", show_alert=True)


async def _show_other_people_page(callback: CallbackQuery, short_id: str, page: int = 0) -> None:
    """Показывает страницу других людей для назначения."""
    try:
        from app.core.people_activity import (
            get_all_people_from_dictionary,
            get_top_people_by_activity,
        )

        # Получаем топ людей для исключения
        top_people = get_top_people_by_activity()
        other_people = get_all_people_from_dictionary(exclude_top=top_people)

        if not other_people:
            await callback.answer("❌ Нет других людей с активностью", show_alert=True)
            return

        # Обновляем сообщение с новой клавиатурой
        total_pages = (len(other_people) + 7) // 8  # 8 людей на страницу

        await callback.message.edit_text(  # type: ignore[union-attr]
            f"👥 <b>Другие исполнители</b>\n\n"
            f"📋 <b>Задача [{short_id}]</b>\n"
            f"Страница {page + 1} из {total_pages}\n\n"
            f"Выберите исполнителя:",
            parse_mode="HTML",
            reply_markup=_build_other_people_keyboard(short_id, page),
        )

        logger.info(f"Showed other people page {page} for assign {short_id}")

    except Exception as e:
        logger.error(f"Error showing other people page: {e}")
        await callback.answer("❌ Ошибка при загрузке страницы", show_alert=True)


@router.callback_query(F.data.startswith("assign:") & F.data.endswith(":manual"))
async def callback_assign_manual(callback: CallbackQuery, state: FSMContext) -> None:
    """Переход к ручному вводу исполнителя."""
    try:
        callback_data = callback.data or ""
        parts = callback_data.split(":")
        short_id = parts[1]

        # Сохраняем short_id в состоянии
        await state.update_data(assign_short_id=short_id)
        await state.set_state(AssignStates.waiting_for_assignee)

        # Обновляем сообщение
        await callback.message.edit_text(  # type: ignore[union-attr]
            f"✏️ <b>Ручной ввод исполнителя</b>\n\n"
            f"📋 <b>Задача [{short_id}]</b>\n\n"
            f"Введите имя исполнителя (можно несколько через запятую):\n\n"
            f"💡 <i>Примеры:</i>\n"
            f"• <code>Sergey Lompa</code>\n"
            f"• <code>Valya Dobrynin, Nodari Kezua</code>\n\n"
            f"Или отправьте /cancel для отмены.",
            parse_mode="HTML",
        )

        await callback.answer("✏️ Введите имя исполнителя")

        logger.info(f"Started manual assign input for {short_id}")

    except Exception as e:
        logger.error(f"Error in callback_assign_manual: {e}")
        await callback.answer("❌ Ошибка при переходе к ручному вводу", show_alert=True)


@router.callback_query(F.data.startswith("assign:") & F.data.endswith(":back"))
async def callback_assign_back(callback: CallbackQuery, state: FSMContext) -> None:
    """Возврат к основному меню выбора исполнителя."""
    try:
        callback_data = callback.data or ""
        parts = callback_data.split(":")
        short_id = parts[1]

        # Проверяем что задача существует
        item = get_by_short_id(short_id)
        if not item:
            await callback.answer(f"❌ Карточка [{short_id}] не найдена", show_alert=True)
            return

        # Возвращаем основное меню
        task_text = item.get("text", "")[:100]
        if len(item.get("text", "")) > 100:
            task_text += "..."

        await callback.message.edit_text(  # type: ignore[union-attr]
            f"👤 <b>Назначение исполнителя</b>\n\n"
            f"📋 <b>Задача [{short_id}]:</b>\n"
            f"<i>{task_text}</i>\n\n"
            f"Выберите исполнителя:",
            parse_mode="HTML",
            reply_markup=_build_assignee_keyboard(short_id),
        )

        await callback.answer()

    except Exception as e:
        logger.error(f"Error in callback_assign_back: {e}")
        await callback.answer("❌ Ошибка при возврате", show_alert=True)


@router.callback_query(F.data.startswith("assign:") & F.data.endswith(":cancel"))
async def callback_assign_cancel(callback: CallbackQuery, state: FSMContext) -> None:
    """Отмена назначения исполнителя."""
    try:
        callback_data = callback.data or ""
        parts = callback_data.split(":")
        short_id = parts[1]

        await callback.message.edit_text(  # type: ignore[union-attr]
            f"❌ <b>Назначение отменено</b>\n\n"
            f"📋 Задача [{short_id}] осталась без исполнителя.\n\n"
            f"💡 Вы можете назначить исполнителя позже командой <code>/assign {short_id}</code>",
            parse_mode="HTML",
        )

        await callback.answer("❌ Назначение отменено")
        await state.clear()

        logger.info(f"Cancelled assign for {short_id}")

    except Exception as e:
        logger.error(f"Error in callback_assign_cancel: {e}")
        await callback.answer("❌ Ошибка при отмене", show_alert=True)


# ====== ОБРАБОТЧИК РУЧНОГО ВВОДА ======


@router.message(AssignStates.waiting_for_assignee)
async def handle_manual_assignee_input(msg: Message, state: FSMContext) -> None:
    """Обработка ручного ввода исполнителя."""
    try:
        # Проверяем отмену
        if msg.text and msg.text.strip().lower() in ["/cancel", "отмена", "cancel"]:
            data = await state.get_data()
            short_id = data.get("assign_short_id", "unknown")

            await msg.answer(
                f"❌ <b>Ввод отменен</b>\n\n"
                f"📋 Задача [{short_id}] осталась без исполнителя.\n\n"
                f"💡 Вы можете назначить исполнителя позже командой <code>/assign {short_id}</code>",
                parse_mode="HTML",
            )
            await state.clear()
            return

        # Получаем данные из состояния
        data = await state.get_data()
        short_id = data.get("assign_short_id")

        if not short_id:
            await msg.answer("❌ Ошибка: потеряна информация о задаче. Начните заново с /assign")
            await state.clear()
            return

        # Проверяем что задача существует
        item = get_by_short_id(short_id)
        if not item:
            await msg.answer(f"❌ Карточка [{short_id}] не найдена. Проверьте /review.")
            await state.clear()
            return

        # Получаем введенные имена
        raw_names = (msg.text or "").strip()
        if not raw_names:
            await msg.answer("❌ Введите имя исполнителя или /cancel для отмены")
            return

        # Используем улучшенную логику из handlers.py
        from app.core.commit_normalize import normalize_assignees

        # Попытка 1: полное имя как есть
        full_name_normalized = normalize_assignees([raw_names.strip()], attendees_en=[])

        if full_name_normalized:
            # Полное имя найдено в словаре
            normalized_assignees = full_name_normalized
        else:
            # Попытка 2: разбиваем по пробелам и запятым
            raw_list = [x.strip() for x in raw_names.replace(",", " ").split() if x.strip()]
            normalized_assignees = normalize_assignees(raw_list, attendees_en=[])

        if not normalized_assignees:
            await msg.answer(
                f"❌ Не удалось распознать исполнителя(ей): {raw_names}\n\n"
                f"💡 Попробуйте ввести имя по-другому или используйте кнопки выбора.\n"
                f"Введите имя заново или /cancel для отмены."
            )
            return

        # Назначаем исполнителя
        success = update_fields(item["page_id"], assignees=normalized_assignees)

        if success:
            assignees_str = ", ".join(normalized_assignees)

            await msg.answer(
                f"✅ <b>Исполнитель назначен</b>\n\n"
                f"📋 <b>Задача [{short_id}]:</b> {item.get('text', '')[:100]}{'...' if len(item.get('text', '')) > 100 else ''}\n"
                f"👤 <b>Исполнитель:</b> {assignees_str}\n\n"
                f"💡 Теперь можете подтвердить задачу командой <code>/confirm {short_id}</code>",
                parse_mode="HTML",
            )

            logger.info(
                f"Manually assigned {assignees_str} to task {short_id} by user {msg.from_user.id if msg.from_user else 'unknown'}"
            )
        else:
            await msg.answer(
                f"❌ Не удалось обновить исполнителя для [{short_id}]. Попробуйте позже."
            )

        # Очищаем состояние
        await state.clear()

    except Exception as e:
        logger.error(f"Error in handle_manual_assignee_input: {e}")
        await msg.answer("❌ Ошибка при обработке ввода исполнителя.")
        await state.clear()


# ====== ОБРАБОТЧИК NOOP ======


@router.callback_query(F.data == "noop")
async def callback_noop(callback: CallbackQuery) -> None:
    """Обработчик для неактивных кнопок (например, индикатор страницы)."""
    await callback.answer()
