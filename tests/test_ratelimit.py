"""Unit tests for :mod:`occfix.ratelimit` driven by a deterministic fake clock."""

from __future__ import annotations

import threading

import pytest

from occfix.config import RateLimitConfig
from occfix.ratelimit import AdaptiveRateLimiter, TokenBucket


class FakeClock:
    """Mutable monotonic clock whose ``sleep`` simply advances virtual time."""

    def __init__(self, start: float = 0.0) -> None:
        self.now = start

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.now += seconds


def make_bucket(rate: float, capacity: float | None = None) -> tuple[TokenBucket, FakeClock]:
    clock = FakeClock()
    bucket = TokenBucket(rate, capacity, time_func=clock.time, sleep_func=clock.sleep)
    return bucket, clock


def test_capacity_defaults_to_max_of_one_and_rate() -> None:
    slow, _ = make_bucket(0.2)
    assert slow.try_acquire(1.0) is True  # capacity floored at 1.0
    assert slow.try_acquire(0.001) is False

    fast, _ = make_bucket(5.0)
    assert sum(fast.try_acquire(1.0) for _ in range(5)) == 5
    assert fast.try_acquire(1.0) is False


def test_burst_up_to_capacity_then_blocks() -> None:
    bucket, _ = make_bucket(2.0, capacity=3.0)
    assert bucket.try_acquire(1.0) is True
    assert bucket.try_acquire(1.0) is True
    assert bucket.try_acquire(1.0) is True
    assert bucket.try_acquire(1.0) is False


def test_refill_over_time() -> None:
    bucket, clock = make_bucket(2.0, capacity=2.0)
    assert bucket.try_acquire(2.0) is True
    assert bucket.try_acquire(1.0) is False

    clock.now += 0.5  # 0.5s * 2/s = 1 token
    assert bucket.try_acquire(1.0) is True
    assert bucket.try_acquire(0.1) is False


def test_refill_is_capped_at_capacity() -> None:
    bucket, clock = make_bucket(1.0, capacity=2.0)
    assert bucket.try_acquire(2.0) is True
    clock.now += 100.0  # would overflow if uncapped
    assert bucket.try_acquire(2.0) is True
    assert bucket.try_acquire(0.1) is False


def test_try_acquire_partial_tokens() -> None:
    bucket, _ = make_bucket(10.0, capacity=1.0)
    assert bucket.try_acquire(0.5) is True
    assert bucket.try_acquire(0.5) is True
    assert bucket.try_acquire(0.5) is False


def test_acquire_blocks_and_returns_wait_time() -> None:
    bucket, clock = make_bucket(2.0, capacity=1.0)
    assert bucket.acquire(1.0) == 0.0  # first token is free

    waited = bucket.acquire(1.0)  # needs 1 token at 2/s -> 0.5s
    assert waited == pytest.approx(0.5)
    assert clock.now == pytest.approx(0.5)


def test_acquire_waits_for_multiple_tokens() -> None:
    bucket, clock = make_bucket(4.0, capacity=2.0)
    assert bucket.acquire(2.0) == 0.0
    waited = bucket.acquire(2.0)  # need 2 tokens at 4/s -> 0.5s
    assert waited == pytest.approx(0.5)
    assert clock.now == pytest.approx(0.5)


def test_set_rate_changes_refill_speed() -> None:
    bucket, clock = make_bucket(1.0, capacity=1.0)
    assert bucket.try_acquire(1.0) is True

    bucket.set_rate(10.0)
    assert bucket.rate == 10.0
    clock.now += 0.1  # 0.1s * 10/s = 1 token
    assert bucket.try_acquire(1.0) is True


def test_set_rate_applies_old_rate_before_switch() -> None:
    bucket, clock = make_bucket(1.0, capacity=5.0)
    assert bucket.try_acquire(5.0) is True
    clock.now += 2.0  # accrue 2 tokens at the old rate of 1/s
    bucket.set_rate(100.0)
    assert bucket.try_acquire(2.0) is True
    assert bucket.try_acquire(0.1) is False  # nothing extra credited at new rate


