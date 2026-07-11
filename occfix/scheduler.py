"""Scheduling helpers: duration parsing, quiet-hours windows, concurrent sweeps."""

from __future__ import annotations

import datetime
import re
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from typing import TypeVar

T = TypeVar("T")
R = TypeVar("R")

_DURATION_RE = re.compile(r"(?P<value>\d+(?:\.\d+)?)(?P<unit>[smhd])?")


def parse_duration(text: str) -> float | None:
    """Parse a duration like ``30s``, ``15m``, ``12h``, ``2d`` into seconds.

    Returns ``None`` for empty input. Bare numbers are treated as seconds.
    """

    text = (text or "").strip().lower()
    if not text:
        return None
    match = _DURATION_RE.fullmatch(text)
    if not match:
        raise ValueError(f"invalid duration: {text!r}")
    value = float(match.group("value"))
    unit = match.group("unit") or "s"
    factor = {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]
    return value * factor


def parse_quiet_hours(text: str) -> tuple[datetime.time, datetime.time] | None:
    """Parse ``HH:MM-HH:MM`` into a (start, end) time window, or ``None``."""

    text = (text or "").strip()
    if not text:
        return None
    try:
        start_raw, end_raw = text.split("-", 1)
        start = datetime.datetime.strptime(start_raw.strip(), "%H:%M").time()
        end = datetime.datetime.strptime(end_raw.strip(), "%H:%M").time()
    except ValueError as exc:
        raise ValueError(f"invalid quiet_hours (want HH:MM-HH:MM): {text!r}") from exc
    return start, end


def in_quiet_hours(
    now: datetime.datetime, window: tuple[datetime.time, datetime.time] | None
) -> bool:
    """Return True if ``now`` falls inside the quiet-hours window (wraps midnight)."""

    if window is None:
        return False
    start, end = window
    current = now.time()
    if start <= end:
        return start <= current < end
    # Window wraps past midnight (e.g. 23:00-06:00).
    return current >= start or current < end


class ConcurrentSweeper:
    """Runs a callable across items using a bounded thread pool.

    Used to attempt several availability domains in parallel while a shared rate
    limiter keeps the aggregate request rate safe.
    """

    def __init__(self, max_workers: int = 3) -> None:
        self.max_workers = max(1, int(max_workers))

    def map(self, fn: Callable[[T], R], items: Sequence[T]) -> list[R]:
        """Apply ``fn`` to each item concurrently, preserving input order."""

        items = list(items)
        if not items:
            return []
        if self.max_workers == 1 or len(items) == 1:
            return [fn(item) for item in items]
        workers = min(self.max_workers, len(items))
        with ThreadPoolExecutor(max_workers=workers) as pool:
            return list(pool.map(fn, items))
