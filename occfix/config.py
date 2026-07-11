"""Layered configuration: built-in defaults < INI < environment < CLI overrides.

Back-compatible with the original ``configuration.ini`` (single target derived
from the ``[OCI]``/``[Instance]``/``[Machine]`` sections) while also supporting
the richer multi-target schema described in ``spec.md``.
"""

from __future__ import annotations

import configparser
import json
import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

from occfix.models import ConfigError, LaunchSpec


@dataclass
class RetryConfig:
    min_interval: float = 1.0
    max_interval: float = 60.0
    capacity_jitter_cap: float = 3.0
    throttle_backoff_cap: float = 300.0
    backoff_factor: float = 1.5
    initial_retry_interval: float = 1.0


@dataclass
class RateLimitConfig:
    mode: str = "adaptive"  # "fixed" | "adaptive"
    max_calls_per_sec: float = 2.0
    min_calls_per_sec: float = 0.2
    concurrency: int = 3


@dataclass
class LimitsConfig:
    max_total_storage_gb: int = 200
    arm_max_ocpus: int = 4
    arm_max_memory_gb: int = 24
    validation_ttl: float = 300.0


@dataclass
class StateConfig:
    backend: str = "sqlite"  # "sqlite" | "json" | "none"
    path: str = "occfix_state.db"


@dataclass
class ObservabilityConfig:
    log_level: str = "INFO"
    log_format: str = "human"  # "human" | "json"
    log_file: str = "oci_occ.log"
    metrics_enabled: bool = False
    metrics_port: int = 9090


@dataclass
class NotifyConfig:
    channels: list[str] = field(default_factory=list)
    digest: bool = False
    telegram_bot_token: str = ""
    telegram_uid: str = ""
    webhook_url: str = ""
    discord_webhook_url: str = ""
    slack_webhook_url: str = ""


@dataclass
class ControlConfig:
    http_enabled: bool = False
    http_host: str = "127.0.0.1"
    http_port: int = 8080
    telegram_commands: bool = False


@dataclass
class ScheduleConfig:
    quiet_hours: str = ""  # e.g. "01:00-06:00"
    max_runtime: str = ""  # e.g. "12h"
    max_attempts: int = 0  # 0 = unlimited


@dataclass
class AuthConfig:
    method: str = "key_file"  # key_file|env|instance_principal|resource_principal|session_token
    oci_config_path: str = "config"
    oci_profile: str = "DEFAULT"


@dataclass
class AppConfig:
    auth: AuthConfig = field(default_factory=AuthConfig)
    retry: RetryConfig = field(default_factory=RetryConfig)
    ratelimit: RateLimitConfig = field(default_factory=RateLimitConfig)
    limits: LimitsConfig = field(default_factory=LimitsConfig)
    state: StateConfig = field(default_factory=StateConfig)
    observability: ObservabilityConfig = field(default_factory=ObservabilityConfig)
    notify: NotifyConfig = field(default_factory=NotifyConfig)
    control: ControlConfig = field(default_factory=ControlConfig)
    schedule: ScheduleConfig = field(default_factory=ScheduleConfig)
    targets: list[LaunchSpec] = field(default_factory=list)

    def validate(self) -> None:
        if not self.targets:
            raise ConfigError("no launch targets configured")
        for spec in self.targets:
            if not spec.availability_domains:
                raise ConfigError(f"target {spec.name}: no availability_domains")
            if not spec.compartment_id:
                raise ConfigError(f"target {spec.name}: missing compartment_id")
            if not spec.subnet_id:
                raise ConfigError(f"target {spec.name}: missing subnet_id")
            if not spec.uses_boot_volume() and not spec.image_id:
                raise ConfigError(
                    f"target {spec.name}: image_id required when not using a boot volume"
                )


def _parse_ad_list(raw: str) -> list[str]:
    raw = (raw or "").strip()
    if not raw:
        return []
    if raw.startswith("["):
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ConfigError(f"invalid availability_domains JSON: {exc}") from exc
        return [str(item).strip() for item in parsed if str(item).strip()]
    return [part.strip() for part in raw.split(",") if part.strip()]


def _get(cp: configparser.ConfigParser, section: str, key: str, fallback: str = "") -> str:
    if cp.has_option(section, key):
        return cp.get(section, key)
    return fallback


def _as_bool(value: str, fallback: bool = False) -> bool:
    if value == "":
        return fallback
    return value.strip().lower() in ("1", "true", "yes", "on")


