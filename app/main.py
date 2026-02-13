from fastapi import FastAPI

from app.api.router import router as api_router


def create_app() -> FastAPI:
    app = FastAPI(title="Anima Server")
    app.include_router(api_router)
    return app


app = create_app()
