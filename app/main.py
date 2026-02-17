import logging
import os

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.schemas.response import APIResponse
from app.api.router import router as api_router

load_dotenv()


def configure_logging() -> None:
    level_name = os.getenv("ANIMA_LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)
    app_logger = logging.getLogger("app")
    app_logger.setLevel(level)

    # Uvicorn may not attach handlers for custom loggers; attach one explicitly.
    if not app_logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
        )
        handler.setLevel(level)
        app_logger.addHandler(handler)

    app_logger.propagate = False


def create_app() -> FastAPI:
    configure_logging()
    app = FastAPI(title="Anima Server")
    app.include_router(api_router)

    @app.exception_handler(StarletteHTTPException)
    async def handle_http_exception(
        _: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        payload = APIResponse.error(
            message=str(exc.detail),
            code=exc.status_code,
        )
        return JSONResponse(status_code=exc.status_code, content=payload.model_dump())

    @app.exception_handler(RequestValidationError)
    async def handle_validation_exception(
        _: Request, exc: RequestValidationError
    ) -> JSONResponse:
        error_messages = []
        for err in exc.errors():
            loc = ".".join(str(item) for item in err.get("loc", []))
            msg = err.get("msg", "validation error")
            error_messages.append(f"{loc}: {msg}")
        payload = APIResponse.error(
            message="; ".join(error_messages) if error_messages else "validation error",
            code=422,
        )
        return JSONResponse(status_code=422, content=payload.model_dump())

    @app.exception_handler(Exception)
    async def handle_unexpected_exception(_: Request, exc: Exception) -> JSONResponse:
        payload = APIResponse.error(
            message=str(exc) or "internal server error",
            code=500,
        )
        return JSONResponse(status_code=500, content=payload.model_dump())

    return app


app = create_app()
