"""Module 3 — Forward / Paper Trading Engine.

Virtual prop-style accounts (one independent $50,000 account per strategy
instance) with simulated fills, the strategy lab that runs instances side by
side, and forward sessions that run the lab on live market data.

``account``      paper accounts: decisions, sizing, fills, ledger
``lab``          the strategy lab (simulations and the incremental core of forward sessions)
``store``, ``pg_store``  where the lab records what happened (memory / PostgreSQL)
``feed``         the live minute feed polled from market-data providers
``forward``, ``pg_forward``  forward sessions: start, replay on restart, verification
``kill_switch``  global / account / strategy kill switches as the lab applies them
``runtime``      the long-running forward paper runtime (``kterminal paper start``, the engine)

Everything here is paper: LIVE (real-money) execution is not implemented.
"""
