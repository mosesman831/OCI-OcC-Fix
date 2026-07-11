"""Unit tests for :mod:`occfix.gateway_real` and :mod:`occfix.auth`.

All OCI access is faked; no live calls or real credentials are used.
"""

from __future__ import annotations

import os
from types import SimpleNamespace

import oci
import pytest

from occfix.auth import build_oci_config_and_signer, key_file_permission_warning
from occfix.config import AuthConfig
from occfix.gateway_real import RealOciGateway
from occfix.models import (
    AuthError,
    CapacityError,
    InstanceInfo,
    LaunchSpec,
    ThrottleError,
    VolumeInfo,
)


def _resp(data):
    return SimpleNamespace(data=data)


class FakeCompute:
    def __init__(self, *, instances=None, launch=None, vnic_attachments=None):
        self._instances = instances or []
        self._launch = launch
        self._vnic_attachments = vnic_attachments or []
        self.launch_calls: list[dict] = []

    def list_instances(self, compartment_id):
        return _resp(self._instances)

    def launch_instance(self, details, opc_retry_token=None):
        self.launch_calls.append({"details": details, "opc_retry_token": opc_retry_token})
        if isinstance(self._launch, Exception):
            raise self._launch
        return _resp(SimpleNamespace(id=self._launch))

    def list_vnic_attachments(self, compartment_id, instance_id):
        return _resp(self._vnic_attachments)


class FakeIdentity:
    def __init__(self, *, ads=None, tenancy_name="acme"):
        self._ads = ads or []
        self._tenancy_name = tenancy_name

    def list_availability_domains(self, compartment_id):
        return _resp([SimpleNamespace(name=n) for n in self._ads])

    def get_tenancy(self, tenancy_id):
        return _resp(SimpleNamespace(name=self._tenancy_name))


class FakeNetwork:
    def __init__(self, *, private_ips=None, public_ip=None):
        self._private_ips = private_ips or []
        self._public_ip = public_ip

    def list_private_ips(self, vnic_id):
        return _resp(self._private_ips)

    def get_public_ip_by_private_ip_id(self, details):
        return _resp(SimpleNamespace(ip_address=self._public_ip))


class FakeBlockstorage:
    def __init__(self, *, volumes=None, boot_volumes=None):
        self._volumes = volumes or []
        self._boot_volumes = boot_volumes or []

    def list_volumes(self, compartment_id):
        return _resp(self._volumes)

    def list_boot_volumes(self, compartment_id, availability_domain):
        return _resp(self._boot_volumes)


def _spec(**overrides) -> LaunchSpec:
    base = dict(
        name="t1",
        region="us-ashburn-1",
        availability_domains=["AD-1"],
        shape="VM.Standard.A1.Flex",
        ocpus=4,
        memory=24,
        compartment_id="ocid1.compartment.oc1..cmp",
        subnet_id="ocid1.subnet.oc1..sub",
        display_name="occ-instance",
        ssh_keys="ssh-rsa AAAA",
        image_id="ocid1.image.oc1..img",
        boot_volume_id="xxxx",
        boot_volume_size=50,
    )
    base.update(overrides)
    return LaunchSpec(**base)


def _gateway(**clients) -> RealOciGateway:
    return RealOciGateway(
        clients.get("compute", FakeCompute()),
        clients.get("identity", FakeIdentity()),
        clients.get("network", FakeNetwork()),
        clients.get("blockstorage", FakeBlockstorage()),
    )


def _service_error(code, status):
    return oci.exceptions.ServiceError(
        status=status,
        code=code,
        headers={},
        message=f"{code} occurred",
    )


def test_list_availability_domains():
    gw = _gateway(identity=FakeIdentity(ads=["AD-1", "AD-2"]))
    assert gw.list_availability_domains("cmp") == ["AD-1", "AD-2"]


def test_list_volumes_maps_to_volume_info():
    blk = FakeBlockstorage(
        volumes=[
            SimpleNamespace(size_in_gbs=100, lifecycle_state="AVAILABLE"),
            SimpleNamespace(size_in_gbs=50, lifecycle_state="TERMINATED"),
        ]
    )
    gw = _gateway(blockstorage=blk)
    volumes = gw.list_volumes("cmp")
    assert volumes == [
        VolumeInfo(size_in_gbs=100, lifecycle_state="AVAILABLE"),
        VolumeInfo(size_in_gbs=50, lifecycle_state="TERMINATED"),
    ]
    assert volumes[0].is_active and not volumes[1].is_active


def test_list_boot_volumes_maps_and_strips_ad():
    blk = FakeBlockstorage(
        boot_volumes=[SimpleNamespace(size_in_gbs=47, lifecycle_state="AVAILABLE")]
    )
    gw = _gateway(blockstorage=blk)
    result = gw.list_boot_volumes("cmp", " AD-1 ")
    assert result == [VolumeInfo(size_in_gbs=47, lifecycle_state="AVAILABLE")]


