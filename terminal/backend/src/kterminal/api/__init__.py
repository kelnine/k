"""Module 12 — Web Dashboard (backend half): REST + WebSocket API.

The React single-page app lives in ``terminal/dashboard`` (Phase 8). This
package exposes the HTTP API it talks to, plus the health endpoints, and in
Phase 6 mounts the TradingView webhook router.
"""

from kterminal.api.app import API_PREFIX, create_app

__all__ = ["API_PREFIX", "create_app"]
