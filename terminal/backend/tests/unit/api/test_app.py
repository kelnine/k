from collections.abc import Iterator
from datetime import UTC, datetime

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from kterminal.api.app import create_app
from kterminal.config.settings import Settings
from kterminal.core.clock import SimulatedClock

T0 = datetime(2026, 10, 5, 14, 30, tzinfo=UTC)


class FakeDatabase:
    def __init__(self, healthy: bool = True) -> None:
        self.healthy = healthy
        self.disposed = False

    async def ping(self, timeout_s: float = 2.0) -> bool:
        return self.healthy

    async def dispose(self) -> None:
        self.disposed = True


@pytest.fixture
def database() -> FakeDatabase:
    return FakeDatabase()


@pytest.fixture
def client(settings: Settings, database: FakeDatabase) -> Iterator[TestClient]:
    app = create_app(settings, database, clock=SimulatedClock(T0))

    failing = APIRouter()

    @failing.get("/boom")
    async def boom() -> None:
        raise RuntimeError("secret internals: postgresql://u:hunter2@db/x")

    app.include_router(failing)
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


def test_liveness(client: TestClient) -> None:
    response = client.get("/health/live")
    assert response.status_code == 200
    assert response.json() == {"status": "ok"}


def test_readiness_ok(client: TestClient) -> None:
    response = client.get("/health/ready")
    assert response.status_code == 200
    assert response.json() == {"status": "ready", "checks": {"database": "ok"}}


def test_readiness_reports_database_outage_with_503(
    client: TestClient, database: FakeDatabase
) -> None:
    database.healthy = False
    response = client.get("/health/ready")
    assert response.status_code == 503
    assert response.json() == {"status": "not_ready", "checks": {"database": "unavailable"}}


def test_system_info_reports_safe_defaults(client: TestClient) -> None:
    body = client.get("/api/v1/system/info").json()
    assert body["default_mode"] == "PAPER"
    assert body["live_trading_permitted"] is False
    assert body["environment"] == "test"
    assert body["server_time"] == "2026-10-05T14:30:00Z"


def test_request_id_is_generated_and_echoed(client: TestClient) -> None:
    response = client.get("/health/live")
    generated = response.headers["X-Request-ID"]
    assert len(generated) == 36  # a UUID

    supplied = client.get("/health/live", headers={"X-Request-ID": "tv-alert-0001"})
    assert supplied.headers["X-Request-ID"] == "tv-alert-0001"


@pytest.mark.parametrize(
    "bad", ["short", "has spaces in it", "x" * 65, "<script>alert(1)</script>"]
)
def test_unsafe_request_ids_are_replaced(client: TestClient, bad: str) -> None:
    response = client.get("/health/live", headers={"X-Request-ID": bad})
    assert response.headers["X-Request-ID"] != bad


def test_unhandled_errors_return_generic_500_with_correlation_id(client: TestClient) -> None:
    response = client.get("/boom", headers={"X-Request-ID": "req-boom-0001"})
    assert response.status_code == 500
    assert response.json() == {
        "status": "error",
        "code": "INTERNAL_ERROR",
        "correlation_id": "req-boom-0001",
    }
    assert "hunter2" not in response.text


def test_database_is_disposed_on_shutdown(settings: Settings) -> None:
    database = FakeDatabase()
    with TestClient(create_app(settings, database)):
        assert not database.disposed
    assert database.disposed


def test_openapi_docs_follow_settings(settings: Settings) -> None:
    with TestClient(create_app(settings, FakeDatabase())) as dev:
        assert dev.get("/api/v1/openapi.json").status_code == 200
    production = Settings(
        _env_file=None, environment="production", database={"password": "a-real-password"}
    )
    with TestClient(create_app(production, FakeDatabase())) as prod:
        assert prod.get("/api/v1/openapi.json").status_code == 404
        assert prod.get("/api/v1/docs").status_code == 404
