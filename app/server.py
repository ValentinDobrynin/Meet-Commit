from fastapi import FastAPI, Request

from app.settings import Healthz, settings

# из app/bot/__init__.py подтянется router с хэндлерами


def create_app() -> FastAPI:
    app = FastAPI(title="MeetingCommit", version="0.2.0")

    @app.get("/healthz", response_model=Healthz)
    def healthz():
        return Healthz(status="ok", env=settings.env)

    # новый маршрут для Telegram webhook
    @app.post("/telegram/webhook")
    async def telegram_webhook(request: Request):
        # Отложенный импорт чтобы избежать circular dependency
        from app.bot.main import bot, dp
        
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
