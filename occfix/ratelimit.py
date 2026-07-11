"""Client-side rate limiting: a thread-safe token bucket plus an AIMD adapter.

The token bucket smooths request bursts against a configurable per-second rate.
:class:`AdaptiveRateLimiter` layers additive-increase/multiplicative-decrease on
top so the engine can back off when OCI throttles and recover afterwards. Both
clocks are injectable so tests can drive a deterministic fake clock.
"""

from __future__ import annotations

import threading
import time
from collections.abc import Callable

from occfix.config import RateLimitConfig


class TokenBucket:
    """Thread-safe token bucket refilling at ``rate`` tokens per second."""

    def __init__(
        self,
        rate: float,
        capacity: float | None = None,
        *,
        time_func: Callable[[], float] = time.monotonic,
        sleep_func: Callable[[float], None] = time.sleep,
    ) -> None:
        self._rate = float(rate)
        self._capacity = float(capacity) if capacity is not None else max(1.0, self._rate)
        self._time = time_func
        self._sleep = sleep_func
        self._tokens = self._capacity
        self._updated = self._time()
        self._lock = threading.Lock()

    def _refill_locked(self) -> None:
        now = self._time()
        elapsed = now - self._updated
        if elapsed > 0:
            self._tokens = min(self._capacity, self._tokens + elapsed * self._rate)
            self._updated = now

    def try_acquire(self, tokens: float = 1.0) -> bool:
        """Consume ``tokens`` without blocking; return whether it succeeded."""

        with self._lock:
            self._refill_locked()
            if self._tokens >= tokens:
                self._tokens -= tokens
                return True
            return False

    def acquire(self, tokens: float = 1.0) -> float:
        """Block until ``tokens`` are available; return the time waited."""

        waited = 0.0
        while True:
            with self._lock:
                self._refill_locked()
                if self._tokens >= tokens:
                    self._tokens -= tokens
                    return waited
                deficit = tokens - self._tokens
                delay = deficit / self._rate if self._rate > 0 else 0.0
            self._sleep(delay)
            waited += delay

    def set_rate(self, rate: float) -> None:
        """Update the refill rate at runtime, refilling with the old rate first."""

        with self._lock:
            self._refill_locked()
            self._rate = float(rate)

    @property
    def rate(self) -> float:
        """Current refill rate in tokens per second."""

        with self._lock:
            return self._rate


class AdaptiveRateLimiter:
    """Token bucket whose rate adapts via AIMD between the config bounds."""

    def __init__(
        self,
        config: RateLimitConfig,
        *,
        time_func: Callable[[], float] = time.monotonic,
        sleep_func: Callable[[float], None] = time.sleep,
        additive_step: float = 0.1,
        multiplicative_factor: float = 0.5,
    ) -> None:
        self._config = config
        self._additive_step = additive_step
        self._multiplicative_factor = multiplicative_factor
        self._adaptive = config.mode == "adaptive"
        self._rate = config.max_calls_per_sec
        self._bucket = TokenBucket(self._rate, time_func=time_func, sleep_func=sleep_func)
        self._lock = threading.Lock()

    def acquire(self, tokens: float = 1.0) -> float:
        """Delegate to the underlying bucket; return the time waited."""

        return self._bucket.acquire(tokens)

    def on_success(self) -> None:
        """Additively increase the rate, capped at ``max_calls_per_sec``."""

        if not self._adaptive:
            return
        with self._lock:
            self._rate = min(self._config.max_calls_per_sec, self._rate + self._additive_step)
            self._bucket.set_rate(self._rate)

    def on_throttle(self) -> None:
        """Multiplicatively decrease the rate, floored at ``min_calls_per_sec``."""

        if not self._adaptive:
            return
        with self._lock:
            self._rate = max(
                self._config.min_calls_per_sec,
                self._rate * self._multiplicative_factor,
            )
            self._bucket.set_rate(self._rate)

    @property
    def current_rate(self) -> float:
        """The current allowed rate in calls per second."""

        with self._lock:
            return self._rate
