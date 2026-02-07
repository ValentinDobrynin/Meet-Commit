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
from .handlers_assign import router as assign_router
from .handlers_direct_commit import router as direct_commit_router
from .handlers_inline import router as inline_router
from .handlers_llm_commit import router as llm_commit_router
from .handlers_people import router as people_router
from .handlers_people_admin import people_admin_router
from .handlers_people_v2 import router as people_v2_router
from .handlers_queries import router as queries_router
from .handlers_review_cleanup import router as review_cleanup_router
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


def create_storage():
    """Создает storage в зависимости от режима развертывания."""
    deployment_mode = os.getenv("DEPLOYMENT_MODE", "local")
    
    if deployment_mode == "render":
        # Облачный режим - используем Redis
        try:
            from aiogram.fsm.storage.redis import RedisStorage
            from redis.asyncio import Redis
            
            redis_url = os.getenv("REDIS_URL")
            
            if not redis_url:
                logger.warning("REDIS_URL не настроен, используем MemoryStorage")
                return MemoryStorage()
            
            logger.info(f"🔄 Using Redis storage for cloud mode")
            # Создаем Redis connection
            redis = Redis.from_url(redis_url, decode_responses=True)
            return RedisStorage(redis=redis)
            
        except ImportError:
            logger.warning("Redis не установлен, используем MemoryStorage")
            return MemoryStorage()
        except Exception as e:
            logger.error(f"Ошибка подключения к Redis: {e}, используем MemoryStorage")
            return MemoryStorage()
    else:
        # Локальный режим - используем память
        logger.info("💾 Using Memory storage (local mode)")
        return MemoryStorage()


bot, dp = build_bot(TELEGRAM_TOKEN, create_storage())

# Флаг для предотвращения повторной регистрации роутеров
_routers_registered = False


def register_routers():
    """Регистрирует роутеры только один раз."""
    global _routers_registered
    if _routers_registered:
        return
    
    # FSM роутеры должны быть зарегистрированы ПЕРВЫМИ для перехвата состояний
    dp.include_router(agenda_router)  # ПЕРВЫЙ: Система повесток с FSM состояниями
    dp.include_router(tags_review_router)  # FSM состояния для тегирования
    dp.include_router(assign_router)  # Интерактивное назначение исполнителей с FSM
    dp.include_router(direct_commit_router)  # Прямые коммиты с FSM
    dp.include_router(people_router)  # People Miner v1 с FSM
    dp.include_router(people_admin_router)  # Админ управление people.json с FSM
    dp.include_router(people_v2_router)  # People Miner v2 с улучшенным UX
    # Команды без FSM
    dp.include_router(llm_commit_router)  # LLM коммиты (без FSM)
    dp.include_router(queries_router)  # Команды запросов к коммитам
    dp.include_router(review_cleanup_router)  # Очистка Review Queue
    dp.include_router(inline_router)
    dp.include_router(admin_router)
    dp.include_router(admin_monitoring_router)  # Расширенные админские команды
    dp.include_router(router)  # Основной роутер ПОСЛЕДНИМ
    
    _routers_registered = True
    logger.debug("Routers registered successfully")


# Регистрируем роутеры при импорте модуля
register_routers()


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
    """Запуск Telegram бота с поддержкой облачного режима."""
    try:
        deployment_mode = os.getenv("DEPLOYMENT_MODE", "local")
        
        if deployment_mode == "render":
            logger.info("🌐 Starting in Render cloud mode...")
            await run_cloud_mode()
        else:
            logger.info("💻 Starting in local polling mode...")
            await run_local_mode()
            
    except Exception as e:
        logger.error(f"Bot error: {e}", exc_info=True)
        raise


async def run_cloud_mode():
    """Запуск в облачном режиме с webhook."""
    
    # 1. Настраиваем webhook
    webhook_url = os.getenv("WEBHOOK_URL")
    if webhook_url:
        try:
            # Удаляем старый webhook если есть
            await bot.delete_webhook(drop_pending_updates=True)
            
            # Устанавливаем новый webhook
            await bot.set_webhook(
                url=webhook_url,
                allowed_updates=["message", "callback_query"],
                drop_pending_updates=True
            )
            logger.info(f"✅ Webhook configured: {webhook_url}")
        except Exception as e:
            logger.error(f"❌ Failed to set webhook: {e}")
            raise
    else:
        logger.warning("⚠️ WEBHOOK_URL не настроен, webhook не установлен")
    
    # 2. Отправляем приветствия
    from app.bot.startup_greeting import send_startup_greetings_safe
    logger.info("Sending startup greetings to active users...")
    await send_startup_greetings_safe(bot)
    
    # 3. Запускаем FastAPI сервер (без circular import)
    logger.info("🚀 Bot ready to receive webhooks via FastAPI")
    
    import uvicorn
    
    port = int(os.getenv("PORT", 8000))
    host = os.getenv("APP_HOST", "0.0.0.0")
    
    logger.info(f"🌐 Starting FastAPI server on {host}:{port}")
    
    # Используем строковый import чтобы избежать circular dependency
    config = uvicorn.Config(
        "app.server:app",
        host=host,
        port=port,
        log_level="info"
    )
    server = uvicorn.Server(config)
    await server.serve()


async def run_local_mode():
    """Запуск в локальном режиме с polling (существующая логика)."""
    logger.info("🤖 Starting bot in polling mode...")

    # Отправляем приветствия активным пользователям при запуске
    from app.bot.startup_greeting import send_startup_greetings_safe

    logger.info("Sending startup greetings to active users...")
    await send_startup_greetings_safe(bot)

    logger.info("Bot polling started. Waiting for messages...")
    await dp.start_polling(bot, allowed_updates=["message", "callback_query"])


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
