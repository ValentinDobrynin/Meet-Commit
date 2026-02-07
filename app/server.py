from fastapi import FastAPI, Request

from app.settings import Healthz, settings

# из app/bot/__init__.py подтянется router с хэндлерами

# Singleton импорт bot и dp - происходит ОДИН раз при загрузке модуля
# Это безопасно т.к. get_bot_and_dp() использует глобальное кэширование
from app.bot.main import bot, dp


def create_app() -> FastAPI:
    app = FastAPI(title="MeetingCommit", version="0.2.0")

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

    # новый маршрут для Telegram webhook
    @app.post("/telegram/webhook")
    async def telegram_webhook(request: Request):
        # bot и dp уже импортированы на уровне модуля (singleton)
        try:
            data = await request.json()
            await dp.feed_raw_update(bot, data)
            return {"ok": True}
        except Exception as e:
            # Логируем ошибку для диагностики
            import logging
            import traceback
            logger = logging.getLogger("webhook")
            logger.error(f"Webhook error: {e}")
            logger.error(f"Traceback: {traceback.format_exc()}")
            # Возвращаем ok=True чтобы Telegram не удалил webhook
            # Ошибка залогирована для последующего исправления
            return {"ok": True, "error": str(e)}

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
