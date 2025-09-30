"""
Обработчики для People Miner v2 - улучшенная система управления кандидатами.

Основные возможности:
- Интерактивный просмотр кандидатов с сортировкой и пагинацией
- Батч-операции для быстрой обработки
- Контекстные сниппеты для принятия решений
- Статистика и мониторинг
- Интеграция с существующей системой админских прав
"""

from __future__ import annotations

import logging
import re
from typing import Any

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot.states.people_states import PeopleStates
from app.core.people_detect import propose_name_en
from app.core.people_miner2 import (
    approve_batch,
    approve_candidate,
    get_candidate_stats,
    list_candidates,
    reject_batch,
    reject_candidate,
)
from app.settings import settings

logger = logging.getLogger(__name__)

router = Router()

# Константы для UI
ITEMS_PER_PAGE = 1  # Показываем по одному кандидату для детального рассмотрения
MAX_CONTEXT_LENGTH = 150  # Максимальная длина контекста в карточке


def _is_admin(user_id: int | None) -> bool:
    """Проверяет, является ли пользователь администратором."""
    return settings.is_admin(user_id)


def _format_candidate_card(item: dict[str, Any], page: int, total: int, sort: str) -> str:
    """Форматирует карточку кандидата для отображения."""
    alias = item["alias"]
    freq = item["freq"]
    meetings = item["meetings"]
    last_seen = item["last_seen"]
    score = item["score"]
    samples = item.get("samples", [])

    # Форматируем контекст (берем последние 2 сниппета)
    context_lines = []
    for sample in samples[-2:]:
        snippet = sample["snippet"]
        if len(snippet) > MAX_CONTEXT_LENGTH:
            snippet = snippet[:MAX_CONTEXT_LENGTH] + "…"
        context_lines.append(f"• {sample['date']}: <i>{snippet}</i>")

    context_text = "\n".join(context_lines) if context_lines else "—"

    # Предлагаем каноническое английское имя
    suggested_name = propose_name_en(alias)

    return (
        f"👤 <b>Кандидат: {alias}</b>\n\n"
        f"📊 <b>Статистика:</b>\n"
        f"   🔢 Частота: {freq}\n"
        f"   📎 Встреч: {meetings}\n"
        f"   🕒 Последний раз: {last_seen}\n"
        f"   ⚖️ Score: {score:.2f}\n\n"
        f"💡 <b>Предлагаемое имя:</b> <code>{suggested_name}</code>\n\n"
        f"🧩 <b>Контекст:</b>\n{context_text}\n\n"
        f"📄 Страница {page} из {(total + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE} "
        f"| Сортировка: {'📅 по дате' if sort == 'date' else '📈 по частоте'}"
    )


def _create_navigation_keyboard(
    alias: str, page: int, total: int, sort: str
) -> InlineKeyboardMarkup:
    """Создает клавиатуру для навигации и действий."""
    total_pages = (total + ITEMS_PER_PAGE - 1) // ITEMS_PER_PAGE

    # Основные действия
    action_row = [
        InlineKeyboardButton(text="✅ Добавить", callback_data=f"pm2:add:{alias}:{page}:{sort}"),
        InlineKeyboardButton(text="❌ Отклонить", callback_data=f"pm2:rej:{alias}:{page}:{sort}"),
    ]

    # Кнопка для кастомного имени
    custom_row = [
        InlineKeyboardButton(text="✏️ Своё имя", callback_data=f"pm2:custom:{alias}:{page}:{sort}"),
    ]

    # Навигация
    nav_buttons = []
    if page > 1:
        nav_buttons.append(
            InlineKeyboardButton(text="⏮️ Назад", callback_data=f"pm2:nav:{page-1}:{sort}")
        )
    if page < total_pages:
        nav_buttons.append(
            InlineKeyboardButton(text="⏭️ Вперед", callback_data=f"pm2:nav:{page+1}:{sort}")
        )

    # Переключение сортировки
    sort_text = "📅 По дате" if sort == "freq" else "📈 По частоте"
    new_sort = "date" if sort == "freq" else "freq"
    sort_button = InlineKeyboardButton(text=sort_text, callback_data=f"pm2:sort:{page}:{new_sort}")

    # Батч-операции
    batch_row = [
        InlineKeyboardButton(text="🟩 Батч +5", callback_data=f"pm2:badd:5:{sort}"),
        InlineKeyboardButton(text="🟥 Батч −5", callback_data=f"pm2:brej:5:{sort}"),
    ]

    # Дополнительные действия
    extra_row = [
        InlineKeyboardButton(text="📊 Статистика", callback_data="pm2:stats"),
        InlineKeyboardButton(text="🚪 Выход", callback_data="pm2:exit"),
    ]

    keyboard = [action_row, custom_row]

    if nav_buttons:
        keyboard.append(nav_buttons)

    keyboard.extend([[sort_button], batch_row, extra_row])

    return InlineKeyboardMarkup(inline_keyboard=keyboard)


