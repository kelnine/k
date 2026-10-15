"""Sign-in rate limiting and lockout.

* **Per username:** ``max_failures`` failed sign-ins within ``window`` lock the
  username until ``window`` has passed since the last failure. Unknown
  usernames are counted exactly like real ones, so a lockout reveals nothing.
* **Per client address:** ``max_failures_per_ip`` failed sign-ins (any
  usernames) within ``window`` block that address for the rest of the window,
  which stops password spraying across many usernames.

A successful sign-in clears the username's failures. State lives in the API
process: it resets on restart and is not shared between replicas (the
dashboard runs one API replica behind Caddy). Memory is bounded by pruning
expired entries and capping the number of tracked keys.
"""

from collections import deque
from datetime import datetime, timedelta

MAX_TRACKED_KEYS = 10_000


class LoginLimiter:
    def __init__(
        self,
        *,
        max_failures: int,
        max_failures_per_ip: int,
        window: timedelta,
    ) -> None:
        self.max_failures = max_failures
        self.max_failures_per_ip = max_failures_per_ip
        self.window = window
        self._users: dict[str, deque[datetime]] = {}
        self._addresses: dict[str, deque[datetime]] = {}

    def blocked_until(self, username: str, address: str, now: datetime) -> datetime | None:
        """When sign-in attempts for ``username`` from ``address`` are possible again."""
        until = []
        failures = self._recent(self._users, _user_key(username), now)
        if len(failures) >= self.max_failures:
            until.append(failures[-1] + self.window)
        failures = self._recent(self._addresses, address, now)
        if len(failures) >= self.max_failures_per_ip:
            until.append(failures[0] + self.window)
        return max(until) if until else None

    def record_failure(self, username: str, address: str, now: datetime) -> bool:
        """Count a failed sign-in; ``True`` when it locks the username."""
        counts = []
        for book, key in ((self._users, _user_key(username)), (self._addresses, address)):
            failures = self._recent(book, key, now)
            failures.append(now)
            book[key] = failures
            counts.append(len(failures))
            if len(book) > MAX_TRACKED_KEYS:
                self._prune(book, now)
        return counts[0] == self.max_failures

    def record_success(self, username: str) -> None:
        self._users.pop(_user_key(username), None)

    def _recent(self, book: dict[str, deque[datetime]], key: str, now: datetime) -> deque[datetime]:
        failures = book.get(key, deque())
        while failures and failures[0] <= now - self.window:
            failures.popleft()
        if not failures:
            book.pop(key, None)
        return failures

    def _prune(self, book: dict[str, deque[datetime]], now: datetime) -> None:
        for key in list(book):
            self._recent(book, key, now)
        while len(book) > MAX_TRACKED_KEYS:  # still full of fresh entries: drop the oldest
            oldest = min(book, key=lambda k: book[k][-1])
            del book[oldest]


def _user_key(username: str) -> str:
    return username.strip().lower()[:128]
