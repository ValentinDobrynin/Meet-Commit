# app/bot/handlers.py
from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import Any

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.core.commit_normalize import (
    build_key,
    build_title,
    normalize_assignees,
    normalize_commits,
    validate_date_iso,
)
from app.core.commit_validate import validate_and_partition
from app.core.constants import REVIEW_STATUS_DROPPED, REVIEW_STATUS_RESOLVED
from app.core.llm_extract_commits import extract_commits
from app.core.llm_summarize import run as summarize_run
from app.core.normalize import run as normalize_run
from app.core.people_store import canonicalize_list
from app.core.review_queue import list_open_reviews
from app.core.tags import tag_text_for_meeting
from app.gateways.notion_commits import upsert_commits
from app.gateways.notion_gateway import upsert_meeting
from app.gateways.notion_review import (
    enqueue_with_upsert,
    get_by_short_id,
    set_status,
    update_fields,
)

logger = logging.getLogger(__name__)

router = Router()

PROMPTS_DIR = Path(__file__).resolve().parent.parent.parent / "prompts" / "summarization"
MAX_PREVIEW_LINES = 12


async def _send_empty_queue_message_with_menu(msg: Message) -> None:
    """Отправляет сообщение о пустой очереди с главным меню."""
    from app.bot.handlers_inline import build_main_menu_kb

    await msg.answer(
        "📋 Review queue пуста.\n\n" "💡 <i>Готов обработать новую встречу!</i>",
        reply_markup=build_main_menu_kb(),
    )


class IngestStates(StatesGroup):
    waiting_prompt = State()
    waiting_extra = State()


def _prompts_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    # Поддерживаем как .txt, так и .md файлы
    txt_files = list(PROMPTS_DIR.glob("*.txt"))
    md_files = list(PROMPTS_DIR.glob("*.md"))
    prompts = sorted(txt_files + md_files)
    for p in prompts:
        kb.button(text=p.stem, callback_data=f"prompt:{p.name}")
    kb.adjust(1)
    return kb.as_markup()


def _skip_kb() -> InlineKeyboardMarkup:
    kb = InlineKeyboardBuilder()
    kb.button(text="Пропустить", callback_data="extra:skip")
    kb.adjust(1)
    return kb.as_markup()


@router.message(F.text == "/start")
async def cmd_start(msg: Message, state: FSMContext):
    await state.clear()

    # Сохраняем пользователя в список активных
    from app.bot.user_storage import add_user

    chat_id = msg.chat.id
    username = msg.from_user.username if msg.from_user else None
    first_name = msg.from_user.first_name if msg.from_user else None

    is_new_user = add_user(chat_id, username, first_name)
    if is_new_user:
        logger.info(f"New user registered: {chat_id} (@{username})")

    welcome_text = (
        "🤖 <b>Добро пожаловать в Meet-Commit!</b>\n\n"
        "Я превращаю ваши встречи в структурированные отчеты с помощью AI.\n\n"
        "📋 <b>Что я умею:</b>\n"
        "• 📝 Суммаризировать встречи (3 стиля на выбор)\n"
        "• 🎯 Извлекать обязательства и задачи\n"
        "• 🏷️ Автоматически расставлять теги\n"
        "• 👥 Распознавать участников встреч\n"
        "• 📊 Создавать повестки на основе задач\n"
        "• 💾 Сохранять всё в Notion\n\n"
        "🚀 <b>Быстрый старт:</b>\n"
        "📎 Отправьте файл встречи (.txt, .pdf, .docx, .vtt)\n"
        "📄 Или просто скопируйте текст встречи в чат\n\n"
        "🔧 <b>Основные команды:</b>\n"
        "❓ /help - полная справка по всем командам\n\n"
        "📝 <b>Создание задач:</b>\n"
        "/commit - создать задачу (интерактивно)\n"
        "/llm (текст) - создать задачу через AI\n\n"
        "🔍 <b>Поиск задач:</b>\n"
        "/mine - мои задачи\n"
        "/due - дедлайны на неделю\n"
        "/today - горящие задачи\n"
        "/commits - последние коммиты\n\n"
        "📊 <b>Повестки:</b>\n"
        "/agenda - создать повестку\n"
        "/agenda_person (имя) - персональная повестка\n\n"
        "📋 <b>Проверка качества:</b>\n"
        "/review - очередь на проверку\n\n"
        "💡 <i>Для полного списка команд используйте /help</i>"
    )
    
    await msg.answer(welcome_text, parse_mode="HTML")