async def _show_candidate_page(
    message_or_callback: Message | CallbackQuery, page: int, sort: str, edit_message: bool = False
) -> None:
    """Показывает страницу с кандидатом."""
    items, total = list_candidates(sort=sort, page=page, per_page=ITEMS_PER_PAGE)

    if not items:
        no_candidates_text = (
            "🧩 <b>People Miner v2</b>\n\n"
            "❌ Кандидатов для обработки нет.\n\n"
            "💡 <i>Кандидаты появляются автоматически при обработке встреч.</i>"
        )

        if edit_message and isinstance(message_or_callback, CallbackQuery):
            if message_or_callback.message and hasattr(message_or_callback.message, "edit_text"):
                await message_or_callback.message.edit_text(no_candidates_text)
        else:
            await message_or_callback.answer(no_candidates_text)
        return

    item = items[0]
    card_text = _format_candidate_card(item, page, total, sort)
    keyboard = _create_navigation_keyboard(item["alias"], page, total, sort)

    if edit_message and isinstance(message_or_callback, CallbackQuery):
        if message_or_callback.message and hasattr(message_or_callback.message, "edit_text"):
            await message_or_callback.message.edit_text(
                card_text, reply_markup=keyboard, parse_mode="HTML"
            )
    else:
        await message_or_callback.answer(card_text, reply_markup=keyboard, parse_mode="HTML")


@router.message(F.text.regexp(r"^/people_miner2(\s+(freq|date))?$"))
async def people_miner_v2_start(message: Message, state: FSMContext) -> None:
    """Запускает People Miner v2."""
    if not _is_admin(message.from_user.id if message.from_user else None):
        await message.answer("❌ Команда доступна только администраторам")
        return

    # Парсим параметры
    parts = (message.text or "").strip().split()
    sort = "freq"  # По умолчанию

    if len(parts) >= 2 and parts[1] in ("freq", "date"):
        sort = parts[1]

    await state.set_state(PeopleStates.v2_reviewing)
    await state.update_data(current_page=1, current_sort=sort)

    await _show_candidate_page(message, page=1, sort=sort)

    user_id = message.from_user.id if message.from_user else "unknown"
    logger.info(f"Started People Miner v2 for user {user_id} with sort={sort}")


