from __future__ import annotations

import pytest

from occfix.capacity import CapacityHeatmap
from occfix.gateway import FakeOciGateway
from occfix.launcher import Engine, Launcher
from occfix.models import (
    AuthError,
    CapacityError,
    InstanceInfo,
    LaunchSpec,
    ThrottleError,
)
from occfix.notify import Dispatcher, Notifier
from occfix.observability import Metrics


class RecordingNotifier(Notifier):
    name = "recording"

    def __init__(self):
        self.events = []

    def send(self, event) -> bool:
        self.events.append(event)
        return True


def _one_ad_spec() -> LaunchSpec:
    return LaunchSpec(
        name="t",
        region="us-ashburn-1",
        availability_domains=["FAKE:AD-1"],
        shape="VM.Standard.A1.Flex",
        ocpus=4,
        memory=24,
        compartment_id="c",
        subnet_id="s",
        display_name="OCI-TEST",
        image_id="img",
        machine_type="ARM",
    )


def _launcher(gateway, app_config, **kw):
    # No-op sleeping and a deterministic single-worker sweep.
    return Launcher(
        gateway,
        app_config,
        heatmap=CapacityHeatmap(explore_ratio=0.0),
        metrics=Metrics(),
        **kw,
    )


def test_attempt_once_success(app_config):
    gw = FakeOciGateway(default_launch="ocid1.instance..ok")
    launcher = _launcher(gw, app_config)
    out = launcher.attempt_once(_one_ad_spec(), "FAKE:AD-1")
    assert out.is_success
    assert out.instance_id == "ocid1.instance..ok"


def test_attempt_once_capacity(app_config):
    gw = FakeOciGateway(default_launch=CapacityError("no cap", code="OutOfHostCapacity"))
    launcher = _launcher(gw, app_config)
    out = launcher.attempt_once(_one_ad_spec(), "FAKE:AD-1")
    assert out.result.value == "capacity"


def test_run_target_succeeds_after_capacity_misses(app_config):
    spec = _one_ad_spec()
    app_config.targets = [spec]
    gw = FakeOciGateway(
        launch_script=[
            CapacityError("x", code="OutOfHostCapacity"),
            CapacityError("x", code="OutOfHostCapacity"),
            "ocid1.instance..win",
        ]
    )
    launcher = _launcher(gw, app_config)
    result = launcher.run_target(spec, max_rounds=10)
    assert result is not None
    assert result.instance_id == "ocid1.instance..win"
    assert result.public_ip == "203.0.113.10"
    assert result.total_attempts == 3


def test_run_target_unique_retry_tokens(app_config):
    spec = _one_ad_spec()
    gw = FakeOciGateway(
        launch_script=[CapacityError("x", code="OutOfHostCapacity"), "ocid1.instance..win"]
    )
    launcher = _launcher(gw, app_config)
    launcher.run_target(spec, max_rounds=10)
    assert len(set(gw.retry_tokens)) == len(gw.retry_tokens)  # all unique


def test_run_target_auth_error_raises(app_config):
    spec = _one_ad_spec()
    gw = FakeOciGateway(default_launch=AuthError("nope", code="NotAuthenticated"))
    launcher = _launcher(gw, app_config)
    with pytest.raises(AuthError):
        launcher.run_target(spec, max_rounds=5)


def test_run_target_duplicate_instance_is_fatal(app_config):
    spec = _one_ad_spec()
    gw = FakeOciGateway(
        instances=[InstanceInfo(display_name="OCI-TEST", lifecycle_state="RUNNING")],
        default_launch="ocid1.instance..ok",
    )
    launcher = _launcher(gw, app_config)
    # validate() should catch the duplicate and return None (no launch attempted).
    assert launcher.run_target(spec, max_rounds=5) is None
    assert gw.launch_calls == []


def test_success_notifies_launched_event(app_config):
    spec = _one_ad_spec()
    rec = RecordingNotifier()
    gw = FakeOciGateway(default_launch="ocid1.instance..ok")
    launcher = _launcher(gw, app_config, dispatcher=Dispatcher([rec]))
    launcher.run_target(spec, max_rounds=5)
    types = [e.type for e in rec.events]
    assert "launched" in types


def test_engine_validate_all(app_config):
    gw = FakeOciGateway()
    results = Engine(app_config, gw).validate_all()
    assert results == {app_config.targets[0].name: None}


def test_engine_run_returns_result(app_config):
    gw = FakeOciGateway(default_launch="ocid1.instance..ok")
    results = Engine(app_config, gw).run(max_rounds=3)
    assert len(results) == 1
    assert results[0].instance_id == "ocid1.instance..ok"


def test_throttle_lowers_adaptive_rate():
    spec = _one_ad_spec()
    from occfix.config import AppConfig

    cfg = AppConfig()
    cfg.targets = [spec]
    cfg.retry.min_interval = 0.0
    cfg.retry.max_interval = 0.0
    cfg.retry.capacity_jitter_cap = 0.0
    cfg.ratelimit.mode = "adaptive"
    cfg.ratelimit.max_calls_per_sec = 100.0
    cfg.ratelimit.min_calls_per_sec = 0.1
    cfg.ratelimit.concurrency = 1
    gw = FakeOciGateway(
        launch_script=[ThrottleError("slow", code="TooManyRequests"), "ocid1.instance..ok"]
    )
    launcher = _launcher(gw, cfg)
    start_rate = launcher.ratelimiter.current_rate
    launcher.run_target(spec, max_rounds=10)
    # A throttle should have pushed the adaptive rate below the starting ceiling.
    assert launcher.ratelimiter.current_rate < start_rate