def _legacy_target(cp: configparser.ConfigParser, oci_region: str) -> LaunchSpec | None:
    """Build a single target from legacy [OCI]/[Instance]/[Machine] sections."""

    if not cp.has_section("OCI"):
        return None
    ads = _parse_ad_list(_get(cp, "OCI", "availability_domains"))
    boot_volume_id = _get(cp, "OCI", "boot_volume_id", "xxxx") or "xxxx"

    def _int(section: str, key: str, default: int) -> int:
        raw = _get(cp, section, key)
        try:
            return int(raw) if raw != "" else default
        except ValueError:
            return default

    return LaunchSpec(
        name="legacy",
        region=oci_region,
        availability_domains=ads,
        shape=_get(cp, "Machine", "shape"),
        ocpus=_int("Machine", "ocpus", 4),
        memory=_int("Machine", "memory", 24),
        compartment_id=_get(cp, "OCI", "compartment_id"),
        subnet_id=_get(cp, "OCI", "subnet_id"),
        display_name=_get(cp, "Instance", "display_name"),
        ssh_keys=_get(cp, "Instance", "ssh_keys"),
        image_id=_get(cp, "OCI", "image_id") or None,
        boot_volume_id=boot_volume_id,
        boot_volume_size=_int("Instance", "boot_volume_size", 47),
        machine_type=(_get(cp, "Machine", "type", "ARM") or "ARM").upper(),
        count=1,
    )


def _read_oci_region(oci_config_path: Path, profile: str) -> str:
    if not oci_config_path.exists():
        return ""
    cp = configparser.ConfigParser()
    cp.read(oci_config_path)
    section = profile if cp.has_section(profile) else "DEFAULT"
    try:
        return cp.get(section, "region", fallback="")
    except configparser.Error:
        return ""


def load_config(
    ini_path: str | os.PathLike = "configuration.ini",
    oci_config_path: str | os.PathLike = "config",
    *,
    env: Mapping[str, str] | None = None,
    overrides: Mapping[str, object] | None = None,
) -> AppConfig:
    """Load and merge configuration from all layers and return an AppConfig."""

    env = os.environ if env is None else env
    ini_path = Path(ini_path)
    oci_config_path = Path(oci_config_path)

    cp = configparser.ConfigParser(interpolation=None)
    if ini_path.exists():
        cp.read(ini_path)

    cfg = AppConfig()
    cfg.auth.oci_config_path = str(oci_config_path)

    # Retry
    if cp.has_section("Retry"):
        r = cfg.retry
        r.min_interval = cp.getfloat("Retry", "min_interval", fallback=r.min_interval)
        r.max_interval = cp.getfloat("Retry", "max_interval", fallback=r.max_interval)
        r.backoff_factor = cp.getfloat("Retry", "backoff_factor", fallback=r.backoff_factor)
        r.initial_retry_interval = cp.getfloat(
            "Retry", "initial_retry_interval", fallback=r.initial_retry_interval
        )
        r.capacity_jitter_cap = cp.getfloat(
            "Retry", "capacity_jitter_cap", fallback=r.capacity_jitter_cap
        )
        r.throttle_backoff_cap = cp.getfloat(
            "Retry", "throttle_backoff_cap", fallback=r.throttle_backoff_cap
        )

    # RateLimit
    if cp.has_section("RateLimit"):
        rl = cfg.ratelimit
        rl.mode = _get(cp, "RateLimit", "mode", rl.mode)
        rl.max_calls_per_sec = cp.getfloat(
            "RateLimit", "max_calls_per_sec", fallback=rl.max_calls_per_sec
        )
        rl.concurrency = cp.getint("RateLimit", "concurrency", fallback=rl.concurrency)

    # Limits
    if cp.has_section("Limits"):
        lim = cfg.limits
        lim.max_total_storage_gb = cp.getint(
            "Limits", "max_total_storage_gb", fallback=lim.max_total_storage_gb
        )
        lim.arm_max_ocpus = cp.getint("Limits", "arm_max_ocpus", fallback=lim.arm_max_ocpus)
        lim.arm_max_memory_gb = cp.getint(
            "Limits", "arm_max_memory_gb", fallback=lim.arm_max_memory_gb
        )

    # Logging / observability
    if cp.has_section("Logging"):
        cfg.observability.log_level = _get(cp, "Logging", "log_level", "INFO").upper()
    if cp.has_section("Observability"):
        ob = cfg.observability
        ob.log_level = _get(cp, "Observability", "log_level", ob.log_level).upper()
        ob.log_format = _get(cp, "Observability", "log_format", ob.log_format)
        ob.metrics_enabled = _as_bool(
            _get(cp, "Observability", "metrics_enabled"), ob.metrics_enabled
        )
        ob.metrics_port = cp.getint("Observability", "metrics_port", fallback=ob.metrics_port)

    # Telegram (legacy) + Notify
    if cp.has_section("Telegram"):
        token = _get(cp, "Telegram", "bot_token", "xxxx")
        uid = _get(cp, "Telegram", "uid", "xxxx")
        cfg.notify.telegram_bot_token = token
        cfg.notify.telegram_uid = uid
        if token and token != "xxxx" and uid and uid != "xxxx":
            cfg.notify.channels.append("telegram")
    if cp.has_section("Notify"):
        channels = _get(cp, "Notify", "channels")
        if channels:
            cfg.notify.channels = [c.strip() for c in channels.split(",") if c.strip()]
        cfg.notify.digest = _as_bool(_get(cp, "Notify", "digest"), cfg.notify.digest)
        cfg.notify.webhook_url = _get(cp, "Notify", "webhook_url", cfg.notify.webhook_url)
        cfg.notify.discord_webhook_url = _get(
            cp, "Notify", "discord_webhook_url", cfg.notify.discord_webhook_url
        )
        cfg.notify.slack_webhook_url = _get(
            cp, "Notify", "slack_webhook_url", cfg.notify.slack_webhook_url
        )

    # State
    if cp.has_section("State"):
        cfg.state.backend = _get(cp, "State", "backend", cfg.state.backend)
        cfg.state.path = _get(cp, "State", "path", cfg.state.path)

    # Control
    if cp.has_section("Control"):
        cfg.control.http_enabled = _as_bool(
            _get(cp, "Control", "http_enabled"), cfg.control.http_enabled
        )
        cfg.control.http_port = cp.getint("Control", "http_port", fallback=cfg.control.http_port)
        cfg.control.telegram_commands = _as_bool(
            _get(cp, "Control", "telegram_commands"), cfg.control.telegram_commands
        )

    # Schedule
    if cp.has_section("Schedule"):
        cfg.schedule.quiet_hours = _get(cp, "Schedule", "quiet_hours")
        cfg.schedule.max_runtime = _get(cp, "Schedule", "max_runtime")
        cfg.schedule.max_attempts = cp.getint("Schedule", "max_attempts", fallback=0)

    # Auth
    if cp.has_section("Auth"):
        cfg.auth.method = _get(cp, "Auth", "method", cfg.auth.method)
        cfg.auth.oci_profile = _get(cp, "Auth", "profile", cfg.auth.oci_profile)

    # Targets: legacy single target for now (multi-target parsing is additive later).
    region = _read_oci_region(oci_config_path, cfg.auth.oci_profile)
    legacy = _legacy_target(cp, region)
    if legacy is not None:
        cfg.targets.append(legacy)

    _apply_env(cfg, env)
    _apply_overrides(cfg, overrides or {})
    return cfg


