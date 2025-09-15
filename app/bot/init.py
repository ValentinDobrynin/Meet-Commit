from app.bot.handlers import router as handlers_router
from app.bot.main import dp

dp.include_router(handlers_router)