@router.callback_query(F.data.startswith("pm2:"))
async def people_miner_v2_callback(callback: CallbackQuery, state: FSMContext) -> None:
    """Обрабатывает все callback-и People Miner v2."""
    if not _is_admin(callback.from_user.id if callback.from_user else None):
        await callback.answer("❌ Недостаточно прав")
        return

    data_parts = (callback.data or "").split(":")
    if len(data_parts) < 2:
        await callback.answer("❌ Некорректные данные")
        return

    action = data_parts[1]

    try:
        if action == "nav":
            # Навигация: pm2:nav:page:sort
            page, sort = int(data_parts[2]), data_parts[3]
            await state.update_data(current_page=page, current_sort=sort)
            await _show_candidate_page(callback, page, sort, edit_message=True)
            await callback.answer(f"Страница {page}")

        elif action == "sort":
            # Переключение сортировки: pm2:sort:page:new_sort
            page, sort = int(data_parts[2]), data_parts[3]
            await state.update_data(current_page=page, current_sort=sort)
            await _show_candidate_page(callback, page, sort, edit_message=True)
            sort_name = "по дате" if sort == "date" else "по частоте"
            await callback.answer(f"Сортировка: {sort_name}")

        elif action == "add":
            # Добавление кандидата: pm2:add:alias:page:sort
            alias, page, sort = data_parts[2], int(data_parts[3]), data_parts[4]

            # Предлагаем каноническое имя и добавляем
            suggested_name = propose_name_en(alias)
            success = approve_candidate(alias, name_en=suggested_name)

            if success:
                await callback.answer(f"✅ Добавлен: {alias} → {suggested_name}")
                logger.info(f"Approved candidate {alias} as {suggested_name}")

                # Показываем следующего кандидата
                await _show_candidate_page(callback, page, sort, edit_message=True)
            else:
                await callback.answer("❌ Ошибка при добавлении")

        elif action == "rej":
            # Отклонение кандидата: pm2:rej:alias:page:sort
            alias, page, sort = data_parts[2], int(data_parts[3]), data_parts[4]

            success = reject_candidate(alias)
            if success:
                await callback.answer(f"❌ Отклонен: {alias}")
                logger.info(f"Rejected candidate {alias}")

                # Показываем следующего кандидата
                await _show_candidate_page(callback, page, sort, edit_message=True)
            else:
                await callback.answer("❌ Ошибка при отклонении")

        elif action == "badd":
            # Батч добавление: pm2:badd:count:sort
            count, sort = int(data_parts[2]), data_parts[3]

            result = approve_batch(top_n=count, sort=sort)
            await callback.answer(f"🟩 Батч добавлен: {result['added']}/{result['selected']}")
            logger.info(f"Batch approved {result['added']}/{result['selected']} candidates")

            # Обновляем отображение
            await _show_candidate_page(callback, 1, sort, edit_message=True)

        elif action == "brej":
            # Батч отклонение: pm2:brej:count:sort
            count, sort = int(data_parts[2]), data_parts[3]

            result = reject_batch(top_n=count, sort=sort)
            await callback.answer(f"🟥 Батч отклонен: {result['removed']}/{result['selected']}")
            logger.info(f"Batch rejected {result['removed']}/{result['selected']} candidates")

            # Обновляем отображение
            await _show_candidate_page(callback, 1, sort, edit_message=True)

        elif action == "stats":
            # Статистика
            stats = get_candidate_stats()

            stats_text = (
                f"📊 <b>Статистика People Miner v2</b>\n\n"
                f"👥 <b>Всего кандидатов:</b> {stats['total']}\n"
                f"📈 <b>Средняя частота:</b> {stats['avg_freq']:.1f}\n"
                f"📎 <b>Среднее встреч:</b> {stats['avg_meetings']:.1f}\n"
                f"🕒 <b>Недавних:</b> {stats['recent_candidates']}\n\n"
                f"📋 <b>По частоте:</b>\n"
                f"   🔴 Высокая (больше 5): {stats['freq_distribution']['high']}\n"
                f"   🟡 Средняя (2-4): {stats['freq_distribution']['medium']}\n"
                f"   🟢 Низкая (меньше 2): {stats['freq_distribution']['low']}"
            )

            if callback.message:
                await callback.message.answer(stats_text, parse_mode="HTML")
            await callback.answer("📊 Статистика показана")

        elif action == "custom":
            # Запрос кастомного имени: pm2:custom:alias:page:sort
            alias, page, sort = data_parts[2], int(data_parts[3]), data_parts[4]

            await state.update_data(pending_alias=alias, current_page=page, current_sort=sort)
            await state.set_state(PeopleStates.v2_waiting_custom_name)

            suggested_name = propose_name_en(alias)
            if callback.message:
                await callback.message.answer(
                    f"✏️ <b>Ввод кастомного имени</b>\n\n"
                    f"👤 <b>Кандидат:</b> {alias}\n"
                    f"💡 <b>Предлагается:</b> <code>{suggested_name}</code>\n\n"
                    f"✏️ <b>Введите своё каноническое английское имя:</b>\n"
                    f"Например: <code>John Smith</code>\n\n"
                    f"<i>Используйте только латинские буквы и пробелы</i>",
                    parse_mode="HTML",
                )
            await callback.answer("Введите кастомное имя")

        elif action == "exit":
            # Выход
            await state.set_state(PeopleStates.idle)
            if callback.message and hasattr(callback.message, "edit_text"):
                await callback.message.edit_text(
                    "🧩 <b>People Miner v2</b>\n\n"
                    "👋 <b>Работа завершена</b>\n\n"
                    "Используйте <code>/people_miner2</code> для повторного запуска.",
                    parse_mode="HTML",
                )
            await callback.answer("Работа завершена")

        else:
            await callback.answer("❌ Неизвестное действие")

    except (ValueError, IndexError) as e:
        logger.error(f"Error processing People Miner v2 callback: {e}")
        await callback.answer("❌ Ошибка обработки команды")
    except Exception as e:
        logger.exception(f"Unexpected error in People Miner v2: {e}")
        await callback.answer("❌ Произошла ошибка")


