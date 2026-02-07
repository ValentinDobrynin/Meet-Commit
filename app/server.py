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

    # новый маршрут для Telegram webhook
    @app.post("/telegram/webhook")
    async def telegram_webhook(request: Request):
        # bot и dp уже импортированы на уровне модуля (singleton)
        data = await request.json()
        await dp.feed_raw_update(bot, data)
        return {"ok": True}

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
