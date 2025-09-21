"""Обработчики для работы с людьми и кандидатами в Telegram боте."""

from __future__ import annotations

import logging
import re
from typing import Any

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.bot.states.people_states import PeopleStates
from app.core.people_store import (
    delete_candidate_by_id,
    get_candidate_by_id,
    load_candidates_raw,
    load_people_raw,
    save_people_raw,
)

logger = logging.getLogger(__name__)

router = Router()


def _validate_en_name(name: str) -> bool:
    """Валидирует английское имя (только буквы и пробелы)."""
    return bool(re.match(r"^[A-Za-z\s]+$", name.strip()))


def _format_candidate_message(cand: dict[str, Any], index: int, total: int) -> str:
    """Форматирует сообщение с информацией о кандидате."""
    return (
        f"🧩 <b>Кандидат {index}/{total}</b>\n\n"
        f"👤 <b>Имя:</b> {cand.get('alias', 'N/A')}\n"
        f"📊 <b>Частота:</b> {cand.get('freq', 0)}\n"
        f"📝 <b>Контекст:</b> {cand.get('context', '—')[:100]}{'...' if len(cand.get('context', '')) > 100 else ''}\n"
        f"🆔 <b>ID:</b> <code>{cand.get('id', 'N/A')}</code>\n"
        f"📍 <b>Источник:</b> {cand.get('source', 'unknown')}"
    )


