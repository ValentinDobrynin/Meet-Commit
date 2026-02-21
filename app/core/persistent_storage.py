"""
Управление постоянным хранилищем для облачного деплоя (Render).

На Render можно подключить Persistent Disk — директорию которая
не сбрасывается при каждом деплое.

Если PERSISTENT_DATA_DIR задан (путь к диску), при старте:
  1. Копируем файлы из git в persistent storage (если их там нет)
  2. Создаём симлинки app/dictionaries/ → persistent storage

Без диска работает как раньше (файлы в проекте, сбрасываются при деплое).
"""

from __future__ import annotations

import logging
import os
import shutil
from pathlib import Path

logger = logging.getLogger(__name__)

# Файлы словарей которые должны персистентно храниться
# (изменяются при работе бота)
PERSISTENT_FILES = [
    "people.json",          # ← Основной! Одобренные имена через /people_miner2
    "people_stopwords.json", # Стоп-слова — редко меняются, но всё же
    "tags.json",            # Правила тегов
    "tag_synonyms.json",    # Синонимы тегов
]

# Файлы которые НЕ переносим (они эфемерны по дизайну)
EPHEMERAL_FILES = [
    "people_candidates.json",  # Пересоздаётся из встреч
    "active_users.json",       # Пересоздаётся из /start
]


def get_persistent_dir() -> Path | None:
    """
    Возвращает путь к persistent storage или None если не настроен.

    В Render Dashboard нужно:
    1. Settings → Disks → Add Disk
    2. Name: meet-commit-data
    3. Mount Path: /data
    4. Size: 1 GB

    Затем добавить env var: PERSISTENT_DATA_DIR=/data/dictionaries
    """
    data_dir = os.getenv("PERSISTENT_DATA_DIR")
    if data_dir:
        return Path(data_dir)
    return None


def init_persistent_storage() -> bool:
    """
    Инициализирует persistent storage при старте.

    Если PERSISTENT_DATA_DIR задан:
    - Создаёт директорию если нет
    - Копирует seed-файлы из git (если их нет в persistent storage)
    - Настраивает пути чтобы код читал/писал в persistent storage

    Возвращает True если persistent storage настроен.
    """
    persistent_dir = get_persistent_dir()

    if not persistent_dir:
        logger.info(
            "PERSISTENT_DATA_DIR not set — using ephemeral filesystem. "
            "people.json changes will be lost on redeploy. "
            "To fix: add Persistent Disk in Render Dashboard, "
            "mount at /data, set PERSISTENT_DATA_DIR=/data/dictionaries"
        )
        return False

    # Создаём директорию
    persistent_dir.mkdir(parents=True, exist_ok=True)
    logger.info(f"✅ Persistent storage: {persistent_dir}")

    # Путь к seed-файлам в проекте (из git)
    app_dir = Path(__file__).resolve().parent.parent
    seed_dir = app_dir / "dictionaries"

    copied = []
    already_exist = []

    for filename in PERSISTENT_FILES:
        persistent_path = persistent_dir / filename
        seed_path = seed_dir / filename

        if persistent_path.exists():
            # Файл уже есть в persistent storage — не трогаем (сохраняем runtime изменения)
            already_exist.append(filename)
        elif seed_path.exists():
            # Первый запуск или файл удалён — копируем из git
            shutil.copy2(seed_path, persistent_path)
            copied.append(filename)
            logger.info(f"Copied seed file to persistent storage: {filename}")
        else:
            logger.warning(f"Seed file not found: {seed_path}")

    if copied:
        logger.info(f"Initialized persistent storage: {copied}")
    if already_exist:
        logger.info(f"Using existing persistent files: {already_exist}")

    # Подменяем пути в people_store и people_miner2
    _patch_dict_paths(persistent_dir, seed_dir)

    return True


def _patch_dict_paths(persistent_dir: Path, seed_dir: Path) -> None:
    """
    Подменяет пути к словарям на persistent storage.

    Это позволяет коду people_store.py и people_miner2.py
    читать/писать в /data/dictionaries вместо app/dictionaries.
    """
    try:
        import app.core.people_store as ps
        import app.core.people_miner2 as pm

        for filename in PERSISTENT_FILES:
            persistent_path = persistent_dir / filename

            # people_store.py использует PEOPLE и CAND константы
            if filename == "people.json":
                ps.PEOPLE = persistent_path  # type: ignore[attr-defined]
                logger.debug(f"Patched people_store.PEOPLE → {persistent_path}")

            elif filename == "people_stopwords.json":
                ps.STOPS = persistent_path  # type: ignore[attr-defined]
                logger.debug(f"Patched people_store.STOPS → {persistent_path}")

        # people_miner2.py использует CANDIDATES_PATH
        candidates_path = persistent_dir / "people_candidates.json"
        if not candidates_path.exists():
            # Создаём пустой файл кандидатов в persistent storage
            candidates_path.write_text("{}", encoding="utf-8")
        pm.CANDIDATES_PATH = candidates_path  # type: ignore[attr-defined]
        logger.debug(f"Patched people_miner2.CANDIDATES_PATH → {candidates_path}")

        logger.info(f"✅ Dictionary paths patched to persistent storage: {persistent_dir}")

    except Exception as e:
        logger.error(f"Failed to patch dict paths: {e}")
