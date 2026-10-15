"""The dashboard's read endpoints against a database the real lab populated.

Every number is checked against an independent source: what the lab computed
in memory, the rows read back directly, or the reference definitions in
:mod:`kterminal.api.metrics`.
"""

import asyncio
from collections.abc import Callable
from datetime import timedelta
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from kterminal.analytics.summary import summarize_trades
from kterminal.api.app import API_PREFIX
from kterminal.api.metrics import drawdown_stats
from kterminal.api.queries.system import RUNTIME_STATE_KEY
from kterminal.core.clock import SimulatedClock
from kterminal.db import models as m
from kterminal.domain.timeframes import Timeframe
from kterminal.paper.runtime import PaperRuntime
from tests.integration.api.conftest import demo_session, sign_in
from tests.integration.api.demo import DemoData, runtime_status

pytestmark = pytest.mark.integration

D = Decimal


def get(client: TestClient, path: str, **params: Any) -> Any:
    response = client.get(f"{API_PREFIX}{path}", params=params)
    assert response.status_code == 200, (path, response.status_code, response.text)
    return response.json()


async def _rows(demo: DemoData, statement: Any) -> list[Any]:
    async with demo_session(demo) as session:
        return list((await session.execute(statement)).all())


def rows(demo: DemoData, statement: Any) -> list[Any]:
    return asyncio.run(_rows(demo, statement))


# ── leaderboard and account metrics ──────────────────────────────────────────
def test_run_accounts_match_what_the_lab_computed(viewer: TestClient, demo: DemoData) -> None:
    page = get(viewer, "/accounts", scope="run", run_id=str(demo.lab_run_id))
    assert page["total"] == 2
    by_instance = {a["instance_id"]: a for a in page["items"]}
    for result in demo.lab.accounts:
        account = by_instance[result.instance_id]
        assert account["id"] == str(result.account_id)
        assert account["kind"] == "RUN"
        assert account["run_id"] == str(demo.lab_run_id)
        assert account["run_kind"] == "LAB_SIMULATION"
        metrics = account["metrics"]
        summary = result.summary
        assert D(metrics["balance"]) == result.balance
        assert D(metrics["equity"]) == result.balance  # everything closed at the end
        assert metrics["open_positions"] == 0
        assert metrics["trades"] == summary.trades
        assert (metrics["wins"], metrics["losses"]) == (summary.wins, summary.losses)
        assert D(metrics["net_pnl"]) == summary.net_pnl
        assert D(metrics["win_rate"]) == summary.win_rate
        assert metrics["profit_factor"] == (
            None if summary.profit_factor is None else str(summary.profit_factor)
        )
        assert D(metrics["average_r"]) == summary.average_r
        assert D(metrics["return_pct"]) == (
            (result.balance - D(50_000)) / D(50_000) * 100
        ).quantize(D("0.01"))


def test_forward_metrics_are_recomputed_from_recorded_rows(
    viewer: TestClient, demo: DemoData
) -> None:
    leaderboard = get(viewer, "/accounts", scope="forward")
    assert leaderboard["total"] == 2
    for account in leaderboard["items"]:
        assert account["kind"] == "FORWARD"
        account_id = account["id"]
        assert account_id == str(demo.forward_accounts[account["instance_id"]])
        closed = rows(
            demo,
            select(m.TradeRow.net_pnl, m.TradeRow.r_multiple).where(
                m.TradeRow.account_id == account_id, m.TradeRow.status == "CLOSED"
            ),
        )
        summary = summarize_trades(closed)
        metrics = account["metrics"]
        assert metrics["trades"] == summary.trades > 0
        assert D(metrics["net_pnl"]) == summary.net_pnl
        (balance,) = rows(
            demo,
            select(m.AccountLedgerRow.balance_after)
            .where(m.AccountLedgerRow.account_id == account_id)
            .order_by(m.AccountLedgerRow.seq.desc())
            .limit(1),
        )[0]
        assert D(metrics["balance"]) == balance
        (ledger_total,) = rows(
            demo,
            select(m.func.sum(m.AccountLedgerRow.amount)).where(
                m.AccountLedgerRow.account_id == account_id
            ),
        )[0]
        assert D(metrics["balance"]) == ledger_total  # the open trade's entry costs included
        # max drawdown: the SQL window query equals the reference definition
        curve = [
            r.equity
            for r in rows(
                demo,
                select(m.EquitySnapshotRow.equity)
                .where(m.EquitySnapshotRow.account_id == account_id)
                .order_by(m.EquitySnapshotRow.ts),
            )
        ]
        reference = drawdown_stats(D(50_000), curve)
        assert reference is not None
        assert D(metrics["max_drawdown"]) == reference.amount
        assert D(metrics["max_drawdown_pct"]) == reference.pct
        # the run left one position open per account: equity is marked to market
        assert metrics["open_positions"] == 1
        assert D(metrics["equity"]) == D(metrics["balance"]) + D(metrics["open_pnl"])
        assert account["runtime"]["account_id"] == account_id
        assert account["version"]["timeframe"] == "5m"
        assert account["version"]["instruments"] == ["XAUUSD"]
        assert account["halted"] is False


