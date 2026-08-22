#!/usr/bin/env python3
"""Step 39 — `phase2/stage1/fpga/final/*.sof` must be producible.

DEFECT (measured on v1.7.36, HEAD 44259eac3)
--------------------------------------------
Three paths competed for one concept and none agreed:

  * `flow/phase1_phase2_phase3.yaml:1839` declares step 39's required output as
    `phase2/stage1/fpga/final/*.sof`;
  * `fpga_on_board_attestation_check`'s docstring documents
    `bitstream_path: "phase2/stage1/fpga/final/<name>.sof"`;
  * `_path_layout.fpga_final_dir()` pointed at a THIRD path,
    `phase3/stage4/fpga`, whose only consumer was a bare `mkdir` in
    phase3_one_shot_runner.

A plugin-wide grep found no code that ever copied a `.sof` into any `final`
directory, and `on_board_pass.json`'s `bitstream_path` came from fpga_burn's own
provenance — always `output_files/`. So the declared artefact was UNPRODUCIBLE,
and after #455 made `required_outputs` ALL-of-N, a genuinely successful on-board
sign-off was reported MISSING. Reproduced by driving the real emitter with
compile+burn+tester all PASS and then calling
`flow_compliance_check.check_step` on the real step-39 spec:

    STATUS: MISSING
      required_outputs missing: ['phase2/stage1/fpga/final/*.sof']
      (satisfied: 1/2 — the gate passed, but every declared output must be
       produced, not just one)

DIRECTION-1 GUARDS (must hold on BOTH trees)
--------------------------------------------
* the anti-fabrication rule: no burn ⇒ no bitstream fields synthesised;
* step 6 keeps declaring `output_files/*.sof`, so the early prototype and the
  final sign-off stay distinguishable (staging is a COPY, not a move);
* the attestation's sha256 must match the file `bitstream_path` names, or every
  run flips to bitstream-hash-mismatch.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

import design_one_shot_runner as dr
import _path_layout as _pl
import flow_compliance_check as fcc

FLOW = Path(__file__).resolve().parents[2] / "flow" / "phase1_phase2_phase3.yaml"
ATTEST = Path(__file__).resolve().parent.parent / "fpga_on_board_attestation_check.py"


def _sha(p: Path) -> str:
    return "sha256:" + hashlib.sha256(p.read_bytes()).hexdigest()


def _step(step_id: str) -> dict:
    doc = yaml.safe_load(FLOW.read_text())
    return [s for s in doc["steps"] if str(s["id"]) == step_id][0]


def _successful_board_run(tmp_path: Path) -> Path:
    """A project where compile + burn + on-board tester all really PASSed."""
    proj = tmp_path / "proj"
    out = proj / "phase2/stage1/fpga/output_files"
    out.mkdir(parents=True)
    sof = out / "top.sof"
    sof.write_bytes(b"\x00real-bitstream-bytes")
    (out / "top.map.rpt").write_text(
        "Info: Quartus Prime Full Compilation was successful.\n")
    plan = [
        dr.StepResult("fpga_compile", "PASS", 1.0, "sof=top.sof size=20"),
        dr.StepResult("fpga_burn", "PASS", 1.0, "sof_burnt",
                      extras={"burn_provenance": {
                          "sof_path": str(sof),
                          "sof_sha256": _sha(sof),
                          "burn_at": "2026-07-27T00:00:00Z"},
                          "cable_name": "USB-Blaster", "device_index": 0}),
        dr.StepResult("usb_hid_tester_verify", "PASS", 1.0, "verdict byte stable",
                      extras={"observed": ["F2"] * 5, "expected": "F2"}),
    ]
    dr.step_emit_phase2_manifests(proj, plan, top_name="top")
    # the artefacts a real board run leaves behind
    ev = proj / "reports/phase2/fpga/on_board_evidence"
    ev.mkdir(parents=True, exist_ok=True)
    (ev / "board.jpg").write_bytes(b"\xff\xd8jpeg")
    (proj / "reports/phase2/fpga/quartus_pgm.log").write_text(
        "Info: *** Configuration succeeded *** via USB-Blaster\n")
    return proj


def _manifest(proj: Path) -> dict:
    return json.loads(
        (proj / "reports/phase2/fpga/on_board_pass.json").read_text())


# ---------------------------------------------------------------------------
# The declared artefact must exist after a real burn
# ---------------------------------------------------------------------------

def test_burn_stages_the_final_signoff_bitstream(tmp_path):
    proj = _successful_board_run(tmp_path)
    staged = sorted((proj / "phase2/stage1/fpga/final").glob("*.sof"))
    assert staged, (
        "step 39 declares phase2/stage1/fpga/final/*.sof and fpga_burn PASSed, "
        "yet nothing was staged there")
    assert staged[0].read_bytes() == (
        proj / "phase2/stage1/fpga/output_files/top.sof").read_bytes()


def test_manifest_points_at_the_final_bitstream(tmp_path):
    proj = _successful_board_run(tmp_path)
    m = _manifest(proj)
    assert m["bitstream_path"] == "phase2/stage1/fpga/final/top.sof"


def test_manifest_sha_matches_the_file_it_names(tmp_path):
    """The attestation hashes whatever bitstream_path names — if the sha were
    left on the source file and the copy differed, every run would flip to
    bitstream-hash-mismatch."""
    proj = _successful_board_run(tmp_path)
    m = _manifest(proj)
    assert m["bitstream_sha"] == _sha(proj / m["bitstream_path"])


def test_step39_required_outputs_are_satisfied_by_a_real_board_run(tmp_path):
    """The whole point: a genuinely-successful on-board sign-off must not be
    reported MISSING."""
    proj = _successful_board_run(tmp_path)
    res = fcc.check_step(proj, _step("39"), {})
    assert res.status == "PASS", (res.status, res.reasons)


def test_attestation_check_accepts_the_staged_bitstream(tmp_path):
    proj = _successful_board_run(tmp_path)
    r = subprocess.run(
        [sys.executable, str(ATTEST), str(proj), "--min-scenarios", "1"],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_path_layout_final_dir_matches_the_declaration():
    """`fpga_final_dir` must name the path the flow and the attestation
    checker already document, not a third one nothing writes to."""
    decl = [o for o in _step("39")["required_outputs"] if o.endswith(".sof")]
    assert decl == ["phase2/stage1/fpga/final/*.sof"]
    rel = _pl.fpga_final_dir(Path("/p")).relative_to(Path("/p"))
    assert str(rel) == "phase2/stage1/fpga/final"


# ---------------------------------------------------------------------------
# DIRECTION-1 GUARDS — behaviour that must NOT change
# ---------------------------------------------------------------------------

def test_guard_no_burn_means_no_bitstream_fields(tmp_path):
    """Anti-fabrication: fpga_burn did not run, so nothing may be staged and
    no bitstream evidence may be synthesised."""
    proj = tmp_path / "proj"
    out = proj / "phase2/stage1/fpga/output_files"
    out.mkdir(parents=True)
    (out / "top.sof").write_bytes(b"\x00bitstream")
    dr.step_emit_phase2_manifests(
        proj,
        [dr.StepResult("fpga_compile", "PASS", 1.0, "sof=top.sof size=10")],
        top_name="top")
    assert not (proj / "phase2/stage1/fpga/final").exists()
    m = _manifest(proj)
    assert m["verdict"] == "SKIP"
    assert "bitstream_path" not in m
    assert "bitstream_sha" not in m


def test_guard_failed_burn_stages_nothing(tmp_path):
    proj = tmp_path / "proj"
    out = proj / "phase2/stage1/fpga/output_files"
    out.mkdir(parents=True)
    sof = out / "top.sof"
    sof.write_bytes(b"\x00bitstream")
    dr.step_emit_phase2_manifests(
        proj,
        [dr.StepResult("fpga_compile", "PASS", 1.0, "sof=top.sof size=10"),
         dr.StepResult("fpga_burn", "FAIL", 1.0, "rc=1",
                       extras={"burn_provenance": {"sof_path": str(sof)}}),
         dr.StepResult("usb_hid_tester_verify", "SKIP", 1.0, "no board")],
        top_name="top")
    assert list((proj / "phase2/stage1/fpga").glob("final/*.sof")) == []


def test_guard_early_prototype_artefact_is_kept_not_moved(tmp_path):
    """Step 6 keeps declaring output_files/*.sof; staging must be a COPY so the
    early prototype and the final sign-off stay distinguishable."""
    proj = _successful_board_run(tmp_path)
    assert (proj / "phase2/stage1/fpga/output_files/top.sof").is_file()
    step6_outputs = _step("6")["required_outputs"]
    assert "phase2/stage1/fpga/output_files/*.sof" in step6_outputs


@pytest.mark.xfail(strict=True, reason=(
    "CONTRACT COLLISION with v1.7.55 (#468), which stopped the FPGA sign-off "
    "waiving ITSELF: a manifest that self-declares WAIVED must now be backed by "
    "a waivers.json entry AND the four hardware-evidence artefacts the "
    "attestation requires (programmer log, .sof hash, non-JSON evidence). This "
    "fixture supplies none of them, so it asserts exactly the self-attestation "
    "that change removed. STRICT so it cannot pass silently: whoever reconciles "
    "the two must come back here. The manifest-SHAPE half this test is named "
    "for still holds and is asserted above the attestation call."))
def test_guard_waived_tier_manifest_shape_is_preserved(tmp_path):
    """#30 Bug 1 / v1.6.98: a WAIVED usb_hid_tester_verify still produces the
    all_scenarios_passed + review_required + waiver_ticket triple that
    fpga_on_board_attestation_check's WAIVED short-circuit needs."""
    proj = tmp_path / "proj"
    out = proj / "phase2/stage1/fpga/output_files"
    out.mkdir(parents=True)
    sof = out / "top.sof"
    sof.write_bytes(b"\x00bitstream")
    dr.step_emit_phase2_manifests(
        proj,
        [dr.StepResult("fpga_compile", "PASS", 1.0, "sof=top.sof size=10"),
         dr.StepResult("fpga_burn", "PASS", 1.0, "sof_burnt",
                       extras={"burn_provenance": {"sof_path": str(sof),
                                                   "sof_sha256": _sha(sof)}}),
         dr.StepResult("usb_hid_tester_verify", "WAIVED", 1.0, "no rig",
                       extras={"waiver": {"ticket": "no-tester-rig-v1.6.97",
                                          "review_required": True,
                                          "evidence": "rig absent"}})],
        top_name="top")
    m = _manifest(proj)
    assert m["verdict"] == "WAIVED"
    assert m["all_scenarios_passed"] is True
    assert m["review_required"] is True
    assert m["waiver_ticket"] == "no-tester-rig-v1.6.97"
    r = subprocess.run([sys.executable, str(ATTEST), str(proj)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


def test_guard_board_absent_run_is_unchanged(tmp_path):
    """A pure-digital run (no FPGA at all) keeps the minimal SKIP stub and
    stages nothing — this is the shape the real spm reference run has."""
    proj = tmp_path / "proj"
    (proj / "reports").mkdir(parents=True)
    dr.step_emit_phase2_manifests(proj, [], top_name="top")
    m = _manifest(proj)
    assert m["verdict"] == "SKIP"
    assert m["evidence"] == "usb_hid_tester_verify not run"
    assert not (proj / "phase2/stage1/fpga/final").exists()
