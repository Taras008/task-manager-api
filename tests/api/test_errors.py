import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

from app.domain.exceptions import (
    BusinessRuleViolationError,
    DomainError,
    DomainValidationError,
    InvalidStatusTransitionError,
    NotFoundError,
    PermissionDeniedError,
)
from app.main import create_app


@pytest.mark.parametrize(
    ("exc", "status", "code"),
    [
        (NotFoundError("x"), 404, "not_found"),
        (PermissionDeniedError("x"), 403, "permission_denied"),
        (InvalidStatusTransitionError("x"), 409, "invalid_status_transition"),
        (BusinessRuleViolationError("x"), 409, "business_rule_violation"),
        (DomainValidationError("x"), 422, "validation_error"),
    ],
)
async def test_domain_errors_are_mapped_to_http(exc: DomainError, status: int, code: str) -> None:
    app: FastAPI = create_app()

    @app.get("/boom")
    async def boom() -> None:
        raise exc

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/boom")

    assert response.status_code == status
    assert response.json() == {"error": {"code": code, "message": "x", "details": {}}}


async def test_request_validation_error_uses_unified_format() -> None:
    app: FastAPI = create_app()

    @app.get("/items/{item_id}")
    async def item(item_id: int) -> dict[str, int]:
        return {"id": item_id}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as ac:
        response = await ac.get("/items/abc")

    assert response.status_code == 422
    assert response.json()["error"]["code"] == "validation_error"
    assert response.json()["error"]["details"]["errors"]
