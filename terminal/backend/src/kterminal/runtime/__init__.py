"""Composition root.

The only place where concrete adapters (database, brokers, notifiers,
market-data providers, strategies) are chosen and wired together for each
process role. Everything below this layer depends on interfaces.
"""

from kterminal.runtime.container import Container

__all__ = ["Container"]
