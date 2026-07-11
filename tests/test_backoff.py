"""Unit tests for :mod:`occfix.backoff`.

Jitter is exercised through a seeded :class:`random.Random`, so tests assert on
bounds and trends rather than exact floats where randomness is involved.
"""

from __future__ import annotations

import random

import pytest

from occfix.backoff import BackoffPolicy
from occfix.config import RetryConfig
from occfix.models import AttemptResult


def _policy(seed: int = 1234, **overrides: float) -> BackoffPolicy:
    retry = RetryConfig(**overrides)
    return BackoffPolicy(retry, rng=random.Random(seed))


def test_initial_returns_configured_seed():
    retry = RetryConfig(initial_retry_interval=2.5)
    policy = BackoffPolicy(retry, rng=random.Random(0))
    assert policy.initial() == 2.5


def test_default_rng_is_created_when_none():
    policy = BackoffPolicy(RetryConfig())
    assert isinstance(policy.rng, random.Random)


def test_capacity_delay_within_bounds():
    retry = RetryConfig(min_interval=1.0, capacity_jitter_cap=3.0)
    policy = BackoffPolicy(retry, rng=random.Random(7))
    lo, hi = retry.min_interval, retry.min_interval + retry.capacity_jitter_cap
    for _ in range(500):
        delay = policy.next_delay(AttemptResult.CAPACITY, prev_delay=0.0)
        assert lo <= delay <= hi


def test_capacity_ignores_prev_delay():
    retry = RetryConfig(min_interval=1.0, capacity_jitter_cap=3.0)
    policy = BackoffPolicy(retry, rng=random.Random(7))
    hi = retry.min_interval + retry.capacity_jitter_cap
    for prev in (0.0, 5.0, 100.0):
        delay = policy.next_delay(AttemptResult.CAPACITY, prev_delay=prev)
        assert delay <= hi


def test_throttle_within_bounds_and_at_least_min():
    retry = RetryConfig(min_interval=1.0, throttle_backoff_cap=300.0)
    policy = BackoffPolicy(retry, rng=random.Random(99))
    prev = 4.0
    upper = min(retry.throttle_backoff_cap, max(prev, retry.min_interval) * 3)
    for _ in range(500):
        delay = policy.next_delay(AttemptResult.THROTTLED, prev_delay=prev)
        assert retry.min_interval <= delay <= upper


def test_throttle_honors_larger_retry_after():
    policy = _policy(seed=3, min_interval=1.0, throttle_backoff_cap=300.0)
    delay = policy.next_delay(AttemptResult.THROTTLED, prev_delay=2.0, retry_after=120.0)
    assert delay >= 120.0


def test_throttle_ignores_smaller_retry_after():
    retry = RetryConfig(min_interval=1.0, throttle_backoff_cap=300.0)
    policy = BackoffPolicy(retry, rng=random.Random(5))
    prev = 10.0
    upper = min(retry.throttle_backoff_cap, max(prev, retry.min_interval) * 3)
    for _ in range(200):
        delay = policy.next_delay(AttemptResult.THROTTLED, prev_delay=prev, retry_after=0.001)
        assert retry.min_interval <= delay <= upper


def test_throttle_growth_trend():
    retry = RetryConfig(min_interval=1.0, throttle_backoff_cap=1000.0)
    policy = BackoffPolicy(retry, rng=random.Random(2024))

    def mean_for(prev: float) -> float:
        samples = [policy.next_delay(AttemptResult.THROTTLED, prev_delay=prev) for _ in range(2000)]
        return sum(samples) / len(samples)

    assert mean_for(2.0) < mean_for(50.0)


def test_throttle_capped():
    retry = RetryConfig(min_interval=1.0, throttle_backoff_cap=20.0)
    policy = BackoffPolicy(retry, rng=random.Random(11))
    for _ in range(500):
        delay = policy.next_delay(AttemptResult.THROTTLED, prev_delay=10_000.0)
        assert delay <= retry.throttle_backoff_cap


def test_transient_never_exceeds_max_interval():
    retry = RetryConfig(min_interval=1.0, max_interval=60.0, backoff_factor=2.0)
    policy = BackoffPolicy(retry, rng=random.Random(42))
    prev = retry.initial_retry_interval
    for _ in range(100):
        prev = policy.next_delay(AttemptResult.TRANSIENT, prev_delay=prev)
        assert retry.min_interval <= prev <= retry.max_interval


def test_transient_exponential_growth_trend():
    retry = RetryConfig(
        min_interval=1.0, max_interval=1_000.0, backoff_factor=2.0, initial_retry_interval=1.0
    )
    policy = BackoffPolicy(retry, rng=random.Random(2025))

    def mean_for(prev: float) -> float:
        samples = [policy.next_delay(AttemptResult.TRANSIENT, prev_delay=prev) for _ in range(2000)]
        return sum(samples) / len(samples)

    assert mean_for(2.0) < mean_for(64.0)


def test_transient_growth_reaches_cap_over_iterations():
    retry = RetryConfig(min_interval=1.0, max_interval=30.0, backoff_factor=2.0)
    policy = BackoffPolicy(retry, rng=random.Random(1))
    prev = retry.initial_retry_interval
    running_max = 0.0
    for _ in range(50):
        prev = policy.next_delay(AttemptResult.TRANSIENT, prev_delay=prev)
        running_max = max(running_max, prev)
    assert running_max > retry.max_interval / 2


@pytest.mark.parametrize("result", [AttemptResult.AUTH_ERROR, AttemptResult.FATAL])
def test_auth_and_fatal_return_zero(result):
    policy = _policy()
    assert policy.next_delay(result, prev_delay=42.0, retry_after=99.0) == 0.0


def test_success_returns_zero():
    policy = _policy()
    assert policy.next_delay(AttemptResult.SUCCESS, prev_delay=42.0) == 0.0


def test_returned_delay_never_negative():
    retry = RetryConfig(min_interval=0.0, capacity_jitter_cap=0.0)
    policy = BackoffPolicy(retry, rng=random.Random(0))
    for result in AttemptResult:
        delay = policy.next_delay(result, prev_delay=0.0)
        assert delay >= 0.0


def test_determinism_with_same_seed():
    a = BackoffPolicy(RetryConfig(), rng=random.Random(777))
    b = BackoffPolicy(RetryConfig(), rng=random.Random(777))
    seq = [AttemptResult.CAPACITY, AttemptResult.THROTTLED, AttemptResult.TRANSIENT]
    prev_a = prev_b = 1.0
    for result in seq * 5:
        prev_a = a.next_delay(result, prev_delay=prev_a)
        prev_b = b.next_delay(result, prev_delay=prev_b)
        assert prev_a == prev_b


def test_different_seeds_differ():
    a = BackoffPolicy(RetryConfig(), rng=random.Random(1))
    b = BackoffPolicy(RetryConfig(), rng=random.Random(2))
    seq_a = [a.next_delay(AttemptResult.TRANSIENT, prev_delay=5.0) for _ in range(20)]
    seq_b = [b.next_delay(AttemptResult.TRANSIENT, prev_delay=5.0) for _ in range(20)]
    assert seq_a != seq_b