@router.message(F.text == "/people_stats_v2")
async def people_stats_v2_handler(message: Message) -> None:
    """Показывает расширенную статистику People Miner v2."""
    if not _is_admin(message.from_user.id if message.from_user else None):
        await message.answer("❌ Команда доступна только администраторам")
        return

    try:
        stats = get_candidate_stats()
        items, total = list_candidates(sort="freq", page=1, per_page=5)

        # Основная статистика
        stats_text = (
            f"📊 <b>People Miner v2 - Подробная статистика</b>\n\n"
            f"👥 <b>Кандидаты:</b> {stats['total']}\n"
            f"📈 <b>Средняя частота:</b> {stats['avg_freq']:.1f}\n"
            f"📎 <b>Среднее встреч:</b> {stats['avg_meetings']:.1f}\n"
            f"🕒 <b>Недавние (≤3 дня):</b> {stats['recent_candidates']}\n\n"
            f"📋 <b>Распределение по частоте:</b>\n"
            f"   🔴 Высокая (≥5): {stats['freq_distribution']['high']}\n"
            f"   🟡 Средняя (2-4): {stats['freq_distribution']['medium']}\n"
            f"   🟢 Низкая (<2): {stats['freq_distribution']['low']}\n\n"
        )

        # Топ кандидаты
        if items:
            stats_text += f"🏆 <b>Топ-{len(items)} кандидатов:</b>\n"
            for i, item in enumerate(items, 1):
                stats_text += (
                    f"{i}. <b>{item['alias']}</b> "
                    f"(freq: {item['freq']}, score: {item['score']:.1f})\n"
                )
        else:
            stats_text += "🏆 <b>Кандидатов нет</b>"

        await message.answer(stats_text, parse_mode="HTML")

        user_id = message.from_user.id if message.from_user else "unknown"
        logger.info(f"People Miner v2 stats requested by user {user_id}")

    except Exception as e:
        logger.exception(f"Error in people_stats_v2_handler: {e}")
        await message.answer("❌ Ошибка получения статистики")


@router.message(PeopleStates.v2_waiting_custom_name)
async def handle_custom_name_input(message: Message, state: FSMContext) -> None:
    """Обрабатывает ввод кастомного имени для кандидата."""
    if not _is_admin(message.from_user.id if message.from_user else None):
        await message.answer("❌ Недостаточно прав")
        await state.clear()
        return

    data = await state.get_data()
    pending_alias = data.get("pending_alias")
    page = data.get("current_page", 1)
    sort = data.get("current_sort", "freq")
    custom_name = (message.text or "").strip()

    if not pending_alias:
        await message.answer(
            "❌ <b>Ошибка состояния</b>\n\n"
            "Данные о кандидате потеряны. Начните заново с <code>/people_miner2</code>",
            parse_mode="HTML",
        )
        await state.clear()
        return

    # Валидация имени
    if not custom_name or not re.match(r"^[A-Za-z\s\-'\.]+$", custom_name):
        await message.answer(
            "❌ <b>Некорректное имя</b>\n\n"
            "Используйте только латинские буквы, пробелы, дефисы и апострофы.\n"
            "Например: <code>John Smith</code> или <code>Mary-Jane O'Connor</code>\n\n"
            "Попробуйте еще раз:",
            parse_mode="HTML",
        )
        return

    # Добавляем кандидата с кастомным именем
    success = approve_candidate(pending_alias, name_en=custom_name)

    if success:
        await message.answer(
            f"✅ <b>Кандидат добавлен с кастомным именем</b>\n\n"
            f"👤 <b>Алиас:</b> {pending_alias}\n"
            f"🏷️ <b>Каноническое имя:</b> {custom_name}\n"
            f"📊 <b>Тег:</b> <code>People/{custom_name}</code>\n\n"
            f"Возвращаемся к списку кандидатов...",
            parse_mode="HTML",
        )
        logger.info(f"Approved candidate {pending_alias} with custom name {custom_name}")
    else:
        await message.answer(
            "❌ <b>Ошибка добавления</b>\n\n" "Не удалось добавить кандидата. Попробуйте еще раз.",
            parse_mode="HTML",
        )

    # Возвращаемся к просмотру кандидатов
    await state.set_state(PeopleStates.v2_reviewing)
    await _show_candidate_page(message, page, sort)


@router.message(F.text == "/people_clear_v2")
async def people_clear_v2_handler(message: Message) -> None:
    """Очищает всех кандидатов (только для администраторов)."""
    if not _is_admin(message.from_user.id if message.from_user else None):
        await message.answer("❌ Команда доступна только администраторам")
        return

    try:
        from app.core.people_miner2 import clear_candidates

        clear_candidates()
        await message.answer(
            "🧹 <b>Кандидаты очищены</b>\n\n"
            "Все кандидаты удалены из системы.\n"
            "Новые кандидаты будут собираться при обработке встреч."
        )

        user_id = message.from_user.id if message.from_user else "unknown"
        logger.info(f"People Miner v2 candidates cleared by user {user_id}")

    except Exception as e:
        logger.exception(f"Error in people_clear_v2_handler: {e}")
        await message.answer("❌ Ошибка очистки кандидатов")
