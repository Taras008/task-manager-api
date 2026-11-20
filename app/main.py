import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from http import HTTPStatus
from typing import Any

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.api.v1.router import api_router
from app.api.v1.routers import health
from app.core.logging import configure_logging
from app.db.session import create_engine, create_session_factory
from app.domain.exceptions import (
    AuthenticationError,
    BusinessRuleViolationError,
    DomainError,
    DomainValidationError,
    InvalidStatusTransitionError,
    NotFoundError,
    PermissionDeniedError,
)
from app.services.notifier import LoggingNotifier, Notifier

logger = logging.getLogger(__name__)

STATUS_BY_ERROR: dict[type[DomainError], int] = {
    AuthenticationError: 401,
    NotFoundError: 404,
    PermissionDeniedError: 403,
    InvalidStatusTransitionError: 409,
    BusinessRuleViolationError: 409,
    DomainValidationError: 422,
}


def error_response(
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "details": details or {}}},
        headers=headers,
    )


async def domain_error_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, DomainError)
    status_code = next(
        (code for cls, code in STATUS_BY_ERROR.items() if isinstance(exc, cls)),
        400,
    )
    headers = {"WWW-Authenticate": "Bearer"} if status_code == 401 else None
    return error_response(status_code, exc.code, exc.message, exc.details, headers)


async def validation_error_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    errors = [{"loc": list(e["loc"]), "msg": e["msg"], "type": e["type"]} for e in exc.errors()]
    return error_response(422, "validation_error", "Request validation failed", {"errors": errors})


async def http_exception_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    code = {401: "unauthorized", 403: "forbidden", 404: "not_found", 405: "method_not_allowed"}.get(
        exc.status_code, HTTPStatus(exc.status_code).phrase.lower().replace(" ", "_")
    )
    return error_response(
        exc.status_code, code, str(exc.detail), headers=getattr(exc, "headers", None)
    )


async def unhandled_error_handler(_: Request, exc: Exception) -> JSONResponse:
    logger.exception("Unhandled error", exc_info=exc)
    return error_response(500, "internal_error", "Internal server error")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Uvicorn не налаштовує root-логер: без цього INFO застосунку (нотифікації) не видно.
    configure_logging()
    if not hasattr(app.state, "session_factory"):
        engine = create_engine()
        app.state.session_factory = create_session_factory(engine)
        app.state.engine = engine
    yield
    engine_ = getattr(app.state, "engine", None)
    if engine_ is not None:
        await engine_.dispose()


def create_app(
    session_factory: async_sessionmaker[AsyncSession] | None = None,
    notifier: Notifier | None = None,
) -> FastAPI:
    app = FastAPI(title="Task Management API", version="0.1.0", lifespan=lifespan)
    if session_factory is not None:
        app.state.session_factory = session_factory
    app.state.notifier = notifier or LoggingNotifier()

    app.add_exception_handler(DomainError, domain_error_handler)
    app.add_exception_handler(RequestValidationError, validation_error_handler)
    app.add_exception_handler(StarletteHTTPException, http_exception_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)

    app.include_router(health.router)
    app.include_router(api_router)
    return app


app = create_app()
