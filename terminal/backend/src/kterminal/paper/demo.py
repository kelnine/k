"""``kterminal lab demo`` — run the configured instances on synthetic data and
prove they did not interfere with each other.

The isolation audit is computed from what the store **recorded**, not from
in-memory state: every decision on an account must reference a signal of that
account's own instance, every trade must belong to that instance, and each
account's balance must equal its starting balance plus the sum of its own
ledger entries.
"""

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any

from kterminal.domain.catalog import InstrumentCatalog
from kterminal.domain.market import Bar
from kterminal.marketdata.synthetic import merge_streams, synthetic_bars
from kterminal.paper.config import LabConfig
from kterminal.paper.lab import Lab, LabResult
from kterminal.paper.store import LabStore

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
    generated only while that instrument's market is open."""
    symbols = sorted({s for i in config.enabled_instances for s in i.instruments})
    streams = []
    for offset, symbol in enumerate(symbols):
        instrument = catalog.instrument(symbol)
        listing = catalog.execution_listing(
            config.account_settings(config.enabled_instances[0]).venue_profile, symbol
        )
        calendar = catalog.calendar_for(listing)
        streams.append(
            synthetic_bars(
                symbol,
                start=start,
                count=int(days * 23 * 60),
                start_price=_START_PRICES.get(symbol, Decimal(100)),
                tick_size=instrument.tick_size,
                seed=seed + offset,
                is_open=calendar.is_open,
                source="synthetic-demo",
            )
        )
    return merge_streams(*streams)


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


async def run_demo(
    catalog: InstrumentCatalog,
    config: LabConfig,
    store: LabStore,
    *,
    days: float = 5,
    seed: int = 21,
    host: str | None = None,
) -> LabResult:
    if host is not None:
        config = config.model_copy(
            update={"defaults": config.defaults.model_copy(update={"host": host})}
        )
    lab = Lab(config, catalog, store, run_name="lab-demo")
    return await lab.run(demo_bars(catalog, config, days=days, seed=seed))


def format_report(result: LabResult, checks: Iterable[IsolationCheck]) -> str:
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