def test_list_instances_maps_to_instance_info():
    compute = FakeCompute(
        instances=[
            SimpleNamespace(
                display_name="a1",
                lifecycle_state="RUNNING",
                shape="VM.Standard.A1.Flex",
                shape_config=SimpleNamespace(ocpus=2.0, memory_in_gbs=12.0),
            ),
            SimpleNamespace(
                display_name="a2",
                lifecycle_state="STOPPED",
                shape="VM.Standard.E2.1.Micro",
                shape_config=None,
            ),
        ]
    )
    gw = _gateway(compute=compute)
    instances = gw.list_instances("cmp")
    assert instances[0] == InstanceInfo(
        display_name="a1",
        lifecycle_state="RUNNING",
        shape="VM.Standard.A1.Flex",
        ocpus=2.0,
        memory_in_gbs=12.0,
    )
    assert instances[1].ocpus == 0.0 and instances[1].memory_in_gbs == 0.0


def test_get_tenancy_name():
    gw = _gateway(identity=FakeIdentity(tenancy_name="my-tenancy"))
    assert gw.get_tenancy_name("ocid1.tenancy.oc1..t") == "my-tenancy"


def test_launch_instance_success_returns_ocid_and_passes_retry_token():
    compute = FakeCompute(launch="ocid1.instance.oc1..new")
    gw = _gateway(compute=compute)
    ocid = gw.launch_instance(_spec(), "AD-1", "retry-token-123")
    assert ocid == "ocid1.instance.oc1..new"
    assert compute.launch_calls[0]["opc_retry_token"] == "retry-token-123"


def test_launch_instance_uses_image_source_when_no_boot_volume():
    compute = FakeCompute(launch="ocid1.instance.oc1..new")
    gw = _gateway(compute=compute)
    gw.launch_instance(_spec(boot_volume_id="xxxx"), "AD-1", "tok")
    source = compute.launch_calls[0]["details"].source_details
    assert isinstance(source, oci.core.models.InstanceSourceViaImageDetails)


def test_launch_instance_uses_boot_volume_source():
    compute = FakeCompute(launch="ocid1.instance.oc1..new")
    gw = _gateway(compute=compute)
    gw.launch_instance(_spec(boot_volume_id="ocid1.bootvolume.oc1..bv"), "AD-1", "tok")
    source = compute.launch_calls[0]["details"].source_details
    assert isinstance(source, oci.core.models.InstanceSourceViaBootVolumeDetails)
    assert source.boot_volume_id == "ocid1.bootvolume.oc1..bv"


def test_launch_instance_capacity_error():
    compute = FakeCompute(launch=_service_error("OutOfHostCapacity", 500))
    gw = _gateway(compute=compute)
    with pytest.raises(CapacityError) as excinfo:
        gw.launch_instance(_spec(), "AD-1", "tok")
    assert excinfo.value.code == "OutOfHostCapacity"


def test_launch_instance_throttle_error_by_code_and_status():
    for code, status in (("TooManyRequests", 429), ("SomethingElse", 429)):
        compute = FakeCompute(launch=_service_error(code, status))
        gw = _gateway(compute=compute)
        with pytest.raises(ThrottleError):
            gw.launch_instance(_spec(), "AD-1", "tok")


def test_launch_instance_parses_retry_after_header():
    err = oci.exceptions.ServiceError(
        status=429,
        code="TooManyRequests",
        headers={"retry-after": "12"},
        message="slow down",
    )
    compute = FakeCompute(launch=err)
    gw = _gateway(compute=compute)
    with pytest.raises(ThrottleError) as excinfo:
        gw.launch_instance(_spec(), "AD-1", "tok")
    assert excinfo.value.retry_after == 12.0


def test_get_public_ip_via_fake_chain():
    compute = FakeCompute(vnic_attachments=[SimpleNamespace(vnic_id="ocid1.vnic.oc1..v")])
    network = FakeNetwork(
        private_ips=[SimpleNamespace(id="ocid1.privateip.oc1..p")],
        public_ip="203.0.113.42",
    )
    gw = _gateway(compute=compute, network=network)
    assert gw.get_public_ip("cmp", "ocid1.instance.oc1..i") == "203.0.113.42"


def test_get_public_ip_returns_none_on_failure():
    gw = _gateway(compute=FakeCompute(vnic_attachments=[]))
    assert gw.get_public_ip("cmp", "ocid1.instance.oc1..i") is None


def test_build_oci_config_unknown_method_raises_auth_error():
    with pytest.raises(AuthError):
        build_oci_config_and_signer(AuthConfig(method="does_not_exist"))


def test_key_file_permission_warning_flags_world_readable(tmp_path):
    pem = tmp_path / "key.pem"
    pem.write_text("-----BEGIN PRIVATE KEY-----\n")
    os.chmod(pem, 0o644)
    warning = key_file_permission_warning(str(pem))
    assert warning is not None
    assert "chmod 600" in warning


def test_key_file_permission_warning_ok_for_secure_file(tmp_path):
    pem = tmp_path / "key.pem"
    pem.write_text("-----BEGIN PRIVATE KEY-----\n")
    os.chmod(pem, 0o600)
    assert key_file_permission_warning(str(pem)) is None
