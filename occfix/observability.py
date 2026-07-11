"""Structured logging and metrics for occfix.

Logging supports human and JSON formats with best-effort secret redaction and a
rotating file handler. Metrics wrap ``prometheus_client`` when available and fall
back to an in-memory registry with an identical method surface otherwise, so the
rest of the app never has to care which backend is active.
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import re
import threading
from datetime import datetime, timezone

from occfix.config import ObservabilityConfig

_HANDLER_TAG = "_occfix_handler"

_RESERVED_LOGRECORD = frozenset(logging.makeLogRecord({}).__dict__.keys()) | {"message", "asctime"}


class JsonFormatter(logging.Formatter):
    """Format log records as single-line JSON objects."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, object] = {
            "level": record.levelname,
            "time": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "message": record.getMessage(),
        }
        for key, value in record.__dict__.items():
            if key in _RESERVED_LOGRECORD or key.startswith("_"):
                continue
            payload[key] = value if _json_safe(value) else repr(value)
        if record.exc_info:
            payload["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(payload, default=str)


def _json_safe(value: object) -> bool:
    return isinstance(value, (str, int, float, bool, type(None), list, dict))


SECRET_KEYS = ("token", "key", "secret", "password")

_BOT_TOKEN_RE = re.compile(r"\b\d{6,}:[A-Za-z0-9_\-]{20,}\b")
_PEM_RE = re.compile(
    r"-----BEGIN [A-Z0-9 ]*?PRIVATE KEY-----.*?-----END [A-Z0-9 ]*?PRIVATE KEY-----",
    re.DOTALL,
)
_PEM_HEADER_RE = re.compile(r"-----BEGIN [A-Z0-9 ]*?PRIVATE KEY-----")
_KV_RE = re.compile(
    r"(?i)\b(\w*(?:" + "|".join(SECRET_KEYS) + r")\w*)\b(\s*[=:]\s*)([^\s,;]+)"
)

_MASK = "***REDACTED***"


def redact(text: str) -> str:
    """Mask obvious secrets (bot tokens, PEM blocks, sensitive key=value)."""

    text = _PEM_RE.sub(_MASK, text)
    text = _PEM_HEADER_RE.sub(_MASK, text)
    text = _BOT_TOKEN_RE.sub(_MASK, text)
    text = _KV_RE.sub(lambda m: f"{m.group(1)}{m.group(2)}{_MASK}", text)
    return text


class SecretRedactionFilter(logging.Filter):
    """Logging filter that redacts secrets from formatted messages."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            record.msg = redact(record.getMessage())
            record.args = ()
        except Exception:  # noqa: BLE001 - never let logging redaction crash callers
            pass
        return True


def setup_logging(config: ObservabilityConfig) -> None:
    """Configure the root logger idempotently from ``config``."""

    root = logging.getLogger()
    root.setLevel(config.log_level.upper())

    for handler in [h for h in root.handlers if getattr(h, _HANDLER_TAG, False)]:
        root.removeHandler(handler)
        handler.close()

    if config.log_format == "json":
        formatter: logging.Formatter = JsonFormatter()
    else:
        formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")

    redaction = SecretRedactionFilter()

    file_handler = logging.handlers.RotatingFileHandler(
        config.log_file, maxBytes=5 * 1024 * 1024, backupCount=3
    )
    stream_handler = logging.StreamHandler()
    for handler in (file_handler, stream_handler):
        handler.setFormatter(formatter)
        handler.addFilter(redaction)
        setattr(handler, _HANDLER_TAG, True)
        root.addHandler(handler)


class Metrics:
    """Metrics facade backed by prometheus_client or an in-memory registry."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._counters: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
        self._gauges: dict[tuple[str, tuple[tuple[str, str], ...]], float] = {}
        self._histograms: dict[tuple[str, tuple[tuple[str, str], ...]], list[float]] = {}
        self._prom: dict[str, object] = {}
        try:
            import prometheus_client  # noqa: F401

            self._prometheus = True
        except Exception:  # noqa: BLE001
            self._prometheus = False

    @staticmethod
    def _key(name: str, labels: dict[str, object]):
        return name, tuple(sorted((k, str(v)) for k, v in labels.items()))

    def inc_counter(self, name: str, value: float = 1, **labels: object) -> None:
        """Increment a counter by ``value``."""

        if self._prometheus:
            self._prom_metric("counter", name, labels).inc(value)
            return
        key = self._key(name, labels)
        with self._lock:
            self._counters[key] = self._counters.get(key, 0.0) + value

    def set_gauge(self, name: str, value: float, **labels: object) -> None:
        """Set a gauge to ``value``."""

        if self._prometheus:
            self._prom_metric("gauge", name, labels).set(value)
            return
        key = self._key(name, labels)
        with self._lock:
            self._gauges[key] = float(value)

    def observe(self, name: str, value: float, **labels: object) -> None:
        """Record ``value`` into a histogram."""

        if self._prometheus:
            self._prom_metric("histogram", name, labels).observe(value)
            return
        key = self._key(name, labels)
        with self._lock:
            self._histograms.setdefault(key, []).append(float(value))

    def snapshot(self) -> dict:
        """Return a plain-dict view of the in-memory registry."""

        with self._lock:
            return {
                "counters": {self._fmt(k): v for k, v in self._counters.items()},
                "gauges": {self._fmt(k): v for k, v in self._gauges.items()},
                "histograms": {self._fmt(k): list(v) for k, v in self._histograms.items()},
            }

    @staticmethod
    def _fmt(key: tuple[str, tuple[tuple[str, str], ...]]) -> str:
        name, labels = key
        if not labels:
            return name
        rendered = ",".join(f"{k}={v}" for k, v in labels)
        return f"{name}{{{rendered}}}"

    def _prom_metric(self, kind: str, name: str, labels: dict[str, object]):
        import prometheus_client

        label_names = tuple(sorted(labels))
        cache_key = f"{kind}:{name}:{','.join(label_names)}"
        metric = self._prom.get(cache_key)
        if metric is None:
            factory = {
                "counter": prometheus_client.Counter,
                "gauge": prometheus_client.Gauge,
                "histogram": prometheus_client.Histogram,
            }[kind]
            metric = factory(name, name, labelnames=label_names)
            self._prom[cache_key] = metric
        if label_names:
            return metric.labels(**{k: str(labels[k]) for k in label_names})  # type: ignore[attr-defined]
        return metric

    def start_http_server(self, port: int) -> bool:
        """Start the Prometheus HTTP server; no-op returning False if unavailable."""

        if not self._prometheus:
            return False
        import prometheus_client

        prometheus_client.start_http_server(port)
        return True


_metrics: Metrics | None = None
_metrics_lock = threading.Lock()


def get_metrics() -> Metrics:
    """Return the process-wide :class:`Metrics` singleton."""

    global _metrics
    if _metrics is None:
        with _metrics_lock:
            if _metrics is None:
                _metrics = Metrics()
    return _metrics