# Curated environment overrides: OCCFIX_<GROUP>_<FIELD>.
_ENV_MAP: dict[str, tuple[str, str, type]] = {
    "OCCFIX_AUTH_METHOD": ("auth", "method", str),
    "OCCFIX_AUTH_OCI_CONFIG_PATH": ("auth", "oci_config_path", str),
    "OCCFIX_LOG_LEVEL": ("observability", "log_level", str),
    "OCCFIX_LOG_FORMAT": ("observability", "log_format", str),
    "OCCFIX_METRICS_ENABLED": ("observability", "metrics_enabled", bool),
    "OCCFIX_RATELIMIT_MODE": ("ratelimit", "mode", str),
    "OCCFIX_RATELIMIT_MAX_CALLS_PER_SEC": ("ratelimit", "max_calls_per_sec", float),
    "OCCFIX_RATELIMIT_CONCURRENCY": ("ratelimit", "concurrency", int),
    "OCCFIX_STATE_BACKEND": ("state", "backend", str),
    "OCCFIX_STATE_PATH": ("state", "path", str),
    "OCCFIX_TELEGRAM_BOT_TOKEN": ("notify", "telegram_bot_token", str),
    "OCCFIX_TELEGRAM_UID": ("notify", "telegram_uid", str),
    "OCCFIX_CONTROL_HTTP_ENABLED": ("control", "http_enabled", bool),
    "OCCFIX_CONTROL_HTTP_PORT": ("control", "http_port", int),
}


def _coerce(value: str, typ: type) -> object:
    if typ is bool:
        return _as_bool(value)
    if typ is int:
        return int(value)
    if typ is float:
        return float(value)
    return value


def _apply_env(cfg: AppConfig, env: Mapping[str, str]) -> None:
    for env_key, (group, field_name, typ) in _ENV_MAP.items():
        if env_key in env and env[env_key] != "":
            setattr(getattr(cfg, group), field_name, _coerce(env[env_key], typ))
    # Telegram creds via env enable the channel too.
    if (
        cfg.notify.telegram_bot_token
        and cfg.notify.telegram_bot_token != "xxxx"
        and (cfg.notify.telegram_uid and cfg.notify.telegram_uid != "xxxx")
        and "telegram" not in cfg.notify.channels
    ):
        cfg.notify.channels.append("telegram")


def _apply_overrides(cfg: AppConfig, overrides: Mapping[str, object]) -> None:
    """Apply flat CLI overrides like {"observability.log_level": "DEBUG"}."""

    for dotted, value in overrides.items():
        if value is None:
            continue
        group, _, field_name = dotted.partition(".")
        target = getattr(cfg, group, None)
        if target is not None and hasattr(target, field_name):
            setattr(target, field_name, value)
