from fastapi import FastAPI

from app.settings import Healthz, settings


def create_app() -> FastAPI:
    app = FastAPI(title="MeetingCommit", version="0.1.0")

    @app.get("/healthz", response_model=Healthz)
    def healthz():
        return Healthz(status="ok", env=settings.env)

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
