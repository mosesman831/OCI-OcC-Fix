"""Unit tests for the occfix state persistence layer."""

from __future__ import annotations

import pytest

from occfix.config import StateConfig
from occfix.models import AttemptResult
from occfix.state import (
    JsonStateStore,
    NullStateStore,
    SqliteStateStore,
    StateStore,
    open_state,
)

BACKENDS = ["sqlite", "json"]


def _make_store(backend: str, tmp_path) -> StateStore:
    if backend == "sqlite":
        return SqliteStateStore(str(tmp_path / "state.db"))
    return JsonStateStore(str(tmp_path / "state.json"))


def _path_for(backend: str, tmp_path) -> str:
    name = "state.db" if backend == "sqlite" else "state.json"
    return str(tmp_path / name)


@pytest.mark.parametrize("backend", BACKENDS)
def test_record_attempt_updates_stats_and_total(backend, tmp_path):
    store = _make_store(backend, tmp_path)
    try:
        assert store.total_attempts() == 0
        assert store.get_stats() == {}

        store.record_attempt("spec-a", "AD-1", AttemptResult.SUCCESS)
        store.record_attempt("spec-a", "AD-1", AttemptResult.CAPACITY)
        store.record_attempt("spec-a", "AD-1", AttemptResult.CAPACITY)
        store.record_attempt("spec-a", "AD-2", AttemptResult.THROTTLED)
        store.record_attempt("spec-b", "AD-1", AttemptResult.SUCCESS)

        assert store.total_attempts() == 5
        stats = store.get_stats()
        assert stats == {
            "spec-a": {
                "AD-1": {"success": 1, "capacity": 2},
                "AD-2": {"throttled": 1},
            },
            "spec-b": {"AD-1": {"success": 1}},
        }
    finally:
        store.close()


@pytest.mark.parametrize("backend", BACKENDS)
def test_stats_are_json_serializable(backend, tmp_path):
    import json

    store = _make_store(backend, tmp_path)
    try:
        store.record_attempt("spec-a", "AD-1", AttemptResult.SUCCESS)
        json.dumps(store.get_stats())
    finally:
        store.close()


@pytest.mark.parametrize("backend", BACKENDS)
def test_launch_recording_and_queries(backend, tmp_path):
    store = _make_store(backend, tmp_path)
    try:
        assert store.get_launched("spec-a") == []
        assert store.is_launched("spec-a", "ocid1") is False

        store.record_launch("spec-a", "ocid1", "AD-1")
        store.record_launch("spec-a", "ocid2", "AD-2")
        store.record_launch("spec-b", "ocid3", "AD-1")

        assert store.get_launched("spec-a") == ["ocid1", "ocid2"]
        assert store.get_launched("spec-b") == ["ocid3"]
        assert store.is_launched("spec-a", "ocid1") is True
        assert store.is_launched("spec-a", "ocid3") is False
        assert store.is_launched("spec-b", "ocid3") is True
    finally:
        store.close()


@pytest.mark.parametrize("backend", BACKENDS)
def test_record_launch_is_idempotent(backend, tmp_path):
    store = _make_store(backend, tmp_path)
    try:
        store.record_launch("spec-a", "ocid1", "AD-1")
        store.record_launch("spec-a", "ocid1", "AD-1")
        assert store.get_launched("spec-a") == ["ocid1"]
    finally:
        store.close()


@pytest.mark.parametrize("backend", BACKENDS)
def test_persistence_across_reopen(backend, tmp_path):
    path = _path_for(backend, tmp_path)
    cls = SqliteStateStore if backend == "sqlite" else JsonStateStore

    store = cls(path)
    store.record_attempt("spec-a", "AD-1", AttemptResult.CAPACITY)
    store.record_launch("spec-a", "ocid1", "AD-1")
    store.close()

    reopened = cls(path)
    try:
        assert reopened.total_attempts() == 1
        assert reopened.get_stats() == {"spec-a": {"AD-1": {"capacity": 1}}}
        assert reopened.get_launched("spec-a") == ["ocid1"]
        assert reopened.is_launched("spec-a", "ocid1") is True
    finally:
        reopened.close()


def test_null_store_is_noop():
    store = NullStateStore()
    store.record_attempt("spec-a", "AD-1", AttemptResult.SUCCESS)
    store.record_launch("spec-a", "ocid1", "AD-1")

    assert store.get_launched("spec-a") == []
    assert store.is_launched("spec-a", "ocid1") is False
    assert store.get_stats() == {}
    assert store.total_attempts() == 0
    store.close()


def test_open_state_factory_returns_correct_types(tmp_path):
    sqlite_store = open_state(StateConfig(backend="sqlite", path=str(tmp_path / "s.db")))
    json_store = open_state(StateConfig(backend="json", path=str(tmp_path / "s.json")))
    null_store = open_state(StateConfig(backend="none", path="unused"))

    try:
        assert isinstance(sqlite_store, SqliteStateStore)
        assert isinstance(json_store, JsonStateStore)
        assert isinstance(null_store, NullStateStore)
    finally:
        sqlite_store.close()
        json_store.close()
        null_store.close()


def test_open_state_rejects_unknown_backend():
    with pytest.raises(ValueError):
        open_state(StateConfig(backend="bogus", path="unused"))
