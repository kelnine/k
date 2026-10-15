"""The per-instrument view: which strategies trade it, their open positions, its feed."""

from collections import defaultdict

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from kterminal.api.queries.candles import last_candle_at
from kterminal.api.queries.common import version_out
from kterminal.api.schemas import InstrumentSummary, RuntimeView
from kterminal.db import models as m


async def list_instruments(
    session: AsyncSession, runtime: RuntimeView, *, symbol: str | None = None
) -> list[InstrumentSummary]:
    """Instruments the configured instances trade (current versions), plus any the
    runtime reports a feed for or that hold an open forward position."""
    instances: dict[str, set[str]] = defaultdict(set)
    timeframes: dict[str, set[str]] = defaultdict(set)
    rows = await session.execute(
        select(m.StrategyInstanceRow.id, m.StrategyVersionRow)
        .join(
            m.StrategyVersionRow,
            m.StrategyVersionRow.id == m.StrategyInstanceRow.current_version_id,
        )
        .where(m.StrategyInstanceRow.enabled)
    )
    for instance_id, version_row in rows:
        version = version_out(version_row)
        for instrument in version.instruments:
            instances[instrument].add(instance_id)
            if version.timeframe:
                timeframes[instrument].add(version.timeframe)
    open_counts = dict(
        (
            await session.execute(
                select(m.TradeRow.instrument, func.count())
                .join(m.AccountRow, m.AccountRow.id == m.TradeRow.account_id)
                .where(m.TradeRow.status == "OPEN", m.AccountRow.strategy_instance_id.is_not(None))
                .group_by(m.TradeRow.instrument)
            )
        ).all()
    )
    feeds = runtime.status.instruments if runtime.status else {}
    symbols = set(instances) | set(feeds) | set(open_counts)
    if symbol is not None:
        symbols &= {symbol}
    if not symbols:
        return []
    catalog = {
        row.symbol: row
        for row in (
            await session.execute(
                select(
                    m.InstrumentRow.symbol, m.InstrumentRow.name, m.InstrumentRow.asset_class
                ).where(m.InstrumentRow.symbol.in_(symbols))
            )
        ).all()
    }
    out = []
    for name in sorted(symbols):
        entry = catalog.get(name)
        out.append(
            InstrumentSummary(
                symbol=name,
                name=entry.name if entry else None,
                asset_class=entry.asset_class if entry else None,
                instances=sorted(instances.get(name, ())),
                timeframes=sorted(timeframes.get(name, ()), key=_tf_order),
                open_positions=int(open_counts.get(name, 0)),
                feed=feeds.get(name),
                last_candle_at=await last_candle_at(session, name),
            )
        )
    return out


def _tf_order(code: str) -> tuple[int, str]:
    units = {"m": 1, "h": 60, "D": 1440, "W": 10080, "M": 43200}
    number = "".join(ch for ch in code if ch.isdigit()) or "1"
    return int(number) * units.get(code[-1:], 1), code