def test_leaderboard_sorting_filtering_and_paging(viewer: TestClient) -> None:
    by_pnl = get(viewer, "/accounts", scope="all", sort="net_pnl", order="desc")["items"]
    pnls = [D(a["metrics"]["net_pnl"]) for a in by_pnl]
    assert pnls == sorted(pnls, reverse=True)
    ascending = get(viewer, "/accounts", scope="all", sort="net_pnl", order="asc")["items"]
    assert [a["id"] for a in ascending] == [a["id"] for a in reversed(by_pnl)]
    by_dd = get(viewer, "/accounts", scope="forward", sort="max_drawdown_pct", order="asc")
    dds = [D(a["metrics"]["max_drawdown_pct"]) for a in by_dd["items"]]
    assert dds == sorted(dds)

    assert get(viewer, "/accounts", scope="all")["total"] == 4
    assert get(viewer, "/accounts", strategy="demo_sma_cross")["total"] == 2
    assert get(viewer, "/accounts", instrument="XAUUSD", timeframe="5m")["total"] == 4
    assert get(viewer, "/accounts", instrument="EURUSD")["total"] == 0
    assert get(viewer, "/accounts", timeframe="15m")["total"] == 0
    assert get(viewer, "/accounts", q="BREAKOUT")["total"] == 2
    assert get(viewer, "/accounts", q="channel breakout")["total"] == 2
    assert get(viewer, "/accounts", instance_id="demo_sma_fast")["total"] == 2

    first = get(viewer, "/accounts", scope="all", sort="name", order="asc", limit=3)
    second = get(viewer, "/accounts", scope="all", sort="name", order="asc", limit=3, offset=3)
    assert first["total"] == second["total"] == 4
    assert len(first["items"]) == 3 and len(second["items"]) == 1
    names = [a["name"] for a in first["items"] + second["items"]]
    assert names == sorted(names, key=str.lower)

    bad = viewer.get(f"{API_PREFIX}/accounts", params={"sort": "drop table"})
    assert bad.status_code == 422


def test_account_detail_and_equity_curve(viewer: TestClient, demo: DemoData) -> None:
    account_id = demo.forward_accounts["demo_sma_fast"]
    detail = get(viewer, f"/accounts/{account_id}")
    assert detail["instance_id"] == "demo_sma_fast"
    assert detail["definition_id"] == "demo_sma_cross"
    assert detail["version"]["params"]["fast"] == 9
    assert detail["config_version"] == 1
    assert detail["config"]["risk_per_trade_pct"] == "0.5"
    assert detail["kill_switches"] == []

    full = get(viewer, f"/accounts/{account_id}/equity", max_points=10_000)
    assert not full["downsampled"]
    assert len(full["points"]) == full["total_points"] > 20
    times = [p["ts"] for p in full["points"]]
    assert times == sorted(times)
    small = get(viewer, f"/accounts/{account_id}/equity", max_points=10)
    assert small["downsampled"]
    assert len(small["points"]) <= 11
    assert small["points"][0] == full["points"][0]
    assert small["points"][-1] == full["points"][-1]

    missing = viewer.get(f"{API_PREFIX}/accounts/00000000-0000-0000-0000-000000000000")
    assert missing.status_code == 404
    assert missing.json()["code"] == "NOT_FOUND"
    assert viewer.get(f"{API_PREFIX}/accounts/not-a-uuid").status_code == 422


