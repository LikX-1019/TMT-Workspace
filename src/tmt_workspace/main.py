"""FastAPI application entry point."""

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from tmt_workspace.api.v1 import api_router
from tmt_workspace.core.config import get_settings
from tmt_workspace.core.errors import AppError, ValidationError
from tmt_workspace.core.responses import ErrorDetail, ErrorEnvelope
from tmt_workspace.db.session import dispose_engine


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await dispose_engine()


def create_app() -> FastAPI:
    """Create a configured FastAPI application."""

    settings = get_settings()
    app = FastAPI(
        title=settings.project_name,
        version="0.1.0",
        lifespan=lifespan,
        docs_url="/api/docs",
        redoc_url="/api/redoc",
        openapi_url="/api/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type"],
    )
    app.include_router(api_router, prefix=settings.api_v1_prefix)
    _register_exception_handlers(app)
    return app


def _register_exception_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def handle_app_error(request: Request, exc: AppError) -> JSONResponse:
        del request
        return JSONResponse(
            status_code=exc.status_code,
            content=ErrorEnvelope(
                error=ErrorDetail(code=exc.code, message=exc.message, details=exc.details)
            ).model_dump(),
        )

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        del request
        error = ValidationError(details={"fields": exc.errors()})
        return JSONResponse(
            status_code=error.status_code,
            content=ErrorEnvelope(
                error=ErrorDetail(
                    code=error.code,
                    message=error.message,
                    details=error.details,
                )
            ).model_dump(),
        )


app = create_app()
