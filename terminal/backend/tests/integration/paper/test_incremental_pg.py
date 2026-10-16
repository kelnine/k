"""Incremental lab processing records in PostgreSQL exactly what Lab.run records."""

from datetime import datetime

import pytest

from kterminal.db.session import Database
from kterminal.domain.market import Bar
from kterminal.paper.demo import _fingerprint
from kterminal.paper.lab import Lab
from kterminal.paper.pg_store import PostgresLabStore
from tests.fixtures.catalog import lab_catalog
from tests.fixtures.forward import FakeTime
from tests.integration.paper.forward_helpers import START, lab_config, providers, registry

pytestmark = pytest.mark.integration


def minutes(bars: list[Bar]) -> list[list[Bar]]:
    groups: dict[datetime, list[Bar]] = {}
    for bar in bars:
        groups.setdefault(bar.open_time, []).append(bar)
    return [groups[t] for t in sorted(groups)]


async def test_lab_run_and_minute_by_minute_processing_record_the_same(
    database: Database,
) -> None:
    feeds = providers(FakeTime(START))
    bars = sorted(
        (b for p in feeds.values() for bars in p.bars.values() for b in bars),
        key=lambda b: (b.open_time, b.instrument),
    )
    bars = [b for b in bars if b.open_time >= START.replace(hour=12)][:600]
    warm, live = bars[:200], bars[200:]
    config = lab_config()
    store = PostgresLabStore(database)

    whole = await Lab(config, lab_catalog(), store, definitions=registry()).run(
        live, warmup_bars=warm
    )

    lab = Lab(config, lab_catalog(), store, definitions=registry())
    await lab.setup()
    run_id = await store.start_run(
        kind="LAB_SIMULATION",
        name="incremental",
        config=config.model_dump(mode="json"),
        catalog_document=lab_catalog().to_document(),
        catalog_fingerprint=lab_catalog().fingerprint,
        started_at=warm[0].open_time,
    )
    await lab.begin(run_id, warmup_bars=warm, started_at=warm[0].open_time)
    groups = minutes(live)
    for index, group in enumerate(groups):
        last = index == len(groups) - 1
        await lab.process_bars(group, through=None if last else group[0].close_time)
    stepwise = await lab.end()

    assert stepwise.batches == whole.batches
    for one, two in zip(whole.accounts, stepwise.accounts, strict=True):
        assert one.instance_id == two.instance_id
        assert _fingerprint(one, await store.closed_trades(one.account_id)) == _fingerprint(
            two, await store.closed_trades(two.account_id)
        )
    assert sum(a.summary.trades for a in whole.accounts) > 5
    checks = await store.isolation_checks(run_id)
    assert checks and all(c.ok for c in checks)
