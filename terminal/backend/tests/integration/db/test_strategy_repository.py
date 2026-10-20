"""Definitions, instances and immutable versions (docs/12 §12.1)."""

from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from kterminal.core.enums import StrategyKind, StrategyStatus
from kterminal.db.audit import hash_document
from kterminal.db.models import StrategyInstanceRow, StrategyPromotionRow, StrategyVersionRow
from kterminal.db.repositories.strategies import (
    DefinitionRecord,
    InstanceRecord,
    StrategyRepositoryError,
    VersionRecord,
    get_or_create_version,
    list_instances,
    set_instance_status,
    upsert_definition,
    upsert_instance,
    version_id_for,
)

pytestmark = pytest.mark.integration


def _version(instance_id: str, params: dict[str, Any], **overrides: Any) -> VersionRecord:
    config = {"definition": "demo_sma_cross", "params": params, "timeframe": "5m"}
    values: dict[str, Any] = {
        "instance_id": instance_id,
        "definition_id": "demo_sma_cross",
        "definition_version": "1.0.0",
        "code_hash": "c0de",
        "params": params,
        "params_hash": hash_document(params),
        "config": config,
        "config_hash": hash_document(config),
        "framework_fingerprint": "0.1.0:abc",
        "kterminal_version": "0.1.0",
    }
    values.update(overrides)
    return VersionRecord(**values)


async def _setup(session: AsyncSession, *instance_ids: str) -> None:
    await upsert_definition(
        session,
        DefinitionRecord(
            id="demo_sma_cross",
            name="Demo SMA cross",
            kind=StrategyKind.INTERNAL,
            latest_version="1.0.0",
            module="kterminal.strategies.demo_sma_cross",
            meta={"timeframes": ["5m"], "warmup_bars": 50},
        ),
    )
    for instance_id in instance_ids:
        await upsert_instance(
            session,
            InstanceRecord(id=instance_id, definition_id="demo_sma_cross", name=instance_id),
        )


async def _current(session: AsyncSession, instance_id: str) -> Any:
    return (
        await session.execute(
            select(StrategyInstanceRow.current_version_id).where(
                StrategyInstanceRow.id == instance_id
            )
        )
    ).scalar_one()


async def _version_count(session: AsyncSession, instance_id: str) -> int:
    return int(
        (
            await session.execute(
                select(func.count()).where(StrategyVersionRow.instance_id == instance_id)
            )
        ).scalar_one()
    )


async def test_versions_are_reused_per_configuration(session: AsyncSession) -> None:
    await _setup(session, "demo_sma_fast")
    first = await get_or_create_version(session, _version("demo_sma_fast", {"fast": 9}))
    assert await get_or_create_version(session, _version("demo_sma_fast", {"fast": 9})) == first
    assert await _version_count(session, "demo_sma_fast") == 1
    assert await _current(session, "demo_sma_fast") == first

    # Any change of configuration is a new, immutable version that becomes current …
    second = await get_or_create_version(session, _version("demo_sma_fast", {"fast": 10}))
    assert second != first
    assert await _current(session, "demo_sma_fast") == second
    # … and going back re-uses the old one instead of forking history.
    assert await get_or_create_version(session, _version("demo_sma_fast", {"fast": 9})) == first
    assert await _current(session, "demo_sma_fast") == first
    assert await _version_count(session, "demo_sma_fast") == 2

    stored = await session.get(StrategyVersionRow, first)
    assert stored is not None
    assert stored.params == {"fast": 9}
    assert stored.config_hash == _version("demo_sma_fast", {"fast": 9}).config_hash
    config_hash = stored.config_hash
    assert await version_id_for(session, "demo_sma_fast", config_hash) == first
    assert await version_id_for(session, "demo_sma_slow", config_hash) is None


async def test_instances_of_one_definition_are_independent(session: AsyncSession) -> None:
    await _setup(session, "demo_sma_fast", "demo_sma_slow")
    same = {"fast": 9, "slow": 21}
    fast = await get_or_create_version(session, _version("demo_sma_fast", same))
    slow = await get_or_create_version(session, _version("demo_sma_slow", same))
    assert fast != slow  # even an identical configuration is versioned per instance

    instances = await list_instances(session)
    assert [i.id for i in instances] == ["demo_sma_fast", "demo_sma_slow"]
    assert {i.current_version_id for i in instances} == {fast, slow}
    expected_hash = hash_document(_version("x", same).config)
    assert all(i.current_config_hash == expected_hash for i in instances)
    assert [i.id for i in await list_instances(session, definition_id="other")] == []


async def test_versions_must_match_their_instance(session: AsyncSession) -> None:
    await _setup(session, "demo_sma_fast")
    with pytest.raises(StrategyRepositoryError, match="unknown strategy instance"):
        await get_or_create_version(session, _version("nobody", {"fast": 9}))
    with pytest.raises(StrategyRepositoryError, match="belongs to"):
        await get_or_create_version(
            session, _version("demo_sma_fast", {"fast": 9}, definition_id="orb")
        )
    with pytest.raises(StrategyRepositoryError, match="config_hash"):
        await get_or_create_version(session, _version("demo_sma_fast", {}, config_hash=""))


async def test_an_instance_cannot_change_definition(session: AsyncSession) -> None:
    await _setup(session, "demo_sma_fast")
    await upsert_definition(
        session,
        DefinitionRecord(id="orb", name="ORB", kind="INTERNAL", latest_version="0.1.0"),
    )
    with pytest.raises(StrategyRepositoryError, match="cannot change definition"):
        await upsert_instance(
            session, InstanceRecord(id="demo_sma_fast", definition_id="orb", name="x")
        )


async def test_status_changes_are_promotions_with_evidence(session: AsyncSession) -> None:
    await _setup(session, "demo_sma_fast")
    version = await get_or_create_version(session, _version("demo_sma_fast", {"fast": 9}))
    promotion = await set_instance_status(
        session, "demo_sma_fast", StrategyStatus.PAPER, evidence={"trades": 0}, note="lab"
    )
    assert promotion is not None
    assert (
        await set_instance_status(session, "demo_sma_fast", StrategyStatus.PAPER, evidence={})
        is None
    )
    row = await session.get(StrategyPromotionRow, promotion)
    assert row is not None
    assert (row.from_status, row.to_status, row.strategy_version_id) == ("DRAFT", "PAPER", version)

    # Re-applying the lab configuration never demotes the instance.
    await upsert_instance(
        session,
        InstanceRecord(id="demo_sma_fast", definition_id="demo_sma_cross", name="renamed"),
    )
    [instance] = await list_instances(session)
    assert (instance.name, instance.status) == ("renamed", StrategyStatus.PAPER)

    with pytest.raises(StrategyRepositoryError, match="approving user"):
        await set_instance_status(
            session, "demo_sma_fast", StrategyStatus.LIVE_APPROVED, evidence={}
        )