# ── positions, trades and explain ────────────────────────────────────────────
def test_open_positions_are_marked_at_the_last_candle(viewer: TestClient, demo: DemoData) -> None:
    positions = get(viewer, "/positions")
    assert len(positions) == 2
    last = demo.forward_bars[-1]
    for position in positions:
        assert position["status"] == "OPEN"
        assert D(position["last_price"]) == last.close
        assert position["last_price_at"] == last.close_time.isoformat().replace("+00:00", "Z")
        entry, stop = D(position["entry_price"]), D(position["initial_stop"])
        qty, risk = D(position["qty"]), D(position["initial_risk"])
        sign = 1 if position["direction"] == "LONG" else -1
        per_unit = risk / (abs(entry - stop) * qty)
        expected = ((last.close - entry) * sign * qty * per_unit).quantize(D("0.01"))
        assert D(position["unrealized_pnl"]) == expected
    only = get(viewer, "/positions", instance_id="demo_sma_fast")
    assert [p["instance_id"] for p in only] == ["demo_sma_fast"]
    assert get(viewer, "/positions", scope="run") == []


def test_trades_list_filters_and_pages(viewer: TestClient, demo: DemoData) -> None:
    every = get(viewer, "/trades", scope="all", limit=500)
    (total,) = rows(demo, select(m.func.count()).select_from(m.TradeRow))[0]
    assert every["total"] == total
    forward = get(viewer, "/trades", scope="forward", limit=500)
    lab = get(viewer, "/trades", scope="run", limit=500)
    assert forward["total"] + lab["total"] == total
    assert {t["run_id"] for t in lab["items"]} == {str(demo.lab_run_id)}
    open_trades = get(viewer, "/trades", status="OPEN")
    assert open_trades["total"] == 2
    longs = get(viewer, "/trades", direction="LONG", limit=500)["items"]
    assert longs and all(t["direction"] == "LONG" for t in longs)
    page = get(viewer, "/trades", scope="all", limit=5, offset=5)
    assert [t["id"] for t in page["items"]] == [t["id"] for t in every["items"][5:10]]
    account = demo.forward_accounts["demo_breakout_xau"]
    mine = get(viewer, "/trades", account_id=str(account), limit=500)["items"]
    assert mine and {t["account_id"] for t in mine} == {str(account)}
    assert all(t["account_name"] == "Paper 50K · demo_breakout_xau" for t in mine)


def test_explain_a_trade(viewer: TestClient, demo: DemoData) -> None:
    trade = get(viewer, "/trades", scope="forward", status="CLOSED", limit=1)["items"][0]
    explained = get(viewer, f"/trades/{trade['id']}")
    assert explained["trade"] == trade
    assert explained["entry_signal"]["action"] == trade["direction"]
    assert explained["entry_signal"]["instance_id"] == trade["instance_id"]
    assert explained["entry_market_snapshot"]["bar"]["close"]
    decision = explained["decision"]
    assert decision["approved"] is True
    assert decision["account_id"] == trade["account_id"]
    assert decision["rule_results"]
    assert decision["account_state"]
    assert explained["version"]["id"] == trade["strategy_version_id"]
    assert explained["version"]["params"]
    assert explained["account_config"]["config"]["starting_balance"] == "50000"
    assert explained["catalog_fingerprint"]
    purposes = [o["purpose"] for o in explained["orders"]]
    assert purposes[0] == "ENTRY"
    assert len(purposes) >= 2  # entry and exit
    assert explained["fills"]
    assert {f["order_id"] for f in explained["fills"]} <= {o["id"] for o in explained["orders"]}
    assert explained["ledger"]
    assert sum(D(e["amount"]) for e in explained["ledger"]) == D(trade["net_pnl"])
    if trade["exit_reason"] in ("REVERSAL", "SIGNAL_EXIT"):
        assert explained["exit_signal"] is not None
    assert viewer.get(f"{API_PREFIX}/trades/{demo.forward_run_id}").status_code == 404