@router.message(F.text == "/help")
async def cmd_help(msg: Message, state: FSMContext):
    """Показывает основные команды бота."""
    help_text = (
        "🤖 <b>Meet-Commit Bot</b>\n\n"
        "📋 <b>Основные команды:</b>\n"
        "🏠 <code>/start</code> - Главное меню и приветствие\n"
        "❓ <code>/help</code> - Эта справка\n"
        "📄 <code>/process</code> - Обработать файл встречи\n\n"
        "📝 <b>Создание коммитов:</b>\n"
        "📝 <code>/commit</code> - Интерактивное создание (4 шага)\n"
        "🤖 <code>/llm (текст)</code> - Создание через естественный язык\n"
        "   💡 <i>Пример: /llm Саша сделает отчет к пятнице</i>\n\n"
        "🔍 <b>Быстрые запросы:</b>\n"
        "📋 <code>/commits</code> - последние коммиты\n"
        "👤 <code>/mine</code> - мои задачи (все)\n"
        "⚡ <code>/mine_active</code> - только активные\n"
        "👥 <code>/theirs</code> - чужие задачи\n"
        "⏰ <code>/due</code> - дедлайны на неделю\n"
        "🔥 <code>/today</code> - горящие задачи\n"
        "🏷️ <code>/by_tag (тег)</code> - поиск по тегу\n"
        "👤 <code>/by_assignee (имя)</code> - задачи исполнителя\n\n"
        "📋 <b>Повестки:</b>\n"
        "📋 <code>/agenda</code> - создать повестку (интерактивно)\n"
        "🏢 <code>/agenda_meeting (id)</code> - повестка встречи\n"
        "👤 <code>/agenda_person (имя)</code> - персональная повестка\n"
        "🏷️ <code>/agenda_tag (тег)</code> - тематическая повестка\n\n"
        "👥 <b>Управление людьми:</b>\n"
        "🆕 <code>/people_miner2</code> - Верификация новых людей (v2, рекомендуется)\n"
        "📊 <code>/people_stats_v2</code> - Детальная статистика системы людей\n\n"
        "📋 <b>Review Queue:</b>\n"
        "🔍 <code>/review</code> - Просмотр очереди проверки коммитов\n"
        "✅ <code>/confirm (id)</code> - Подтвердить коммит из очереди\n"
        "❌ <code>/delete (id)</code> - Удалить коммит из очереди\n"
        "🔄 <code>/flip (id)</code> - Изменить direction коммита\n"
        "👤 <code>/assign (id)</code> - Назначить исполнителя (интерактивно)\n"
        "👤 <code>/assign (id) (имя)</code> - Назначить исполнителя (ручной ввод)\n"
        "🧹 <code>/review_clean</code> - Очистка старых записей и дубликатов (админы)\n"
        "📊 <code>/review_stats</code> - Статистика Review Queue (админы)\n\n"
        "📎 <b>Обработка файлов:</b>\n"
        "• Просто отправьте файл встречи в чат\n"
        "• Поддерживаются: .txt, .pdf, .docx, .vtt, .webvtt\n"
        "• Бот автоматически извлечет коммиты и сохранит в Notion\n"
        "• После обработки доступно интерактивное редактирование тегов\n\n"
        "🎯 <b>Что делает бот:</b>\n"
        "• 📝 Суммаризирует встречи через AI (3 стиля)\n"
        "• 🎯 Извлекает обязательства и действия\n"
        "• 🏷️ Автоматически расставляет теги (двойная система)\n"
        "• 👥 Обнаруживает и верифицирует участников\n"
        "• 📊 Создает структурированные повестки\n"
        "• 💾 Сохраняет все в Notion с умной организацией\n"
        "• 🔍 Управляет очередью задач на проверку\n"
        "• 🧹 Автоматически поддерживает чистоту данных\n\n"
        "💡 <i>Для административных функций используйте /admin_help</i>\n"
        "🧹 <i>Администраторы могут очищать Review Queue от старых записей и дубликатов</i>"
    )
    await msg.answer(help_text)


@router.message(F.text == "/process")
async def cmd_process(msg: Message, state: FSMContext):
    """Запускает процесс обработки файла встречи."""
    await msg.answer(
        "📎 <b>Обработка файла встречи</b>\n\n"
        "📋 <b>Инструкция:</b>\n"
        "1. Отправьте файл с записью встречи\n"
        "2. Бот автоматически обработает его\n"
        "3. Результат будет сохранен в Notion\n\n"
        "🎯 <b>Поддерживаемые форматы:</b>\n"
        "• 📄 Текстовые файлы (.txt)\n"
        "• 📋 PDF документы (.pdf)\n"
        "• 📝 Word документы (.docx)\n"
        "• 📺 Субтитры (.vtt, .webvtt)\n\n"
        "💡 <i>Просто перетащите файл в чат!</i>"
    )


@router.message(F.text == "/cancel")
async def cmd_cancel(msg: Message, state: FSMContext):
    await state.clear()
    await msg.answer("Ок. Сбросил состояние.")


