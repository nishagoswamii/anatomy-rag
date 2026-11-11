"""In-memory abuse and spend protection for the public demo.

These counters reset when the process restarts, so the hard spending backstop
is the spend limit configured in the Anthropic Console, not this module.
"""

from __future__ import annotations

import threading
import time
from collections import defaultdict, deque
from datetime import UTC, datetime

# Reserved per request before the answer streams, then corrected to the real
# cost. A request the client abandons mid-stream keeps its reservation.
ESTIMATED_COST_USD = 0.05


class RateLimiter:
    def __init__(self, per_minute: int, per_day: int, clock=time.monotonic):
        self.per_minute = per_minute
        self.per_day = per_day
        self.clock = clock
        self._hits: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def check(self, key: str) -> str | None:
        """Record a request. Returns None if allowed, else the limit that was hit."""
        now = self.clock()
        with self._lock:
            hits = self._hits[key]
            while hits and now - hits[0] > 86400:
                hits.popleft()
            if len(hits) >= self.per_day:
                return "day"
            if sum(1 for t in hits if now - t <= 60) >= self.per_minute:
                return "minute"
            hits.append(now)
            return None


class DailyBudget:
    def __init__(self, limit_usd: float, today=lambda: datetime.now(UTC).date()):
        self.limit_usd = limit_usd
        self.today = today
        self._day = today()
        self._spent = 0.0
        self._lock = threading.Lock()

    def _roll(self) -> None:
        if self.today() != self._day:
            self._day, self._spent = self.today(), 0.0

    @property
    def spent(self) -> float:
        with self._lock:
            self._roll()
            return self._spent

    def reserve(self, amount: float = ESTIMATED_COST_USD) -> bool:
        with self._lock:
            self._roll()
            if self._spent + amount > self.limit_usd:
                return False
            self._spent += amount
            return True

    def settle(self, reserved: float, actual: float) -> None:
        with self._lock:
            self._roll()
            self._spent = max(0.0, self._spent - reserved + actual)