def _create_candidate_keyboard(cid: str) -> InlineKeyboardMarkup:
    """Создает клавиатуру для действий с кандидатом."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Добавить", callback_data=f"pm_add:{cid}"),
                InlineKeyboardButton(text="❌ Удалить", callback_data=f"pm_del:{cid}"),
            ],
            [
                InlineKeyboardButton(text="⏭ Пропустить", callback_data=f"pm_skip:{cid}"),
            ],
            [
                InlineKeyboardButton(text="📊 Статистика", callback_data="pm_stats"),
                InlineKeyboardButton(text="🚪 Выход", callback_data="pm_exit"),
            ],
        ]
    )


def _pick_next_candidate(exclude_id: str | None = None) -> tuple[dict[str, Any] | None, int, int]:
    """Выбирает следующего кандидата для обработки."""
    all_candidates = load_candidates_raw()
    if not all_candidates:
        return None, 0, 0

    # Исключаем кандидата по ID если указан
    candidates = (
        [c for c in all_candidates if c.get("id") != exclude_id] if exclude_id else all_candidates
    )

    if not candidates:
        return None, 0, len(all_candidates)

    # Сортируем по частоте (убывание), затем по имени
    candidates.sort(key=lambda x: (-(x.get("freq") or 0), x.get("alias", "").lower()))

    # Вычисляем правильный индекс (позицию в отсортированном списке)
    current_candidate = candidates[0]
    sorted_all = sorted(
        all_candidates, key=lambda x: (-(x.get("freq") or 0), x.get("alias", "").lower())
    )
    try:
        index = sorted_all.index(current_candidate) + 1
    except ValueError:
        index = 1

    return candidates[0], index, len(all_candidates)


@router.message(F.text == "/people_miner")
async def people_miner_start(message: Message, state: FSMContext) -> None:
    """Запускает people miner для обработки кандидатов."""
    await state.set_state(PeopleStates.reviewing)

    candidate, index, total = _pick_next_candidate()

    if not candidate:
        await message.answer(
            "🧩 <b>People Miner</b>\n\n"
            "❌ Кандидатов для обработки нет.\n"
            "Используйте бота для обработки встреч, чтобы собрать новых кандидатов."
        )
        await state.set_state(PeopleStates.idle)
        return

    msg_text = _format_candidate_message(candidate, index, total)
    keyboard = _create_candidate_keyboard(candidate["id"])

    await message.answer(msg_text, reply_markup=keyboard)
    logger.info(
        f"Started people miner for user {message.from_user.id if message.from_user else 'unknown'}"
    )


async def pm_next_handler_with_exclude(
    callback: CallbackQuery, state: FSMContext, exclude_id: str | None = None
) -> None:
    """Обрабатывает переход к следующему кандидату с возможностью исключения."""
    candidate, index, total = _pick_next_candidate(exclude_id)

    if not candidate:
        if callback.message and hasattr(callback.message, "edit_text"):
            await callback.message.edit_text(
                "🧩 <b>People Miner</b>\n\n"
                "✅ <b>Все кандидаты обработаны!</b>\n\n"
                "Больше кандидатов для обработки нет."
            )
        await state.set_state(PeopleStates.idle)
        await callback.answer()
        return

    msg_text = _format_candidate_message(candidate, index, total)
    keyboard = _create_candidate_keyboard(candidate["id"])

    if callback.message and hasattr(callback.message, "edit_text"):
        await callback.message.edit_text(msg_text, reply_markup=keyboard)
    await callback.answer("Переходим к следующему кандидату")


# Убрали обработчик pm_next, так как он дублирует функциональность pm_skip


@router.callback_query(F.data.startswith("pm_del:"))
async def pm_delete_handler(callback: CallbackQuery, state: FSMContext) -> None:
    """Удаляет кандидата из списка."""
    cid = (callback.data or "").split(":", 1)[1]

    success = delete_candidate_by_id(cid)

    if success:
        await callback.answer("✅ Кандидат удален")
        logger.info(
            f"Deleted candidate {cid} by user {callback.from_user.id if callback.from_user else 'unknown'}"
        )
    else:
        await callback.answer("❌ Кандидат не найден")

    # Переходим к следующему
    await pm_next_handler_with_exclude(callback, state)


@router.callback_query(F.data.startswith("pm_skip:"))
async def pm_skip_handler(callback: CallbackQuery, state: FSMContext) -> None:
    """Пропускает кандидата (оставляет в списке)."""
    logger.info(f"pm_skip_handler called with data: {callback.data}")
    cid = (callback.data or "").split(":", 1)[1]
    await callback.answer("⏭ Кандидат пропущен")
    # Переходим к следующему, исключая текущего
    await pm_next_handler_with_exclude(callback, state, exclude_id=cid)


@router.callback_query(F.data.startswith("pm_add:"))
async def pm_add_handler(callback: CallbackQuery, state: FSMContext) -> None:
    """Запрашивает английское имя для добавления кандидата."""
    cid = (callback.data or "").split(":", 1)[1]
    candidate = get_candidate_by_id(cid)

    if not candidate:
        await callback.answer("❌ Кандидат не найден")
        return

    # Сохраняем кандидата в состоянии и переходим к вводу имени
    await state.update_data(pending_candidate=candidate)
    await state.set_state(PeopleStates.waiting_assign_en)

    if callback.message and hasattr(callback.message, "answer"):
        await callback.message.answer(
            f"👤 <b>Добавление кандидата</b>\n\n"
            f"<b>Имя:</b> {candidate['alias']}\n"
            f"<b>Частота:</b> {candidate.get('freq', 0)}\n\n"
            f"✏️ <b>Введите каноническое английское имя:</b>\n"
            f"Например: <code>Sasha Katanov</code>\n\n"
            f"<i>Используйте только латинские буквы и пробелы</i>"
        )
    await callback.answer()


@router.message(PeopleStates.waiting_assign_en)
async def set_en_name_handler(message: Message, state: FSMContext) -> None:
    """Обрабатывает ввод английского имени для кандидата."""
    data = await state.get_data()
    candidate = data.get("pending_candidate")
    name_en = (message.text or "").strip()

    if not candidate or not name_en:
        await message.answer(
            "❌ <b>Ошибка ввода</b>\n\n" "Повторите команду /people_miner для начала заново."
        )
        await state.set_state(PeopleStates.idle)
        return

    # Валидируем имя
    if not _validate_en_name(name_en):
        await message.answer(
            "❌ <b>Некорректное имя</b>\n\n"
            "Используйте только латинские буквы и пробелы.\n"
            "Например: <code>Sasha Katanov</code>\n\n"
            "Попробуйте еще раз:"
        )
        return

    # Добавляем в основной словарь
    people = load_people_raw()
    existing_person = next((p for p in people if p.get("name_en") == name_en), None)

    if existing_person:
        # Расширяем алиасы существующего человека
        aliases = set(existing_person.get("aliases", []))
        aliases.add(candidate["alias"])
        existing_person["aliases"] = sorted(list(aliases))
        logger.info(f"Extended aliases for {name_en}: added {candidate['alias']}")
    else:
        # Создаем нового человека
        people.append({"name_en": name_en, "aliases": [candidate["alias"]], "role": "", "org": ""})
        logger.info(f"Added new person: {name_en} with alias {candidate['alias']}")

    save_people_raw(people)

    # Удаляем кандидата
    delete_candidate_by_id(candidate["id"])

    await message.answer(
        f"✅ <b>Кандидат добавлен</b>\n\n"
        f"👤 <b>Имя:</b> {candidate['alias']}\n"
        f"🏷️ <b>Каноническое имя:</b> {name_en}\n"
        f"📊 <b>Тег:</b> <code>People/{name_en}</code>\n\n"
        f"Переходим к следующему кандидату..."
    )

    # Возвращаемся к обработке кандидатов
    await state.set_state(PeopleStates.reviewing)
    await people_miner_start(message, state)


@router.callback_query(F.data == "pm_stats")
async def pm_stats_handler(callback: CallbackQuery, state: FSMContext) -> None:
    """Показывает статистику по людям и кандидатам."""
    logger.info(f"pm_stats_handler called with data: {callback.data}")
    people = load_people_raw()
    candidates = load_candidates_raw()

    # Статистика по частоте кандидатов
    if candidates:
        freq_stats = {
            "high": len([c for c in candidates if (c.get("freq") or 0) >= 5]),
            "medium": len([c for c in candidates if 2 <= (c.get("freq") or 0) < 5]),
            "low": len([c for c in candidates if (c.get("freq") or 0) < 2]),
        }
        total_freq = sum(c.get("freq", 0) for c in candidates)
        avg_freq = total_freq / len(candidates) if candidates else 0
    else:
        freq_stats = {"high": 0, "medium": 0, "low": 0}
        avg_freq = 0

    stats_text = (
        f"📊 <b>Статистика People Miner</b>\n\n"
        f"👥 <b>Люди в словаре:</b> {len(people)}\n"
        f"🧩 <b>Кандидаты:</b> {len(candidates)}\n\n"
        f"📈 <b>По частоте:</b>\n"
        f"   🔴 Высокая (≥5): {freq_stats['high']}\n"
        f"   🟡 Средняя (2-4): {freq_stats['medium']}\n"
        f"   🟢 Низкая (&lt;2): {freq_stats['low']}\n\n"
        f"📊 <b>Средняя частота:</b> {avg_freq:.1f}"
    )

    await callback.answer()
    if callback.message and hasattr(callback.message, "answer"):
        await callback.message.answer(stats_text)


@router.callback_query(F.data == "pm_exit")
async def pm_exit_handler(callback: CallbackQuery, state: FSMContext) -> None:
    """Завершает работу с people miner."""
    await state.set_state(PeopleStates.idle)
    if callback.message and hasattr(callback.message, "edit_text"):
        await callback.message.edit_text(
            "🧩 <b>People Miner</b>\n\n"
            "👋 <b>Работа завершена</b>\n\n"
            "Используйте /people_miner для повторного запуска."
        )
    await callback.answer("People Miner завершен")


@router.message(F.text == "/people_stats")
async def people_stats_handler(message: Message) -> None:
    """Показывает общую статистику по людям и кандидатам."""
    people = load_people_raw()
    candidates = load_candidates_raw()

    # Подсчитываем общее количество алиасов
    total_aliases = sum(len(p.get("aliases", [])) for p in people)

    stats_text = (
        f"📊 <b>Статистика людей</b>\n\n"
        f"👥 <b>Люди в словаре:</b> {len(people)}\n"
        f"🏷️ <b>Всего алиасов:</b> {total_aliases}\n"
        f"🧩 <b>Кандидаты:</b> {len(candidates)}\n\n"
        f"📈 <b>Топ кандидаты:</b>\n"
    )

    # Показываем топ-5 кандидатов
    if candidates:
        sorted_candidates = sorted(candidates, key=lambda x: x.get("freq", 0), reverse=True)
        for i, cand in enumerate(sorted_candidates[:5], 1):
            stats_text += f"{i}. {cand.get('alias', 'N/A')} ({cand.get('freq', 0)})\n"
    else:
        stats_text += "Кандидатов нет"

    await message.answer(stats_text)
    logger.info(
        f"People stats requested by user {message.from_user.id if message.from_user else 'unknown'}"
    )


@router.message(F.text == "/people_reset")
async def people_reset_handler(message: Message, state: FSMContext) -> None:
    """Сбрасывает состояние people miner."""
    await state.clear()
    await message.answer(
        "🔄 <b>Состояние сброшено</b>\n\n"
        "Все данные FSM очищены.\n"
        "Используйте /people_miner для начала заново."
    )
    logger.info(
        f"People miner state reset by user {message.from_user.id if message.from_user else 'unknown'}"
    )
