# app/bot/handlers.py
from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.core.commit_normalize import normalize_commits
from app.core.commit_validate import validate_and_partition
from app.core.llm_extract_commits import extract_commits
from app.core.llm_summarize import run as summarize_run
from app.core.normalize import run as normalize_run
from app.core.tagger import run as tagger_run
from app.gateways.notion_commits import upsert_commits
from app.gateways.notion_gateway import upsert_meeting
from app.gateways.notion_review import enqueue

logger = logging.getLogger(__name__)

router = Router()

PROMPTS_DIR = Path(__file__).resolve().parent.parent / "prompts"
MAX_PREVIEW_LINES = 12


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
    await msg.answer("Пришли файл или текст транскрипта. Затем выбери шаблон суммаризации.")


@router.message(F.text == "/cancel")
async def cmd_cancel(msg: Message, state: FSMContext):
    await state.clear()
    await msg.answer("Ок. Сбросил состояние.")


@router.message(F.document | (F.text & ~F.text.startswith("/")))
async def receive_input(msg: Message, state: FSMContext):
    # Проверяем, не находимся ли мы в состоянии ожидания дополнительного промпта
    current_state = await state.get_state()
    if current_state == IngestStates.waiting_extra:
        # Если да, то это дополнительный промпт, передаем управление соответствующему обработчику
        await extra_entered(msg, state)
        return

    raw_bytes: bytes | None = None
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
        else:
            await msg.answer("Ошибка: не удалось загрузить файл")
            return
        filename = msg.document.file_name or "meeting.txt"
    else:
        text = msg.text or ""

    await state.update_data(raw_bytes=raw_bytes, text=text, filename=filename)
    await state.set_state(IngestStates.waiting_prompt)
    await msg.answer("Выбери шаблон суммаризации:", reply_markup=_prompts_kb())


@router.callback_query(F.data.startswith("prompt:"))
async def choose_prompt(cb: CallbackQuery, state: FSMContext):
    try:
        data = await state.get_data()

        if not data.get("raw_bytes") and not data.get("text"):
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
    Извлекает page_id из Notion URL.

    Args:
        notion_url: URL страницы Notion

    Returns:
        Page ID для использования в API

    Example:
        https://notion.so/page_123abc -> page_123abc
    """
    # Notion URLs обычно имеют формат: https://notion.so/{page_id}
    # или https://www.notion.so/{workspace}/{page_id}
    parts = notion_url.rstrip("/").split("/")
    return parts[-1]


async def run_commits_pipeline(
    meeting_page_id: str,
    meeting_text: str,
    attendees_en: list[str],
    meeting_date_iso: str,
    meeting_tags: list[str] | None,
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

        # 5) Отправка проблемных коммитов в Review Queue (в executor, т.к. синхронный)
        review_ids: list[str] = []
        if partition_result.to_review:
            review_ids = await asyncio.get_event_loop().run_in_executor(
                None, lambda: enqueue(partition_result.to_review, meeting_page_id)
            )

        stats = {
            "created": len(commits_result.get("created", [])),
            "updated": len(commits_result.get("updated", [])),
            "review": len(review_ids),
        }

        logger.info(f"Commits pipeline completed: {stats}")
        return stats

    except Exception as e:
        logger.exception(f"Error in commits pipeline for meeting {meeting_page_id}: {e}")
        # Возвращаем нулевую статистику при ошибке
        return {"created": 0, "updated": 0, "review": 0}


async def run_pipeline(msg: Message, state: FSMContext, extra: str | None):
    try:
        data = await state.get_data()
        raw_bytes = data.get("raw_bytes")
        text = data.get("text")
        filename = data.get("filename") or "meeting.txt"
        prompt_file = data.get("prompt_file")

        if not prompt_file:
            await msg.answer("Не выбран шаблон. Начни заново: пришли файл/текст.")
            await state.clear()
            return

        # Уведомляем о начале обработки
        await msg.answer("🔄 <b>Начинаю обработку...</b>\n\n📄 Извлекаю текст из файла...")

        # 1) normalize
        meta = normalize_run(raw_bytes=raw_bytes, text=text, filename=filename)

        # Уведомляем о суммаризации
        await msg.answer("🤖 <b>Суммаризирую через AI...</b>\n\n⏳ Это может занять 1-4 минуты...")

        # 2) summarize
        prompt_path = (PROMPTS_DIR / prompt_file).as_posix()
        summary_md = await summarize_run(text=meta["text"], prompt_path=prompt_path, extra=extra)

        # 3) tagger v0
        tags = tagger_run(summary_md=summary_md, meta=meta)

        # Уведомляем о сохранении в Notion
        await msg.answer("💾 <b>Сохраняю в Notion...</b>\n\n📝 Создаю страницу в базе данных...")

        # 4) Notion upsert
        notion_url = upsert_meeting(
            {
                "title": meta["title"],
                "date": meta["date"],
                "attendees": meta.get("attendees", []),
                "source": "telegram",
                "raw_hash": meta["raw_hash"],
                "summary_md": summary_md,
                "tags": tags,
            }
        )

        # 5) Обработка коммитов
        await msg.answer(
            "🔍 <b>Обрабатываю коммиты...</b>\n\n🤖 Извлекаю обязательства из транскрипта..."
        )

        try:
            # Извлекаем page_id из URL для связи коммитов с встречей
            meeting_page_id = _extract_page_id_from_url(notion_url)

            # Запускаем пайплайн коммитов асинхронно
            stats = await run_commits_pipeline(
                meeting_page_id=meeting_page_id,
                meeting_text=meta["text"],
                attendees_en=meta.get("attendees", []),
                meeting_date_iso=meta["date"],
                meeting_tags=tags,
            )

            # Формируем отчет по коммитам
            commits_report = (
                f"📊 <b>Коммиты обработаны:</b>\n"
                f"• ✅ Сохранено: {stats['created'] + stats['updated']}\n"
                f"• 🆕 Создано: {stats['created']}\n"
                f"• 🔄 Обновлено: {stats['updated']}\n"
                f"• 🔍 На ревью: {stats['review']}"
            )

        except Exception as e:
            logger.exception(f"Error in commits pipeline: {e}")
            commits_report = "⚠️ <b>Коммиты:</b> ошибка обработки, встреча сохранена."

        # 6) Финальный ответ
        preview = "\n".join(summary_md.splitlines()[:MAX_PREVIEW_LINES])
        chunks = [
            f"✅ <b>Готово!</b>\n\n📋 <b>Предварительный просмотр:</b>\n<pre>{preview}</pre>",
            commits_report,
            f"🔗 <a href='{notion_url}'>Открыть полный результат в Notion</a>",
        ]
        for part in chunks:
            await msg.answer(part)

    except Exception as e:
        await msg.answer(f"Не удалось обработать. Причина: {type(e).__name__}: {e}")
    finally:
        await state.clear()
