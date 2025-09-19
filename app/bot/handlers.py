# app/bot/handlers.py
from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path

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
from app.core.tagger import run as tagger_run
from app.gateways.notion_commits import upsert_commits
from app.gateways.notion_gateway import upsert_meeting
from app.gateways.notion_review import (
    enqueue,
    get_by_short_id,
    list_pending,
    set_status,
    update_fields,
)

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

        # DEBUG: Показываем что извлек LLM
        if msg:
            await msg.answer(f"[debug] extracted={len(extracted_commits)}")

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

        # DEBUG: Показываем результат партиционирования
        if msg:
            await msg.answer(
                f"[debug] to_commits={len(partition_result.to_commits)} to_review={len(partition_result.to_review)}"
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
            try:
                review_ids = await asyncio.get_event_loop().run_in_executor(
                    None, lambda: enqueue(partition_result.to_review, meeting_page_id)
                )
            except Exception as e:
                logger.error(f"Error enqueueing review items: {e}")
                # Продолжаем работу даже если Review Queue не работает

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

        # 4) Подготовка данных для Notion
        # Канонизируем участников к EN именам
        raw_attendees = meta.get("attendees", [])
        attendees_en = canonicalize_list(raw_attendees)

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
            commits_report = (
                f"📊 <b>Коммиты обработаны:</b>\n"
                f"• ✅ Сохранено: {stats['created'] + stats['updated']}\n"
                f"• 🆕 Создано: {stats['created']}\n"
                f"• 🔄 Обновлено: {stats['updated']}\n"
                f"• 🔍 На ревью: {stats['review']}"
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


# ====== КОМАНДЫ ДЛЯ УПРАВЛЕНИЯ REVIEW QUEUE ======


def _clean_sid(s: str) -> str:
    """Очищает short ID от лишних символов и возвращает последние 6 символов."""
    return re.sub(r"[^0-9A-Za-z]", "", s)[-6:]


@router.message(F.text.regexp(r"^/review(\s+\d+)?$"))
async def cmd_review(msg: Message):
    """Показывает список pending элементов в Review queue."""
    try:
        parts = (msg.text or "").strip().split()
        limit = int(parts[1]) if len(parts) > 1 else 5

        items = list_pending(limit=limit)

        if not items:
            await msg.answer("📋 Review queue пуста.")
            return

        lines = ["📋 Pending review:"]
        for item in items:
            assignees_str = ", ".join(item["assignees"]) if item["assignees"] else "—"
            due_str = item["due_iso"] or "—"
            conf_str = f"{item['confidence']:.2f}" if item["confidence"] is not None else "—"

            text_preview = (item["text"] or "")[:90]
            if len(item["text"] or "") > 90:
                text_preview += "..."

            lines.append(
                f"[{item['short_id']}] {text_preview}\n"
                f"    dir={item['direction'] or '?'} | who={assignees_str} | due={due_str} | conf={conf_str}"
            )

        await msg.answer("\n\n".join(lines))

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
async def cmd_assign(msg: Message):
    """Назначает исполнителя на карточку."""
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

        # Разбираем имена (через пробел или запятую)
        raw_list = [x.strip() for x in raw_names.replace(",", " ").split() if x.strip()]

        # Нормализуем через словарь people.json
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
            set_status(item["page_id"], REVIEW_STATUS_DROPPED)
            await msg.answer(f"✅ [{short_id}] Удалено (dropped).")
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
            await msg.answer(f"❌ Команда /confirm принимает только ID карточки.\n"
                           f"Синтаксис: /confirm <short_id>\n"
                           f"Возможно, вы хотели: /assign {parts[1]} {' '.join(parts[2:])}")
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

        if created or updated:
            # Помечаем review как resolved
            try:
                set_status(item["page_id"], REVIEW_STATUS_RESOLVED)
                await msg.answer(
                    f"✅ [{short_id}] Confirmed! Создано: {created}, обновлено: {updated}."
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
        await msg.answer("❌ Неправильный синтаксис.\n"
                        "Используйте: /review [количество]")
    elif text.startswith("/flip"):
        await msg.answer("❌ Неправильный синтаксис.\n"
                        "Используйте: /flip <short_id>")
    elif text.startswith("/assign"):
        await msg.answer("❌ Неправильный синтаксис.\n"
                        "Используйте: /assign <short_id> <имя>")
    elif text.startswith("/delete"):
        await msg.answer("❌ Неправильный синтаксис.\n"
                        "Используйте: /delete <short_id>")
    elif text.startswith("/confirm"):
        await msg.answer("❌ Неправильный синтаксис.\n"
                        "Используйте: /confirm <short_id>")
