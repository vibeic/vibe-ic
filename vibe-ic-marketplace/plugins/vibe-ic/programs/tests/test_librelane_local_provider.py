"""Bounded LOCAL LibreLane provider contract.

The LOCAL provider is an already-attested host tool/PDK tree.  It must be
resolved before the Docker image resolver and must never turn a host receipt
into an image claim.
"""
from __future__ import annotations

import json
import socket
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
import _container_exec as container_exec  # noqa: E402
import _eda_pin  # noqa: E402
import librelane_contract as contract  # noqa: E402


def _receipt(tmp_path: Path) -> tuple[Path, Path, Path]:
    tools = tmp_path / "tools"
    pdk_root = tmp_path / "pdks"
    pdk = pdk_root / "gf180mcuD"
    (tools / "bin").mkdir(parents=True)
    pdk.mkdir(parents=True)
    receipt = tmp_path / "local-provider.json"
    receipt.write_text(json.dumps({
        "schema": "vibeic/librelane-local-provider/1",
        "execution_route": "LOCAL",
        "hostname": socket.gethostname(),
        "tool_root": str(tools),
        "pdk_root": str(pdk_root),
        "pdk": "gf180mcuD",
        "tool_identity": {"root": str(tools)},
        "pdk_identity": {"root": str(pdk_root), "name": "gf180mcuD"},
    }) + "\n")
    return receipt, tools, pdk_root


@pytest.fixture
def local_provider(tmp_path, monkeypatch):
    receipt, tools, pdk_root = _receipt(tmp_path)
    monkeypatch.setenv(contract.LOCAL_PROVIDER_RECEIPT_ENV, str(receipt))
    monkeypatch.setenv(contract.LOCAL_EXECUTION_ROUTE_ENV, "LOCAL")
    monkeypatch.delenv("VIBEIC_LIBRELANE_IMAGE", raising=False)
    monkeypatch.delenv("VIBEIC_EDA_IMAGE", raising=False)
    monkeypatch.delenv("VIBEIC_LIBRELANE_PDK_ROOT", raising=False)
    # This is an explicit provider route on a host that still has docker.
    monkeypatch.setattr(container_exec, "no_container_route", lambda: False)
    return receipt, tools, pdk_root


def test_local_provider_resolves_before_docker_image(local_provider, tmp_path, monkeypatch):
    receipt, tools, pdk_root = local_provider

    def no_image(*_args, **_kwargs):
        raise _eda_pin.ImageNotResolvable(["fixture: no image is present"])

    monkeypatch.setattr(_eda_pin, "image_reference", no_image)
    project = tmp_path / "project"
    (project / "phase3").mkdir(parents=True)

    assert contract.resolve_image(project) == contract.LOCAL_EXECUTION_IDENTITY
    image_provenance = json.loads(
        (project / "phase3/librelane_image.provenance.json").read_text())
    assert image_provenance["execution_route"] == "LOCAL"
    assert image_provenance["image"] is None
    assert image_provenance["tool_root"] == str(tools)

    answer = contract.pdk_root_resolution(project, "gf180mcuD")
    assert answer["path"] == str(pdk_root)
    assert answer["source"] == "resolved_local"
    assert answer["derivation"]["execution_route"] == "LOCAL"
    assert answer["derivation"]["pdk"] == "gf180mcuD"


def test_local_provider_runs_without_inserting_an_image(local_provider, monkeypatch):
    receipt, tools, _pdk_root = local_provider
    marker = tools / "ran.txt"
    result = contract.run_container(
        ["docker", "run", "--rm", "--entrypoint", sys.executable,
         contract.LOCAL_EXECUTION_IDENTITY, "-c",
         f"from pathlib import Path; Path({str(marker)!r}).write_text('ok')"],
        probe_deadline_s=5)
    assert result.returncode == 0
    assert marker.read_text() == "ok"
    assert json.loads(receipt.read_text())["execution_route"] == "LOCAL"


def test_local_provider_accepts_the_existing_receipt_variable(local_provider, monkeypatch):
    receipt, _tools, _pdk_root = local_provider
    monkeypatch.delenv(contract.LOCAL_PROVIDER_RECEIPT_ENV)
    monkeypatch.setenv(contract.LOCAL_ATTESTATION_ENV, str(receipt))
    assert contract.resolve_image() == contract.LOCAL_EXECUTION_IDENTITY


def test_local_provider_switch_receipt_reaches_the_native_child(local_provider, monkeypatch, tmp_path):
    receipt, tools, _pdk_root = local_provider
    monkeypatch.delenv(contract.LOCAL_PROVIDER_RECEIPT_ENV)
    monkeypatch.delenv(contract.LOCAL_EXECUTION_ROUTE_ENV)
    project = tmp_path / "project"
    (project / "phase3").mkdir(parents=True)
    (project / "phase3/librelane_switch.json").write_text(
        json.dumps({"local_provider_receipt": str(receipt)}) + "\n")
    marker = tools / "switch-child.txt"
    result = contract.run_container(
        ["docker", "run", "--rm", "--entrypoint", sys.executable,
         contract.LOCAL_EXECUTION_IDENTITY, "-c",
         f"from pathlib import Path; Path({str(marker)!r}).write_text('ok')"],
        probe_deadline_s=5, local_provider_project=project)
    assert result.returncode == 0
    assert marker.read_text() == "ok"


def test_local_provider_missing_receipt_refuses_without_image_fallback(local_provider, monkeypatch):
    monkeypatch.delenv(contract.LOCAL_PROVIDER_RECEIPT_ENV)
    monkeypatch.delenv(contract.LOCAL_ATTESTATION_ENV, raising=False)
    monkeypatch.setattr(_eda_pin, "image_reference",
                        lambda: pytest.fail("LOCAL provider must not resolve a Docker image"))
    with pytest.raises(contract.Refusal, match="LL_LOCAL_PROVIDER_UNATTESTED"):
        contract.resolve_image()


@pytest.mark.parametrize("mutation", ["hostname", "tool_root", "pdk_root", "pdk"])
def test_local_provider_stale_or_unbound_receipt_refuses(local_provider, mutation):
    receipt, _tools, _pdk_root = local_provider
    record = json.loads(receipt.read_text())
    if mutation == "hostname":
        record["hostname"] = "different-host"
    elif mutation == "tool_root":
        record["tool_root"] = "/stale/tools"
        record["tool_identity"]["root"] = "/stale/tools"
    elif mutation == "pdk_root":
        record["pdk_root"] = "/stale/pdks"
        record["pdk_identity"]["root"] = "/stale/pdks"
    else:
        record["pdk"] = "other-pdk"
    receipt.write_text(json.dumps(record) + "\n")
    with pytest.raises(contract.Refusal, match="LL_LOCAL_PROVIDER_UNATTESTED"):
        contract.resolve_image()


def test_local_provider_rejects_an_explicit_image_binding(local_provider):
    with pytest.raises(contract.Refusal, match="LL_LOCAL_IMAGE_UNBOUND"):
        contract.pdk_root_resolution(None, "gf180mcuD", image="sha256:" + "a" * 64)


def test_local_provider_rejects_a_switch_image_binding(local_provider, tmp_path):
    receipt, _tools, _pdk_root = local_provider
    project = tmp_path / "project"
    (project / "phase3").mkdir(parents=True)
    (project / "phase3/librelane_switch.json").write_text(json.dumps({
        "local_provider_receipt": str(receipt),
        "image": "sha256:" + "b" * 64,
    }) + "\n")
    with pytest.raises(contract.Refusal, match="LL_LOCAL_IMAGE_UNBOUND"):
        contract.resolve_image(project)
