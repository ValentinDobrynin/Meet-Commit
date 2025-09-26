import asyncio
import fcntl
import logging
import os
import sys
import tempfile
from pathlib import Path

from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv

from .handlers import router
from .handlers_admin import router as admin_router
from .handlers_admin_monitoring import router as admin_monitoring_router
from .handlers_agenda import router as agenda_router
from .handlers_direct_commit import router as direct_commit_router
from .handlers_inline import router as inline_router
from .handlers_llm_commit import router as llm_commit_router
from .handlers_people import router as people_router
from .handlers_queries import router as queries_router
from .handlers_tags_review import router as tags_review_router
from .init import build_bot

# Загружаем переменные окружения из .env файла ПЕРЕД импортами
load_dotenv()


# Настройка логирования
def setup_logging():
    """Настраивает логирование для бота."""
    # Создаем директорию для логов если не существует
    log_dir = Path("logs")
    log_dir.mkdir(exist_ok=True)

    # Настраиваем форматирование
    log_format = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
    date_format = "%Y-%m-%d %H:%M:%S"

    # Создаем обработчики
    all_logs_handler = logging.FileHandler("logs/bot.log", encoding="utf-8")
    all_logs_handler.setLevel(logging.INFO)

    error_logs_handler = logging.FileHandler("logs/bot_errors.log", encoding="utf-8")
    error_logs_handler.setLevel(logging.ERROR)

    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setLevel(logging.INFO)

    # Настраиваем форматтеры
    formatter = logging.Formatter(log_format, date_format)
    all_logs_handler.setFormatter(formatter)
    error_logs_handler.setFormatter(formatter)
    console_handler.setFormatter(formatter)

    # Настраиваем логгеры
    logging.basicConfig(
        level=logging.INFO,  # Возвращаем INFO уровень
        handlers=[all_logs_handler, error_logs_handler, console_handler],
    )

    # Настраиваем уровни для разных модулей
    logging.getLogger("aiogram").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    # Создаем основной логгер для бота
    logger = logging.getLogger("meet_commit_bot")
    logger.setLevel(logging.INFO)

    return logger


# Инициализируем логирование
logger = setup_logging()

# Проверяем наличие обязательных переменных окружения
try:
    TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
except KeyError:
    raise ValueError("TELEGRAM_TOKEN not found in environment variables") from None

bot, dp = build_bot(TELEGRAM_TOKEN, MemoryStorage())
# Специализированные роутеры должны быть зарегистрированы ПЕРЕД основным
dp.include_router(tags_review_router)  # Приоритет для FSM состояний
dp.include_router(direct_commit_router)  # Прямые коммиты с FSM
dp.include_router(llm_commit_router)  # LLM коммиты (без FSM)
dp.include_router(agenda_router)  # Система повесток с FSM
dp.include_router(queries_router)  # Команды запросов к коммитам
dp.include_router(inline_router)
dp.include_router(admin_router)
dp.include_router(admin_monitoring_router)  # Расширенные админские команды
dp.include_router(people_router)
dp.include_router(router)  # Основной роутер последним


def acquire_lock():
    """Создает lock-файл для предотвращения множественных запусков"""
    lock_file = Path(tempfile.gettempdir()) / "meet_commit_bot.lock"

    try:
        # Создаем lock-файл
        lock_fd = os.open(lock_file, os.O_CREAT | os.O_WRONLY | os.O_TRUNC)
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)

        # Записываем PID процесса
        os.write(lock_fd, str(os.getpid()).encode())
        os.close(lock_fd)

        logger.info(f"Lock acquired. PID: {os.getpid()}")
        return True

    except OSError as e:
        if e.errno == 11:  # EAGAIN - файл заблокирован
            logger.error("Bot is already running! Another instance is active.")
            logger.info("To stop the existing bot, run: pkill -f 'python app/bot/main.py'")
            return False
        else:
            logger.error(f"Failed to acquire lock: {e}")
            return False


def release_lock():
    """Освобождает lock-файл"""
    lock_file = Path(tempfile.gettempdir()) / "meet_commit_bot.lock"
    try:
        if lock_file.exists():
            lock_file.unlink()
            logger.info("Lock released.")
    except Exception as e:
        logger.warning(f"Could not release lock: {e}")


async def run() -> None:
    """Запуск Telegram бота"""
    try:
        logger.info("🤖 Starting bot in polling mode...")

        # Отправляем приветствия активным пользователям при запуске
        from app.bot.startup_greeting import send_startup_greetings_safe

        logger.info("Sending startup greetings to active users...")
        await send_startup_greetings_safe(bot)

        logger.info("Bot polling started. Waiting for messages...")
        await dp.start_polling(bot, allowed_updates=["message", "callback_query"])
    except Exception as e:
        logger.error(f"Bot error: {e}", exc_info=True)
        raise


if __name__ == "__main__":
    # Проверяем, не запущен ли уже бот
    if not acquire_lock():
        sys.exit(1)

    try:
        logger.info("🚀 Meet-Commit Bot starting...")
        asyncio.run(run())
    except KeyboardInterrupt:
        logger.info("⏹️  Bot stopped by user")
    except Exception as e:
        logger.error(f"Error starting bot: {e}", exc_info=True)
    finally:
        release_lock()
        logger.info("Bot shutdown completed")
