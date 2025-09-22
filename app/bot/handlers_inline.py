# app/bot/handlers_inline.py
"""Inline кнопки для управления Review Queue."""

from __future__ import annotations

import logging

from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from app.core.commit_normalize import build_key, build_title
from app.core.constants import REVIEW_STATUS_DROPPED, REVIEW_STATUS_RESOLVED
from app.gateways.notion_commits import upsert_commits
from app.gateways.notion_review import get_by_short_id, list_pending, set_status, update_fields

logger = logging.getLogger(__name__)
router = Router()


async def _send_empty_queue_message(message: Message) -> None:
    """Отправляет сообщение о пустой очереди с предложением загрузить новый файл."""
    empty_queue_kb = InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📄 Загрузить новый файл", callback_data="main_new_file"),
            ]
        ]
    )
    await message.answer(
        "📋 Review queue пуста.\n\n" "💡 <i>Готов обработать новую встречу!</i>",
        reply_markup=empty_queue_kb,
    )


def build_main_menu_kb() -> InlineKeyboardMarkup:
    """Создает клавиатуру главного меню после обработки транскрипта."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📄 Новый файл", callback_data="main_new_file"),
                InlineKeyboardButton(text="🔍 Review", callback_data="main_review"),
            ]
        ]
    )


def build_review_item_kb(short_id: str) -> InlineKeyboardMarkup:
    """Создает клавиатуру для управления элементом Review Queue."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="✅ Confirm", callback_data=f"review_confirm:{short_id}"),
                InlineKeyboardButton(text="🔄 Flip", callback_data=f"review_flip:{short_id}"),
            ],
            [
                InlineKeyboardButton(text="🗑 Delete", callback_data=f"review_delete:{short_id}"),
                InlineKeyboardButton(text="👤 Assign", callback_data=f"review_assign:{short_id}"),
            ],
        ]
    )


@router.callback_query(F.data == "main_new_file")
async def cb_main_new_file(callback: CallbackQuery):
    """Обработка кнопки 'Обработать новый файл'."""
    await callback.answer()
    if callback.message:
        await callback.message.answer(
            "📎 <b>Отправьте файл встречи для обработки</b>\n\n"
            "🎯 <b>Поддерживаемые форматы:</b>\n"
            "• 📄 Текстовые файлы (.txt)\n"
            "• 📋 PDF документы (.pdf)\n"
            "• 📝 Word документы (.docx)\n"
            "• 📺 Субтитры (.vtt, .webvtt)\n\n"
            "💡 <i>Просто перетащите файл в чат или используйте кнопку прикрепления</i>"
        )


@router.callback_query(F.data == "main_review")
async def cb_main_review(callback: CallbackQuery):
    """Обработка кнопки 'Review Commits'."""
    await callback.answer()

    try:
        # Используем новую логику фильтрации открытых записей
        from app.core.review_queue import list_open_reviews
        items = list_open_reviews(limit=10)  # Показываем больше элементов через кнопки

        if not items:
            if callback.message and isinstance(callback.message, Message):
                await _send_empty_queue_message(callback.message)
            return

        if callback.message:
            # Добавляем кнопку "Confirm All" если есть элементы
            confirm_all_kb = InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(
                            text="✅ Confirm All", callback_data="review_confirm_all"
                        )
                    ]
                ]
            )
            await callback.message.answer(
                f"📋 <b>Pending review ({len(items)} элементов):</b>", reply_markup=confirm_all_kb
            )

        for item in items:
            short_id = item["short_id"]
            text = (item.get("text") or "")[:90]
            direction = item.get("direction") or "?"
            assignees = item.get("assignees") or []
            due = item.get("due_iso") or "—"
            confidence = item.get("confidence")

            # Форматируем assignees
            who = ", ".join(assignees) if assignees else "—"
            conf_str = f"{confidence:.2f}" if confidence is not None else "—"

            message_text = (
                f"<b>[{short_id}]</b> {text}\n"
                f"📍 <i>dir={direction} | who={who} | due={due} | conf={conf_str}</i>"
            )

            if callback.message:
                await callback.message.answer(
                    message_text, reply_markup=build_review_item_kb(short_id)
                )

    except Exception as e:
        logger.error(f"Error in cb_main_review: {e}")
        if callback.message:
            await callback.message.answer("❌ Ошибка при загрузке Review queue.")


