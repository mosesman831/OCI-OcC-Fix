"""Run-state persistence so a restart can resume without re-launching.

Three interchangeable backends implement the :class:`StateStore` contract:
SQLite (durable, default), JSON (simple/portable), and a null no-op store. All
implementations are safe to use from multiple threads.
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from abc import ABC, abstractmethod

from occfix.config import StateConfig
from occfix.models import AttemptResult


class StateStore(ABC):
    """Interface every state backend must implement."""

    @abstractmethod
    def record_attempt(self, spec_name: str, ad: str, result: AttemptResult) -> None:
        """Persist the outcome of a single launch attempt."""

    @abstractmethod
    def record_launch(self, spec_name: str, instance_id: str, availability_domain: str) -> None:
        """Persist a successful launch for later resume/dedup."""

    @abstractmethod
    def get_launched(self, spec_name: str) -> list[str]:
        """Return instance ids already launched for ``spec_name``."""

    @abstractmethod
    def is_launched(self, spec_name: str, instance_id: str) -> bool:
        """Return whether ``instance_id`` is recorded for ``spec_name``."""

    @abstractmethod
    def get_stats(self) -> dict:
        """Return attempt counts nested by spec name, AD, then result."""

    @abstractmethod
    def total_attempts(self) -> int:
        """Return the total number of recorded attempts."""

    @abstractmethod
    def close(self) -> None:
        """Release any underlying resources."""


class SqliteStateStore(StateStore):
    """Durable store backed by stdlib :mod:`sqlite3`."""

    def __init__(self, path: str) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(path, check_same_thread=False)
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS attempts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                spec_name TEXT NOT NULL,
                ad TEXT NOT NULL,
                result TEXT NOT NULL
            )
            """
        )
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS launches (
                spec_name TEXT NOT NULL,
                instance_id TEXT NOT NULL,
                availability_domain TEXT NOT NULL,
                UNIQUE(spec_name, instance_id)
            )
            """
        )
        self._conn.commit()

    def record_attempt(self, spec_name: str, ad: str, result: AttemptResult) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO attempts (spec_name, ad, result) VALUES (?, ?, ?)",
                (spec_name, ad, AttemptResult(result).value),
            )
            self._conn.commit()

    def record_launch(self, spec_name: str, instance_id: str, availability_domain: str) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT OR IGNORE INTO launches
                    (spec_name, instance_id, availability_domain)
                VALUES (?, ?, ?)
                """,
                (spec_name, instance_id, availability_domain),
            )
            self._conn.commit()

    def get_launched(self, spec_name: str) -> list[str]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT instance_id FROM launches WHERE spec_name = ? ORDER BY rowid",
                (spec_name,),
            ).fetchall()
        return [row[0] for row in rows]

    def is_launched(self, spec_name: str, instance_id: str) -> bool:
        with self._lock:
            row = self._conn.execute(
                "SELECT 1 FROM launches WHERE spec_name = ? AND instance_id = ?",
                (spec_name, instance_id),
            ).fetchone()
        return row is not None

    def get_stats(self) -> dict:
        with self._lock:
            rows = self._conn.execute(
                "SELECT spec_name, ad, result, COUNT(*) FROM attempts "
                "GROUP BY spec_name, ad, result"
            ).fetchall()
        stats: dict = {}
        for spec_name, ad, result, count in rows:
            stats.setdefault(spec_name, {}).setdefault(ad, {})[result] = count
        return stats

    def total_attempts(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) FROM attempts").fetchone()
        return int(row[0])

    def close(self) -> None:
        with self._lock:
            self._conn.close()


class JsonStateStore(StateStore):
    """Simple store persisting the full state to a JSON file on each write."""

    def __init__(self, path: str) -> None:
        self._path = path
        self._lock = threading.Lock()
        self._state: dict = {"attempts": [], "launches": []}
        self._load()

    def _load(self) -> None:
        if not os.path.exists(self._path):
            return
        with open(self._path, encoding="utf-8") as fh:
            data = json.load(fh)
        self._state["attempts"] = list(data.get("attempts", []))
        self._state["launches"] = list(data.get("launches", []))

    def _flush(self) -> None:
        tmp = f"{self._path}.tmp"
        with open(tmp, "w", encoding="utf-8") as fh:
            json.dump(self._state, fh)
        os.replace(tmp, self._path)

    def record_attempt(self, spec_name: str, ad: str, result: AttemptResult) -> None:
        with self._lock:
            self._state["attempts"].append(
                {
                    "spec_name": spec_name,
                    "ad": ad,
                    "result": AttemptResult(result).value,
                }
            )
            self._flush()

    def record_launch(self, spec_name: str, instance_id: str, availability_domain: str) -> None:
        with self._lock:
            for entry in self._state["launches"]:
                if entry["spec_name"] == spec_name and entry["instance_id"] == instance_id:
                    return
            self._state["launches"].append(
                {
                    "spec_name": spec_name,
                    "instance_id": instance_id,
                    "availability_domain": availability_domain,
                }
            )
            self._flush()

    def get_launched(self, spec_name: str) -> list[str]:
        with self._lock:
            return [
                entry["instance_id"]
                for entry in self._state["launches"]
                if entry["spec_name"] == spec_name
            ]

    def is_launched(self, spec_name: str, instance_id: str) -> bool:
        with self._lock:
            return any(
                entry["spec_name"] == spec_name and entry["instance_id"] == instance_id
                for entry in self._state["launches"]
            )

    def get_stats(self) -> dict:
        with self._lock:
            stats: dict = {}
            for entry in self._state["attempts"]:
                spec = stats.setdefault(entry["spec_name"], {})
                ad = spec.setdefault(entry["ad"], {})
                ad[entry["result"]] = ad.get(entry["result"], 0) + 1
            return stats

    def total_attempts(self) -> int:
        with self._lock:
            return len(self._state["attempts"])

    def close(self) -> None:
        pass


class NullStateStore(StateStore):
    """No-op store used when state persistence is disabled."""

    def record_attempt(self, spec_name: str, ad: str, result: AttemptResult) -> None:
        pass

    def record_launch(self, spec_name: str, instance_id: str, availability_domain: str) -> None:
        pass

    def get_launched(self, spec_name: str) -> list[str]:
        return []

    def is_launched(self, spec_name: str, instance_id: str) -> bool:
        return False

    def get_stats(self) -> dict:
        return {}

    def total_attempts(self) -> int:
        return 0

    def close(self) -> None:
        pass


def open_state(config: StateConfig) -> StateStore:
    """Return the state store matching ``config.backend``."""

    backend = config.backend
    if backend == "sqlite":
        return SqliteStateStore(config.path)
    if backend == "json":
        return JsonStateStore(config.path)
    if backend == "none":
        return NullStateStore()
    raise ValueError(f"unknown state backend: {backend!r}")
