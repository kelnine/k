"""Pine-compatible technical indicators used by strategy plug-ins.

Pure numpy functions that reproduce TradingView's ``ta.*`` semantics exactly
(e.g. ``ta.rma``/``ta.ema`` seeded with an SMA, ``ta.atr`` built on RMA), so a
ported Pine strategy produces the same signals as the original.

Status: scaffold (Phase 1). Implemented in Phase 3.
"""
