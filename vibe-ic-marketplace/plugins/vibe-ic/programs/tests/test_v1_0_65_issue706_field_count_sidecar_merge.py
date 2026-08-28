#!/usr/bin/env python3
"""ORGANIC #706 (LOW/P3 hardening) — l_doc_structured_field_count_check must
honor the SAME `phase1/ai_deep_review_patches.json` sidecar its sibling
phase1_doc_input_completeness_check already merges.

LATENT ASYMMETRY: both phase-1 doc-floor gates read the same
generated_docs/L*.json, but only the completeness gate merged the durable AI
deep-review sidecar (the home of MANDATORY AI recoveries — generated_docs/L*.json
is rewritten every Phase-1 run, so a recovered field survives ONLY in the
sidecar). So an AI-recovered, doc-traceable TYPED field credited by the
completeness gate could not satisfy a typed-field COUNT floor (L6 fsm_states,
L3 opcodes, L4 registers, L9 ports) — a future false-FAIL.

FIX: a fail-closed sidecar merge in the count gate — only entries carrying the
typed SHAPE the floor requires (name + a substantive shape key) are credited.

§4.05 NO-LEAK (this RELAXES a gate): a genuinely thin doc with NO qualifying
sidecar entry still FAILs/waives exactly as before (the ibex run that surfaced
this is a CORRECT FAIL — its 2nd FSM state is RTL-only, not doc-traceable). A
BARE-token sidecar entry (name only, no shape) cannot inflate a count floor, and
an UNMARKED entry (no ai_deep_review_patch strategy) is never even loaded.

chip-AGNOSTIC: sidecar channel + typed-shape grammar; no chip/vendor literal.
"""
import json
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import l_doc_structured_field_count_check as G  # noqa: E402
import _path_layout as _pl  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

PROG = _PROGRAMS / "l_doc_structured_field_count_check.py"


# ── defect-artifact fixture builder (the issue's 現象) ───────────────────────
def _build_defect_fixture(tmp_path, *, ic_class="processor_cpu",
                          l6_states=None, sidecar_patches=None):
    """Shape a project like the round-7 RISC-V 現象: a processor_cpu (l6_min=2)
    whose L6 doc carries only 1 typed FSM state, optionally with an
    ai_deep_review_patches sidecar. Returns the project dir."""
    proj = tmp_path / "proj"
    gd = _pl.generated_docs_dir(proj)
    gd.mkdir(parents=True, exist_ok=True)
    (proj / "reports").mkdir(parents=True, exist_ok=True)
    (proj / "reports" / "ic_class.json").write_text(json.dumps(
        {"ic_class": ic_class, "has_command_protocol": False}))
    states = l6_states if l6_states is not None else [
        {"name": "IDLE", "transitions": ["start->BUSY"]}]
    (gd / "L6_CONTROL_LOGIC.json").write_text(json.dumps(
        {"schema_version": 1, "layer": 6, "fsm_states": states}))
    if sidecar_patches is not None:
        side = _pl.phase1_ai_deep_review_patches_file(proj)
        side.parent.mkdir(parents=True, exist_ok=True)
        side.write_text(json.dumps({"patches": sidecar_patches}))
    return proj


def _run(proj):
    return subprocess.run([sys.executable, str(PROG), str(proj)],
                          capture_output=True, text=True)


_AI = "ai_deep_review_patch"


def _typed_state(name="BUSY"):
    return {"name": name, "transitions": ["done->IDLE"],
            "actions": ["assert valid"], "extraction_strategy": _AI}


# ── END-STATE (the real gate, the 現象 artifact) ─────────────────────────────
def test_phenomenon_without_sidecar_still_FAILs(tmp_path):
    """The ibex 現象: 1 doc-traceable state, no sidecar → CORRECT FAIL (rc 1)."""
    proj = _build_defect_fixture(tmp_path)
    r = _run(proj)
    assert r.returncode == 1, r.stdout
    assert "have 1" in r.stdout and "fsm_states" in r.stdout, r.stdout


def test_typed_sidecar_recovers_the_floor_PASS(tmp_path):
    """A typed AI-recovered 2nd state in the sidecar is now credited → PASS."""
    proj = _build_defect_fixture(
        tmp_path, sidecar_patches={"L6_CONTROL_LOGIC": [_typed_state()]})
    r = _run(proj)
    assert r.returncode == 0, r.stdout
    assert "PASS" in r.stdout, r.stdout