# ── signals ──────────────────────────────────────────────────────────────────
def test_signal_log_shows_outcomes_and_reject_codes(viewer: TestClient, demo: DemoData) -> None:
    account = demo.forward_accounts["demo_sma_fast"]
    log = get(viewer, "/signals", account_id=str(account), limit=500)
    by_id = {s["id"]: s for s in log["items"]}
    rejected = by_id[str(demo.rejected_signal_id)]
    assert rejected["outcome"] == "REJECTED"
    assert rejected["outcome_code"] == "MAX_OPEN_POSITIONS"
    assert rejected["decision"]["approved"] is False
    invalid = by_id[str(demo.invalid_signal_id)]
    assert invalid["outcome"] == "INVALID"
    assert invalid["outcome_code"] == "INVALID_SIGNAL"
    assert invalid["reject_detail"]
    approved = [s for s in log["items"] if s["outcome"] == "APPROVED"]
    assert approved and all(s["decision"]["account_id"] == str(account) for s in approved)
    # only this account's instance, only forward signals
    assert {s["instance_id"] for s in log["items"]} == {"demo_sma_fast"}
    assert {s["run_id"] for s in log["items"]} == {str(demo.forward_run_id)}

    only_rejected = get(viewer, "/signals", outcome="REJECTED", limit=500)["items"]
    assert str(demo.rejected_signal_id) in {s["id"] for s in only_rejected}
    assert {s["outcome"] for s in only_rejected} == {"REJECTED"}
    assert all(s["outcome_code"] for s in only_rejected)
    only_invalid = get(viewer, "/signals", outcome="INVALID")
    assert only_invalid["total"] == 1
    lab_account = demo.lab_accounts["demo_sma_fast"]
    lab_log = get(viewer, "/signals", account_id=str(lab_account), limit=500)
    assert lab_log["total"] > 0
    assert {s["run_id"] for s in lab_log["items"]} == {str(demo.lab_run_id)}
    signals_newest_first = [s["signal_time"] for s in log["items"]]
    assert signals_newest_first == sorted(signals_newest_first, reverse=True)
    missing = viewer.get(
        f"{API_PREFIX}/signals", params={"account_id": "00000000-0000-0000-0000-000000000000"}
    )
    assert missing.status_code == 404


# ── candles and the per-instrument view ──────────────────────────────────────
def test_stored_candles_are_returned_as_stored(viewer: TestClient, demo: DemoData) -> None:
    chart = get(viewer, "/candles", instrument="XAUUSD", timeframe="1m", limit=50, markers="none")
    assert chart["source"] == "oanda"
    assert chart["sources"] == ["oanda"]
    assert chart["built_from"] is None
    assert chart["markers"] == []
    expected = demo.forward_bars[-50:]
    assert [D(c["c"]) for c in chart["candles"]] == [b.close for b in expected]
    assert chart["candles"][0]["t"] == expected[0].open_time.isoformat().replace("+00:00", "Z")


def test_higher_timeframes_are_aggregated_from_stored_bars(
    viewer: TestClient, demo: DemoData
) -> None:
    chart = get(viewer, "/candles", instrument="XAUUSD", timeframe="15m", limit=20)
    assert chart["built_from"] == "1m"
    assert len(chart["candles"]) == 20
    tf = Timeframe.parse("15m")
    buckets: dict[Any, list[Any]] = {}
    for bar in demo.forward_bars:
        buckets.setdefault(tf.floor(bar.open_time), []).append(bar)
    for candle in chart["candles"]:
        start = next(k for k in buckets if k.isoformat().replace("+00:00", "Z") == candle["t"])
        bars = buckets[start]
        assert D(candle["o"]) == bars[0].open
        assert D(candle["h"]) == max(b.high for b in bars)
        assert D(candle["l"]) == min(b.low for b in bars)
        assert D(candle["c"]) == bars[-1].close
        assert D(candle["v"]) == sum(b.volume for b in bars)
    # paging back: everything strictly before the first bar shown
    older = get(
        viewer,
        "/candles",
        instrument="XAUUSD",
        timeframe="15m",
        limit=5,
        until=chart["candles"][0]["t"],
    )
    assert older["candles"][-1]["t"] < chart["candles"][0]["t"]
    assert len(older["candles"]) == 5


