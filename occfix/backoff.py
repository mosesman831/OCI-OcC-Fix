"""Retry delay computation keyed off the attempt outcome classification.

:class:`BackoffPolicy` turns an :class:`~occfix.models.AttemptResult` into a
concrete sleep duration using the tunables in
:class:`~occfix.config.RetryConfig`. Randomness flows through an injectable
:class:`random.Random` so callers (and tests) can make jitter deterministic by
seeding.
"""

from __future__ import annotations

import random

from occfix.config import RetryConfig
from occfix.models import AttemptResult


class BackoffPolicy:
    """Compute per-outcome retry delays with jittered backoff strategies."""

    def __init__(self, retry: RetryConfig, rng: random.Random | None = None) -> None:
        self.retry = retry
        self.rng = rng if rng is not None else random.Random()

    def initial(self) -> float:
        """Return the seed delay to use before the first backoff step."""

        return self.retry.initial_retry_interval

    def next_delay(
        self,
        result: AttemptResult,
        prev_delay: float,
        retry_after: float | None = None,
    ) -> float:
        """Return the delay (seconds) to wait before the next attempt."""

        retry = self.retry

        if result is AttemptResult.CAPACITY:
            delay = self.rng.uniform(
                retry.min_interval, retry.min_interval + retry.capacity_jitter_cap
            )
        elif result is AttemptResult.THROTTLED:
            upper = max(prev_delay, retry.min_interval) * 3
            delay = min(retry.throttle_backoff_cap, self.rng.uniform(retry.min_interval, upper))
            if retry_after is not None:
                delay = max(retry_after, delay)
            delay = max(delay, retry.min_interval)
        elif result is AttemptResult.TRANSIENT:
            base = min(
                retry.max_interval,
                max(prev_delay, retry.initial_retry_interval) * retry.backoff_factor,
            )
            delay = self.rng.uniform(retry.min_interval, base)
        else:
            # SUCCESS, AUTH_ERROR, FATAL: no point waiting.
            delay = 0.0

        return max(0.0, delay)
