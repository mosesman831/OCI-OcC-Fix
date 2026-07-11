"""Shared pytest fixtures for occfix tests."""

from __future__ import annotations

import pytest

from occfix.config import AppConfig
from occfix.models import LaunchSpec


@pytest.fixture
def spec() -> LaunchSpec:
    return LaunchSpec(
        name="test",
        region="us-ashburn-1",
        availability_domains=["FAKE:AD-1", "FAKE:AD-2"],
        shape="VM.Standard.A1.Flex",
        ocpus=4,
        memory=24,
        compartment_id="ocid1.compartment.oc1..test",
        subnet_id="ocid1.subnet.oc1..test",
        display_name="OCI-TEST",
        ssh_keys="ssh-rsa AAAA test",
        image_id="ocid1.image.oc1..test",
        machine_type="ARM",
    )


@pytest.fixture
def app_config(spec: LaunchSpec) -> AppConfig:
    cfg = AppConfig()
    cfg.targets = [spec]
    # Fast, deterministic-ish settings for tests.
    cfg.retry.min_interval = 0.0
    cfg.retry.capacity_jitter_cap = 0.0
    cfg.retry.max_interval = 0.0
    cfg.ratelimit.mode = "fixed"
    cfg.ratelimit.max_calls_per_sec = 1e9
    cfg.ratelimit.concurrency = 1
    return cfg