def test_acquire_thread_safe_under_concurrency() -> None:
    bucket, _ = make_bucket(1000.0, capacity=1000.0)
    results: list[float] = []
    lock = threading.Lock()

    def worker() -> None:
        waited = bucket.acquire(1.0)
        with lock:
            results.append(waited)

    threads = [threading.Thread(target=worker) for _ in range(100)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert len(results) == 100
    assert bucket.try_acquire(1.0) is True  # 900 tokens remain


def _adaptive_limiter(**overrides: object) -> tuple[AdaptiveRateLimiter, FakeClock]:
    clock = FakeClock()
    cfg = RateLimitConfig(
        mode=str(overrides.get("mode", "adaptive")),
        max_calls_per_sec=float(overrides.get("max_calls_per_sec", 2.0)),
        min_calls_per_sec=float(overrides.get("min_calls_per_sec", 0.2)),
    )
    limiter = AdaptiveRateLimiter(
        cfg,
        time_func=clock.time,
        sleep_func=clock.sleep,
        additive_step=float(overrides.get("additive_step", 0.1)),
        multiplicative_factor=float(overrides.get("multiplicative_factor", 0.5)),
    )
    return limiter, clock


def test_adaptive_starts_at_max() -> None:
    limiter, _ = _adaptive_limiter(max_calls_per_sec=2.0)
    assert limiter.current_rate == 2.0


def test_adaptive_increase_capped_at_max() -> None:
    limiter, _ = _adaptive_limiter(max_calls_per_sec=2.0, additive_step=0.5)
    # Already at ceiling; success should not exceed max.
    limiter.on_success()
    assert limiter.current_rate == 2.0

    limiter.on_throttle()  # 2.0 -> 1.0
    assert limiter.current_rate == pytest.approx(1.0)
    limiter.on_success()  # 1.0 -> 1.5
    assert limiter.current_rate == pytest.approx(1.5)
    limiter.on_success()  # 1.5 -> 2.0 (capped)
    assert limiter.current_rate == pytest.approx(2.0)
    limiter.on_success()  # stays at max
    assert limiter.current_rate == pytest.approx(2.0)


def test_adaptive_decrease_floored_at_min() -> None:
    limiter, _ = _adaptive_limiter(
        max_calls_per_sec=8.0, min_calls_per_sec=1.0, multiplicative_factor=0.5
    )
    limiter.on_throttle()  # 8 -> 4
    assert limiter.current_rate == pytest.approx(4.0)
    limiter.on_throttle()  # 4 -> 2
    assert limiter.current_rate == pytest.approx(2.0)
    limiter.on_throttle()  # 2 -> 1 (floor)
    assert limiter.current_rate == pytest.approx(1.0)
    limiter.on_throttle()  # stays at floor
    assert limiter.current_rate == pytest.approx(1.0)


def test_adaptive_rate_change_affects_bucket() -> None:
    limiter, clock = _adaptive_limiter(
        max_calls_per_sec=10.0, min_calls_per_sec=0.1, multiplicative_factor=0.5
    )
    # Drain the initial burst (capacity == max rate == 10 tokens).
    assert limiter.acquire(10.0) == 0.0
    limiter.on_throttle()  # rate 10 -> 5
    assert limiter.current_rate == pytest.approx(5.0)
    waited = limiter.acquire(5.0)  # 5 tokens at 5/s -> 1.0s
    assert waited == pytest.approx(1.0)
    assert clock.now == pytest.approx(1.0)


def test_fixed_mode_never_changes_rate() -> None:
    limiter, _ = _adaptive_limiter(mode="fixed", max_calls_per_sec=3.0)
    assert limiter.current_rate == 3.0
    limiter.on_success()
    limiter.on_throttle()
    limiter.on_success()
    assert limiter.current_rate == 3.0


def test_fixed_mode_acquire_uses_max_rate() -> None:
    limiter, clock = _adaptive_limiter(mode="fixed", max_calls_per_sec=2.0)
    assert limiter.acquire(2.0) == 0.0  # capacity == 2
    waited = limiter.acquire(1.0)  # 1 token at 2/s -> 0.5s
    assert waited == pytest.approx(0.5)
    assert clock.now == pytest.approx(0.5)