def test_candles_carry_every_strategys_trade_markers(viewer: TestClient, demo: DemoData) -> None:
    chart = get(viewer, "/candles", instrument="XAUUSD", timeframe="5m", limit=1_000)
    first = chart["candles"][0]["t"]
    markers = chart["markers"]
    assert {m_["instance_id"] for m_ in markers} == {"demo_sma_fast", "demo_breakout_xau"}
    assert all(m_["exit_time"] is None or m_["exit_time"] >= first for m_ in markers)
    assert {m_["status"] for m_ in markers} == {"OPEN", "CLOSED"}
    only = get(
        viewer,
        "/candles",
        instrument="XAUUSD",
        timeframe="5m",
        limit=1_000,
        instance="demo_sma_fast",
    )["markers"]
    assert only and {m_["instance_id"] for m_ in only} == {"demo_sma_fast"}
    lab = get(viewer, "/candles", instrument="XAUUSD", timeframe="5m", markers="run")["markers"]
    assert lab == []  # the lab run traded a week earlier than the stored candles


def test_candle_requests_are_validated(viewer: TestClient) -> None:
    bad = viewer.get(f"{API_PREFIX}/candles", params={"instrument": "XAUUSD", "timeframe": "1D"})
    assert bad.status_code == 422
    assert bad.json()["code"] == "INVALID_TIMEFRAME"
    nothing = get(viewer, "/candles", instrument="EURUSD", timeframe="5m")
    assert nothing["candles"] == [] and nothing["source"] is None
    injected = viewer.get(f"{API_PREFIX}/candles", params={"instrument": "XAU'; drop"})
    assert injected.status_code == 422


def test_instruments(viewer: TestClient, demo: DemoData) -> None:
    (gold,) = get(viewer, "/instruments")
    assert gold["symbol"] == "XAUUSD"
    assert gold["name"] == "Gold / US Dollar"
    assert gold["instances"] == ["demo_breakout_xau", "demo_sma_fast"]
    assert gold["timeframes"] == ["5m"]
    assert gold["open_positions"] == 2
    assert gold["feed"]["provider"] == "oanda"
    assert gold["last_candle_at"] == demo.forward_bars[-1].close_time.isoformat().replace(
        "+00:00", "Z"
    )
    detail = get(viewer, "/instruments/XAUUSD")
    assert {a["instance_id"] for a in detail["accounts"]} == {"demo_sma_fast", "demo_breakout_xau"}
    assert all(a["kind"] == "FORWARD" for a in detail["accounts"])
    assert len(detail["positions"]) == 2
    assert viewer.get(f"{API_PREFIX}/instruments/EURUSD").status_code == 404


# ── strategies, runs, system ─────────────────────────────────────────────────
def test_instances(viewer: TestClient, demo: DemoData) -> None:
    instances = {i["id"]: i for i in get(viewer, "/instances")}
    assert set(instances) == {"demo_sma_fast", "demo_breakout_xau"}
    sma = instances["demo_sma_fast"]
    assert sma["definition_id"] == "demo_sma_cross"
    assert sma["version"]["params"] == {
        "fast": 9,
        "slow": 21,
        "range_bars": 14,
        "reward_risk": "2",
        "stop_range_mult": "1.5",
    }
    assert sma["version"]["context_timeframes"] == ["15m", "1h"]
    assert sma["account_id"] == str(demo.forward_accounts["demo_sma_fast"])
    assert sma["runtime"]["state"] == "RUNNING"
    assert instances["demo_breakout_xau"]["runtime"]["state"] == "FAULTED"
    detail = get(viewer, "/instances/demo_sma_fast")
    assert detail["version_history"][0]["id"] == sma["version"]["id"]
    assert viewer.get(f"{API_PREFIX}/instances/nope").status_code == 404


def test_runs(viewer: TestClient, demo: DemoData) -> None:
    runs = get(viewer, "/runs")
    assert runs["total"] == 2
    forward, lab = runs["items"]  # newest first
    assert forward["id"] == str(demo.forward_run_id)
    assert forward["kind"] == "FORWARD"
    assert lab["kind"] == "LAB_SIMULATION"
    assert lab["instances"] == ["demo_sma_fast", "demo_breakout_xau"]
    assert lab["accounts"] == 2 and forward["accounts"] == 2
    lab_trades = rows(
        demo,
        select(m.func.count()).select_from(m.TradeRow).where(m.TradeRow.run_id == demo.lab_run_id),
    )[0][0]
    assert lab["trades"] == lab_trades
    assert get(viewer, "/runs", kind="FORWARD")["total"] == 1
    assert get(viewer, f"/runs/{demo.lab_run_id}")["id"] == str(demo.lab_run_id)
    assert (
        viewer.get(f"{API_PREFIX}/runs/{demo.forward_accounts['demo_sma_fast']}").status_code == 404
    )
    run_accounts = get(viewer, "/accounts", run_id=str(demo.forward_run_id))
    assert {a["kind"] for a in run_accounts["items"]} == {"FORWARD"}


