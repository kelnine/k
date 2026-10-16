"""One populated database for every dashboard API test (see :mod:`.demo`).

Created next to the test database (``KT_TEST_DATABASE_URL``) once per test run,
populated with the real lab code, and dropped at the end. API tests read it
through ``TestClient``; the few that write (sign-ins, kill switches) undo or
tolerate each other's changes.
"""

import asyncio
from collections.abc import AsyncIterator, Callable, Iterator
from contextlib import asynccontextmanager

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import pool, text
from sqlalchemy.engine import make_url
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from kterminal.api.app import create_app
from kterminal.api.auth.settings import AuthSettings
from kterminal.config.settings import DatabaseSettings, Settings
from kterminal.core.clock import SimulatedClock
from kterminal.core.ids import uuid7
from kterminal.db import migrate
from kterminal.db.session import Database
from tests.conftest import TEST_DATABASE_URL
from tests.integration.api.demo import PASSWORD, DemoData, cheap_passwords, populate

SECRET = "test-session-secret-0123456789-abcdefghij"


async def _admin(url: str, statement: str) -> None:
    engine = create_async_engine(
        DatabaseSettings.model_validate({"url": url}).dsn(),
        poolclass=pool.NullPool,
        isolation_level="AUTOCOMMIT",
    )
    try:
        async with engine.connect() as conn:
            await conn.execute(text(statement))
    finally:
        await engine.dispose()


@pytest.fixture(scope="session")
def demo() -> Iterator[DemoData]:
    if not TEST_DATABASE_URL:
        pytest.skip("KT_TEST_DATABASE_URL not set — integration test skipped")
    name = f"kt_dash_{uuid7().hex[-12:]}"
    url = make_url(TEST_DATABASE_URL).set(database=name).render_as_string(hide_password=False)
    asyncio.run(_admin(TEST_DATABASE_URL, f'CREATE DATABASE "{name}"'))
    try:
        asyncio.run(migrate.upgrade(url))
        yield asyncio.run(populate(url))
    finally:
        asyncio.run(_admin(TEST_DATABASE_URL, f'DROP DATABASE IF EXISTS "{name}" WITH (FORCE)'))


@pytest.fixture
def make_client(demo: DemoData) -> Iterator[Callable[..., TestClient]]:
    """``make_client(**auth_overrides)``: a TestClient on the demo database."""
    clients: list[TestClient] = []

    def factory(clock: SimulatedClock | None = None, **auth: object) -> TestClient:
        settings = Settings(_env_file=None, environment="test")
        database = Database(
            DatabaseSettings.model_validate({"url": demo.url}), application_name="kt-api-tests"
        )
        app = create_app(
            settings,
            database,
            clock=clock or SimulatedClock(demo.now),
            auth_settings=AuthSettings(
                _env_file=None,  # type: ignore[call-arg]
                **{"session_secret": SECRET, "cookie_secure": False, **auth},
            ),
            passwords=cheap_passwords(),
        )
        client = TestClient(app, raise_server_exceptions=False)
        client.__enter__()
        clients.append(client)
        return client

    yield factory
    for client in clients:
        client.__exit__(None, None, None)


@pytest.fixture
def client(make_client: Callable[..., TestClient]) -> TestClient:
    return make_client()


def sign_in(client: TestClient, username: str, password: str = PASSWORD) -> str:
    """Sign in and return the CSRF token (the session cookie stays in the client)."""
    response = client.post("/api/v1/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text
    token: str = response.json()["csrf_token"]
    return token


@pytest.fixture
def viewer(client: TestClient) -> TestClient:
    sign_in(client, "vera")
    return client


@asynccontextmanager
async def demo_session(demo: DemoData) -> AsyncIterator[AsyncSession]:
    """A committing session on the demo database (for ``asyncio.run`` in sync tests)."""
    database = Database(DatabaseSettings.model_validate({"url": demo.url}))
    try:
        async with database.session() as session:
            yield session
    finally:
        await database.dispose()