@router.message(F.text & ~F.text.startswith("/"))
async def handle_text_with_fsm_check(msg: Message, state: FSMContext):
    """Обработчик текста - проверяет FSM состояния перед основной логикой."""
    current_state = await state.get_state()
    logger.debug(f"Text input '{msg.text}' in state: {current_state}")

    # Проверяем agenda состояния
    from app.bot.handlers_agenda import AgendaStates

    if current_state == AgendaStates.waiting_person_name:
        logger.info(f"Redirecting person name '{msg.text}' to agenda handler")
        from app.bot.handlers_agenda import handle_person_name_input

        await handle_person_name_input(msg, state)
        return

    if current_state == AgendaStates.waiting_meeting_id:
        logger.info(f"Redirecting meeting ID '{msg.text}' to agenda handler")
        from app.bot.handlers_agenda import handle_meeting_id_input

        await handle_meeting_id_input(msg, state)
        return

    if current_state == AgendaStates.waiting_tag_name:
        logger.info(f"Redirecting tag name '{msg.text}' to agenda handler")
        from app.bot.handlers_agenda import handle_tag_name_input

        await handle_tag_name_input(msg, state)
        return

    # Проверяем people miner состояния
    from app.bot.states.people_states import PeopleStates

    if current_state == PeopleStates.waiting_assign_en:
        logger.info(f"Redirecting EN name '{msg.text}' to people handler v1")
        from app.bot.handlers_people import set_en_name_handler

        await set_en_name_handler(msg, state)
        return

    if current_state == PeopleStates.v2_waiting_custom_name:
        logger.info(f"Redirecting custom name '{msg.text}' to people handler v2")
        from app.bot.handlers_people_v2 import handle_custom_name_input

        await handle_custom_name_input(msg, state)
        return

    # Если нет активного FSM состояния, обрабатываем как обычный текст для суммаризации
    await _process_ingest_input(msg, state)


async def _process_ingest_input(msg: Message, state: FSMContext):
    """Обрабатывает ввод для суммаризации (документы и текст)."""
    import base64
    
    raw_bytes: bytes | None = None
    raw_bytes_b64: str | None = None  # Для Redis storage
    text: str | None = None
    filename = "message.txt"

    if msg.document:
        if not msg.bot:
            await msg.answer("Ошибка: бот недоступен")
            return
        file = await msg.bot.get_file(msg.document.file_id)
        if not file.file_path:
            await msg.answer("Ошибка: путь к файлу не найден")
            return
        bytes_io = await msg.bot.download_file(file.file_path)
        if bytes_io:
            raw_bytes = bytes_io.read()
            # Конвертируем bytes в base64 для Redis storage
            raw_bytes_b64 = base64.b64encode(raw_bytes).decode('utf-8')
        else:
            await msg.answer("Ошибка: не удалось загрузить файл")
            return
        filename = msg.document.file_name or "meeting.txt"
    else:
        text = msg.text or ""

    # Сохраняем base64 строку вместо bytes для совместимости с Redis
    await state.update_data(raw_bytes_b64=raw_bytes_b64, text=text, filename=filename)
    await state.set_state(IngestStates.waiting_prompt)
    await msg.answer("Выбери шаблон суммаризации:", reply_markup=_prompts_kb())


@router.message(F.document)
async def receive_document(msg: Message, state: FSMContext):
    """Обработчик документов для суммаризации."""
    await _process_ingest_input(msg, state)


@router.callback_query(F.data.startswith("prompt:"))
async def choose_prompt(cb: CallbackQuery, state: FSMContext):
    try:
        data = await state.get_data()

        # Проверяем наличие данных (поддерживаем оба формата для совместимости)
        if not data.get("raw_bytes_b64") and not data.get("raw_bytes") and not data.get("text"):
            await cb.answer("Нет входных данных. Пришли файл или текст.", show_alert=True)
            return

        if not cb.data:
            await cb.answer("Ошибка: данные callback не найдены", show_alert=True)
            return

        prompt_file = cb.data.split("prompt:", 1)[1]
        await state.update_data(prompt_file=prompt_file)
        await state.set_state(IngestStates.waiting_extra)

        if cb.message:
            await cb.message.answer(
                "Добавить уточнение к промпту? Напиши текст или нажми «Пропустить».",
                reply_markup=_skip_kb(),
            )
        await cb.answer()
    except Exception as e:
        # Отвечаем на callback даже при ошибке
        try:
            await cb.answer("Произошла ошибка при обработке запроса.")
        except Exception:
            pass  # Игнорируем ошибки ответа на callback
        print(f"Error in choose_prompt: {e}")


@router.callback_query(F.data == "extra:skip")
async def extra_skip(cb: CallbackQuery, state: FSMContext):
    try:
        await cb.answer()  # Отвечаем сразу на callback
        if cb.message and isinstance(cb.message, Message):
            await run_pipeline(cb.message, state, extra=None)
    except Exception as e:
        # Отвечаем на callback даже при ошибке
        try:
            await cb.answer("Произошла ошибка при обработке запроса.")
        except Exception:
            pass  # Игнорируем ошибки ответа на callback
        print(f"Error in extra_skip: {e}")


