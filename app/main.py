from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.schemas.response import APIResponse
from app.api.router import router as api_router


def create_app() -> FastAPI:
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
