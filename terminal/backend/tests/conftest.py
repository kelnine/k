import io
import os

import pytest
from hypothesis import settings as hypothesis_settings

from kterminal.config.settings import LogFormat, LoggingSettings, Settings
from kterminal.observability.logging import configure_logging

# Property tests check correctness, not machine speed: no per-example deadline (cold CI
# runners and first-import costs would otherwise make them flaky).
hypothesis_settings.register_profile("kterminal", deadline=None)
hypothesis_settings.load_profile("kterminal")

# Read before the environment is isolated below.
TEST_DATABASE_URL = os.environ.get("KT_TEST_DATABASE_URL")


@pytest.fixture(autouse=True)
def _isolated_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path_factory: pytest.TempPathFactory
) -> None:
    """Tests never see the developer's KT_* variables or .env file."""
    for name in list(os.environ):
        if name.upper().startswith("KT_"):
            monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path_factory.mktemp("cwd"))


@pytest.fixture(autouse=True)
def _test_logging() -> None:
    """Route structlog through stdlib logging (so ``caplog`` sees it) at DEBUG for every test."""
    configure_logging(
        LoggingSettings(level="DEBUG", format=LogFormat.CONSOLE),
        service="kterminal-tests",
        environment="test",
        stream=io.StringIO(),
    )


@pytest.fixture
def settings() -> Settings:
    return Settings(_env_file=None, environment="test")


@pytest.fixture
def database_url() -> str:
    if not TEST_DATABASE_URL:
        pytest.skip("KT_TEST_DATABASE_URL not set — integration test skipped")
    return TEST_DATABASE_URL