def test_overview(viewer: TestClient, demo: DemoData) -> None:
    overview = get(viewer, "/overview")
    assert overview["live_trading_permitted"] is False
    runtime = overview["runtime"]
    assert runtime["present"] and not runtime["stale"]
    assert runtime["age_seconds"] == 5.0
    assert runtime["status"]["status"] == "running"
    assert runtime["status"]["error"] is None
    assert runtime["status"]["instruments"]["XAUUSD"]["state"] == "ok"
    assert runtime["status"]["kill_switch"] == {"global": False, "accounts": [], "strategies": []}
    forward = overview["forward"]
    assert forward["accounts"] == 2
    assert forward["open_positions"] == 2
    leaderboard = get(viewer, "/accounts", scope="forward")["items"]
    assert D(forward["net_pnl"]) == sum(D(a["metrics"]["net_pnl"]) for a in leaderboard)
    assert D(forward["equity"]) == sum(D(a["metrics"]["equity"]) for a in leaderboard)
    assert [r["id"] for r in overview["recent_runs"]] == [
        str(demo.forward_run_id),
        str(demo.lab_run_id),
    ]


def test_a_silent_runtime_is_reported_stale(
    make_client: Callable[..., TestClient], demo: DemoData
) -> None:
    client = make_client(clock=SimulatedClock(demo.now + timedelta(minutes=10)))
    sign_in(client, "vera")
    runtime = get(client, "/system/runtime")
    assert runtime["present"] and runtime["stale"]
    assert runtime["age_seconds"] == 605.0


def test_no_forward_session_yet(viewer: TestClient, demo: DemoData) -> None:
    async def remove() -> None:
        async with demo_session(demo) as session:
            await session.execute(
                delete(m.SystemStateRow).where(m.SystemStateRow.key == RUNTIME_STATE_KEY)
            )

    async def restore(value: Any) -> None:
        async with demo_session(demo) as session:
            session.add(
                m.SystemStateRow(
                    key=RUNTIME_STATE_KEY, value=value, updated_at=demo.now - timedelta(seconds=5)
                )
            )

    asyncio.run(remove())
    try:
        runtime = get(viewer, "/overview")["runtime"]
        assert runtime == {
            "present": False,
            "stale": True,
            "age_seconds": None,
            "stale_after_seconds": 120.0,
            "status": None,
            "error": None,
        }
        assert all(i["runtime"] is None for i in get(viewer, "/instances"))
        assert get(viewer, "/instruments")[0]["feed"] is None
        asyncio.run(restore({"status": ["not", "an", "object"]}))
        broken = get(viewer, "/system/runtime")
        assert broken["present"] and broken["status"] is None
        assert broken["error"] == "the runtime status could not be read"
        asyncio.run(remove())
        # a runtime that could not even be built publishes its reason
        failure = PaperRuntime.failure_document(
            "DataSourceError: no source for XAUUSD", demo.now - timedelta(seconds=5)
        )
        asyncio.run(restore(failure))
        failed = get(viewer, "/system/runtime")
        assert failed["present"] and failed["error"] is None
        assert failed["status"]["status"] == "error"
        assert failed["status"]["error"] == "DataSourceError: no source for XAUUSD"
        assert failed["status"]["run_id"] is None and failed["status"]["instruments"] == {}
        assert failed["status"]["kill_switch"] == {
            "global": False,
            "accounts": [],
            "strategies": [],
        }
    finally:
        asyncio.run(remove())
        last = demo.forward_bars[-1]
        asyncio.run(
            restore(runtime_status(demo.forward_run_id, last, demo.forward_accounts, demo.now))
        )


def test_faults(viewer: TestClient) -> None:
    page = get(viewer, "/system/faults")
    assert page == {"items": [], "total": 0, "limit": 50, "offset": 0}
