"""Account settings for lab / paper accounts.

Every strategy instance gets its own account built from these settings
(defaults come from ``terminal/config/lab.yaml``). The whole settings object
is hashed into an *account configuration version*; risk decisions and trades
record the version they were made under.
"""

from decimal import Decimal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from kterminal.core.canonical import canonical_data, canonical_json
from kterminal.core.enums import TradingMode

DEFAULT_STARTING_BALANCE = Decimal("50000")
MONEY_QUANTUM = Decimal("0.0001")  # account money is stored with 4 decimal places


class AccountSettings(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    starting_balance: Decimal = Field(default=DEFAULT_STARTING_BALANCE, gt=0)
    currency: str = "USD"
    mode: TradingMode = TradingMode.PAPER
    venue_profile: str = "lab_default"
    risk_per_trade_pct: Decimal = Field(default=Decimal("0.5"), gt=0, le=5)
    max_open_positions: int = Field(default=1, ge=1, le=100)
    trading_day: str = Field(
        default="ny_1700", description="Trading-day rule for daily P&L (e.g. 17:00 New York)"
    )
    stablecoin_usd_rate: Decimal = Field(
        default=Decimal(1), gt=0, description="Assumed USD value of 1 USDT/USDC"
    )

    @field_validator("mode")
    @classmethod
    def _simulated_only(cls, value: TradingMode) -> TradingMode:
        if value not in (TradingMode.PAPER, TradingMode.BACKTEST):
            raise ValueError(
                f"{value} accounts are not available yet: only PAPER and BACKTEST are supported"
            )
        return value

    @field_validator("starting_balance")
    @classmethod
    def _storable_balance(cls, value: Decimal) -> Decimal:
        # The ledger stores money with 4 decimals: a balance with more would be rounded on
        # the way in, so the simulation and the stored deposit would disagree.
        if value != value.quantize(MONEY_QUANTUM):
            raise ValueError("starting_balance can have at most 4 decimal places")
        return value

    @field_validator("currency")
    @classmethod
    def _currency(cls, value: str) -> str:
        if not value.isalnum() or not value.isupper():
            raise ValueError(f"invalid currency {value!r}")
        return value

    def document(self) -> dict[str, object]:
        """JSON-safe, canonical representation used for hashing and storage: numbers are
        written without redundant zeros, so ``50000`` and ``50000.00`` are the same."""
        data: dict[str, object] = canonical_data(self.model_dump())
        return data

    def document_json(self) -> str:
        """Canonical string form (equal settings ⇔ equal strings)."""
        return canonical_json(self.document())

    @property
    def display_name_prefix(self) -> str:
        """e.g. ``Paper 50K`` or ``Paper 100K``."""
        amount = self.starting_balance
        if amount >= 1000 and amount % 1000 == 0:
            label = f"{amount / 1000:.0f}K"
        else:
            label = f"{amount:,.2f}"
        return f"{self.mode.value.title()} {label}"