@router.message(IngestStates.waiting_extra, F.text)
async def extra_entered(msg: Message, state: FSMContext):
    await run_pipeline(msg, state, extra=msg.text)


def _extract_page_id_from_url(notion_url: str) -> str:
    """
    Извлекает page_id из Notion URL и форматирует в правильный UUID.

    Args:
        notion_url: URL страницы Notion

    Returns:
        Page ID в формате UUID для использования в API

    Example:
        https://notion.so/mock-tr6-272344c5676681a6b2a4f9c9df62305f -> 272344c5-6766-81a6-b2a4-f9c9df62305f
    """
    # Notion URLs обычно имеют формат: https://notion.so/{page_id}
    # или https://www.notion.so/{workspace}/{page_id}
    parts = notion_url.rstrip("/").split("/")
    page_id_raw = parts[-1]

    # Убираем префиксы и извлекаем только hex часть
    if len(page_id_raw) == 36 and page_id_raw.count("-") == 4:
        # Уже в UUID формате
        return page_id_raw
    elif len(page_id_raw) > 32:
        # Есть префикс, берем последние 32 hex символа
        hex_part = page_id_raw[-32:]
    else:
        # Убираем все дефисы и работаем с hex
        hex_part = page_id_raw.replace("-", "")

    # Форматируем в UUID: XXXXXXXX-XXXX-XXXX-XXXX-XXXXXXXXXXXX
    if len(hex_part) == 32:
        formatted_uuid = (
            f"{hex_part[:8]}-{hex_part[8:12]}-{hex_part[12:16]}-{hex_part[16:20]}-{hex_part[20:32]}"
        )
        return formatted_uuid
    else:
        # Если не можем распарсить, возвращаем как есть
        return page_id_raw


async def run_commits_pipeline(
    meeting_page_id: str,
    meeting_text: str,
    attendees_en: list[str],
    meeting_date_iso: str,
    meeting_tags: list[str] | None,
    msg: Message | None = None,
) -> dict[str, int]:
    """
    Обрабатывает коммиты для встречи: извлекает, нормализует, валидирует и сохраняет.

    Args:
        meeting_page_id: ID страницы встречи в Notion
        meeting_text: Нормализованный транскрипт встречи
        attendees_en: Список участников в канонических EN именах
        meeting_date_iso: Дата встречи в формате YYYY-MM-DD
        meeting_tags: Теги встречи для наследования

    Returns:
        Словарь со статистикой: {"created": int, "updated": int, "review": int}

    Pipeline:
        1. extract_commits() - извлечение коммитов через LLM
        2. normalize_commits() - нормализация исполнителей и дедлайнов
        3. validate_and_partition() - валидация и маршрутизация по качеству
        4. upsert_commits() - сохранение качественных коммитов
        5. enqueue() - отправка проблемных коммитов в Review Queue
    """
    try:
        logger.info(f"Starting commits pipeline for meeting {meeting_page_id}")

        # 1) LLM извлечение коммитов (в executor, т.к. синхронный)
        extracted_commits = await asyncio.get_event_loop().run_in_executor(
            None,
            lambda: extract_commits(
                text=meeting_text,
                attendees_en=attendees_en,
                meeting_date_iso=meeting_date_iso,
            ),
        )
        logger.info(f"Extracted {len(extracted_commits)} commits from LLM")

        # 2) Нормализация (исполнители, дедлайны, title, key)
        normalized_commits = normalize_commits(
            extracted_commits,
            attendees_en=attendees_en,
            meeting_date_iso=meeting_date_iso,
        )
        logger.info(f"Normalized {len(normalized_commits)} commits")

        # 3) Валидация и разделение по качеству
        partition_result = validate_and_partition(
            normalized_commits,
            attendees_en=attendees_en,
            meeting_date_iso=meeting_date_iso,
            meeting_tags=meeting_tags or [],
        )
        logger.info(
            f"Partitioned commits: {len(partition_result.to_commits)} to store, {len(partition_result.to_review)} to review"
        )

        # 4) Сохранение качественных коммитов в Commits (в executor, т.к. синхронный)
        commits_result: dict[str, list[str]] = {"created": [], "updated": []}
        if partition_result.to_commits:
            commits_dict = [commit.__dict__ for commit in partition_result.to_commits]
            commits_result = await asyncio.get_event_loop().run_in_executor(
                None, lambda: upsert_commits(meeting_page_id, commits_dict)
            )

        # 5) Сохранение сомнительных коммитов в Review Queue с дедупликацией (в executor, т.к. синхронный)
        review_stats = {"created": 0, "updated": 0}

        if partition_result.to_review:
            try:
                # to_review уже содержит словари, только добавляем недостающие поля
                review_items: list[dict[str, Any]] = []
                for review_dict in partition_result.to_review:
                    # review_dict уже является словарем из commit_validate.py
                    # Добавляем недостающие поля для Review Queue
                    review_item = review_dict.copy()  # Копируем исходный словарь

                    # Добавляем reason из флагов если есть
                    if "reason" not in review_item:
                        review_item["reason"] = (
                            ", ".join(review_dict.get("flags", [])) or "Low confidence"
                        )

                    # Восстанавливаем генерацию key для дедупликации
                    if "key" not in review_item:
                        review_item["key"] = build_key(
                            review_dict.get("text", ""),
                            review_dict.get("assignees", []),
                            review_dict.get("due_iso"),
                        )

                    # Добавляем теги встречи
                    review_item["tags"] = review_dict.get("tags", []) + meeting_tags

                    review_items.append(review_item)

                # Используем upsert с дедупликацией по ключу
                review_stats = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: enqueue_with_upsert(review_items, meeting_page_id)
                )

            except Exception as e:
                logger.error(f"Error enqueueing review items: {e}")
                # Продолжаем работу даже если Review Queue не работает

        stats = {
            "created": len(commits_result.get("created", [])),
            "updated": len(commits_result.get("updated", [])),
            "review_created": review_stats.get("created", 0),
            "review_updated": review_stats.get("updated", 0),
        }

        logger.info(f"Commits pipeline completed: {stats}")
        return stats

    except Exception as e:
        logger.exception(f"Error in commits pipeline for meeting {meeting_page_id}: {e}")
        # Возвращаем нулевую статистику при ошибке
        return {"created": 0, "updated": 0, "review_created": 0, "review_updated": 0}


