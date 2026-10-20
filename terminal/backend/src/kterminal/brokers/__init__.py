"""Module 8 — Broker / prop-firm adapters.

One module per venue, each implementing the standard ``BrokerAdapter``
interface (``connect``, ``disconnect``, ``get_account``, ``get_positions``,
``get_orders``, ``place_order``, ``modify_order``, ``cancel_order``,
``close_position``, ``close_all``, ``get_execution_status``) and declaring its
capabilities. The application is never coupled to one broker.

Only ``execution`` (and the ``paper``/``backtest`` engines and ``runtime``
wiring that construct adapters) may import this package.

Status: scaffold (Phase 1). Simulated/paper adapters in Phases 3/5, demo in
Phase 9, prop/live in Phase 10.
"""
