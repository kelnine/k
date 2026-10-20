"""Strategy plug-ins — one sub-package per ``strategy_id``.

Each strategy lives in its own folder (``strategies/<strategy_id>/``) with
its code, default parameters, original Pine source and tests, and is
discovered automatically at start-up. Adding a strategy never requires a
change anywhere else.

Sandbox (enforced by import-linter): code here may import ``core``,
``strategy_engine``, ``indicators`` and ``marketdata`` types only — never
brokers, execution, risk, storage or the API.
"""
