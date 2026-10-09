"""``kterminal lab demo`` — run the configured instances on synthetic data and
prove they did not interfere with each other.

Two independent proofs that the instances did not affect each other:

* the **isolation audit**, computed from what the store *recorded*: every
  decision on an account references a signal produced by that account's own
  instance, every trade was opened by one of that instance's signals, and each
  account's balance equals its starting balance plus its own ledger entries;
* the **alone-vs-together check**: every instance is run again *alone* on the
  very same bars, and its signals, trades and final balance must be identical
  to what it produced alongside the others. Anything one instance could do to
  another (shared state, ordering, timing, a crash) would show up here.
"""

import hashlib
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from kterminal.core.canonical import hash_data
from kterminal.domain.catalog import InstrumentCatalog
from kterminal.domain.market import Bar
from kterminal.marketdata.synthetic import merge_streams, synthetic_bars
from kterminal.paper.config import LabConfig
from kterminal.paper.lab import AccountResult, Lab, LabResult
from kterminal.paper.records import TradeRecord
from kterminal.paper.store import InMemoryLabStore, LabStore

# Sunday 6 September 2026, 22:00 UTC = 18:00 New York: the weekly open of metals/indices.
DEMO_START = datetime(2026, 9, 6, 22, 0, tzinfo=UTC)

_START_PRICES = {
    "XAUUSD": Decimal("4000.00"),
    "XAGUSD": Decimal("45.000"),
    "NAS100": Decimal("24000.0"),
    "MNQ": Decimal("24000.00"),
    "US30": Decimal("46000.0"),
    "US500": Decimal("6600.0"),
    "EURUSD": Decimal("1.17000"),
    "GBPUSD": Decimal("1.35000"),
    "BTCUSD": Decimal("110000.0"),
    "SOLUSD": Decimal("200.00"),
}


def demo_bars(
    catalog: InstrumentCatalog,
    config: LabConfig,
    *,
    start: datetime = DEMO_START,
    days: float = 5,
    seed: int = 21,
) -> list[Bar]:
    """Synthetic 1-minute bars for every instrument the enabled instances trade,
    generated only while that instrument's market is open.

    Each symbol's stream depends only on the symbol, the seed and the
    instrument's own trading calendar — never on which other instruments or
    instances are configured.
    """
    symbols = sorted({s for i in config.enabled_instances for s in i.instruments})
    streams = []
    for symbol in symbols:
        instrument = catalog.instrument(symbol)
        calendar = catalog.sessions.calendar(instrument.trading_hours)
        streams.append(
            synthetic_bars(
                symbol,
                start=start,
                count=int(days * 23 * 60),
                start_price=_START_PRICES.get(symbol, Decimal(100)),
                tick_size=instrument.tick_size,
                seed=_symbol_seed(seed, symbol),
                is_open=calendar.is_open,
                source="synthetic-demo",
            )
        )
    return merge_streams(*streams)


def _symbol_seed(seed: int, symbol: str) -> int:
    return int.from_bytes(hashlib.sha256(f"{seed}:{symbol}".encode()).digest()[:4], "big")


@dataclass(frozen=True, slots=True)
class IsolationCheck:
    instance_id: str
    account_id: str
    decisions: int
    decisions_on_foreign_signals: int
    trades: int
    trades_of_other_instances: int
    ledger_entries: int
    balance_matches_ledger: bool

    @property
    def ok(self) -> bool:
        return (
            self.decisions_on_foreign_signals == 0
            and self.trades_of_other_instances == 0
            and self.balance_matches_ledger
        )


@dataclass(frozen=True, slots=True)
class SoloCheck:
    """An instance's results alongside the others vs. alone on the same bars."""

    instance_id: str
    together: str  # fingerprint of signals, trades and final balance
    alone: str
    signals: int
    trades: int

    @property
    def ok(self) -> bool:
        return self.together == self.alone


@dataclass(frozen=True, slots=True)
class DemoRun:
    result: LabResult
    solo: list[SoloCheck]