async def run_pipeline(msg: Message, state: FSMContext, extra: str | None):
    try:
        import base64
        
        data = await state.get_data()
        raw_bytes_b64 = data.get("raw_bytes_b64")
        
        # Конвертируем base64 обратно в bytes если есть
        raw_bytes = None
        if raw_bytes_b64:
            raw_bytes = base64.b64decode(raw_bytes_b64)
        
        text = data.get("text")
        filename = data.get("filename") or "meeting.txt"
        prompt_file = data.get("prompt_file")

        if not prompt_file:
            await msg.answer("Не выбран шаблон. Начни заново: пришли файл/текст.")
            await state.clear()
            return

        # Уведомляем о начале обработки
        await msg.answer("🔄 <b>Начинаю обработку...</b>\n\n📄 Извлекаю текст из файла...", parse_mode="HTML")

        # 1) normalize
        meta = normalize_run(raw_bytes=raw_bytes, text=text, filename=filename)

        # Уведомляем о суммаризации
        await msg.answer("🤖 <b>Суммаризирую через AI...</b>\n\n⏳ Это может занять 1-4 минуты...", parse_mode="HTML")

        # 2) summarize
        prompt_path = (PROMPTS_DIR / prompt_file).as_posix()
        summary_md = await summarize_run(text=meta["text"], prompt_path=prompt_path, extra=extra)

        # 3) унифицированное тегирование (v0/v1/both в зависимости от настроек)
        tags = tag_text_for_meeting(summary_md, meta)
        logger.info(f"Meeting tagged with {len(tags)} canonical tags using unified system")

        # Уведомляем о сохранении в Notion
        await msg.answer("💾 <b>Сохраняю в Notion...</b>\n\n📝 Создаю страницу в базе данных...", parse_mode="HTML")

        # 4) Подготовка данных для Notion
        # Канонизируем участников к EN именам
        raw_attendees = meta.get("attendees", [])
        attendees_en = canonicalize_list(raw_attendees)
        logger.info(f"Attendees processing: raw={raw_attendees} → canonical={attendees_en}")

        # Валидируем и подготавливаем дату встречи
        raw_date = meta.get("date", "").strip()
        meeting_date_iso = validate_date_iso(raw_date)

        if not meeting_date_iso:
            # Если дата невалидна или отсутствует, используем дату сообщения
            meeting_date_iso = msg.date.date().isoformat()
            if raw_date:
                logger.warning(
                    f"Invalid date format '{raw_date}', using message date: {meeting_date_iso}"
                )
            else:
                logger.info(f"No date found in transcript, using message date: {meeting_date_iso}")

        # Notion upsert с канонизированными данными
        notion_url = upsert_meeting(
            {
                "title": meta["title"],
                "date": meeting_date_iso,
                "attendees": attendees_en,  # Канонические EN имена
                "source": "telegram",
                "raw_hash": meta["raw_hash"],
                "summary_md": summary_md,
                "tags": tags,
            }
        )

        # 4.5) Обновляем кандидатов людей через People Miner v2
        try:
            from app.core.people_miner2 import ingest_text

            meeting_page_id = _extract_page_id_from_url(notion_url)
            ingest_text(
                text=meta["text"], meeting_id=meeting_page_id, meeting_date=meeting_date_iso
            )
            logger.info("People Miner v2: candidates updated from meeting text")
        except Exception as e:
            logger.warning(f"People Miner v2 ingest failed: {e}")
            # Не критично - продолжаем обработку

        # 5) Обработка коммитов
        await msg.answer(
            "🔍 <b>Обрабатываю коммиты...</b>\n\n🤖 Извлекаю обязательства из транскрипта..."
        )

        try:
            # Извлекаем page_id из URL для связи коммитов с встречей
            meeting_page_id = _extract_page_id_from_url(notion_url)

            # Запускаем пайплайн коммитов с теми же канонизированными данными
            stats = await run_commits_pipeline(
                meeting_page_id=meeting_page_id,
                meeting_text=meta["text"],
                attendees_en=attendees_en,  # Те же канонические EN имена
                meeting_date_iso=meeting_date_iso,  # Валидированная ISO дата
                meeting_tags=tags,
                msg=msg,  # Передаем message для отладки
            )

            # Формируем отчет по коммитам
            # Подсчитываем общее количество элементов в ревью
            total_review = stats.get("review_created", 0) + stats.get("review_updated", 0)

            commits_report = (
                f"📊 <b>Коммиты обработаны:</b>\n"
                f"• ✅ Сохранено: {stats['created'] + stats['updated']}\n"
                f"• 🆕 Создано: {stats['created']}\n"
                f"• 🔄 Обновлено: {stats['updated']}\n"
                f"• 🔍 На ревью: {total_review}"
            )

            # Добавляем детали по ревью если есть активность
            if total_review > 0:
                commits_report += (
                    f" (🆕{stats.get('review_created', 0)} 🔄{stats.get('review_updated', 0)})"
                )

        except Exception as e:
            logger.exception(f"Error in commits pipeline: {e}")
            # Более детальная информация об ошибке для отладки
            if "COMMITS_DB_ID" in str(e) or "REVIEW_DB_ID" in str(e):
                commits_report = "⚠️ <b>Коммиты:</b> не настроены базы данных Notion (COMMITS_DB_ID/REVIEW_DB_ID)."
            elif "400 Bad Request" in str(e):
                commits_report = (
                    "⚠️ <b>Коммиты:</b> ошибка Notion API (проверьте настройки баз данных)."
                )
            else:
                commits_report = "⚠️ <b>Коммиты:</b> ошибка обработки, встреча сохранена."

        # 6) Финальный ответ с красивым форматированием
        from app.bot.formatters import format_meeting_card, format_success_card

        # Формируем данные встречи для карточки
        meeting_data = {
            "title": filename.replace("_", " ").replace(".txt", ""),
            "date": meta.get("meeting_date"),
            "attendees": attendees_en,
            "tags": tags,
            "url": notion_url,
        }

        # Красивая карточка встречи
        meeting_card = format_meeting_card(meeting_data)

        # Предварительный просмотр (экранируем HTML для безопасности)
        import html
        preview = "\n".join(summary_md.splitlines()[:MAX_PREVIEW_LINES])
        # Экранируем HTML entities чтобы избежать ошибок парсинга
        preview_escaped = html.escape(preview)
        preview_card = f"📋 <b>Предварительный просмотр:</b>\n\n" f"<pre>{preview_escaped}</pre>"

        chunks = [
            format_success_card("Встреча обработана успешно!"),
            meeting_card,
            preview_card,
            commits_report,
        ]
        import re as _re, html as _html
        for part in chunks:
            try:
                await msg.answer(part, parse_mode="HTML")
            except Exception as html_err:
                # Если HTML парсинг не работает - стрипаем ВСЕ HTML теги и отправляем plain
                logger.warning(f"HTML parse error, sending as plain text: {html_err}")
                plain = _html.unescape(_re.sub(r"<[^>]+>", "", part))
                # ВАЖНО: явно передаем parse_mode=None, иначе бот использует дефолтный HTML
                await msg.answer(plain, parse_mode=None)

        # 7) Запускаем интерактивное ревью тегов (если включено)
        tags_review_started = False
        try:
            from app.bot.handlers_tags_review import start_tags_review

            meeting_page_id = _extract_page_id_from_url(notion_url)
            user_id = msg.from_user.id if msg.from_user else 0

            await start_tags_review(
                meeting_id=meeting_page_id,
                original_tags=tags,
                user_id=user_id,
                message=msg,
                state=state,
            )
            tags_review_started = True

        except Exception as e:
            logger.warning(f"Failed to start tags review: {e}")
            # Не критично - показываем обычное меню
            from app.bot.handlers_inline import build_main_menu_kb

            await msg.answer("🎯 <b>Что дальше?</b>", reply_markup=build_main_menu_kb(), parse_mode="HTML")

        # Очищаем состояние только если ревью тегов НЕ было запущено
        if not tags_review_started:
            await state.clear()

    except Exception as e:
        await msg.answer(f"Не удалось обработать. Причина: {type(e).__name__}: {e}")
        await state.clear()  # При ошибке всегда очищаем состояние