@router.callback_query(F.data.startswith("review_confirm:"))
async def cb_review_confirm(callback: CallbackQuery):
    """Подтверждает элемент Review и создает коммит."""
    try:
        if not callback.data:
            await callback.answer("❌ Ошибка данных", show_alert=True)
            return
        short_id = callback.data.split(":")[1]
        item = get_by_short_id(short_id)

        if not item:
            await callback.answer("❌ Элемент не найден", show_alert=True)
            return

        # Используем логику из существующей команды /confirm
        text = item["text"] or ""
        direction = item["direction"] or "theirs"
        assignees = item["assignees"] or []
        due_iso = item["due_iso"]

        # Генерируем title и key
        title = build_title(direction, text, assignees, due_iso)
        key = build_key(text, assignees, due_iso)

        # Создаем коммит
        commit_item = {
            "title": title,
            "text": text,
            "direction": direction,
            "assignees": assignees,
            "due_iso": due_iso,
            "confidence": item["confidence"] or 0.6,
            "flags": [],
            "key": key,
            "tags": [],
            "status": "open",
        }

        # Сохраняем в Commits
        meeting_page_id = item["meeting_page_id"]
        if not meeting_page_id:
            await callback.answer("❌ Не найден meeting_page_id", show_alert=True)
            return

        result = upsert_commits(meeting_page_id, [commit_item])
        created = len(result.get("created", []))
        updated = len(result.get("updated", []))

        # Валидируем действие
        from app.core.review_queue import validate_review_action
        
        is_valid, error_msg = validate_review_action(item, "confirm")
        if not is_valid:
            await callback.answer(f"❌ {error_msg}", show_alert=True)
            return

        if created or updated:
            # Получаем ID созданного коммита
            commit_ids = result.get("created", []) + result.get("updated", [])
            commit_id = commit_ids[0] if commit_ids else None
            
            # Помечаем как resolved с привязкой к коммиту
            set_status(item["page_id"], REVIEW_STATUS_RESOLVED, linked_commit_id=commit_id)
            await callback.answer("✅ Confirmed!")
            if callback.message and isinstance(callback.message, Message):
                await callback.message.edit_text(
                    f"✅ <b>[{short_id}] Подтверждено</b>\n"
                    f"📝 {text}\n"
                    f"📊 Создано: {created}, обновлено: {updated}\n"
                    f"🔗 Привязан коммит: {commit_id[:8] if commit_id else 'none'}"
                )
            logger.info(f"Review item {short_id} confirmed via inline, linked to commit {commit_id[:8] if commit_id else 'none'}")
        else:
            await callback.answer("❌ Не удалось создать коммит", show_alert=True)

    except Exception as e:
        logger.error(f"Error in cb_review_confirm: {e}")
        await callback.answer("❌ Ошибка при подтверждении", show_alert=True)


@router.callback_query(F.data.startswith("review_flip:"))
async def cb_review_flip(callback: CallbackQuery):
    """Переключает direction элемента Review."""
    try:
        if not callback.data:
            await callback.answer("❌ Ошибка данных", show_alert=True)
            return
        short_id = callback.data.split(":")[1]
        item = get_by_short_id(short_id)

        if not item:
            await callback.answer("❌ Элемент не найден", show_alert=True)
            return

        current_direction = item["direction"] or "theirs"
        new_direction = "mine" if current_direction == "theirs" else "theirs"

        success = update_fields(item["page_id"], direction=new_direction)

        if success:
            await callback.answer(f"🔄 Direction → {new_direction}")
            # Обновляем сообщение
            text = (item.get("text") or "")[:90]
            assignees = item.get("assignees") or []
            due = item.get("due_iso") or "—"
            confidence = item.get("confidence")

            who = ", ".join(assignees) if assignees else "—"
            conf_str = f"{confidence:.2f}" if confidence is not None else "—"

            updated_text = (
                f"<b>[{short_id}]</b> {text}\n"
                f"📍 <i>dir={new_direction} | who={who} | due={due} | conf={conf_str}</i>"
            )

            if callback.message and isinstance(callback.message, Message):
                await callback.message.edit_text(
                    updated_text, reply_markup=build_review_item_kb(short_id)
                )
        else:
            await callback.answer("❌ Ошибка при изменении direction", show_alert=True)

    except Exception as e:
        logger.error(f"Error in cb_review_flip: {e}")
        await callback.answer("❌ Ошибка при переключении", show_alert=True)