async def run_demo(
    catalog: InstrumentCatalog,
    config: LabConfig,
    store: LabStore,
    *,
    days: float = 5,
    seed: int = 21,
    host: str | None = None,
) -> DemoRun:
    if host is not None:
        config = config.model_copy(
            update={"defaults": config.defaults.model_copy(update={"host": host})}
        )
    bars = demo_bars(catalog, config, days=days, seed=seed)
    result = await Lab(config, catalog, store, run_name="lab-demo").run(bars)
    solo = []
    for instance in config.enabled_instances:
        alone_config = config.model_copy(update={"instances": (instance,), "experiments": ()})
        alone_store = InMemoryLabStore()
        alone = await Lab(alone_config, catalog, alone_store, run_name="lab-demo-solo").run(bars)
        (together_account,) = [a for a in result.accounts if a.instance_id == instance.id]
        (alone_account,) = alone.accounts
        solo.append(
            SoloCheck(
                instance_id=instance.id,
                together=_fingerprint(
                    together_account, await store.closed_trades(together_account.account_id)
                ),
                alone=_fingerprint(
                    alone_account, await alone_store.closed_trades(alone_account.account_id)
                ),
                signals=together_account.signals,
                trades=together_account.summary.trades,
            )
        )
    return DemoRun(result, solo)


def _fingerprint(account: AccountResult, trades: Sequence[TradeRecord]) -> str:
    """Everything an instance did, independent of ids and of how a store formats
    numbers (``49670.2200`` from PostgreSQL equals ``49670.22`` in memory)."""
    document = {
        "balance": _num(account.balance),
        "signals": account.signals,
        "approved": account.approved,
        "rejected": account.rejected,
        "reject_codes": dict(sorted(account.reject_codes.items())),
        "fault": account.fault,
        "trades": [
            [
                t.instrument,
                t.direction.value,
                _num(t.qty),
                t.entry_time.isoformat(),
                _num(t.entry_price),
                t.exit_time.isoformat() if t.exit_time else None,
                _num(t.exit_price),
                t.exit_reason,
                _num(t.net_pnl),
            ]
            for t in trades
        ],
    }
    return hash_data(document)


def _num(value: Any) -> str | None:
    if value is None:
        return None
    number = Decimal(value)
    return "0" if number.is_zero() else format(number.normalize(), "f")


def format_report(
    result: LabResult, checks: Iterable[IsolationCheck], solo: Iterable[SoloCheck] = ()
) -> str:
    lines = [
        f"Lab run {result.run_id} — {result.batches} bar batches "
        f"({_fmt_time(result.started_at)} → {_fmt_time(result.finished_at)})",
        "Data: synthetic pure random walk — no strategy has an edge on it, so these numbers",
        "demonstrate mechanics and isolation, NOT strategy quality.",
        "",
        f"{'instance':<22}{'account':<30}{'start':>11}{'balance':>12}{'trades':>8}"
        f"{'W/L':>9}{'win%':>7}{'net P&L':>12}{'avg R':>8}{'signals':>9}{'rej':>5}",
    ]
    for acc in result.accounts:
        s = acc.summary
        win = f"{s.win_rate * 100:.1f}" if s.win_rate is not None else "—"
        avg_r = f"{s.average_r:.2f}" if s.average_r is not None else "—"
        lines.append(
            f"{acc.instance_id:<22}{acc.account_name:<30}{_money(acc.starting_balance):>11}"
            f"{_money(acc.balance):>12}{s.trades:>8}{f'{s.wins}/{s.losses}':>9}{win:>7}"
            f"{_money(s.net_pnl, signed=True):>12}{avg_r:>8}{acc.signals:>9}{acc.rejected:>5}"
        )
        if acc.fault:
            lines.append(f"{'':<22}FAULTED: {acc.fault}")
    lines += ["", "Isolation audit (from recorded rows):"]
    for check in checks:
        status = "OK " if check.ok else "FAIL"
        lines.append(
            f"  [{status}] {check.instance_id}: {check.decisions} decisions, "
            f"{check.decisions_on_foreign_signals} on other instances' signals; "
            f"{check.trades} trades, {check.trades_of_other_instances} of other instances; "
            f"balance {'=' if check.balance_matches_ledger else '≠'} start + Σ "
            f"{check.ledger_entries} own ledger entries"
        )
    solo = list(solo)
    if solo:
        lines += ["", "Alone vs. together (each instance re-run alone on the same bars):"]
        for item in solo:
            status = "OK " if item.ok else "FAIL"
            verdict = "identical" if item.ok else "DIFFERENT"
            lines.append(
                f"  [{status}] {item.instance_id}: {item.signals} signals, {item.trades} trades, "
                f"final balance — {verdict} (fingerprint {item.together[:12]})"
            )
    return "\n".join(lines)


def _money(value: Any, *, signed: bool = False) -> str:
    amount = Decimal(value)
    text = f"{abs(amount):,.2f}"
    if signed:
        return f"{'+' if amount >= 0 else '−'}{text}"
    return text


def _fmt_time(value: datetime | None) -> str:
    return value.strftime("%Y-%m-%d %H:%M UTC") if value else "—"


def demo_period(days: float) -> timedelta:
    return timedelta(days=days)