# ====== КОМАНДЫ ДЛЯ УПРАВЛЕНИЯ REVIEW QUEUE ======


def _clean_sid(s: str) -> str:
    """Очищает short ID от лишних символов и возвращает последние 6 символов."""
    return re.sub(r"[^0-9A-Za-z]", "", s)[-6:]


@router.message(F.text.regexp(r"^/review(\s+\d+)?$"))
async def cmd_review(msg: Message):
    """Показывает список открытых элементов в Review queue."""
    try:
        parts = (msg.text or "").strip().split()
        limit = int(parts[1]) if len(parts) > 1 else 5

        # Используем новую логику фильтрации открытых записей
        items = list_open_reviews(limit=limit)

        if not items:
            await _send_empty_queue_message_with_menu(msg)
            return

        # Используем новое красивое форматирование
        # Показываем заголовок с кнопкой "Confirm All"
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

        from app.bot.formatters import format_review_card
        from app.bot.handlers_inline import build_review_item_kb

        confirm_all_kb = InlineKeyboardMarkup(
            inline_keyboard=[
                [
                    InlineKeyboardButton(text="✅ Confirm All", callback_data="review_confirm_all"),
                    InlineKeyboardButton(text="🔄 Обновить", callback_data="main_review"),
                ]
            ]
        )

        await msg.answer(
            f"📋 <b>Review Queue ({len(items)} элементов):</b>\n\n"
            f"💡 <i>Проверьте и подтвердите коммиты:</i>",
            reply_markup=confirm_all_kb,
        )

        # Показываем каждый элемент с кнопками
        for item in items:
            short_id = item["short_id"]
            formatted_card = format_review_card(item)
            await msg.answer(
                formatted_card, parse_mode="HTML", reply_markup=build_review_item_kb(short_id)
            )

    except Exception as e:
        logger.error(f"Error in cmd_review: {e}")
        await msg.answer("❌ Ошибка при получении списка review.")


