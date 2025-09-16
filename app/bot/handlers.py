# app/bot/handlers.py
from __future__ import annotations

from pathlib import Path

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, Message
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.core.llm_summarize import run as summarize_run
from app.core.normalize import run as normalize_run
from app.core.tagger import run as tagger_run
from app.gateways.notion_gateway import upsert_meeting

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

        # 5) Финальный ответ
        preview = "\n".join(summary_md.splitlines()[:MAX_PREVIEW_LINES])
        chunks = [
            f"✅ <b>Готово!</b>\n\n📋 <b>Предварительный просмотр:</b>\n<pre>{preview}</pre>",
            f"🔗 <a href='{notion_url}'>Открыть полный результат в Notion</a>",
        ]
        for part in chunks:
            await msg.answer(part)

    except Exception as e:
        await msg.answer(f"Не удалось обработать. Причина: {type(e).__name__}: {e}")
    finally:
        await state.clear()
