"""Unit tests for occfix.observability."""

from __future__ import annotations

import json
import logging

import pytest

from occfix.config import ObservabilityConfig
from occfix.observability import (
    JsonFormatter,
    Metrics,
    SecretRedactionFilter,
    get_metrics,
    redact,
    setup_logging,
)


def _make_record(msg: str, level: int = logging.INFO, **extra) -> logging.LogRecord:
    record = logging.LogRecord(
        name="test",
        level=level,
        pathname=__file__,
        lineno=1,
        msg=msg,
        args=(),
        exc_info=None,
    )
    for key, value in extra.items():
        setattr(record, key, value)
    return record


def test_json_formatter_valid_json_with_level_and_message() -> None:
    formatter = JsonFormatter()
    out = formatter.format(_make_record("hello world", logging.WARNING))
    parsed = json.loads(out)
    assert parsed["level"] == "WARNING"
    assert parsed["message"] == "hello world"
    assert "\n" not in out
    assert "time" in parsed


def test_json_formatter_includes_extra_fields() -> None:
    formatter = JsonFormatter()
    out = formatter.format(_make_record("with extra", region="us-1", attempts=3))
    parsed = json.loads(out)
    assert parsed["region"] == "us-1"
    assert parsed["attempts"] == 3


def test_redact_masks_telegram_bot_token() -> None:
    fake = "123456789:AAExampleFakeTokenValue0123456789abc"
    out = redact(f"sending via {fake} now")
    assert fake not in out
    assert "REDACTED" in out


def test_redact_masks_pem_header() -> None:
    pem = "-----BEGIN RSA PRIVATE KEY-----\nMIIabc\n-----END RSA PRIVATE KEY-----"
    out = redact(f"key is {pem}")
    assert "BEGIN RSA PRIVATE KEY" not in out
    assert "MIIabc" not in out


def test_redact_masks_sensitive_key_values() -> None:
    out = redact("bot_token=super-secret-value password: hunter2")
    assert "super-secret-value" not in out
    assert "hunter2" not in out


def test_redaction_filter_rewrites_record_message() -> None:
    flt = SecretRedactionFilter()
    record = _make_record("token=abcdef123456")
    assert flt.filter(record) is True
    assert "abcdef123456" not in record.getMessage()


def test_setup_logging_writes_to_file(tmp_path) -> None:
    log_file = tmp_path / "app.log"
    config = ObservabilityConfig(log_level="DEBUG", log_file=str(log_file))
    setup_logging(config)
    logging.getLogger("occfix.test").info("hello file")
    for handler in logging.getLogger().handlers:
        handler.flush()
    assert log_file.exists()
    assert "hello file" in log_file.read_text()


def test_setup_logging_is_idempotent(tmp_path) -> None:
    config = ObservabilityConfig(log_file=str(tmp_path / "a.log"))
    setup_logging(config)
    first = len(logging.getLogger().handlers)
    setup_logging(config)
    setup_logging(config)
    assert len(logging.getLogger().handlers) == first


def test_setup_logging_json_format_redacts(tmp_path) -> None:
    log_file = tmp_path / "j.log"
    config = ObservabilityConfig(log_format="json", log_file=str(log_file))
    setup_logging(config)
    logging.getLogger("occfix.test").warning("token=leakme123456789")
    for handler in logging.getLogger().handlers:
        handler.flush()
    content = log_file.read_text().strip().splitlines()[-1]
    parsed = json.loads(content)
    assert "leakme123456789" not in parsed["message"]


def test_metrics_fallback_counter() -> None:
    m = Metrics()
    m._prometheus = False
    m.inc_counter("launches", 2, region="us-1")
    m.inc_counter("launches", 3, region="us-1")
    snap = m.snapshot()
    assert snap["counters"]["launches{region=us-1}"] == 5


def test_metrics_fallback_gauge_and_observe() -> None:
    m = Metrics()
    m._prometheus = False
    m.set_gauge("in_flight", 7)
    m.set_gauge("in_flight", 4)
    m.observe("latency", 0.1)
    m.observe("latency", 0.2)
    snap = m.snapshot()
    assert snap["gauges"]["in_flight"] == 4
    assert snap["histograms"]["latency"] == [0.1, 0.2]


def test_metrics_start_http_server_no_prometheus_is_noop() -> None:
    m = Metrics()
    m._prometheus = False
    assert m.start_http_server(0) is False


def test_get_metrics_singleton() -> None:
    assert get_metrics() is get_metrics()


@pytest.mark.skipif(Metrics()._prometheus is False, reason="prometheus_client not installed")
def test_metrics_prometheus_start_http_server() -> None:
    m = Metrics()
    assert m.start_http_server(0) is True
