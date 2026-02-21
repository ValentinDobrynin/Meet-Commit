"""
LLM-фильтрация кандидатов в имена людей.

Отсекает слова и фразы, которые заведомо не являются именами:
глаголы, существительные, названия компаний, технические термины и т.д.

Используется батчевый запрос к GPT: одним вызовом проверяем до 50 кандидатов.
"""

from __future__ import annotations

import json
import logging
from typing import Any

logger = logging.getLogger(__name__)

PROMPT = """Ты проверяешь список строк и определяешь, какие из них являются именами реальных людей.

Правила:
- Имя человека: "Иван", "Саша Петров", "John Smith", "Катанов", "Влад" → KEEP
- Русское имя в падеже: "Ваней", "Наталье", "Артёма", "Сережей" → KEEP (это имена в косвенных падежах)
- Глагол или наречие: "Планируем", "Фиксируем", "Слушай", "Торопись" → SKIP
- Существительное (не имя): "Привет", "Спасибо", "Пожалуйста", "Давайте", "Супер" → SKIP
- Топоним или страна: "Узбекистан", "Берн", "Аляска", "Турции" → SKIP
- Название компании/продукта: "Alpharace", "Synergy", "Oracle", "Advanced Integration" → SKIP
- Технический термин: "Deliverables", "Monitoring", "Energy", "Documents" → SKIP
- Бессмысленное слово: "Березаряде", "Гидроидс", "Переметрируйте" → SKIP
- Союз/местоимение: "Один", "Либо", "Разве", "Чтобы", "Тебя" → SKIP
- Краткое прилагательное: "Главное", "Просто", "Скорее", "Чуть" → SKIP

Верни JSON объект:
{"keep": ["имя1", "имя2", ...], "skip": ["слово1", "слово2", ...]}

Строки для проверки:
{candidates_json}"""


def filter_candidates_via_llm(
    candidates: list[str],
    *,
    batch_size: int = 50,
) -> tuple[list[str], list[str]]:
    """
    Фильтрует кандидатов через LLM.

    Args:
        candidates: Список строк для проверки
        batch_size: Размер батча (не больше 50 для экономии токенов)

    Returns:
        (keep_list, skip_list) — что оставить и что отклонить
    """
    if not candidates:
        return [], []

    try:
        from app.core.clients import get_openai_client
    except Exception as e:
        logger.error(f"Cannot get OpenAI client: {e}")
        return candidates, []

    keep_total: list[str] = []
    skip_total: list[str] = []

    # Разбиваем на батчи
    for i in range(0, len(candidates), batch_size):
        batch = candidates[i : i + batch_size]
        keep, skip = _filter_batch(batch)
        keep_total.extend(keep)
        skip_total.extend(skip)

    logger.info(
        f"LLM people filter: {len(keep_total)} kept, {len(skip_total)} skipped "
        f"from {len(candidates)} candidates"
    )
    return keep_total, skip_total


def _filter_batch(batch: list[str]) -> tuple[list[str], list[str]]:
    """Отправляет один батч в LLM и возвращает (keep, skip)."""
    from app.core.clients import get_openai_client

    candidates_json = json.dumps(batch, ensure_ascii=False)
    prompt = PROMPT.replace("{candidates_json}", candidates_json)

    client = get_openai_client()
    try:
        resp = client.chat.completions.create(
            model="gpt-4o-mini",
            temperature=0.1,
            messages=[
                {"role": "user", "content": prompt},
            ],
            response_format={"type": "json_object"},
        )
        raw = (resp.choices[0].message.content or "").strip()
        result: dict[str, Any] = json.loads(raw)

        keep = [str(x) for x in result.get("keep", [])]
        skip = [str(x) for x in result.get("skip", [])]

        # Добавляем то, что LLM не отнёс ни к keep ни к skip — по умолчанию keep
        classified = set(keep) | set(skip)
        unclassified = [c for c in batch if c not in classified]
        if unclassified:
            logger.debug(f"LLM didn't classify {len(unclassified)} items, keeping: {unclassified}")
            keep.extend(unclassified)

        return keep, skip

    except Exception as e:
        logger.error(f"LLM people filter batch error: {e}")
        # При ошибке — пропускаем все (не теряем данные)
        return batch, []
    finally:
        client.close()


def clean_existing_candidates() -> dict[str, int]:
    """
    Разовая очистка существующих кандидатов через LLM.

    Полезно для исправления накопленного шлака.
    Возвращает: {"kept": N, "removed": M}

    Важно: использует people_miner2._load_candidates() и reject_candidate(),
    так как /people_miner2 хранит кандидатов в собственном формате (CandidateData),
    отдельном от people_store.load_candidates() (простой {alias: count}).
    """
    # Импортируем напрямую из people_miner2 — там хранятся данные для /people_miner2
    from app.core.people_miner2 import _load_candidates, reject_candidate

    all_candidates = _load_candidates()
    if not all_candidates:
        logger.info("No candidates to clean")
        return {"kept": 0, "removed": 0}

    aliases = list(all_candidates.keys())
    logger.info(f"Cleaning {len(aliases)} candidates via LLM (miner2 format)...")

    keep, skip = filter_candidates_via_llm(aliases)

    removed = 0
    for alias in skip:
        if reject_candidate(alias):
            removed += 1
            logger.info(f"Removed junk candidate: {alias!r}")

    return {"kept": len(keep), "removed": removed}
