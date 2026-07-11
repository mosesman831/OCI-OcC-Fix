"""Abstract OCI gateway interface + an in-memory fake for tests.

All OCI access flows through :class:`OciGateway`, so the rest of the engine can
be unit tested without a live tenancy. The real implementation lives in
``occfix.gateway_real`` to keep the heavy ``oci`` import out of the hot path and
tests.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable, Sequence

from occfix.models import (
    AuthError,
    InstanceInfo,
    LaunchError,
    LaunchSpec,
    VolumeInfo,
)


class OciGateway(ABC):
    """Interface every gateway (real or fake) must implement."""

    @abstractmethod
    def list_availability_domains(self, compartment_id: str) -> list[str]:
        """Return AD names for the compartment/tenancy."""

    @abstractmethod
    def list_volumes(self, compartment_id: str) -> list[VolumeInfo]:
        """List block volumes in a compartment."""

    @abstractmethod
    def list_boot_volumes(self, compartment_id: str, availability_domain: str) -> list[VolumeInfo]:
        """List boot volumes in a compartment + AD."""

    @abstractmethod
    def list_instances(self, compartment_id: str) -> list[InstanceInfo]:
        """List compute instances in a compartment."""

    @abstractmethod
    def launch_instance(self, spec: LaunchSpec, availability_domain: str, retry_token: str) -> str:
        """Attempt to launch an instance; return its OCID on success.

        Must raise a :class:`~occfix.models.LaunchError` subclass on failure so
        callers can classify the outcome.
        """

    @abstractmethod
    def get_public_ip(self, compartment_id: str, instance_id: str) -> str | None:
        """Return the public IP for a launched instance, if any."""

    @abstractmethod
    def get_tenancy_name(self, tenancy_id: str) -> str:
        """Return a human-readable tenancy name (best-effort)."""


# A scripted launch step for the fake: either an OCID string to return, or a
# LaunchError to raise, or a callable producing one of those.
LaunchStep = str | LaunchError | Callable[[LaunchSpec, str], "str | LaunchError"]


class FakeOciGateway(OciGateway):
    """Deterministic in-memory gateway for tests.

    ``launch_script`` is consumed one entry per :meth:`launch_instance` call.
    When exhausted, the ``default_launch`` behaviour is used.
    """

    def __init__(
        self,
        *,
        availability_domains: Sequence[str] | None = None,
        volumes: Sequence[VolumeInfo] | None = None,
        boot_volumes: Sequence[VolumeInfo] | None = None,
        instances: Sequence[InstanceInfo] | None = None,
        launch_script: Sequence[LaunchStep] | None = None,
        default_launch: LaunchStep | None = None,
        tenancy_name: str = "fake-tenancy",
        public_ip: str = "203.0.113.10",
    ) -> None:
        self._ads = list(availability_domains or ["FAKE:AD-1", "FAKE:AD-2"])
        self._volumes = list(volumes or [])
        self._boot_volumes = list(boot_volumes or [])
        self._instances = list(instances or [])
        self._script = list(launch_script or [])
        self._default = default_launch
        self._tenancy_name = tenancy_name
        self._public_ip = public_ip

        # Introspection for assertions in tests.
        self.launch_calls: list[tuple[str, str]] = []  # (availability_domain, retry_token)
        self.retry_tokens: list[str] = []

    # -- read APIs -------------------------------------------------------
    def list_availability_domains(self, compartment_id: str) -> list[str]:
        return list(self._ads)

    def list_volumes(self, compartment_id: str) -> list[VolumeInfo]:
        return list(self._volumes)

    def list_boot_volumes(self, compartment_id: str, availability_domain: str) -> list[VolumeInfo]:
        return list(self._boot_volumes)

    def list_instances(self, compartment_id: str) -> list[InstanceInfo]:
        return list(self._instances)

    def get_public_ip(self, compartment_id: str, instance_id: str) -> str | None:
        return self._public_ip

    def get_tenancy_name(self, tenancy_id: str) -> str:
        return self._tenancy_name

    # -- launch ----------------------------------------------------------
    def launch_instance(self, spec: LaunchSpec, availability_domain: str, retry_token: str) -> str:
        self.launch_calls.append((availability_domain, retry_token))
        self.retry_tokens.append(retry_token)

        step: LaunchStep | None
        if self._script:
            step = self._script.pop(0)
        else:
            step = self._default

        return self._resolve(step, spec, availability_domain)

    def _resolve(self, step: LaunchStep | None, spec: LaunchSpec, ad: str) -> str:
        if step is None:
            raise AuthError("no launch step configured", code="FakeNoStep")
        if callable(step):
            step = step(spec, ad)
        if isinstance(step, LaunchError):
            raise step
        if isinstance(step, str):
            self._instances.append(
                InstanceInfo(
                    display_name=spec.display_name,
                    lifecycle_state="RUNNING",
                    shape=spec.shape,
                    ocpus=spec.ocpus,
                    memory_in_gbs=spec.memory,
                )
            )
            return step
        raise TypeError(f"unsupported launch step: {step!r}")