@router.message(F.text.regexp(r"^/flip\s+\S+$", flags=re.I))
async def cmd_flip(msg: Message):
    """Переключает direction между mine и theirs."""
    try:
        short_id = _clean_sid((msg.text or "").strip().split()[1])
        item = get_by_short_id(short_id)

        if not item:
            await msg.answer(f"❌ Карточка [{short_id}] не найдена. Проверьте /review.")
            return

        current_direction = item["direction"] or "theirs"
        new_direction = "mine" if current_direction == "theirs" else "theirs"

        try:
            success = update_fields(item["page_id"], direction=new_direction)
            if success:
                await msg.answer(f"✅ [{short_id}] Direction → {new_direction}")
            else:
                await msg.answer(f"❌ Не удалось обновить direction для [{short_id}].")
        except Exception as e:
            logger.error(f"Error updating direction: {e}")
            await msg.answer(f"❌ Ошибка обновления direction: {e}")

    except Exception as e:
        logger.error(f"Error in cmd_flip: {e}")
        await msg.answer("❌ Ошибка при выполнении flip.")


@router.message(F.text.regexp(r"^/assign\s+\S+\s+.+$", flags=re.I))
async def cmd_assign_manual(msg: Message):
    """Назначает исполнителя на карточку (ручной ввод - legacy)."""
    try:
        parts = (msg.text or "").strip().split(maxsplit=2)
        if len(parts) < 3:
            await msg.answer("Синтаксис: /assign <id> <имя>")
            return

        short_id = _clean_sid(parts[1])
        raw_names = parts[2]
        item = get_by_short_id(short_id)

        if not item:
            await msg.answer(f"❌ Карточка [{short_id}] не найдена. Проверьте /review.")
            return

        # Сначала пытаемся найти полное имя как есть, потом разбиваем
        # Это исправляет проблему с "Sergey Lompa" -> ["Sergey", "Lompa"]

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
            await msg.answer(f"❌ Не удалось распознать исполнителя(ей): {raw_names}")
            return

        success = update_fields(item["page_id"], assignees=normalized_assignees)

        if success:
            assignees_str = ", ".join(normalized_assignees)
            await msg.answer(f"✅ [{short_id}] Assignee → {assignees_str}")
        else:
            await msg.answer(f"❌ Не удалось обновить assignee для [{short_id}].")

    except Exception as e:
        logger.error(f"Error in cmd_assign: {e}")
        await msg.answer("❌ Ошибка при выполнении assign.")


