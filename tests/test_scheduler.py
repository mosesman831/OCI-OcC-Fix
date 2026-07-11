from __future__ import annotations

import datetime

import pytest

from occfix.scheduler import (
    ConcurrentSweeper,
    in_quiet_hours,
    parse_duration,
    parse_quiet_hours,
)


def test_parse_duration_units():
    assert parse_duration("") is None
    assert parse_duration("30") == 30
    assert parse_duration("30s") == 30
    assert parse_duration("15m") == 900
    assert parse_duration("12h") == 12 * 3600
    assert parse_duration("2d") == 2 * 86400


def test_parse_duration_invalid():
    with pytest.raises(ValueError):
        parse_duration("abc")


def test_quiet_hours_normal_window():
    window = parse_quiet_hours("01:00-06:00")
    assert in_quiet_hours(datetime.datetime(2026, 1, 1, 2, 30), window)
    assert not in_quiet_hours(datetime.datetime(2026, 1, 1, 7, 0), window)


def test_quiet_hours_wrap_midnight():
    window = parse_quiet_hours("23:00-06:00")
    assert in_quiet_hours(datetime.datetime(2026, 1, 1, 23, 30), window)
    assert in_quiet_hours(datetime.datetime(2026, 1, 1, 5, 0), window)
    assert not in_quiet_hours(datetime.datetime(2026, 1, 1, 12, 0), window)


def test_quiet_hours_none():
    assert parse_quiet_hours("") is None
    assert not in_quiet_hours(datetime.datetime(2026, 1, 1, 3, 0), None)


def test_sweeper_preserves_order():
    sweeper = ConcurrentSweeper(max_workers=4)
    assert sweeper.map(lambda x: x * 2, [1, 2, 3, 4]) == [2, 4, 6, 8]


def test_sweeper_empty():
    assert ConcurrentSweeper(3).map(lambda x: x, []) == []


def test_sweeper_single_worker_sequential():
    assert ConcurrentSweeper(1).map(lambda x: x + 1, [1, 2, 3]) == [2, 3, 4]
