"""Per-process service container."""

from dataclasses import dataclass

from kterminal.config.settings import Settings
from kterminal.core.clock import Clock, SystemClock
from kterminal.core.events import EventBus, InMemoryEventBus
from kterminal.db.session import Database


@dataclass(slots=True)
class Container:
    """Long-lived services shared by one process.

    Grows phase by phase (strategy registry, risk engine, execution engine,
    broker adapters, notifiers …); modules receive what they need from here
    instead of constructing their own dependencies.
    """

    settings: Settings
    clock: Clock
    db: Database
    events: EventBus

    @classmethod
    def build(cls, settings: Settings, *, role: str) -> "Container":
        return cls(
            settings=settings,
            clock=SystemClock(),
            db=Database(settings.database, application_name=f"{settings.service_name}-{role}"),
            events=InMemoryEventBus(),
        )

    async def aclose(self) -> None:
        await self.db.dispose()
