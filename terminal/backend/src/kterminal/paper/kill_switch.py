"""The kill switches as the lab sees them.

:class:`KillSwitchState` is the set of *active* switches at one bar batch. The
lab applies a new state after the batch's fills and before its signals:

* every account a switch covers (``GLOBAL``, its ``ACCOUNT`` id or its
  ``STRATEGY`` instance) refuses new entries with ``KILL_SWITCH_ACTIVE`` — a
  recorded risk decision like any other rejection;
* resting entry orders of a newly covered account are cancelled
  (``cancel_orders``, on by default);
* with ``close_positions`` its open positions are flattened at the next base
  bar's open (``FLATTEN`` orders, exit reason ``KILL_SWITCH``);
* exits, stop moves and the protective brackets keep working.

The state is plain data so a forward session can record which state took
effect at which batch and apply it again, at the same batch, when it replays.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any
from uuid import UUID

from kterminal.db.repositories.kill_switches import GLOBAL_SCOPE_ID, KillSwitchRecord

KILL_SWITCH_CODE = "KILL_SWITCH_ACTIVE"
_PRECEDENCE = {"GLOBAL": 0, "ACCOUNT": 1, "STRATEGY": 2}


@dataclass(frozen=True, slots=True, order=True)
class ActiveSwitch:
    scope: str
    scope_id: str
    reason: str
    close_positions: bool = False
    cancel_orders: bool = True

    @property
    def label(self) -> str:
        return "GLOBAL" if self.scope == "GLOBAL" else f"{self.scope} {self.scope_id}"

    def document(self) -> dict[str, Any]:
        return {
            "scope": self.scope,
            "scope_id": self.scope_id,
            "reason": self.reason,
            "close_positions": self.close_positions,
            "cancel_orders": self.cancel_orders,
        }


@dataclass(frozen=True, slots=True)
class KillSwitchState:
    switches: tuple[ActiveSwitch, ...] = ()

    @classmethod
    def from_records(cls, records: Iterable[KillSwitchRecord]) -> "KillSwitchState":
        return cls(
            tuple(
                sorted(
                    ActiveSwitch(r.scope, r.scope_id, r.reason, r.close_positions, r.cancel_orders)
                    for r in records
                    if r.active
                )
            )
        )

    @classmethod
    def from_document(cls, document: Mapping[str, Any]) -> "KillSwitchState":
        return cls(
            tuple(
                sorted(
                    ActiveSwitch(
                        str(s["scope"]),
                        str(s["scope_id"]),
                        str(s.get("reason", "")),
                        bool(s.get("close_positions", False)),
                        bool(s.get("cancel_orders", True)),
                    )
                    for s in document.get("switches", ())
                )
            )
        )

    def document(self) -> dict[str, Any]:
        return {"switches": [s.document() for s in self.switches]}

    def covering(self, account_id: UUID, instance_id: str) -> list[ActiveSwitch]:
        """The active switches that cover this account, most general first."""
        hits = [
            s
            for s in self.switches
            if (s.scope == "GLOBAL" and s.scope_id == GLOBAL_SCOPE_ID)
            or (s.scope == "ACCOUNT" and s.scope_id == str(account_id))
            or (s.scope == "STRATEGY" and s.scope_id == instance_id)
        ]
        return sorted(hits, key=lambda s: _PRECEDENCE.get(s.scope, 9))

    def halt_reason(self, account_id: UUID, instance_id: str) -> str | None:
        hits = self.covering(account_id, instance_id)
        if not hits:
            return None
        first = hits[0]
        return f"{first.label} kill switch active: {first.reason}"[:500]

    def closes_positions(self, account_id: UUID, instance_id: str) -> bool:
        return any(s.close_positions for s in self.covering(account_id, instance_id))

    def cancels_orders(self, account_id: UUID, instance_id: str) -> bool:
        return any(s.cancel_orders for s in self.covering(account_id, instance_id))

    def summary(self) -> dict[str, Any]:
        """``{global, accounts, strategies}`` for the runtime status document."""
        return {
            "global": any(s.scope == "GLOBAL" for s in self.switches),
            "accounts": sorted(s.scope_id for s in self.switches if s.scope == "ACCOUNT"),
            "strategies": sorted(s.scope_id for s in self.switches if s.scope == "STRATEGY"),
        }


NO_KILL_SWITCHES = KillSwitchState()

__all__ = ["KILL_SWITCH_CODE", "NO_KILL_SWITCHES", "ActiveSwitch", "KillSwitchState"]
