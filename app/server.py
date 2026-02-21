import logging
import os
from contextlib import asynccontextmanager

from aiogram.types import Update
from fastapi import FastAPI, Request, Response

# Импортируем bot, dp и функцию регистрации роутеров
# Импорт происходит ОДИН раз при загрузке модуля
from app.bot.main import bot, dp, register_all_routers
from app.settings import Healthz, settings

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    FastAPI lifespan context manager.
    Выполняется ОДИН раз при старте приложения.
    """
    # Startup
    deployment_mode = os.getenv("DEPLOYMENT_MODE", "local")
    logger.info(f"🌐 Starting Meet-Commit in {deployment_mode} mode...")

    # Инициализируем persistent storage (если настроен)
    try:
        from app.core.persistent_storage import init_persistent_storage
        init_persistent_storage()
    except Exception as e:
        logger.warning(f"Persistent storage init failed: {e}")

    # Регистрируем роутеры (выполняется ОДИН раз!)
    register_all_routers()

    # В облачном режиме настраиваем webhook
    if deployment_mode == "render":
        webhook_url = os.getenv("WEBHOOK_URL")
        if webhook_url:
            try:
                await bot.set_webhook(
                    url=webhook_url,
                    allowed_updates=["message", "callback_query"],
                    drop_pending_updates=True,
                )
                logger.info(f"✅ Webhook configured: {webhook_url}")
            except Exception as e:
                logger.error(f"❌ Failed to set webhook: {e}")

    # Отправляем startup greetings
    try:
        from app.bot.startup_greeting import send_startup_greetings_safe

        await send_startup_greetings_safe(bot)
        logger.info("✅ Startup greetings sent")
    except Exception as e:
        logger.warning(f"Failed to send startup greetings: {e}")

    logger.info("🚀 Meet-Commit started successfully!")

    yield

    # Shutdown
    logger.info("Shutting down Meet-Commit...")
    # Не удаляем webhook чтобы избежать проблем при рестартах
    logger.info("✅ Shutdown complete")


def create_app() -> FastAPI:
    app = FastAPI(
        title="MeetingCommit",
        version="0.2.0",
        lifespan=lifespan,  # ← Добавляем lifespan!
    )

    @app.get("/healthz", response_model=Healthz)
    def healthz():
        return Healthz(status="ok", env=settings.env)

    # Временный debug endpoint для диагностики
    @app.get("/debug/bot_status")
    async def debug_bot_status():
        """Показывает статус bot и dp для диагностики."""
        try:
            import os

            bot_info = {
                "bot_id": bot.id if bot else None,
                "bot_token_set": bool(os.getenv("TELEGRAM_TOKEN")),
                "dp_exists": dp is not None,
                "deployment_mode": os.getenv("DEPLOYMENT_MODE", "local"),
                "redis_url_set": bool(os.getenv("REDIS_URL")),
                "webhook_url": os.getenv("WEBHOOK_URL"),
            }
            return {"status": "ok", "bot_info": bot_info}
        except Exception as e:
            import traceback

            return {"status": "error", "error": str(e), "traceback": traceback.format_exc()}

    # Telegram webhook endpoint (как в FoodBot и Wedding-bot)
    @app.post("/telegram/webhook")
    async def telegram_webhook(request: Request):
        """
        Handle incoming Telegram updates.
        bot и dp уже созданы на уровне модуля и роутеры зарегистрированы в lifespan.
        """
        try:
            # Parse update data
            update_data = await request.json()

            # Create Update object (как в Wedding-bot)
            update = Update(**update_data)

            # Feed to dispatcher (используем feed_update, не feed_raw_update!)
            await dp.feed_update(bot, update)

            return Response(status_code=200)

        except Exception as e:
            logger.error(f"Error handling webhook: {e}", exc_info=True)
            # Возвращаем 200 чтобы Telegram не удалил webhook
            # Ошибка залогирована для последующего исправления
            return Response(status_code=200)

    return app


app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(
        "app.server:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=True,
    )
