from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode
from aiogram.fsm.storage.memory import MemoryStorage

from app.bot.handlers import router as handlers_router


def build_bot(token: str | None = None) -> tuple[Bot, Dispatcher]:
    """Создает и настраивает бота и диспетчер"""
    import os
    
    tkn = token or os.environ.get("TELEGRAM_TOKEN")
    if not tkn:
        raise RuntimeError("TELEGRAM_TOKEN отсутствует")
    
    bot = Bot(
        token=tkn,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML)
    )
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(handlers_router)
    return bot, dp
