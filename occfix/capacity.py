"""Adaptive capacity heatmap: learn which ADs (and hours) yield capacity.

The engine sweeps a set of availability domains looking for host capacity. This
module records the outcome of each attempt and turns that history into a
weighted, best-first ordering so the sweep favours ADs that have recently given
capacity, while still occasionally exploring under-sampled ones.
"""

from __future__ import annotations

import datetime
import random
from collections.abc import Callable

from occfix.models import AttemptResult

# Additive (Laplace) smoothing so an AD with no history scores at the neutral
# prior of 0.5 instead of a degenerate 0 or 1.
_ALPHA = 1.0

# Outcomes that carry a capacity signal. Everything else (THROTTLED, AUTH_ERROR,
# TRANSIENT, FATAL) tells us nothing about whether capacity exists.
_POSITIVE = AttemptResult.SUCCESS
_NEGATIVE = AttemptResult.CAPACITY


def _default_clock() -> datetime.datetime:
    return datetime.datetime.now()


def _empty_counts() -> dict[str, float]:
    return {"pos": 0.0, "neg": 0.0, "other": 0.0}


class CapacityHeatmap:
    """Learns per-AD (and per-hour) capacity likelihood from attempt outcomes."""

    def __init__(
        self,
        *,
        explore_ratio: float = 0.2,
        rng: random.Random | None = None,
        clock: Callable[[], datetime.datetime] | None = None,
    ) -> None:
        self.explore_ratio = explore_ratio
        self._rng = rng or random.Random()
        self._clock = clock or _default_clock
        self._totals: dict[str, dict[str, float]] = {}
        self._hourly: dict[str, dict[int, dict[str, float]]] = {}

    def record(self, ad: str, result: AttemptResult) -> None:
        """Fold one attempt outcome into the per-AD and per-hour counters."""
        hour = self._clock().hour
        totals = self._totals.setdefault(ad, _empty_counts())
        hourly = self._hourly.setdefault(ad, {}).setdefault(hour, _empty_counts())
        if result is _POSITIVE:
            key = "pos"
        elif result is _NEGATIVE:
            key = "neg"
        else:
            key = "other"
        totals[key] += 1.0
        hourly[key] += 1.0

    def score(self, ad: str) -> float:
        """Smoothed likelihood of getting capacity from ``ad`` right now (~[0,1])."""
        hour = self._clock().hour
        bucket = self._hourly.get(ad, {}).get(hour)
        if not bucket or (bucket["pos"] + bucket["neg"]) == 0.0:
            bucket = self._totals.get(ad)
        return self._bucket_score(bucket)

    def order(self, ads: list[str]) -> list[str]:
        """Return ``ads`` best-first, with epsilon-greedy exploration."""
        if self._rng.random() < self.explore_ratio:
            explored = list(ads)
            self._rng.shuffle(explored)
            return explored
        return sorted(ads, key=self.score, reverse=True)

    def to_dict(self) -> dict:
        """Serialize learned counters to a JSON-friendly dict."""
        return {
            "explore_ratio": self.explore_ratio,
            "totals": {ad: dict(counts) for ad, counts in self._totals.items()},
            "hourly": {
                ad: {str(hour): dict(counts) for hour, counts in hours.items()}
                for ad, hours in self._hourly.items()
            },
        }

    @classmethod
    def from_dict(cls, data: dict) -> CapacityHeatmap:
        """Rebuild a heatmap from :meth:`to_dict` output."""
        heatmap = cls(explore_ratio=data.get("explore_ratio", 0.2))
        heatmap._totals = {
            ad: {**_empty_counts(), **counts} for ad, counts in data.get("totals", {}).items()
        }
        heatmap._hourly = {
            ad: {int(hour): {**_empty_counts(), **counts} for hour, counts in hours.items()}
            for ad, hours in data.get("hourly", {}).items()
        }
        return heatmap

    @staticmethod
    def _bucket_score(bucket: dict[str, float] | None) -> float:
        if not bucket:
            return 0.5
        pos, neg = bucket["pos"], bucket["neg"]
        return (pos + _ALPHA) / (pos + neg + 2.0 * _ALPHA)
