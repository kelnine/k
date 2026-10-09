"""The documented "explain trade" query (docs/04 §4.9) runs against the real schema."""

import re
from datetime import timedelta
from decimal import Decimal
from pathlib import Path

import pytest
from sqlalchemy import insert, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from kterminal.core.ids import new_correlation_id, uuid7
from kterminal.db.models import FillRow, OrderRow, RiskDecisionRow, TradeRow, WebhookEventRow
from tests.integration.db.helpers import T0, insert_closed_trade, seed_catalog, seed_lab_subject

pytestmark = pytest.mark.integration

DOC = Path(__file__).resolve().parents[4] / "docs" / "04-database-schema.md"


def documented_query() -> str:
    match = re.search(r"```sql\n(-- \"Explain trade.*?)```", DOC.read_text(), re.DOTALL)
    assert match, "explain-trade query not found in docs/04-database-schema.md"
    return match.group(1)


async def test_explain_trade_reconstructs_the_whole_chain(session: AsyncSession) -> None:
    snapshot_id = await seed_catalog(session)
    version_id, account = await seed_lab_subject(session, "demo_sma_fast")
    trade_id = await insert_closed_trade(
        session,
        instance_id="demo_sma_fast",
        version_id=version_id,
        account=account,
        net_pnl=Decimal("496.25"),
        catalog_snapshot_id=snapshot_id,
    )
    signal_id = (
        await session.execute(select(TradeRow.entry_signal_id).where(TradeRow.id == trade_id))
    ).scalar_one()
    decision_id = uuid7()
    await session.execute(
        insert(RiskDecisionRow).values(
            id=decision_id,
            signal_id=signal_id,
            account_id=account.account_id,
            strategy_instance_id="demo_sma_fast",
            account_config_version_id=account.config_version_id,
            decided_at=T0,
            approved=True,
            rule_results=[{"rule": "max_open_positions", "passed": True}],
            account_state={"balance": "50000"},
            quote={"bid": "2649.9", "ask": "2650.1"},
            approved_qty=Decimal("0.25"),
            correlation_id=new_correlation_id(),
        )
    )
    await session.execute(
        insert(WebhookEventRow).values(
            id=uuid7(),
            received_at=T0,
            source_ip="52.89.214.238",
            body_sha256="ab" * 32,
            strategy_instance_id="demo_sma_fast",
            status="ACCEPTED",
            signal_id=signal_id,
            processing_ms=4,
            correlation_id=new_correlation_id(),
        )
    )
    entry_order, exit_order = uuid7(), uuid7()
    for order_id, purpose, side, decision, at in (
        (entry_order, "ENTRY", "BUY", decision_id, T0),
        (exit_order, "TAKE_PROFIT", "SELL", None, T0 + timedelta(hours=1)),
    ):
        await session.execute(
            insert(OrderRow).values(
                id=order_id,
                client_order_id=f"kt-{order_id}",
                account_id=account.account_id,
                strategy_instance_id="demo_sma_fast",
                trade_id=trade_id,
                signal_id=signal_id,
                risk_decision_id=decision,
                purpose=purpose,
                mode="PAPER",
                venue="generic_mt5_cfd",
                instrument="XAUUSD",
                venue_symbol="XAUUSD",
                side=side,
                order_type="MARKET",
                qty=Decimal("0.25"),
                status="FILLED",
                filled_qty=Decimal("0.25"),
                created_at=at,
                correlation_id=new_correlation_id(),
            )
        )
        await session.execute(
            insert(FillRow).values(
                id=uuid7(),
                order_id=order_id,
                account_id=account.account_id,
                ts=at,
                qty=Decimal("0.25"),
                price=Decimal("2650.10") if purpose == "ENTRY" else Decimal("2670.00"),
                liquidity="TAKER",
                spread_cost=Decimal("2.50"),
                slippage=Decimal("0.05"),
            )
        )

    rows = (await session.execute(text(documented_query()), {"trade_id": trade_id})).mappings()
    steps = list(rows)
    assert [s["purpose"] for s in steps] == ["ENTRY", "TAKE_PROFIT"]
    first = steps[0]
    assert first["strategy_instance_id"] == "demo_sma_fast"
    assert first["definition_id"] == "demo_sma_cross"
    assert first["account_config_version"] == 1
    assert first["catalog_fingerprint"] == "fp-base"
    assert first["approved"] is True
    assert str(first["source_ip"]) == "52.89.214.238"
    assert first["fill_price"] == Decimal("2650.10")
    assert steps[1]["net_pnl"] == Decimal("496.25")
