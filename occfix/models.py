"""Core data models, enums, and exceptions shared across occfix modules.

These types are the stable contract every other module builds against, so keep
changes backwards compatible.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class AttemptResult(str, Enum):
    """Outcome classification for a single launch attempt."""

    SUCCESS = "success"
    CAPACITY = "capacity"       # OutOfHostCapacity / OutOfCapacity -> retry fast (jittered)
    THROTTLED = "throttled"     # TooManyRequests / 429 -> exponential backoff
    AUTH_ERROR = "auth_error"   # 401/403/invalid config -> fail fast, do not hammer
    TRANSIENT = "transient"     # network/5xx/unknown -> capped exponential backoff
    FATAL = "fatal"             # unrecoverable (e.g. duplicate name, quota) -> stop target


# Error codes returned by OCI that are safe/expected to retry against.
CAPACITY_ERROR_CODES = frozenset({"OutOfHostCapacity", "OutOfCapacity"})
THROTTLE_ERROR_CODES = frozenset({"TooManyRequests"})
AUTH_ERROR_CODES = frozenset(
    {"NotAuthenticated", "NotAuthorized", "NotAuthorizedOrNotFound", "SignUpRequired"}
)


class OccfixError(Exception):
    """Base class for all occfix errors."""


class ConfigError(OccfixError):
    """Raised when configuration is missing or invalid."""


class LaunchError(OccfixError):
    """Base error for a failed launch attempt.

    Carries enough context for the backoff/scheduler layers to decide how to
    react without importing OCI-specific types.
    """

    #: Default classification; subclasses override.
    result: AttemptResult = AttemptResult.TRANSIENT

    def __init__(
        self,
        message: str = "",
        *,
        code: Optional[str] = None,
        retry_after: Optional[float] = None,
        status: Optional[int] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.code = code
        self.retry_after = retry_after
        self.status = status

    def __str__(self) -> str:  # pragma: no cover - trivial
        base = self.message or self.__class__.__name__
        if self.code:
            return f"{self.code}: {base}"
        return base


class CapacityError(LaunchError):
    """OCI reported no host capacity for the requested shape/AD."""

    result = AttemptResult.CAPACITY


class ThrottleError(LaunchError):
    """OCI throttled the request (429/TooManyRequests)."""

    result = AttemptResult.THROTTLED


class AuthError(LaunchError):
    """Authentication/authorization/config failure. Not worth retrying."""

    result = AttemptResult.AUTH_ERROR


class TransientError(LaunchError):
    """Transient/network/unknown error, safe to retry with backoff."""

    result = AttemptResult.TRANSIENT


class FatalLaunchError(LaunchError):
    """Unrecoverable error for this target (e.g. duplicate name, quota exceeded)."""

    result = AttemptResult.FATAL


def classify_oci_code(
    code: Optional[str], status: Optional[int]
) -> AttemptResult:
    """Map an OCI error code / HTTP status to an :class:`AttemptResult`."""

    if code in CAPACITY_ERROR_CODES:
        return AttemptResult.CAPACITY
    if code in THROTTLE_ERROR_CODES or status == 429:
        return AttemptResult.THROTTLED
    if code in AUTH_ERROR_CODES or status in (401, 403):
        return AttemptResult.AUTH_ERROR
    if status is not None and 500 <= status < 600:
        return AttemptResult.TRANSIENT
    if status == 404:
        # Ambiguous in OCI; treat as auth/config (often wrong OCID/permission).
        return AttemptResult.AUTH_ERROR
    return AttemptResult.TRANSIENT


def error_for(
    message: str,
    *,
    code: Optional[str] = None,
    status: Optional[int] = None,
    retry_after: Optional[float] = None,
) -> LaunchError:
    """Build the appropriate :class:`LaunchError` subclass from OCI context."""

    result = classify_oci_code(code, status)
    kind = {
        AttemptResult.CAPACITY: CapacityError,
        AttemptResult.THROTTLED: ThrottleError,
        AttemptResult.AUTH_ERROR: AuthError,
        AttemptResult.TRANSIENT: TransientError,
        AttemptResult.FATAL: FatalLaunchError,
    }[result]
    return kind(message, code=code, retry_after=retry_after, status=status)


@dataclass
class VolumeInfo:
    """Minimal block/boot volume representation used for quota validation."""

    size_in_gbs: int
    lifecycle_state: str = "AVAILABLE"

    @property
    def is_active(self) -> bool:
        return self.lifecycle_state not in ("TERMINATING", "TERMINATED")


@dataclass
class InstanceInfo:
    """Minimal compute instance representation used for quota/dup validation."""

    display_name: str
    lifecycle_state: str = "RUNNING"
    shape: str = ""
    ocpus: float = 0.0
    memory_in_gbs: float = 0.0

    @property
    def is_active(self) -> bool:
        return self.lifecycle_state not in ("TERMINATING", "TERMINATED")


@dataclass
class LaunchSpec:
    """A single capacity target the engine will try to launch."""

    name: str
    region: str
    availability_domains: list[str]
    shape: str
    ocpus: int
    memory: int
    compartment_id: str
    subnet_id: str
    display_name: str
    ssh_keys: str = ""
    image_id: Optional[str] = None
    boot_volume_id: Optional[str] = None
    boot_volume_size: int = 47
    machine_type: str = "ARM"
    count: int = 1

    def uses_boot_volume(self) -> bool:
        return bool(self.boot_volume_id) and self.boot_volume_id != "xxxx"


@dataclass
class AttemptOutcome:
    """Result of one launch attempt against one availability domain."""

    result: AttemptResult
    ad: str
    spec_name: str = ""
    instance_id: Optional[str] = None
    code: Optional[str] = None
    message: str = ""
    retry_after: Optional[float] = None
    latency: Optional[float] = None

    @property
    def is_success(self) -> bool:
        return self.result is AttemptResult.SUCCESS


@dataclass
class LaunchResult:
    """Final result for a target once launched (or given up)."""

    spec_name: str
    instance_id: str
    availability_domain: str
    public_ip: Optional[str] = None
    total_attempts: int = 0
    metadata: dict = field(default_factory=dict)
