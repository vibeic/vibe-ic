"""The ordinary A3 caller must consume real staged models without typed L19.

These are neutral software model declarations, not native model qualification.
"""
from __future__ import annotations

import json


import analog_a3_netlist_emit as A3
import analog_pdk_availability as availability


ROLES = ["nmos", "pmos", "cap", "res"]
DEVICES = {"nmos": "neutral_nch", "pmos": "neutral_pch",
           "cap": "neutral_cap", "res": "neutral_res"}


def staged_project(root, *, include_cap=True, declared=None):
    models = root / "input/pdk/models"
    models.mkdir(parents=True)
    text = (".LIB dev_tt\n"
            ".subckt neutral_nch d g s b w=1u l=1u\n.ends\n"
            ".subckt neutral_pch d g s b w=1u l=1u\n.ends\n"
            ".subckt neutral_res p n bn w=2u l=10u\n.ends\n")
    if include_cap:
        text += ".subckt neutral_cap p n w=10u l=10u\n.ends\n"
    (models / "corner_devices.lib").write_text(text + ".ENDL dev_tt\n")
    if declared:
        path = root / "phase1/generated_docs/L19_CONSTRAINTS_PDK.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"fields": {"pdk_target": declared}}))
    return root


def test_no_l19_staged_models_reach_the_ordinary_context(tmp_path):
    project = staged_project(tmp_path)
    context = A3.resolve_pdk_context(project, "neutral_process", "", ROLES)
    assert context["status"] == "OK", context
    assert context["role_models"] == DEVICES
    assert context["model_lib"] == str(project / "input/pdk/models/corner_devices.lib")
    assert context["cross_pdk_bindings"] == []


def test_staged_models_missing_a_required_role_are_not_accepted(tmp_path):
    project = staged_project(tmp_path, include_cap=False)
    context = A3.resolve_pdk_context(project, "neutral_process", "", ROLES)
    assert context["status"] != "OK", context
    assert "cap" in context["unresolved_roles"]
    assert "cap" not in context["role_models"]


def test_declared_family_still_owns_identity_over_a_conflicting_request(tmp_path):
    project = staged_project(tmp_path, declared="declared_process")
    context = A3.resolve_pdk_context(project, "requested_other_process", "", ROLES)
    assert context["status"] == "OK", context
    assert context["family"] == "declaredprocess"
    assert context["role_models"] == DEVICES
    assert not A3.pdk_request_is_bound("requested_other_process", context["family"],
                                      context.get("registry_family"))


def test_no_l19_or_assets_keeps_legacy_refusal_without_native_probes(tmp_path, monkeypatch):
    probes = []

    def forbidden_probe(*args, **kwargs):
        probes.append((args, kwargs))
        raise AssertionError("no target or assets must not probe an installed runtime")

    monkeypatch.setattr(availability, "_docker_lister", forbidden_probe)
    monkeypatch.setattr(availability, "_local_lister", forbidden_probe)
    context = A3.resolve_pdk_context(tmp_path, "neutral_process", "unused_container", ROLES)
    assert context["status"] == A3.PDK_CROSS_BINDING
    assert context["model_lib"] is None
    assert probes == []


def test_an_injected_resolution_is_preserved(tmp_path, monkeypatch):
    project = staged_project(tmp_path)
    resolved = availability.resolve_pdk("injected_process", project=project, container="")

    def forbidden_resolution(*args, **kwargs):
        raise AssertionError("an already resolved input must not be rediscovered")

    monkeypatch.setattr(availability, "resolve_pdk", forbidden_resolution)
    context = A3.resolve_pdk_context(project, "injected_process", "", ROLES,
                                     resolution=resolved)
    assert context["status"] == "OK", context
    assert context["family"] == "injectedprocess"
    assert context["role_models"] == DEVICES


def test_resolver_image_mismatch_keeps_its_original_exception(tmp_path, monkeypatch):
    import _container_exec as container_exec

    project = staged_project(tmp_path, declared="declared_process")
    refusal = container_exec.ContainerImageMismatch("original resolver image refusal")

    def refused_resolution(*args, **kwargs):
        raise refusal

    monkeypatch.setattr(availability, "resolve_pdk", refused_resolution)
    try:
        A3.resolve_pdk_context(project, "declared_process", "", ROLES)
    except container_exec.ContainerImageMismatch as actual:
        assert actual is refusal
    else:
        raise AssertionError("resolver image refusal was converted into a model outcome")
