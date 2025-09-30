"""Обработчики для создания прямых коммитов без транскрипта встречи."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot.states.commit_states import DirectCommitStates
from app.core.commit_normalize import build_key, build_title, validate_date_iso
from app.core.people_store import canonicalize_list, load_people
from app.core.tags import tag_text_for_commit
from app.gateways.notion_commits_async import upsert_commits_async
from app.gateways.notion_gateway import upsert_meeting

logger = logging.getLogger(__name__)

router = Router()


def _get_people_suggestions() -> list[str]:
    """Получает список людей для подсказок."""
    try:
        people = load_people()
        return [person.get("name_en", "") for person in people if person.get("name_en")][:10]
    except Exception as e:
        logger.warning(f"Failed to load people suggestions: {e}")
        return []


def _build_people_keyboard(suggestions: list[str], callback_prefix: str) -> InlineKeyboardMarkup:
    """Создает клавиатуру с подсказками людей."""
    buttons = []

    # Добавляем подсказки людей (по 2 в ряд)
    for i in range(0, min(len(suggestions), 6), 2):
        row = []
        for j in range(i, min(i + 2, len(suggestions))):
            person = suggestions[j]
            row.append(
                InlineKeyboardButton(text=person, callback_data=f"{callback_prefix}:{person}")
            )
        if row:
            buttons.append(row)

    # Кнопки управления
    buttons.append(
        [
            InlineKeyboardButton(
                text="✍️ Ввести вручную", callback_data=f"{callback_prefix}:manual"
            ),
            InlineKeyboardButton(text="📝 Самостоятельно", callback_data=f"{callback_prefix}:self"),
        ]
    )
    buttons.append(
        [
            InlineKeyboardButton(text="❌ Отмена", callback_data="direct_commit:cancel"),
        ]
    )

    return InlineKeyboardMarkup(inline_keyboard=buttons)


def _build_confirm_keyboard() -> InlineKeyboardMarkup:
    """Создает клавиатуру подтверждения."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Создать", callback_data="direct_commit:confirm"),
                InlineKeyboardButton(text="✏️ Редактировать", callback_data="direct_commit:edit"),
            ],
            [
                InlineKeyboardButton(text="❌ Отмена", callback_data="direct_commit:cancel"),
            ],
        ]
    )


