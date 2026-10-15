"""``kterminal users add | list | disable | enable | set-password`` against PostgreSQL."""

import asyncio

import pytest
from typer.testing import CliRunner

from kterminal.api.auth.passwords import Passwords
from kterminal.api.auth.users import Role, get_user_by_username
from kterminal.cli import app
from tests.integration.api.conftest import demo_session
from tests.integration.api.demo import DemoData

pytestmark = pytest.mark.integration

GOOD = "a long and unusual passphrase"


@pytest.fixture
def cli(demo: DemoData, monkeypatch: pytest.MonkeyPatch) -> CliRunner:
    monkeypatch.setenv("KT_DATABASE__URL", demo.url)
    monkeypatch.setenv("KT_LOGGING__FORMAT", "console")
    return CliRunner()


def test_add_list_disable_enable_and_set_password(cli: CliRunner, demo: DemoData) -> None:
    added = cli.invoke(
        app, ["users", "add", "Grace", "--role", "operator"], input=f"{GOOD}\n{GOOD}\n"
    )
    assert added.exit_code == 0, added.output
    assert "user grace created (OPERATOR)" in added.output
    assert GOOD not in added.output  # never echoed

    async def stored() -> object:
        async with demo_session(demo) as session:
            return await get_user_by_username(session, "grace")

    user = asyncio.run(stored())
    assert user is not None
    assert user.role is Role.OPERATOR  # type: ignore[attr-defined]
    assert user.password_hash.startswith("$argon2id$")  # type: ignore[attr-defined]
    assert Passwords().verify(user.password_hash, GOOD)  # type: ignore[attr-defined]

    listing = cli.invoke(app, ["users", "list"])
    assert listing.exit_code == 0
    assert "grace" in listing.output and "OPERATOR" in listing.output
    assert "dora" in listing.output and "disabled" in listing.output

    assert cli.invoke(app, ["users", "disable", "grace"]).exit_code == 0
    assert asyncio.run(stored()).disabled  # type: ignore[attr-defined]
    assert cli.invoke(app, ["users", "enable", "grace"]).exit_code == 0
    assert not asyncio.run(stored()).disabled  # type: ignore[attr-defined]

    new = "another fine passphrase"
    changed = cli.invoke(app, ["users", "set-password", "grace"], input=f"{new}\n{new}\n")
    assert changed.exit_code == 0, changed.output
    assert Passwords().verify(asyncio.run(stored()).password_hash, new)  # type: ignore[attr-defined]


def test_duplicates_weak_passwords_and_bad_input_are_refused(cli: CliRunner) -> None:
    duplicate = cli.invoke(app, ["users", "add", "vera"], input=f"{GOOD}\n{GOOD}\n")
    assert duplicate.exit_code == 1
    assert "already exists" in duplicate.output
    weak = cli.invoke(app, ["users", "add", "weakling"], input="short\nshort\n")
    assert weak.exit_code == 1
    assert "at least 12 characters" in weak.output
    mismatch = cli.invoke(app, ["users", "add", "typo"], input=f"{GOOD}\n{GOOD}x\n{GOOD}\n{GOOD}\n")
    assert mismatch.exit_code == 0  # asked again until both entries match
    assert "do not match" in mismatch.output
    bad_role = cli.invoke(app, ["users", "add", "someone", "--role", "ROOT"])
    assert bad_role.exit_code == 2
    bad_name = cli.invoke(app, ["users", "add", "1-bad name"], input=f"{GOOD}\n{GOOD}\n")
    assert bad_name.exit_code == 1
    assert "usernames are 3-32 characters" in bad_name.output
    unknown = cli.invoke(app, ["users", "disable", "nobody"])
    assert unknown.exit_code == 1
    assert "no user 'nobody'" in unknown.output
