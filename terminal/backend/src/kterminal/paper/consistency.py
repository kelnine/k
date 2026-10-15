"""Book/account consistency: does each strategy's theoretical book agree with its account?

The theoretical book resolves an instance's orders with its account's own rules — the
same base bars, bid/ask, slippage and tick rounding (``kterminal.strategy_engine.fills``)
— so the position a strategy sees (``ctx.position``, ``ctx.pending_entry``) is the one
its account holds, unless the account refused something the book accepted: an entry
refused for risk reasons (sizing, limits, a closed account), or a kill switch. This
module checks that, after every batch, per instance, instrument and account:

* the position: held or not, direction, entry price, stop, target, exiting at the next
  open;
* the resting entry: present or not, direction, order type and (LIMIT/STOP) price.

A batch on which the two differ is a *divergent* observation; consecutive divergent
batches of one instance, instrument and account form an *episode*. An episode is
*explained* when the account refused that instance's latest entry on the symbol
(``PaperAccount.entry_rejects``, its decision code) or a kill switch covers the account
(``KILL_SWITCH``); anything else is a bug to look at. Each episode is logged when it
starts (``lab.book_divergence``: a warning when unexplained) and when it ends
(``lab.book_divergence_resolved``); the run summary keeps the counts and the first
episodes (:meth:`ConsistencyReport.summary`).
"""

from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

from kterminal.core.enums import OrderType
from kterminal.observability.logging import get_logger
from kterminal.paper.account import PaperAccount
from kterminal.strategy_engine.model import BookState

_log = get_logger("kterminal.paper.lab")

MAX_EXAMPLES = 20

POSITION = "POSITION"  # one side holds a position the other does not, or the other way
ENTRY_PRICE = "ENTRY_PRICE"
STOP = "STOP"
TARGET = "TARGET"
EXITING = "EXITING"  # one side closes the position at the next open, the other does not
PENDING_ENTRY = "PENDING_ENTRY"  # resting entries differ (presence, direction, type, price)


@dataclass(frozen=True, slots=True)
class Divergence:
    """The first batch of an episode: what the book and the account held."""

    instance_id: str
    instrument: str
    account_id: UUID
    at: datetime
    kinds: tuple[str, ...]
    book: dict[str, Any]
    account: dict[str, Any]
    explained_by: str | None

    def document(self) -> dict[str, Any]:
        return {
            "instance_id": self.instance_id,
            "instrument": self.instrument,
            "account_id": str(self.account_id),
            "at": self.at.isoformat(),
            "kinds": list(self.kinds),
            "book": _plain(self.book),
            "account": _plain(self.account),
            "explained_by": self.explained_by,
        }


@dataclass
class _Episode:
    first: Divergence
    batches: int = 1


@dataclass
class ConsistencyReport:
    checks: int = 0  # (instance, instrument, account) comparisons made
    divergent: int = 0  # … of which differed
    episodes: int = 0
    unexplained_episodes: int = 0
    divergent_by_instance: Counter[str] = field(default_factory=Counter)
    episodes_by_instance: Counter[str] = field(default_factory=Counter)
    examples: list[Divergence] = field(default_factory=list)
    _open: dict[tuple[str, str, UUID], _Episode] = field(default_factory=dict)

    def observe(self, instance_id: str, account: PaperAccount, state: BookState) -> None:
        """Compare one instrument's book (after a batch) with the instance's account."""
        self.checks += 1
        symbol = state.instrument
        key = (instance_id, symbol, account.account_id)
        book, held = _book_document(state), _account_document(account, symbol, state.time)
        kinds = _differences(book, held)
        episode = self._open.get(key)
        if not kinds:
            if episode is not None:
                del self._open[key]
                _log.info(
                    "lab.book_divergence_resolved",
                    instance=instance_id,
                    instrument=symbol,
                    account_id=str(account.account_id),
                    at=state.time.isoformat(),
                    batches=episode.batches,
                )
            return
        self.divergent += 1
        self.divergent_by_instance[instance_id] += 1
        if episode is not None:
            episode.batches += 1
            return
        divergence = Divergence(
            instance_id=instance_id,
            instrument=symbol,
            account_id=account.account_id,
            at=state.time,
            kinds=kinds,
            book=book,
            account=held,
            explained_by=_explanation(account, symbol),
        )
        self._open[key] = _Episode(divergence)
        self.episodes += 1
        self.episodes_by_instance[instance_id] += 1
        if divergence.explained_by is None:
            self.unexplained_episodes += 1
        if len(self.examples) < MAX_EXAMPLES:
            self.examples.append(divergence)
        log = _log.info if divergence.explained_by is not None else _log.warning
        log("lab.book_divergence", **divergence.document())

    def instance_counts(self, instance_id: str) -> dict[str, int]:
        """This instance's divergent batches and episodes (for the runtime status)."""
        return {
            "divergent_batches": self.divergent_by_instance[instance_id],
            "episodes": self.episodes_by_instance[instance_id],
            "open": sum(1 for key in self._open if key[0] == instance_id),
        }

    def summary(self) -> dict[str, Any]:
        """The report as plain JSON (stored in ``runs.summary["consistency"]``)."""
        return {
            "checks": self.checks,
            "divergent": self.divergent,
            "episodes": self.episodes,
            "unexplained_episodes": self.unexplained_episodes,
            "open_episodes": len(self._open),
            "by_instance": {
                instance: {
                    "divergent_batches": self.divergent_by_instance[instance],
                    "episodes": self.episodes_by_instance[instance],
                }
                for instance in sorted(self.episodes_by_instance)
            },
            "examples": [d.document() for d in self.examples],
        }


