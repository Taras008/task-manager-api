import pytest
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from tests.factories import auth_headers, create_task, create_user

TASKS = "/api/v1/tasks"
HUGE = 2**63  # на одиницю більше за межу BIGINT
BAD_IDS = [0, -1, HUGE, 10**30]


@pytest.mark.parametrize("bad", BAD_IDS)
@pytest.mark.parametrize("suffix", ["", "/comments"])
async def test_path_id_out_of_range_is_422_not_500(
    client: AsyncClient,
    session_factory: async_sessionmaker[AsyncSession],
    bad: int,
    suffix: str,
) -> None:
    user = await create_user(session_factory)
    r = await client.get(f"{TASKS}/{bad}{suffix}", headers=auth_headers(user.id))
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"


@pytest.mark.parametrize("bad", BAD_IDS)
async def test_assignee_id_out_of_range_is_422(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession], bad: int
) -> None:
    user = await create_user(session_factory)
    task = await create_task(session_factory, user.id)
    headers = auth_headers(user.id)
    r = await client.patch(f"{TASKS}/{task.id}", headers=headers, json={"assignee_id": bad})
    assert r.status_code == 422
    r = await client.get(TASKS, headers=headers, params={"assignee_id": bad})
    assert r.status_code == 422


async def test_max_bigint_id_is_plain_404(
    client: AsyncClient, session_factory: async_sessionmaker[AsyncSession]
) -> None:
    user = await create_user(session_factory)
    r = await client.get(f"{TASKS}/{2**63 - 1}", headers=auth_headers(user.id))
    assert r.status_code == 404