@router.callback_query(F.data.startswith("review_delete:"))
async def cb_review_delete(callback: CallbackQuery):
    """Помечает элемент Review как dropped."""
    try:
        if not callback.data:
            await callback.answer("❌ Ошибка данных", show_alert=True)
            return
        short_id = callback.data.split(":")[1]
        item = get_by_short_id(short_id)

        if not item:
            await callback.answer("❌ Элемент не найден", show_alert=True)
            return

        # Валидируем действие
        from app.core.review_queue import validate_review_action
        
        is_valid, error_msg = validate_review_action(item, "delete")
        if not is_valid:
            await callback.answer(f"❌ {error_msg}", show_alert=True)
            return
        
        set_status(item["page_id"], REVIEW_STATUS_DROPPED)
        await callback.answer("🗑 Удалено")
        if callback.message and isinstance(callback.message, Message):
            await callback.message.edit_text(
                f"🗑 <b>[{short_id}] Удалено</b>\n" f"📝 {item.get('text', '')[:90]}"
            )
        logger.info(f"Review item {short_id} marked as dropped via inline button")

    except Exception as e:
        logger.error(f"Error in cb_review_delete: {e}")
        await callback.answer("❌ Ошибка при удалении", show_alert=True)


@router.callback_query(F.data.startswith("review_assign:"))
async def cb_review_assign(callback: CallbackQuery):
    """Предлагает назначить исполнителя через текстовую команду."""
    try:
        if not callback.data:
            await callback.answer("❌ Ошибка данных", show_alert=True)
            return
        short_id = callback.data.split(":")[1]
        item = get_by_short_id(short_id)

        if not item:
            await callback.answer("❌ Элемент не найден", show_alert=True)
            return

        await callback.answer()
        if callback.message:
            await callback.message.answer(
                f"👤 <b>Назначение исполнителя для [{short_id}]</b>\n\n"
                f"📝 Задача: {item.get('text', '')[:100]}\n\n"
                f"💡 <b>Шаг 1:</b> Введите команду:\n"
                f"<code>/assign {short_id} &lt;имя&gt;</code>\n\n"
                f"<i>Например: /assign {short_id} Daniil</i>\n\n"
                f"💡 <b>Шаг 2:</b> После назначения нажмите кнопку <b>✅ Confirm</b> "
                f"чтобы перенести задачу в Commits\n\n"
                f"🔄 <i>Или используйте кнопку \"✅ Confirm All\" для подтверждения всех задач сразу</i>"
            )

    except Exception as e:
        logger.error(f"Error in cb_review_assign: {e}")
        await callback.answer("❌ Ошибка при назначении", show_alert=True)


@router.callback_query(F.data == "review_confirm_all")
async def cb_review_confirm_all(callback: CallbackQuery):
    """Подтверждает все элементы Review и создает коммиты."""
    await callback.answer()

    try:
        from app.core.review_queue import list_open_reviews
        items = list_open_reviews(limit=50)  # Получаем все открытые элементы

        if not items:
            if callback.message and isinstance(callback.message, Message):
                await _send_empty_queue_message(callback.message)
            return

        confirmed_count = 0
        errors_count = 0

        for item in items:
            try:
                # Используем ту же логику что и в cb_review_confirm
                text = item["text"] or ""
                direction = item["direction"] or "theirs"
                assignees = item["assignees"] or []
                due_iso = item["due_iso"]

                # Генерируем title и key
                title = build_title(direction, text, assignees, due_iso)
                key = build_key(text, assignees, due_iso)

                # Создаем коммит
                commit_item = {
                    "title": title,
                    "text": text,
                    "direction": direction,
                    "assignees": assignees,
                    "due_iso": due_iso,
                    "confidence": item["confidence"] or 0.6,
                    "flags": [],
                    "key": key,
                    "tags": [],
                    "status": "open",
                }

                # Сохраняем в Commits
                meeting_page_id = item["meeting_page_id"]
                if not meeting_page_id:
                    errors_count += 1
                    continue

                result = upsert_commits(meeting_page_id, [commit_item])
                created = len(result.get("created", []))
                updated = len(result.get("updated", []))

                if created or updated:
                    # Помечаем как resolved
                    set_status(item["page_id"], REVIEW_STATUS_RESOLVED)
                    confirmed_count += 1
                else:
                    errors_count += 1

            except Exception as e:
                logger.error(f"Error confirming item {item.get('short_id', 'unknown')}: {e}")
                errors_count += 1
                continue

        # Отчет о результатах
        if callback.message:
            if confirmed_count > 0:
                result_msg = f"✅ <b>Подтверждено: {confirmed_count} элементов</b>"
                if errors_count > 0:
                    result_msg += f"\n⚠️ Ошибок: {errors_count}"
                await callback.message.answer(result_msg)

                # Проверяем, пуста ли очередь после обработки
                remaining_items = list_pending(limit=1)
                if not remaining_items and isinstance(callback.message, Message):
                    await _send_empty_queue_message(callback.message)
            else:
                await callback.message.answer("❌ Не удалось подтвердить ни одного элемента")

    except Exception as e:
        logger.error(f"Error in cb_review_confirm_all: {e}")
        if callback.message:
            await callback.message.answer("❌ Ошибка при массовом подтверждении")
