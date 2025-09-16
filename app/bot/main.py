import asyncio
import fcntl
import os
import sys
import tempfile
from pathlib import Path

from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv

from .handlers import router
from .init import build_bot

# Загружаем переменные окружения из .env файла ПЕРЕД импортами
load_dotenv()

# Проверяем наличие обязательных переменных окружения
try:
    TELEGRAM_TOKEN = os.environ["TELEGRAM_TOKEN"]
except KeyError:
    raise ValueError("TELEGRAM_TOKEN not found in environment variables") from None

bot, dp = build_bot(TELEGRAM_TOKEN, MemoryStorage())
dp.include_router(router)


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

        print(f"Lock acquired. PID: {os.getpid()}")
        return True

    except OSError as e:
        if e.errno == 11:  # EAGAIN - файл заблокирован
            print("❌ Bot is already running! Another instance is active.")
            print("   To stop the existing bot, run: pkill -f 'python app/bot/main.py'")
            return False
        else:
            print(f"❌ Failed to acquire lock: {e}")
            return False


def release_lock():
    """Освобождает lock-файл"""
    lock_file = Path(tempfile.gettempdir()) / "meet_commit_bot.lock"
    try:
        if lock_file.exists():
            lock_file.unlink()
            print("Lock released.")
    except Exception as e:
        print(f"Warning: Could not release lock: {e}")


async def run() -> None:
    """Запуск Telegram бота"""
    try:
        print("🤖 Starting bot in polling mode...")
        await dp.start_polling(bot, allowed_updates=["message", "callback_query"])
    except Exception as e:
        print(f"❌ Bot error: {e}")
        raise


if __name__ == "__main__":
    # Проверяем, не запущен ли уже бот
    if not acquire_lock():
        sys.exit(1)

    try:
        print("🚀 Meet-Commit Bot starting...")
        asyncio.run(run())
    except KeyboardInterrupt:
        print("\n⏹️  Bot stopped by user")
    except Exception as e:
        print(f"❌ Error starting bot: {e}")
    finally:
        release_lock()
