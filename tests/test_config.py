from __future__ import annotations

from pathlib import Path

import pytest

from occfix.config import load_config
from occfix.models import ConfigError

LEGACY_INI = """
[OCI]
image_id = ocid1.image.oc1..img
availability_domains = ["FAKE:AD-1","FAKE:AD-2"]
compartment_id = ocid1.tenancy.oc1..comp
subnet_id = ocid1.subnet.oc1..sub
boot_volume_id = xxxx

[Instance]
display_name = OCI-ARM-01
ssh_keys = ssh-rsa AAAA test
boot_volume_size = 50

[Telegram]
bot_token = xxxx
uid = xxxx

[Machine]
type = ARM
shape = VM.Standard.A1.Flex
ocpus = 4
memory = 24

[Retry]
min_interval = 1
max_interval = 60
initial_retry_interval = 1
backoff_factor = 1.5

[Logging]
log_level = INFO
"""

OCI_CFG = """
[DEFAULT]
user=ocid1.user.oc1..u
fingerprint=aa:bb
tenancy=ocid1.tenancy.oc1..t
region=uk-london-1
key_file=/tmp/x.pem
"""


def _write(tmp_path: Path) -> tuple[Path, Path]:
    ini = tmp_path / "configuration.ini"
    oci = tmp_path / "config"
    ini.write_text(LEGACY_INI)
    oci.write_text(OCI_CFG)
    return ini, oci


def test_legacy_ini_builds_single_target(tmp_path):
    ini, oci = _write(tmp_path)
    cfg = load_config(ini, oci, env={})
    assert len(cfg.targets) == 1
    t = cfg.targets[0]
    assert t.availability_domains == ["FAKE:AD-1", "FAKE:AD-2"]
    assert t.shape == "VM.Standard.A1.Flex"
    assert t.ocpus == 4 and t.memory == 24
    assert t.boot_volume_size == 50
    assert t.region == "uk-london-1"  # read from OCI config
    assert cfg.retry.backoff_factor == 1.5
    cfg.validate()  # should not raise


def test_disabled_telegram_not_a_channel(tmp_path):
    ini, oci = _write(tmp_path)
    cfg = load_config(ini, oci, env={})
    assert "telegram" not in cfg.notify.channels


def test_env_overrides(tmp_path):
    ini, oci = _write(tmp_path)
    cfg = load_config(
        ini,
        oci,
        env={"OCCFIX_LOG_LEVEL": "DEBUG", "OCCFIX_RATELIMIT_CONCURRENCY": "7"},
    )
    assert cfg.observability.log_level == "DEBUG"
    assert cfg.ratelimit.concurrency == 7


def test_cli_overrides(tmp_path):
    ini, oci = _write(tmp_path)
    cfg = load_config(ini, oci, env={}, overrides={"observability.log_format": "json"})
    assert cfg.observability.log_format == "json"


def test_env_telegram_enables_channel(tmp_path):
    ini, oci = _write(tmp_path)
    cfg = load_config(
        ini,
        oci,
        env={"OCCFIX_TELEGRAM_BOT_TOKEN": "123:abc", "OCCFIX_TELEGRAM_UID": "999"},
    )
    assert "telegram" in cfg.notify.channels


def test_missing_targets_validate_raises():
    cfg = load_config("/nonexistent.ini", "/nonexistent", env={})
    assert cfg.targets == []
    with pytest.raises(ConfigError):
        cfg.validate()
