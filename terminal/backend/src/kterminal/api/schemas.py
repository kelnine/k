"""Typed response (and request) bodies of the dashboard API.

Money, prices and quantities are ``Decimal`` and travel as JSON strings, so no
value is ever rounded through a binary float on the way to the browser.
Timestamps are UTC ISO-8601. Lists that can grow without bound are paginated
(:class:`Page`).
"""

from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, SecretStr

from kterminal.api.auth.users import Role


class ApiModel(BaseModel):
    model_config = ConfigDict(frozen=True)


class Page[T](ApiModel):
    items: list[T]
    total: int
    limit: int
    offset: int


# ── auth ─────────────────────────────────────────────────────────────────────
class LoginRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str = Field(min_length=1, max_length=64)
    password: SecretStr = Field(min_length=1, max_length=1024)


class UserOut(ApiModel):
    id: UUID
    username: str
    role: Role


class SessionOut(ApiModel):
    user: UserOut
    csrf_token: str
    expires_at: datetime


# ── forward runtime status (system_state 'paper.runtime') ────────────────────
class FeedStatus(ApiModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    provider: str | None = None
    last_bar_open: datetime | None = None
    lag_seconds: float | None = None
    state: str | None = None
    last_error: str | None = None


class InstanceRuntime(ApiModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    state: str | None = None
    fault: JsonValue = None
    account_id: str | None = None


class RuntimeKillSwitch(ApiModel):
    model_config = ConfigDict(frozen=True, extra="ignore", populate_by_name=True)

    global_: bool | None = Field(default=None, alias="global")
    accounts: JsonValue = None
    strategies: JsonValue = None


class RuntimeStatus(ApiModel):
    """What the forward paper runtime last reported about itself."""

    model_config = ConfigDict(frozen=True, extra="ignore")

    session_id: str | None = None
    run_id: str | None = None
    status: str | None = None
    started_at: datetime | None = None
    updated_at: datetime | None = None
    last_batch_close: datetime | None = None
    instruments: dict[str, FeedStatus] = Field(default_factory=dict)
    instances: dict[str, InstanceRuntime] = Field(default_factory=dict)
    kill_switch: RuntimeKillSwitch | None = None


class RuntimeView(ApiModel):
    present: bool  # the runtime has written a status at least once
    stale: bool  # no update within the staleness limit (or never)
    age_seconds: float | None
    stale_after_seconds: float
    status: RuntimeStatus | None
    error: str | None  # the stored status could not be read


# ── strategies ───────────────────────────────────────────────────────────────
class VersionOut(ApiModel):
    id: UUID
    config_hash: str
    definition_version: str
    code_hash: str | None
    params: dict[str, JsonValue]
    timeframe: str | None
    context_timeframes: list[str]
    instruments: list[str]
    created_at: datetime


class InstanceOut(ApiModel):
    id: str
    name: str
    description: str
    definition_id: str
    definition_name: str
    kind: str
    status: str
    enabled: bool
    tags: list[str]
    version: VersionOut | None
    versions: int
    account_id: UUID | None  # the dedicated forward account
    runtime: InstanceRuntime | None


class InstanceDetailOut(InstanceOut):
    version_history: list[VersionOut]


# ── accounts and metrics ─────────────────────────────────────────────────────
class AccountMetrics(ApiModel):
    """Appendix A metrics recomputed from recorded trades, ledger and equity snapshots."""

    starting_balance: Decimal
    balance: Decimal
    equity: Decimal
    equity_at: datetime | None
    open_pnl: Decimal | None
    net_pnl: Decimal
    return_pct: Decimal
    trades: int
    wins: int
    losses: int
    scratches: int
    win_rate: Decimal | None
    gross_profit: Decimal
    gross_loss: Decimal
    profit_factor: Decimal | None
    average_r: Decimal | None
    realized_r: Decimal
    avg_winner: Decimal | None
    avg_loser: Decimal | None
    expectancy: Decimal | None
    max_drawdown: Decimal | None
    max_drawdown_pct: Decimal | None
    open_positions: int
    low_sample: bool
    last_trade_at: datetime | None


AccountKind = Literal["FORWARD", "RUN"]


class AccountOut(ApiModel):
    id: UUID
    name: str
    kind: AccountKind  # FORWARD: an instance's dedicated account; RUN: one simulation run's
    mode: str
    broker: str
    status: str
    currency: str
    instance_id: str | None
    instance_name: str | None
    definition_id: str | None
    definition_name: str | None
    run_id: UUID | None
    run_kind: str | None
    run_name: str | None
    version: VersionOut | None
    metrics: AccountMetrics
    halted: bool  # a kill switch (global, this account or its strategy) is active
    runtime: InstanceRuntime | None
    created_at: datetime


class AccountDetailOut(AccountOut):
    config_version: int | None
    config: dict[str, JsonValue] | None
    high_water_mark: Decimal
    kill_switches: list["KillSwitchOut"]


class EquityPoint(ApiModel):
    ts: datetime
    balance: Decimal
    equity: Decimal
    open_pnl: Decimal
    drawdown: Decimal


class EquityOut(ApiModel):
    account_id: UUID
    starting_balance: Decimal
    points: list[EquityPoint]
    total_points: int
    downsampled: bool


# ── trades ───────────────────────────────────────────────────────────────────
class TradeOut(ApiModel):
    id: UUID
    account_id: UUID
    account_name: str
    instance_id: str
    strategy_version_id: UUID
    run_id: UUID | None
    mode: str
    instrument: str
    venue: str
    venue_symbol: str
    timeframe: str
    direction: str
    status: str
    qty: Decimal
    entry_requested: Decimal
    entry_price: Decimal
    entry_time: datetime
    initial_stop: Decimal
    initial_target: Decimal | None
    current_stop: Decimal | None
    current_target: Decimal | None
    exit_price: Decimal | None
    exit_time: datetime | None
    exit_reason: str | None
    initial_risk: Decimal
    gross_pnl: Decimal | None
    commission: Decimal
    swap: Decimal
    funding: Decimal
    spread_cost: Decimal
    net_pnl: Decimal | None
    r_multiple: Decimal | None
    entry_slippage: Decimal | None
    exit_slippage: Decimal | None
    mae: Decimal | None
    mfe: Decimal | None
    session: str | None


class PositionOut(TradeOut):
    """An open trade, marked at the instrument's latest recorded candle close."""

    last_price: Decimal | None
    last_price_at: datetime | None
    unrealized_pnl: Decimal | None  # before exit costs
    unrealized_r: Decimal | None


class SignalOut(ApiModel):
    id: UUID
    instance_id: str
    strategy_version_id: UUID | None
    source: str
    run_id: UUID | None
    instrument: str | None
    timeframe: str | None
    bar_time: datetime | None
    signal_time: datetime
    received_at: datetime
    action: str | None
    order_type: str
    entry: Decimal | None
    stop_loss: Decimal | None
    take_profit: Decimal | None
    risk_pct: Decimal | None
    confidence: Decimal | None
    reason: str | None
    status: str
    reject_code: str | None
    reject_detail: str | None
    metadata: dict[str, JsonValue]


class DecisionSummary(ApiModel):
    id: UUID
    account_id: UUID
    decided_at: datetime
    approved: bool
    primary_reason: str | None
    approved_qty: Decimal | None
    risk_amount: Decimal | None


class SignalLogItem(SignalOut):
    decision: DecisionSummary | None
    outcome: str  # APPROVED | REJECTED | INVALID | IGNORED | NO_DECISION
    outcome_code: str | None  # the rejection code (risk rule or signal validation)


class DecisionOut(DecisionSummary):
    requested_qty: Decimal | None
    risk_pct: Decimal | None
    rule_results: list[JsonValue]
    account_state: dict[str, JsonValue]
    quote: dict[str, JsonValue]


class OrderOut(ApiModel):
    id: UUID
    purpose: str
    side: str
    order_type: str
    qty: Decimal
    requested_price: Decimal | None
    status: str
    filled_qty: Decimal
    avg_fill_price: Decimal | None
    slippage: Decimal | None
    commission: Decimal
    reject_reason: str | None
    created_at: datetime
    submitted_at: datetime | None
    completed_at: datetime | None


class FillOut(ApiModel):
    id: UUID
    order_id: UUID
    ts: datetime
    qty: Decimal
    price: Decimal
    commission: Decimal
    liquidity: str | None
    spread_cost: Decimal
    slippage: Decimal


class TradeEventOut(ApiModel):
    id: UUID
    ts: datetime
    kind: str
    old_value: Decimal | None
    new_value: Decimal | None
    signal_id: UUID | None
    details: dict[str, JsonValue]


class LedgerEntryOut(ApiModel):
    ts: datetime
    kind: str
    amount: Decimal
    balance_after: Decimal
    note: str


class AccountConfigOut(ApiModel):
    id: UUID
    version: int
    config: dict[str, JsonValue]


class TradeExplainOut(ApiModel):
    """Everything recorded about one trade: docs/04 §4.9 "explain this trade"."""

    trade: TradeOut
    definition_id: str
    definition_name: str
    version: VersionOut
    account_config: AccountConfigOut
    catalog_fingerprint: str | None
    entry_signal: SignalOut
    entry_market_snapshot: dict[str, JsonValue]
    exit_signal: SignalOut | None
    decision: DecisionOut | None
    orders: list[OrderOut]
    fills: list[FillOut]
    events: list[TradeEventOut]
    ledger: list[LedgerEntryOut]


# ── market data ──────────────────────────────────────────────────────────────
class CandleOut(ApiModel):
    t: datetime  # bar open time
    o: Decimal
    h: Decimal
    l: Decimal  # noqa: E741 - OHLC field names
    c: Decimal
    v: Decimal | None


class TradeMarker(ApiModel):
    trade_id: UUID
    account_id: UUID
    instance_id: str
    timeframe: str
    direction: str
    status: str
    qty: Decimal
    entry_time: datetime
    entry_price: Decimal
    exit_time: datetime | None
    exit_price: Decimal | None
    exit_reason: str | None
    initial_stop: Decimal
    initial_target: Decimal | None
    current_stop: Decimal | None
    current_target: Decimal | None
    net_pnl: Decimal | None
    r_multiple: Decimal | None


class CandlesOut(ApiModel):
    instrument: str
    timeframe: str
    source: str | None  # candles.source the bars come from
    sources: list[str]  # every source holding bars of the instrument
    built_from: str | None  # the stored timeframe the bars were aggregated from
    candles: list[CandleOut]
    markers: list[TradeMarker]


class InstrumentSummary(ApiModel):
    symbol: str
    name: str | None
    asset_class: str | None
    instances: list[str]  # forward instances (current versions) that trade it
    timeframes: list[str]
    open_positions: int
    feed: FeedStatus | None
    last_candle_at: datetime | None


class InstrumentDetailOut(InstrumentSummary):
    accounts: list[AccountOut]
    positions: list[PositionOut]


# ── runs, kill switches, system ──────────────────────────────────────────────
class RunOut(ApiModel):
    id: UUID
    kind: str
    name: str
    status: str
    created_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    summary: dict[str, JsonValue] | None
    error: str | None
    instances: list[str]
    accounts: int
    signals: int
    trades: int


KillSwitchScope = Literal["GLOBAL", "ACCOUNT", "STRATEGY"]


class KillSwitchOut(ApiModel):
    scope: KillSwitchScope
    scope_id: str
    label: str  # "all trading", an account name or a strategy instance id
    active: bool
    close_positions: bool
    cancel_orders: bool
    reason: str
    changed_by: str
    changed_by_username: str | None
    changed_at: datetime


class KillSwitchEvent(ApiModel):
    seq: int
    ts: datetime
    actor: str
    action: str
    scope: str
    scope_id: str
    data: dict[str, JsonValue]


class KillSwitchesOut(ApiModel):
    switches: list[KillSwitchOut]
    history: list[KillSwitchEvent]


class KillSwitchRequest(BaseModel):
    """Activate or release a kill switch. Releasing needs the operator's password."""

    model_config = ConfigDict(extra="forbid")

    scope: KillSwitchScope
    scope_id: str = Field(default="*", min_length=1, max_length=128)
    active: bool
    reason: str = Field(min_length=3, max_length=500)
    close_positions: bool = False
    password: SecretStr | None = Field(default=None, max_length=1024)


class FaultOut(ApiModel):
    id: UUID
    ts: datetime
    component: str
    severity: str
    message: str
    strategy_instance_id: str | None
    run_id: UUID | None
    context: dict[str, JsonValue]


class ForwardSummary(ApiModel):
    accounts: int
    instances_enabled: int
    open_positions: int
    closed_trades: int
    net_pnl: Decimal
    equity: Decimal
    starting_balance: Decimal


class OverviewOut(ApiModel):
    server_time: datetime
    environment: str
    live_trading_permitted: bool
    runtime: RuntimeView
    global_halt: bool
    active_kill_switches: list[KillSwitchOut]
    forward: ForwardSummary
    recent_runs: list[RunOut]
    faults_24h: int


AccountDetailOut.model_rebuild()