@router.message(F.text.regexp(r"^/delete\s+\S+$", flags=re.I))
async def cmd_delete(msg: Message):
    """Помечает карточку как dropped."""
    try:
        short_id = _clean_sid((msg.text or "").strip().split()[1])
        item = get_by_short_id(short_id)

        if not item:
            await msg.answer(f"❌ Карточка [{short_id}] не найдена. Проверьте /review.")
            return

        try:
            # Валидируем действие
            from app.core.review_queue import validate_review_action

            is_valid, error_msg = validate_review_action(item, "delete")
            if not is_valid:
                await msg.answer(f"❌ {error_msg}")
                return

            set_status(item["page_id"], REVIEW_STATUS_DROPPED)
            await msg.answer(f"✅ [{short_id}] Удалено (dropped).")
            logger.info(f"Review item {short_id} marked as dropped")
        except Exception as e:
            logger.error(f"Error setting status: {e}")
            await msg.answer(f"❌ Ошибка удаления: {e}")

    except Exception as e:
        logger.error(f"Error in cmd_delete: {e}")
        await msg.answer("❌ Ошибка при выполнении delete.")


@router.message(F.text.regexp(r"^/confirm\s+\S+.*$", flags=re.I))
async def cmd_confirm(msg: Message):
    """Подтверждает карточку и создает коммит."""
    try:
        parts = (msg.text or "").strip().split()
        if len(parts) < 2:
            await msg.answer("❌ Синтаксис: /confirm <short_id>")
            return

        if len(parts) > 2:
            await msg.answer(
                f"❌ Команда /confirm принимает только ID карточки.\n"
                f"Синтаксис: /confirm <short_id>\n"
                f"Возможно, вы хотели: /assign {parts[1]} {' '.join(parts[2:])}"
            )
            return

        short_id = _clean_sid(parts[1])
        item = get_by_short_id(short_id)

        if not item:
            await msg.answer(f"❌ Карточка [{short_id}] не найдена. Проверьте /review.")
            return

        # Собираем данные для коммита
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
            "from_person": ["System"],  # Для подтвержденных из Review - заказчик System
            "due_iso": due_iso,
            "confidence": item["confidence"] or 0.6,
            "flags": [],
            "key": key,
            "tags": [],  # TODO: можно добавить наследование тегов из Meeting
            "status": "open",
        }

        # Сохраняем в Commits
        meeting_page_id = item["meeting_page_id"]
        if not meeting_page_id:
            await msg.answer(f"❌ [{short_id}] Не найден meeting_page_id.")
            return

        result = upsert_commits(meeting_page_id, [commit_item])
        created = len(result.get("created", []))
        updated = len(result.get("updated", []))

        # Валидируем действие
        from app.core.review_queue import validate_review_action

        is_valid, error_msg = validate_review_action(item, "confirm")
        if not is_valid:
            await msg.answer(f"❌ {error_msg}")
            return

        if created or updated:
            # Получаем ID созданного/обновленного коммита
            commit_ids = result.get("created", []) + result.get("updated", [])
            commit_id = commit_ids[0] if commit_ids else None

            # Помечаем review как resolved с привязкой к коммиту
            try:
                set_status(item["page_id"], REVIEW_STATUS_RESOLVED, linked_commit_id=commit_id)
                # Используем красивое форматирование для успеха
                from app.bot.formatters import format_success_card

                success_details = {
                    "created": created,
                    "updated": updated,
                    "commit_id": commit_id,
                    "review_status": "resolved",
                }

                formatted_response = format_success_card(
                    f"[{short_id}] Коммит подтвержден", success_details
                )
                await msg.answer(formatted_response, parse_mode="HTML")
                logger.info(
                    f"Review item {short_id} confirmed, linked to commit {commit_id[:8] if commit_id else 'none'}"
                )
            except Exception as e:
                logger.error(f"Error setting resolved status: {e}")
                await msg.answer(
                    f"✅ [{short_id}] Коммит создан, но не удалось обновить статус: {e}"
                )
        else:
            await msg.answer(f"❌ [{short_id}] Не удалось создать коммит.")

    except Exception as e:
        logger.error(f"Error in cmd_confirm: {e}")
        await msg.answer("❌ Ошибка при выполнении confirm.")


@router.message(F.text.regexp(r"^/(review|flip|assign|delete|confirm)\b", flags=re.I))
async def cmd_review_fallback(msg: Message):
    """Fallback для неправильного синтаксиса команд review."""
    text = (msg.text or "").strip()

    if text.startswith("/review"):
        await msg.answer("❌ Неправильный синтаксис.\n" "Используйте: /review [количество]")
    elif text.startswith("/flip"):
        await msg.answer("❌ Неправильный синтаксис.\n" "Используйте: /flip <short_id>")
    elif text.startswith("/assign"):
        await msg.answer("❌ Неправильный синтаксис.\n" "Используйте: /assign <short_id> <имя>")
    elif text.startswith("/delete"):
        await msg.answer("❌ Неправильный синтаксис.\n" "Используйте: /delete <short_id>")
    elif text.startswith("/confirm"):
        await msg.answer("❌ Неправильный синтаксис.\n" "Используйте: /confirm <short_id>")
