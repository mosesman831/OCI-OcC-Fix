"""occfix: modular engine for OCI-OcC-Fix.

Public API is intentionally small; import submodules directly for internals.
"""

from occfix.models import (
    AttemptOutcome,
    AttemptResult,
    AuthError,
    CapacityError,
    ConfigError,
    FatalLaunchError,
    InstanceInfo,
    LaunchError,
    LaunchSpec,
    OccfixError,
    ThrottleError,
    TransientError,
    VolumeInfo,
)

__version__ = "3.0.0-dev"

__all__ = [
    "AttemptOutcome",
    "AttemptResult",
    "AuthError",
    "CapacityError",
    "ConfigError",
    "FatalLaunchError",
    "InstanceInfo",
    "LaunchError",
    "LaunchSpec",
    "OccfixError",
    "ThrottleError",
    "TransientError",
    "VolumeInfo",
    "__version__",
]