def _build_edit_keyboard() -> InlineKeyboardMarkup:
    """Создает клавиатуру редактирования."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📝 Текст", callback_data="direct_commit:edit:text"),
                InlineKeyboardButton(text="👤 Заказчик", callback_data="direct_commit:edit:from"),
            ],
            [
                InlineKeyboardButton(text="👥 Исполнитель", callback_data="direct_commit:edit:to"),
                InlineKeyboardButton(text="⏰ Дедлайн", callback_data="direct_commit:edit:due"),
            ],
            [
                InlineKeyboardButton(text="✅ Готово", callback_data="direct_commit:confirm"),
                InlineKeyboardButton(text="❌ Отмена", callback_data="direct_commit:cancel"),
            ],
        ]
    )


async def _create_direct_meeting() -> str:
    """Создает или переиспользует единую встречу 'Direct Commits' для всех прямых коммитов."""
    try:
        # Используем фиксированный хеш для единой встречи Direct Commits
        # Это позволит upsert_meeting переиспользовать существующую встречу
        DIRECT_COMMITS_HASH = "direct-commits-permanent-meeting"

        direct_meeting_data = {
            "title": "Direct Commits (Прямые коммиты)",
            "date": "2025-01-01",  # Фиксированная дата для постоянной встречи
            "attendees": ["System"],
            "source": "direct_commit",
            "raw_hash": DIRECT_COMMITS_HASH,  # Фиксированный хеш для дедупликации
            "summary_md": "Постоянная встреча для всех прямых коммитов, созданных через команду /commit. Позволяет избежать замусоривания базы данных Meetings.",
            "tags": ["Topic/Direct"],
        }

        notion_url = upsert_meeting(direct_meeting_data)

        # Извлекаем page_id из URL
        from app.bot.handlers import _extract_page_id_from_url

        return _extract_page_id_from_url(notion_url)

    except Exception as e:
        logger.error(f"Failed to create direct meeting: {e}")
        raise RuntimeError("Не удалось создать встречу для прямого коммита") from e


@router.message(F.text == "/commit")
async def start_direct_commit(message: Message, state: FSMContext) -> None:
    """Запускает процесс создания прямого коммита."""
    await state.clear()

    await message.answer(
        "📝 <b>Создание прямого коммита</b>\n\n"
        "✍️ <b>Шаг 1/4:</b> Введите текст коммита\n\n"
        "💡 <i>Например: 'Подготовить отчет по продажам до пятницы'</i>",
        parse_mode="HTML",
    )

    await state.set_state(DirectCommitStates.waiting_text)
    logger.info(
        f"User {message.from_user.id if message.from_user else 'unknown'} started direct commit creation"
    )


@router.message(DirectCommitStates.waiting_text, F.text)
async def set_commit_text(message: Message, state: FSMContext) -> None:
    """Обрабатывает ввод текста коммита."""
    if not message.text or not message.text.strip():
        await message.answer("❌ Текст коммита не может быть пустым. Попробуйте еще раз:")
        return

    text = message.text.strip()
    await state.update_data(text=text)

    # Получаем подсказки людей
    suggestions = _get_people_suggestions()
    keyboard = _build_people_keyboard(suggestions, "direct_commit:from")

    await message.answer(
        "👤 <b>Шаг 2/4:</b> Кто поставил задачу?\n\n"
        "💡 <i>Выберите заказчика или укажите тип задачи:</i>",
        reply_markup=keyboard,
        parse_mode="HTML",
    )

    await state.set_state(DirectCommitStates.waiting_from)


@router.callback_query(DirectCommitStates.waiting_from, F.data.startswith("direct_commit:from:"))
async def set_from_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """Обрабатывает выбор отправителя через кнопку."""
    await callback.answer()

    if not callback.data:
        return

    choice = callback.data.split(":", 2)[2]

    if choice == "manual":
        if callback.message:
            await callback.message.edit_text(  # type: ignore[union-attr]  # type: ignore[union-attr]
                "👤 <b>Шаг 2/4:</b> Кто поставил задачу?\n\n" "✍️ Введите имя заказчика:",
                parse_mode="HTML",
            )
        return

    if choice == "self":
        # Самостоятельная задача - заказчик = исполнитель
        current_user = callback.from_user.first_name if callback.from_user else "Пользователь"
        choice = f"{current_user} (самостоятельно)"

    # Выбран конкретный человек
    await state.update_data(from_person=choice)

    # Переходим к следующему шагу
    suggestions = _get_people_suggestions()
    keyboard = _build_people_keyboard(suggestions, "direct_commit:to")

    if callback.message:
        await callback.message.edit_text(  # type: ignore[union-attr]
            f"✅ <b>Заказчик:</b> {choice}\n\n"
            "👥 <b>Шаг 3/4:</b> Кто исполнитель?\n\n"
            "💡 <i>Выберите, кто будет выполнять задачу:</i>",
            reply_markup=keyboard,
            parse_mode="HTML",
        )

    await state.set_state(DirectCommitStates.waiting_to)


@router.message(DirectCommitStates.waiting_from, F.text)
async def set_from_manual(message: Message, state: FSMContext) -> None:
    """Обрабатывает ручной ввод отправителя."""
    if not message.text or not message.text.strip():
        await message.answer("❌ Имя заказчика не может быть пустым. Попробуйте еще раз:")
        return

    from_person = message.text.strip()
    await state.update_data(from_person=from_person)

    # Переходим к следующему шагу
    suggestions = _get_people_suggestions()
    keyboard = _build_people_keyboard(suggestions, "direct_commit:to")

    await message.answer(
        f"✅ <b>Заказчик:</b> {from_person}\n\n"
        "👥 <b>Шаг 3/4:</b> Кто исполнитель?\n\n"
        "💡 <i>Выберите, кто будет выполнять задачу:</i>",
        reply_markup=keyboard,
        parse_mode="HTML",
    )

    await state.set_state(DirectCommitStates.waiting_to)


@router.callback_query(DirectCommitStates.waiting_to, F.data.startswith("direct_commit:to:"))
async def set_to_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """Обрабатывает выбор исполнителя через кнопку."""
    await callback.answer()

    if not callback.data:
        return

    choice = callback.data.split(":", 2)[2]

    if choice == "manual":
        if callback.message:
            await callback.message.edit_text(  # type: ignore[union-attr]  # type: ignore[union-attr]
                "👥 <b>Шаг 3/4:</b> Кто исполнитель?\n\n" "✍️ Введите имя исполнителя:",
                parse_mode="HTML",
            )
        return

    if choice == "self":
        # Самостоятельное выполнение - исполнитель = текущий пользователь
        current_user = callback.from_user.first_name if callback.from_user else "Пользователь"
        choice = f"{current_user} (сам)"

    # Выбран конкретный человек
    await state.update_data(to_person=choice)

    # Переходим к дедлайну
    due_keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📅 Сегодня", callback_data="direct_commit:due:today"),
                InlineKeyboardButton(text="📅 Завтра", callback_data="direct_commit:due:tomorrow"),
            ],
            [
                InlineKeyboardButton(
                    text="📅 Эта неделя", callback_data="direct_commit:due:this_week"
                ),
                InlineKeyboardButton(
                    text="📅 След. неделя", callback_data="direct_commit:due:next_week"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="✍️ Ввести дату", callback_data="direct_commit:due:manual"
                ),
                InlineKeyboardButton(text="⏭️ Без дедлайна", callback_data="direct_commit:due:skip"),
            ],
            [
                InlineKeyboardButton(text="❌ Отмена", callback_data="direct_commit:cancel"),
            ],
        ]
    )

    if callback.message:
        await callback.message.edit_text(  # type: ignore[union-attr]
            f"✅ <b>Исполнитель:</b> {choice}\n\n"
            "⏰ <b>Шаг 4/4:</b> Дедлайн коммита\n\n"
            "💡 <i>Выберите или введите дату:</i>",
            reply_markup=due_keyboard,
            parse_mode="HTML",
        )

    await state.set_state(DirectCommitStates.waiting_due)


@router.message(DirectCommitStates.waiting_to, F.text)
async def set_to_manual(message: Message, state: FSMContext) -> None:
    """Обрабатывает ручной ввод исполнителя."""
    if not message.text or not message.text.strip():
        await message.answer("❌ Имя исполнителя не может быть пустым. Попробуйте еще раз:")
        return

    to_person = message.text.strip()
    await state.update_data(to_person=to_person)

    # Переходим к дедлайну
    due_keyboard = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📅 Сегодня", callback_data="direct_commit:due:today"),
                InlineKeyboardButton(text="📅 Завтра", callback_data="direct_commit:due:tomorrow"),
            ],
            [
                InlineKeyboardButton(
                    text="📅 Эта неделя", callback_data="direct_commit:due:this_week"
                ),
                InlineKeyboardButton(
                    text="📅 След. неделя", callback_data="direct_commit:due:next_week"
                ),
            ],
            [
                InlineKeyboardButton(
                    text="✍️ Ввести дату", callback_data="direct_commit:due:manual"
                ),
                InlineKeyboardButton(text="⏭️ Без дедлайна", callback_data="direct_commit:due:skip"),
            ],
            [
                InlineKeyboardButton(text="❌ Отмена", callback_data="direct_commit:cancel"),
            ],
        ]
    )

    await message.answer(
        f"✅ <b>Исполнитель:</b> {to_person}\n\n"
        "⏰ <b>Шаг 4/4:</b> Дедлайн коммита\n\n"
        "💡 <i>Выберите или введите дату:</i>",
        reply_markup=due_keyboard,
        parse_mode="HTML",
    )

    await state.set_state(DirectCommitStates.waiting_due)


@router.callback_query(DirectCommitStates.waiting_due, F.data.startswith("direct_commit:due:"))
async def set_due_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """Обрабатывает выбор дедлайна через кнопку."""
    await callback.answer()

    if not callback.data:
        return

    choice = callback.data.split(":", 2)[2]

    if choice == "manual":
        if callback.message:
            await callback.message.edit_text(  # type: ignore[union-attr]  # type: ignore[union-attr]
                "⏰ <b>Шаг 4/4:</b> Дедлайн коммита\n\n"
                "✍️ Введите дату в формате:\n"
                "• <code>2025-10-15</code>\n"
                "• <code>15.10.2025</code>\n"
                "• <code>15 октября</code>\n"
                "• <code>завтра</code>\n\n"
                "Или <code>/skip</code> для пропуска:",
                parse_mode="HTML",
            )
        return

    # Обрабатываем предустановленные варианты
    from datetime import date, timedelta

    today = date.today()
    due_iso = None

    if choice == "today":
        due_iso = today.isoformat()
    elif choice == "tomorrow":
        due_iso = (today + timedelta(days=1)).isoformat()
    elif choice == "this_week":
        # Пятница текущей недели
        days_until_friday = (4 - today.weekday()) % 7
        if days_until_friday == 0:  # Сегодня пятница
            days_until_friday = 7  # Следующая пятница
        due_iso = (today + timedelta(days=days_until_friday)).isoformat()
    elif choice == "next_week":
        # Пятница следующей недели
        days_until_next_friday = (4 - today.weekday()) % 7 + 7
        due_iso = (today + timedelta(days=days_until_next_friday)).isoformat()
    elif choice == "skip":
        due_iso = None

    await state.update_data(due_iso=due_iso)
    if callback.message:
        await _show_confirmation(callback.message, state)  # type: ignore[arg-type]


@router.message(DirectCommitStates.waiting_due, F.text)
async def set_due_manual(message: Message, state: FSMContext) -> None:
    """Обрабатывает ручной ввод дедлайна."""
    if message.text and message.text.strip().lower() in ["/skip", "skip", "пропустить"]:
        await state.update_data(due_iso=None)
        await _show_confirmation(message, state)
        return

    # Валидируем дату
    due_iso = validate_date_iso(message.text.strip()) if message.text else None

    if not due_iso and message.text and message.text.strip():
        await message.answer(
            "❌ Неверный формат даты. Попробуйте:\n"
            "• <code>2025-10-15</code>\n"
            "• <code>15.10.2025</code>\n"
            "• <code>15 октября</code>\n"
            "• <code>/skip</code> для пропуска",
            parse_mode="HTML",
        )
        return

    await state.update_data(due_iso=due_iso)
    await _show_confirmation(message, state)


async def _show_confirmation(message: Message, state: FSMContext) -> None:
    """Показывает экран подтверждения коммита."""
    data = await state.get_data()

    # Форматируем данные для отображения
    text = data.get("text", "—")
    from_person = data.get("from_person", "—")
    to_person = data.get("to_person", "—")
    due_iso = data.get("due_iso")

    # Форматируем дедлайн
    if due_iso:
        try:
            from datetime import datetime

            due_date = datetime.fromisoformat(due_iso)
            due_formatted = due_date.strftime("%d.%m.%Y")
        except (ValueError, TypeError):
            due_formatted = str(due_iso)
    else:
        due_formatted = "—"

    # Определяем направление
    # Простая эвристика: если заказчик содержит "valya/валя/valentin" - это mine
    from_lower = from_person.lower()
    direction = (
        "mine"
        if any(name in from_lower for name in ["valya", "валя", "valentin", "валентин"])
        else "theirs"
    )
    direction_text = "📤 мой" if direction == "mine" else "📥 чужой"

    # Предварительный просмотр тегов
    try:
        preview_tags = tag_text_for_commit(text)
        tags_preview = ", ".join(preview_tags[:3])
        if len(preview_tags) > 3:
            tags_preview += f" <i>+{len(preview_tags) - 3}</i>"
        tags_text = f"🏷️ <b>Теги:</b> {tags_preview}\n" if preview_tags else ""
    except Exception:
        tags_text = ""

    confirmation_text = (
        "📋 <b>Подтверждение коммита</b>\n\n"
        f"📝 <b>Текст:</b> {text}\n"
        f"👤 <b>Заказчик:</b> {from_person}\n"
        f"👥 <b>Исполнитель:</b> {to_person}\n"
        f"⏰ <b>Дедлайн:</b> {due_formatted}\n"
        f"🎯 <b>Направление:</b> {direction_text}\n"
        f"{tags_text}\n"
        "✅ Создать коммит?"
    )

    await state.set_state(DirectCommitStates.confirm)

    if hasattr(message, "edit_text"):
        await message.edit_text(
            confirmation_text, reply_markup=_build_confirm_keyboard(), parse_mode="HTML"
        )
    else:
        await message.answer(
            confirmation_text, reply_markup=_build_confirm_keyboard(), parse_mode="HTML"
        )


@router.callback_query(DirectCommitStates.confirm, F.data == "direct_commit:confirm")
async def confirm_direct_commit(callback: CallbackQuery, state: FSMContext) -> None:
    """Создает прямой коммит в Notion."""
    await callback.answer()

    try:
        data = await state.get_data()

        # Валидируем данные
        text = data.get("text", "").strip()
        from_person = data.get("from_person", "").strip()
        to_person = data.get("to_person", "").strip()
        due_iso = data.get("due_iso")

        if not all([text, from_person, to_person]):
            if callback.message:
                await callback.message.edit_text(  # type: ignore[union-attr]
                    "❌ <b>Ошибка:</b> Не все обязательные поля заполнены", parse_mode="HTML"
                )
            return

        # Канонизируем имена
        to_canonical = canonicalize_list([to_person])

        # Определяем направление
        from_lower = from_person.lower()
        direction = (
            "mine"
            if any(name in from_lower for name in ["valya", "валя", "valentin", "валентин"])
            else "theirs"
        )

        # Генерируем ключ и заголовок
        assignees = to_canonical
        key = build_key(text, assignees, due_iso)
        title = build_title(direction, text, assignees, due_iso)

        # Генерируем теги
        tags = tag_text_for_commit(text)

        # Создаем или получаем Direct встречу
        direct_meeting_id = await _create_direct_meeting()

        # Подготавливаем данные коммита
        commit_data = {
            "title": title,
            "text": text,
            "direction": direction,
            "assignees": assignees,
            "from_person": [from_person],  # Заказчик (кто поставил задачу)
            "due_iso": due_iso,
            "confidence": 1.0,  # Прямые коммиты имеют максимальную уверенность
            "flags": ["direct"],  # Флаг для отличия от извлеченных коммитов
            "key": key,
            "status": "open",
            "tags": tags,
        }

        # Сохраняем в Notion
        result = await upsert_commits_async(direct_meeting_id, [commit_data])
        created = result.get("created", [])
        updated = result.get("updated", [])

        if created or updated:
            # Формируем ответ с красивым форматированием
            from app.bot.formatters import format_commit_card, format_success_card

            success_details = {
                "created": len(created),
                "updated": len(updated),
                "commit_id": created[0] if created else updated[0] if updated else "unknown",
                "tags_count": len(tags),
                "direction": direction,
            }

            success_message = format_success_card("Прямой коммит создан!", success_details)

            # Показываем карточку созданного коммита
            commit_card = format_commit_card(
                {
                    "text": text,
                    "status": "open",
                    "direction": direction,
                    "assignees": assignees,
                    "from_person": [from_person],  # Добавляем заказчика
                    "due_iso": due_iso,
                    "confidence": 1.0,
                    "tags": tags,
                    "short_id": key[:8],
                }
            )

            if callback.message:
                await callback.message.edit_text(success_message, parse_mode="HTML")  # type: ignore[union-attr]
                await callback.message.answer(
                    f"📝 <b>Созданный коммит:</b>\n\n{commit_card}", parse_mode="HTML"
                )

            user_id = callback.from_user.id if callback.from_user else None
            logger.info(
                f"Direct commit created by user {user_id}: '{text}' "
                f"from {from_person} to {to_person}, due {due_iso or 'none'}"
            )
        else:
            if callback.message:
                await callback.message.edit_text(  # type: ignore[union-attr]
                    "❌ <b>Ошибка создания коммита</b>\n\n"
                    "Попробуйте еще раз или обратитесь к администратору.",
                    parse_mode="HTML",
                )

    except Exception as e:
        logger.error(f"Error creating direct commit: {e}")
        if callback.message:
            await callback.message.edit_text(  # type: ignore[union-attr]  # type: ignore[union-attr]
                f"❌ <b>Ошибка создания коммита</b>\n\n" f"<code>{str(e)}</code>", parse_mode="HTML"
            )
    finally:
        await state.clear()


@router.callback_query(DirectCommitStates.confirm, F.data == "direct_commit:edit")
async def edit_direct_commit(callback: CallbackQuery, state: FSMContext) -> None:
    """Показывает меню редактирования коммита."""
    await callback.answer()

    data = await state.get_data()

    edit_text = (
        "✏️ <b>Редактирование коммита</b>\n\n"
        f"📝 <b>Текст:</b> {data.get('text', '—')}\n"
        f"👤 <b>Заказчик:</b> {data.get('from_person', '—')}\n"
        f"👥 <b>Исполнитель:</b> {data.get('to_person', '—')}\n"
        f"⏰ <b>Дедлайн:</b> {data.get('due_iso', '—')}\n\n"
        "Что хотите изменить?"
    )

    if callback.message:
        await callback.message.edit_text(  # type: ignore[union-attr]
            edit_text, reply_markup=_build_edit_keyboard(), parse_mode="HTML"
        )


@router.callback_query(F.data.startswith("direct_commit:edit:"))
async def handle_edit_field(callback: CallbackQuery, state: FSMContext) -> None:
    """Обрабатывает редактирование конкретного поля."""
    await callback.answer()

    if not callback.data:
        return

    field = callback.data.split(":", 2)[2]

    if field == "text":
        if callback.message:
            await callback.message.edit_text(  # type: ignore[union-attr]  # type: ignore[union-attr]
                "📝 <b>Редактирование текста</b>\n\n" "✍️ Введите новый текст коммита:",
                parse_mode="HTML",
            )
        await state.set_state(DirectCommitStates.waiting_text)
    elif field == "from":
        suggestions = _get_people_suggestions()
        keyboard = _build_people_keyboard(suggestions, "direct_commit:from")
        if callback.message:
            await callback.message.edit_text(  # type: ignore[union-attr]  # type: ignore[union-attr]
                "👤 <b>Редактирование заказчика</b>\n\n" "💡 <i>Выберите или введите:</i>",
                reply_markup=keyboard,
                parse_mode="HTML",
            )
        await state.set_state(DirectCommitStates.waiting_from)
    elif field == "to":
        suggestions = _get_people_suggestions()
        keyboard = _build_people_keyboard(suggestions, "direct_commit:to")
        if callback.message:
            await callback.message.edit_text(  # type: ignore[union-attr]  # type: ignore[union-attr]
                "👥 <b>Редактирование исполнителя</b>\n\n" "💡 <i>Выберите или введите:</i>",
                reply_markup=keyboard,
                parse_mode="HTML",
            )
        await state.set_state(DirectCommitStates.waiting_to)
    elif field == "due":
        due_keyboard = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(
                        text="📅 Сегодня", callback_data="direct_commit:due:today"
                    ),
                    InlineKeyboardButton(
                        text="📅 Завтра", callback_data="direct_commit:due:tomorrow"
                    ),
                ],
                [
                    InlineKeyboardButton(
                        text="✍️ Ввести дату", callback_data="direct_commit:due:manual"
                    ),
                    InlineKeyboardButton(
                        text="⏭️ Без дедлайна", callback_data="direct_commit:due:skip"
                    ),
                ],
                [
                    InlineKeyboardButton(text="❌ Отмена", callback_data="direct_commit:cancel"),
                ],
            ]
        )
        if callback.message:
            await callback.message.edit_text(  # type: ignore[union-attr]  # type: ignore[union-attr]
                "⏰ <b>Редактирование дедлайна</b>\n\n" "💡 <i>Выберите или введите дату:</i>",
                reply_markup=due_keyboard,
                parse_mode="HTML",
            )
        await state.set_state(DirectCommitStates.waiting_due)


@router.callback_query(F.data == "direct_commit:cancel")
async def cancel_direct_commit(callback: CallbackQuery, state: FSMContext) -> None:
    """Отменяет создание прямого коммита."""
    await callback.answer()
    await state.clear()

    if callback.message:
        await callback.message.edit_text(  # type: ignore[union-attr]
            "❌ <b>Создание коммита отменено</b>\n\n"
            "💡 <i>Используйте /commit для создания нового</i>",
            parse_mode="HTML",
        )

    user_id = callback.from_user.id if callback.from_user else "unknown"
    logger.info(f"Direct commit creation cancelled by user {user_id}")
