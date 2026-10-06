"""Module 7 — Execution Engine.

Signal router (fan-out of one signal to every allocated account), order
manager and order state machine, position manager, bracket/stop management
and reconciliation with the broker. Accepts only ``ApprovedOrder`` objects
produced by the risk engine; risk-reducing actions (exits, flattening) are
always permitted.

Status: scaffold (Phase 1). Implemented in Phases 3 and 5.
"""
