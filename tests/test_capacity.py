"""Unit tests for :mod:`occfix.capacity`."""

from __future__ import annotations

import datetime
import random

import pytest

from occfix.capacity import CapacityHeatmap
from occfix.models import AttemptResult


def make_clock(hour: int):
    """Return a clock callable pinned to a fixed hour-of-day."""
    fixed = datetime.datetime(2024, 1, 1, hour, 30, 0)

    def clock() -> datetime.datetime:
        return fixed

    return clock


@pytest.fixture
def heatmap():
    return CapacityHeatmap(explore_ratio=0.0, rng=random.Random(1234), clock=make_clock(12))


def test_unseen_ad_scores_neutral(heatmap):
    assert heatmap.score("FAKE:AD-unseen") == pytest.approx(0.5)


def test_success_scores_higher_than_capacity_misses(heatmap):
    for _ in range(10):
        heatmap.record("good", AttemptResult.SUCCESS)
    for _ in range(10):
        heatmap.record("bad", AttemptResult.CAPACITY)

    good, bad = heatmap.score("good"), heatmap.score("bad")
    assert good > 0.5 > bad
    assert good > bad


def test_non_capacity_results_are_neutral(heatmap):
    for result in (
        AttemptResult.THROTTLED,
        AttemptResult.AUTH_ERROR,
        AttemptResult.TRANSIENT,
    ):
        for _ in range(5):
            heatmap.record("noise", result)
    assert heatmap.score("noise") == pytest.approx(0.5)


def test_order_best_first_without_exploration(heatmap):
    for _ in range(8):
        heatmap.record("winner", AttemptResult.SUCCESS)
    for _ in range(8):
        heatmap.record("loser", AttemptResult.CAPACITY)

    ordered = heatmap.order(["loser", "middle", "winner"])
    assert ordered == ["winner", "middle", "loser"]


def test_exploration_can_reorder():
    hm = CapacityHeatmap(explore_ratio=1.0, rng=random.Random(7), clock=make_clock(9))
    for _ in range(5):
        hm.record("a", AttemptResult.SUCCESS)
    ads = ["a", "b", "c", "d"]
    ordered = hm.order(ads)
    assert sorted(ordered) == sorted(ads)


def test_exploration_is_deterministic_given_rng():
    ads = ["a", "b", "c", "d"]
    first = CapacityHeatmap(explore_ratio=1.0, rng=random.Random(42), clock=make_clock(3))
    second = CapacityHeatmap(explore_ratio=1.0, rng=random.Random(42), clock=make_clock(3))
    assert first.order(ads) == second.order(ads)


def test_to_dict_from_dict_round_trip_preserves_scores(heatmap):
    for _ in range(6):
        heatmap.record("x", AttemptResult.SUCCESS)
    for _ in range(3):
        heatmap.record("y", AttemptResult.CAPACITY)

    data = heatmap.to_dict()

    import json

    restored = CapacityHeatmap.from_dict(json.loads(json.dumps(data)))
    restored._clock = make_clock(12)

    for ad in ("x", "y", "unseen"):
        assert restored.score(ad) == pytest.approx(heatmap.score(ad))
    assert restored.explore_ratio == heatmap.explore_ratio


def test_hour_bucketing_influences_score():
    rng = random.Random(0)
    hm = CapacityHeatmap(explore_ratio=0.0, rng=rng, clock=make_clock(8))
    for _ in range(10):
        hm.record("ad", AttemptResult.SUCCESS)

    assert hm.score("ad") > 0.8

    hm._clock = make_clock(20)
    for _ in range(10):
        hm.record("ad", AttemptResult.CAPACITY)
    assert hm.score("ad") < 0.2

    hm._clock = make_clock(8)
    assert hm.score("ad") > 0.8


def test_current_hour_bucket_preferred_over_all_time():
    hm = CapacityHeatmap(explore_ratio=0.0, rng=random.Random(0), clock=make_clock(1))
    for _ in range(20):
        hm.record("ad", AttemptResult.CAPACITY)

    hm._clock = make_clock(2)
    for _ in range(20):
        hm.record("ad", AttemptResult.SUCCESS)

    assert hm.score("ad") > 0.8
