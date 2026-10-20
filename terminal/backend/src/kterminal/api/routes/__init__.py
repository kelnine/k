"""HTTP routers. Each module adds its own router here as it is implemented.

``health`` is public; ``auth`` signs in and out; every other router is mounted
under ``/api/v1`` behind the session and CSRF checks (see ``kterminal.api.app``).
"""