def test_noleak_bare_token_sidecar_still_FAILs(tmp_path):
    """§4.05: a BARE token (name only, no transitions/actions shape) cannot
    inflate the count floor → still FAIL (rc 1)."""
    proj = _build_defect_fixture(
        tmp_path,
        sidecar_patches={"L6_CONTROL_LOGIC": [
            {"name": "BUSY", "extraction_strategy": _AI}]})
    r = _run(proj)
    assert r.returncode == 1, r.stdout
    assert "have 1" in r.stdout, r.stdout


def test_noleak_unmarked_sidecar_entry_not_credited(tmp_path):
    """§4.05: a typed entry WITHOUT the ai_deep_review_patch marker is not the
    AI-recovery channel → not loaded, not credited → still FAIL."""
    proj = _build_defect_fixture(
        tmp_path,
        sidecar_patches={"L6_CONTROL_LOGIC": [
            {"name": "BUSY", "transitions": ["x"]}]})  # no marker
    r = _run(proj)
    assert r.returncode == 1, r.stdout


def test_noleak_no_sidecar_file_is_noop(tmp_path):
    """No sidecar file at all → loader returns {} and the verdict is unchanged
    (the sidecar is purely additive)."""
    proj = _build_defect_fixture(tmp_path)
    assert not _pl.phase1_ai_deep_review_patches_file(proj).is_file()
    assert _run(proj).returncode == 1


# ── unit-level: the merge / shape / loader helpers ──────────────────────────
def test_merge_preserves_existing_alias_and_appends():
    data = {"layer": 6, "states": [{"name": "IDLE", "transitions": ["a"]}]}
    G._merge_sidecar_for_layer(6, data, {6: [_typed_state("RUN")]})
    # appended into the SAME alias _check_l_doc reads first (non-empty `states`)
    assert [s["name"] for s in data["states"]] == ["IDLE", "RUN"]
    assert "fsm_states" not in data  # did not split into a new alias


def test_merge_creates_canonical_when_all_aliases_empty():
    data = {"layer": 6, "fsm_states": [], "states": []}
    G._merge_sidecar_for_layer(6, data, {6: [_typed_state("RUN")]})
    assert [s["name"] for s in data["fsm_states"]] == ["RUN"]


def test_typed_patch_ok_requires_name_and_shape():
    nk, sk = ("name", "state"), ("transitions", "actions")
    assert G._typed_patch_ok({"name": "X", "transitions": ["t"]}, nk, sk)
    assert not G._typed_patch_ok({"name": "X"}, nk, sk)          # no shape
    assert not G._typed_patch_ok({"transitions": ["t"]}, nk, sk)  # no name
    assert not G._typed_patch_ok({"name": "", "actions": ["a"]}, nk, sk)


def test_is_ai_patch_entry_marker_keys():
    assert G._is_ai_patch_entry({"extraction_strategy": _AI})
    assert G._is_ai_patch_entry({"label": _AI})
    assert G._is_ai_patch_entry({"strategy": _AI})
    assert not G._is_ai_patch_entry({"extraction_strategy": "program"})
    assert not G._is_ai_patch_entry("not a dict")


def test_loader_filters_unmarked_and_maps_layer(tmp_path):
    proj = tmp_path / "p"
    side = _pl.phase1_ai_deep_review_patches_file(proj)
    side.parent.mkdir(parents=True, exist_ok=True)
    side.write_text(json.dumps({"patches": {
        "L6_CONTROL_LOGIC": [_typed_state(), {"name": "nomarker"}],
        "L9_INTEGRATION_SPEC": [
            {"name": "clk", "dir": "input", "width": 1,
             "extraction_strategy": _AI}],
    }}))
    out = G._load_field_count_sidecar(proj)
    assert sorted(out) == [6, 9]
    assert len(out[6]) == 1  # the unmarked entry is dropped at load
    assert out[6][0]["name"] == "BUSY"


def test_loader_missing_file_returns_empty(tmp_path):
    assert G._load_field_count_sidecar(tmp_path / "absent") == {}


def test_other_layer_floor_also_honors_sidecar_L9_ports():
    """The merge is general — L9 ports get the same fail-closed credit."""
    data = {"layer": 9, "top_module": "top", "ports": [
        {"name": "clk", "dir": "input", "width": 1}]}
    G._merge_sidecar_for_layer(9, data, {9: [
        {"name": "rst", "dir": "input", "width": 1,
         "extraction_strategy": _AI}]})
    assert [p["name"] for p in data["ports"]] == ["clk", "rst"]


def test_chip_agnostic_guard():
    prog = _PROGRAMS / "source_chip_agnostic_check.py"
    r = _pr.run([sys.executable, str(prog), str(_PROGRAMS.parent)],
               capture_output=True, text=True)
    assert r.returncode == 0, r.stdout[-1500:] + r.stderr[-400:]


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