def _plain(value: Any) -> Any:
    """Decimals as text, recursively (the documents compare numerically, store as JSON)."""
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, dict):
        return {k: _plain(v) for k, v in value.items()}
    return value


def _book_document(state: BookState) -> dict[str, Any]:
    position, pending = state.position, state.pending_entry
    return {
        "position": None
        if position is None
        else {
            "direction": position.direction.value,
            "entry_price": position.entry_price,
            "stop": position.stop_loss,
            "target": position.take_profit,
            "exiting": state.exiting,
        },
        "pending_entry": None
        if pending is None
        else {
            "direction": pending.direction.value,
            "order_type": pending.order_type.value,
            "price": None if pending.order_type is OrderType.MARKET else pending.entry,
        },
    }


def _account_document(account: PaperAccount, symbol: str, at: datetime) -> dict[str, Any]:
    position = account.positions.get(symbol)
    pending = account.pending_entries.get(symbol)
    if account.entry_used_up(symbol, at):
        pending = None  # the book expired it at this close; the account drops it next bar
    trade = position.trade if position is not None else None
    order = pending.signal if pending is not None else None
    return {
        "position": None
        if trade is None
        else {
            "direction": trade.direction.value,
            "entry_price": trade.entry_price,
            "stop": trade.current_stop,
            "target": trade.current_target,
            "exiting": symbol in account.pending_exits,
        },
        "pending_entry": None
        if order is None or order.signal.direction is None
        else {
            "direction": order.signal.direction.value,
            "order_type": order.order_type.value,
            "price": None if order.order_type is OrderType.MARKET else order.entry,
        },
    }


def _differences(book: dict[str, Any], account: dict[str, Any]) -> tuple[str, ...]:
    kinds: list[str] = []
    mine, theirs = book["position"], account["position"]
    if mine is None or theirs is None or mine["direction"] != theirs["direction"]:
        if mine != theirs:
            kinds.append(POSITION)
    else:
        for name, kind in (
            ("entry_price", ENTRY_PRICE),
            ("stop", STOP),
            ("target", TARGET),
            ("exiting", EXITING),
        ):
            if mine[name] != theirs[name]:
                kinds.append(kind)
    if book["pending_entry"] != account["pending_entry"]:
        kinds.append(PENDING_ENTRY)
    return tuple(kinds)


def _explanation(account: PaperAccount, symbol: str) -> str | None:
    if account.entry_halt is not None:
        return "KILL_SWITCH"
    return account.entry_rejects.get(symbol)


__all__ = [
    "ENTRY_PRICE",
    "EXITING",
    "MAX_EXAMPLES",
    "PENDING_ENTRY",
    "POSITION",
    "STOP",
    "TARGET",
    "ConsistencyReport",
    "Divergence",
]
