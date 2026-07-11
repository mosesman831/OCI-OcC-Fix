"""Build OCI SDK config dicts and signers from an :class:`AuthConfig`.

The ``oci`` package is imported lazily so the rest of occfix (and its tests)
never pay the import cost unless a real gateway is constructed.
"""

from __future__ import annotations

import os
import stat

from occfix.config import AuthConfig
from occfix.models import AuthError, ConfigError


def build_oci_config_and_signer(auth: AuthConfig) -> tuple[dict, object | None]:
    """Return an ``(oci_config, signer)`` pair usable to build OCI clients.

    ``signer`` is ``None`` for API-key based auth; otherwise it is an OCI
    security-token/principals signer to pass as ``signer=`` to the clients.
    """

    try:
        import oci  # noqa: PLC0415 - lazy import keeps the SDK off the hot path
    except ImportError as exc:  # pragma: no cover - environment specific
        raise ConfigError(f"the 'oci' SDK is required for real auth: {exc}") from exc

    method = (auth.method or "key_file").strip().lower()

    if method == "key_file":
        return _key_file(oci, auth)
    if method == "instance_principal":
        return _instance_principal(oci)
    if method == "resource_principal":
        return _resource_principal(oci)
    if method in ("session_token", "security_token"):
        return _session_token(oci, auth)
    if method == "env":
        return _env(oci)
    raise AuthError(f"unknown auth method: {auth.method!r}", code="UnknownAuthMethod")


def _key_file(oci, auth: AuthConfig) -> tuple[dict, None]:
    try:
        config = oci.config.from_file(auth.oci_config_path, auth.oci_profile)
    except Exception as exc:
        raise AuthError(
            f"failed to load OCI config from {auth.oci_config_path!r} "
            f"(profile {auth.oci_profile!r}): {exc}",
            code="ConfigLoadFailed",
        ) from exc
    return config, None


def _instance_principal(oci) -> tuple[dict, object]:
    try:
        signer = oci.auth.signers.InstancePrincipalsSecurityTokenSigner()
    except Exception as exc:
        raise AuthError(
            f"failed to build instance principals signer: {exc}",
            code="InstancePrincipalFailed",
        ) from exc
    config = {"region": signer.region} if getattr(signer, "region", None) else {}
    return config, signer


def _resource_principal(oci) -> tuple[dict, object]:
    try:
        signer = oci.auth.signers.get_resource_principals_signer()
    except Exception as exc:
        raise AuthError(
            f"failed to build resource principals signer: {exc}",
            code="ResourcePrincipalFailed",
        ) from exc
    config = {"region": signer.region} if getattr(signer, "region", None) else {}
    return config, signer


def _session_token(oci, auth: AuthConfig) -> tuple[dict, object]:
    try:
        config = oci.config.from_file(auth.oci_config_path, auth.oci_profile)
    except Exception as exc:
        raise AuthError(
            f"failed to load OCI config from {auth.oci_config_path!r} "
            f"(profile {auth.oci_profile!r}): {exc}",
            code="ConfigLoadFailed",
        ) from exc

    token_file = config.get("security_token_file")
    if not token_file:
        raise AuthError(
            "session_token auth requires 'security_token_file' in the OCI config",
            code="MissingSecurityTokenFile",
        )
    try:
        token = _read_text(os.path.expanduser(token_file))
        private_key = oci.signer.load_private_key_from_file(config["key_file"])
        signer = oci.auth.signers.SecurityTokenSigner(token, private_key)
    except Exception as exc:
        raise AuthError(
            f"failed to build security token signer: {exc}",
            code="SecurityTokenFailed",
        ) from exc
    return config, signer


def _env(oci) -> tuple[dict, None]:
    required = {
        "user": "OCI_USER",
        "fingerprint": "OCI_FINGERPRINT",
        "tenancy": "OCI_TENANCY",
        "region": "OCI_REGION",
    }
    config: dict = {}
    missing: list[str] = []
    for key, env_name in required.items():
        value = os.environ.get(env_name, "")
        if not value:
            missing.append(env_name)
        config[key] = value

    key_file = os.environ.get("OCI_KEY_FILE", "")
    key_content = os.environ.get("OCI_KEY_CONTENT", "")
    if key_file:
        config["key_file"] = os.path.expanduser(key_file)
    elif key_content:
        config["key_content"] = key_content
    else:
        missing.append("OCI_KEY_FILE|OCI_KEY_CONTENT")

    if missing:
        raise AuthError(
            "missing required environment variables for env auth: " + ", ".join(missing),
            code="MissingEnvConfig",
        )

    try:
        oci.config.validate_config(config)
    except Exception as exc:
        raise AuthError(
            f"invalid OCI config from environment: {exc}",
            code="InvalidEnvConfig",
        ) from exc
    return config, None


def _read_text(path: str) -> str:
    with open(path, encoding="utf-8") as handle:
        return handle.read()


def key_file_permission_warning(path: str) -> str | None:
    """Warn if the PEM at ``path`` is group/world readable (POSIX, best-effort)."""

    try:
        mode = os.stat(path).st_mode
    except OSError:
        return None
    if mode & (stat.S_IRGRP | stat.S_IWGRP | stat.S_IROTH | stat.S_IWOTH):
        return (
            f"private key {path!r} is group/world accessible "
            f"({stat.filemode(mode)}); tighten with 'chmod 600'"
        )
    return None
