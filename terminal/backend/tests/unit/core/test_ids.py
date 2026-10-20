from datetime import UTC, datetime, timedelta

import pytest

from kterminal.core.ids import new_correlation_id, uuid7, uuid7_time


def test_uuid7_version_and_variant() -> None:
    value = uuid7()
    assert value.version == 7
    assert value.variant == "specified in RFC 4122"


def test_uuid7_embeds_creation_time() -> None:
    before = datetime.now(UTC) - timedelta(milliseconds=1)
    created = uuid7_time(uuid7())
    after = datetime.now(UTC) + timedelta(milliseconds=1)
    assert before <= created <= after


def test_uuid7_sorts_by_creation_time() -> None:
    first = uuid7()
    later = uuid7()
    # Same-millisecond IDs are random relative to each other; across milliseconds they sort.
    assert uuid7_time(first) <= uuid7_time(later)
    assert len({uuid7() for _ in range(10_000)}) == 10_000


def test_uuid7_time_rejects_other_versions() -> None:
    import uuid

    with pytest.raises(ValueError, match="not a UUIDv7"):
        uuid7_time(uuid.uuid4())


def test_correlation_ids_are_uuid7() -> None:
    assert new_correlation_id().version == 7
