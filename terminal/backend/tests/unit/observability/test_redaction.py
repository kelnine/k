from pydantic import SecretStr

from kterminal.observability.redaction import REDACTED, redact, redact_text


def test_sensitive_keys_are_masked_at_any_depth() -> None:
    data = {
        "secret": "tv-webhook-secret",
        "nested": {"api_key": "k", "Authorization": "Bearer abc", "ok": "visible"},
        "items": [{"password": "p"}, {"bot_token": "t"}],
        "idempotency_key": "not-a-secret",
    }
    result = redact(data)
    assert result["secret"] == REDACTED
    assert result["nested"]["api_key"] == REDACTED
    assert result["nested"]["Authorization"] == REDACTED
    assert result["nested"]["ok"] == "visible"
    assert result["items"] == [{"password": REDACTED}, {"bot_token": REDACTED}]
    assert result["idempotency_key"] == "not-a-secret"
    assert data["secret"] == "tv-webhook-secret"  # input is not mutated


def test_empty_sensitive_values_are_left_alone() -> None:
    assert redact({"password": None, "token": ""}) == {"password": None, "token": ""}


def test_secret_types_are_masked() -> None:
    assert redact({"value": SecretStr("x")}) == {"value": REDACTED}


def test_credentials_in_urls() -> None:
    text = "connect failed: postgresql+asyncpg://kterminal:hunter2@db:5432/kterminal"
    assert (
        redact_text(text)
        == f"connect failed: postgresql+asyncpg://kterminal:{REDACTED}@db:5432/kterminal"
    )


def test_telegram_bot_token() -> None:
    token = "123456789:AAHdqTcvCH1vGWJxfSeofSAs0K5PALDsaw1"
    assert token not in redact_text(f"POST https://api.telegram.org/bot{token}/sendMessage")


def test_bearer_tokens() -> None:
    assert (
        redact_text("Authorization: Bearer eyJhbGciOi.abc.def")
        == f"Authorization: Bearer {REDACTED}"
    )


def test_secret_fields_inside_free_text() -> None:
    body = '{"secret":"tv-webhook-secret","strategy":"breakout_retest"}'
    result = redact_text(body)
    assert "tv-webhook-secret" not in result
    assert '"strategy":"breakout_retest"' in result
    assert "password=abc&user=x" not in redact_text("password=abc&user=x")


def test_tuples_and_sets_are_handled() -> None:
    assert redact(("a", {"token": "t"})) == ("a", {"token": REDACTED})
    assert redact({"x"}) == ["x"]


def test_depth_limit() -> None:
    deep: dict[str, object] = {}
    node = deep
    for _ in range(50):
        child: dict[str, object] = {}
        node["n"] = child
        node = child
    assert "[TRUNCATED]" in str(redact(deep))
