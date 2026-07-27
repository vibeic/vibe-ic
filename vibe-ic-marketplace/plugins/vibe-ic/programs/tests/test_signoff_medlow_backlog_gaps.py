#!/usr/bin/env python3
"""Sign-off backlog (steps 28-39): declared-but-unverified artefacts, gates
that measure something adjacent to what they claim, and a declared gate the
report never admitted it had skipped.

Every test here is written against an OBSERVABLE property — a program's exit
code, the content of the JSON report it writes, or the verdict
`flow_compliance_check` produces for a synthetic project — never against a
source substring or a private symbol, so an alternative correct fix passes
them and reverting the program files fails them.

What each group pins, and the measurement that produced it (real completed run:
`~/campaign_pr427/spm/converge_ihp-sg13g2` on 192.168.1.120, a pure DIGITAL
standard-cell flow; the analog A1-A9 / mixed-signal M1-M4 tracks produce no
artefacts there and are NOT exercised by that run — the fixtures below are
synthetic and stand on their own):

  1. foundry_handoff_package_check called itself a "kit completeness" gate
     while `_REQUIRED_FILES` named 2 of the 4 members the pack generator
     emits. On the real run scribe_line_layout.gds was ABSENT (only the
     generator's honest `.PENDING_FOUNDRY.txt` note stood in its place) and the
     gate reported PASS / "all 2 required artefacts present" / missing=[].
  2. that same note — the generator's own disclosure that the frame is
     foundry-supplied — never reached `pending_foundry_fields`, because the
     PENDING_FOUNDRY_* scan only reads dict keys inside .json members. The
     tapeout checklist builds its reviewer to-do list from exactly that field,
     so the open item was invisible downstream.
  3. power_report_check rebuilt its own argv and dropped every flag after the
     project dir, so the `--json` the flow declared for Step 33 was dead and no
     audit trail was written. (Verified live: the file named by --json was
     byte-identical before and after the run.)
  4. metal_fill_density_check reported `density_checked: true` when all it had
     done was open a file: on the real run layers_ok=0, layers_bad=0 and not a
     single per-layer CMP density value was examined.
  5. flow_compliance_check resolved a step to SKIPPED-CONDITION through the
     #675-strict sibling-self-skip path without ever naming the declared gate
     that consequently did not run.
"""
from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
PROGRAMS = PLUGIN_ROOT / "programs"
FLOW_YAML = PLUGIN_ROOT / "flow" / "phase1_phase2_phase3.yaml"

sys.path.insert(0, str(PROGRAMS))


def _run(prog: str, *args: str):
    """Run a program the way the flow gate does; return (rc, stdout)."""
    proc = subprocess.run(
        [sys.executable, str(PROGRAMS / prog), *args],
        capture_output=True, text=True)
    return proc.returncode, proc.stdout


def _flow_steps():
    return yaml.safe_load(FLOW_YAML.read_text())["steps"]


def _step(sid):
    for st in _flow_steps():
        if st.get("id") == sid:
            return st
    raise AssertionError(f"step {sid} not in {FLOW_YAML}")


# ─────────────────────────────────────────────────────────────────────
# 1 + 2 — foundry handoff kit completeness, and the scribe-line
#         disclosure the gate never surfaced
# ─────────────────────────────────────────────────────────────────────

def _handoff_kit(tmp_path: Path, *, corner_vectors=True, scribe="note",
                 ic_name="demo_top") -> Path:
    """A minimal foundry-handoff project shaped like the pack generator's.

    `scribe`: "note" (the PENDING_FOUNDRY .txt the generator writes when the
    foundry has not supplied the frame), "gds" (a real supplied frame), or
    "none".
    """
    proj = tmp_path / "proj"
    hd = proj / "phase3/stage4/foundry_handoff"
    hd.mkdir(parents=True)
    (hd / "mask_spec.json").write_text(json.dumps(
        {"pdk": "demo130", "PENDING_FOUNDRY_mask_layers": "foundry"}) + "\n")
    (hd / "wat_plan.json").write_text(json.dumps(
        {"pdk": "demo130", "PENDING_FOUNDRY_wat_structures": "foundry"}) + "\n")
    if corner_vectors:
        (hd / "corner_test_vectors.json").write_text(json.dumps(
            {"pdk": "demo130", "cell_count": 12}) + "\n")
    if scribe == "note":
        (hd / "scribe_line_layout.PENDING_FOUNDRY.txt").write_text(
            "scribe_line_layout.gds is FOUNDRY-SUPPLIED and is NOT generated "
            f"here.\n# design: {proj.name}\n")
    elif scribe == "gds":
        (hd / "scribe_line_layout.gds").write_bytes(b"HEADER\x00scribe frame\n")
    # a real chip GDS named after the design, so the chip-GDS sub-gate passes
    gds_dir = hd / "gds"
    gds_dir.mkdir()
    (gds_dir / f"{ic_name}.gds").write_bytes(b"HEADER\x00chip layout\n" * 32)
    docs = proj / "phase1/generated_docs"
    docs.mkdir(parents=True)
    (docs / "L1_DATASHEET.json").write_text(
        json.dumps({"ic_name": ic_name}) + "\n")
    return proj


def _handoff_report(proj: Path, tmp_path: Path):
    out = tmp_path / "handoff_audit.json"
    rc, _ = _run("foundry_handoff_package_check.py", str(proj),
                 "--json", str(out))
    return rc, json.loads(out.read_text())


def test_handoff_kit_incomplete_when_a_declared_member_is_absent(tmp_path):
    """A kit missing corner_test_vectors.json must NOT read as complete.

    The flow declares four kit members for Step 38; the gate judged two. This
    is the exact shape that let the real run's absent scribe frame pass as
    "all required artefacts present".
    """
    proj = _handoff_kit(tmp_path, corner_vectors=False)
    rc, rep = _handoff_report(proj, tmp_path)

    assert rc != 0, "an incomplete kit must not exit 0"
    assert rep["verdict"] != "PASS"
    joined = " ".join(rep["missing"])
    assert "corner_test_vectors.json" in joined, (
        f"the absent member must be named in `missing`; got {rep['missing']}")


def test_handoff_kit_missing_scribe_entirely_is_a_gap(tmp_path):
    """Neither the frame nor a note saying where it comes from = a real gap.

    The flow yaml already says this in words ("NEITHER present is still a real
    gap, because then nothing states where the frame is coming from"); the gate
    now enforces it.
    """
    proj = _handoff_kit(tmp_path, scribe="none")
    rc, rep = _handoff_report(proj, tmp_path)

    assert rc != 0
    assert any("scribe_line_layout" in m for m in rep["missing"]), rep["missing"]


def test_scribe_pending_note_becomes_a_named_open_item(tmp_path):
    """The generator's honest disclosure must reach `pending_foundry_fields`.

    tapeout_checklist_gen builds its reviewer to-do list from that field, so a
    disclosure that never lands in it is a disclosure nobody reads.
    """
    proj = _handoff_kit(tmp_path, scribe="note")
    rc, rep = _handoff_report(proj, tmp_path)

    assert rc == 0 and rep["verdict"] == "PASS"
    pending = rep["pending_foundry_fields"]
    assert any("scribe_line_layout" in p for p in pending), (
        f"scribe-line open item absent from pending_foundry_fields: {pending}")


def test_supplied_scribe_gds_raises_no_pending_item(tmp_path):
    """DIRECTION-1 guard: a real foundry-supplied frame is not an open item.

    Must hold on both trees — the fix must not invent a pending item for a kit
    that is genuinely complete.
    """
    proj = _handoff_kit(tmp_path, scribe="gds")
    rc, rep = _handoff_report(proj, tmp_path)

    assert rc == 0 and rep["verdict"] == "PASS"
    assert not any("scribe_line_layout" in p
                   for p in rep["pending_foundry_fields"])


def test_complete_kit_still_passes(tmp_path):
    """DIRECTION-1 guard: the honest complete kit stays a PASS on both trees."""
    proj = _handoff_kit(tmp_path, scribe="note")
    rc, rep = _handoff_report(proj, tmp_path)
    assert rc == 0
    assert rep["verdict"] == "PASS"
    assert rep["missing"] == []


def test_zero_byte_member_still_hard_fails(tmp_path):
    """DIRECTION-1 guard: the pre-existing 0-byte hard-fail (#433d) survives."""
    proj = _handoff_kit(tmp_path, scribe="note")
    (proj / "phase3/stage4/foundry_handoff/wat_plan.json").write_text("")
    rc, _ = _run("foundry_handoff_package_check.py", str(proj))
    assert rc == 1


# ─────────────────────────────────────────────────────────────────────
# 1b — an INCOMPLETE kit must never SILENCE the chip-GDS verdict
#
# Widening `_REQUIRED_FILES` from 2 members to 4 armed a latent inversion in
# the verdict ladder: `missing -> SKIP rc=2` was evaluated BEFORE
# `chip_gds_finding -> FAIL rc=1`. rc=2 is NOT CHECKED (flow_compliance_check
# reads it as VACUOUS_PASS) and `tapeout_checklist_gen` builds the reviewer
# to-do list out of the same reports/phase3/foundry_handoff_audit.json — so on
# the #60 P2-7 anti-scribe control the chip-GDS ERROR silently dropped off the
# tape-out checklist:
#
#     before the widening   rc=1  FAIL   FOUNDRY_HANDOFF_SCRIBE_ONLY = ERROR
#     with the widening     rc=2  SKIP   that ERROR GONE
#
# These tests pin the ladder by DRIVING the gate on exactly that fixture.
# ─────────────────────────────────────────────────────────────────────

def _anti_scribe_kit(tmp_path: Path, *, chip_gds=None,
                     ic_name="gadget_project") -> Path:
    """The #60 P2-7 anti-scribe control, verbatim.

    `phase3/stage4/foundry_handoff/{mask_spec,wat_plan}.json` present (so the
    kit is INCOMPLETE under the four-member requirement — no
    corner_test_vectors.json and no account of the scribe frame),
    `L1_DATASHEET.json` carrying an ic_name, and `phase3/stage4/gds/` holding
    ONLY the foundry-supplied `scribe_line_layout.gds` — never a chip GDS.

    `chip_gds="chip"` instead writes a real chip GDS there, which is the
    direction-1 control: same incomplete kit, no substance defect.
    """
    proj = tmp_path / "antiscribe"
    hd = proj / "phase3/stage4/foundry_handoff"
    hd.mkdir(parents=True)
    (hd / "mask_spec.json").write_text(json.dumps(
        {"pdk": "demo130", "cell_count": 12}) + "\n")
    (hd / "wat_plan.json").write_text(json.dumps(
        {"pdk": "demo130", "structures": ["gadget"]}) + "\n")
    docs = proj / "phase1/generated_docs"
    docs.mkdir(parents=True)
    (docs / "L1_DATASHEET.json").write_text(
        json.dumps({"ic_name": ic_name}) + "\n")
    if chip_gds is not None:
        gds_dir = proj / "phase3/stage4/gds"
        gds_dir.mkdir(parents=True)
        name = (f"{ic_name}.gds" if chip_gds == "chip"
                else "scribe_line_layout.gds")
        (gds_dir / name).write_bytes(b"HEADER\x00layout\n" * 8)
    return proj


def test_incomplete_kit_never_silences_the_scribe_only_verdict(tmp_path):
    """Anti-scribe control: only the foundry frame, no chip GDS → rc=1 FAIL.

    The kit is incomplete AND the chip GDS is absent. The incomplete kit must
    not downgrade the proved defect to NOT CHECKED.
    """
    proj = _anti_scribe_kit(tmp_path, chip_gds="scribe")
    rc, rep = _handoff_report(proj, tmp_path)

    assert rc == 1, f"chip-GDS defect silenced by the incomplete kit: {rep}"
    assert rep["verdict"] == "FAIL", rep
    rules = [f["rule"] for f in rep["findings"]]
    assert "FOUNDRY_HANDOFF_SCRIBE_ONLY" in rules, rules
    assert any(f["severity"] == "ERROR" for f in rep["findings"]), rep


def test_incomplete_kit_never_silences_the_missing_chip_gds_verdict(tmp_path):
    """Same ladder, the other chip-GDS ERROR: no GDS directory at all."""
    proj = _anti_scribe_kit(tmp_path, chip_gds=None)
    rc, rep = _handoff_report(proj, tmp_path)

    assert rc == 1, f"chip-GDS defect silenced by the incomplete kit: {rep}"
    assert rep["verdict"] == "FAIL", rep
    rules = [f["rule"] for f in rep["findings"]]
    assert "FOUNDRY_HANDOFF_CHIP_GDS_MISSING" in rules, rules


def test_the_chip_gds_fail_still_names_the_absent_kit_members(tmp_path):
    """Precedence must not cost disclosure: the FAIL still reports which kit
    members were absent, so the incompleteness is not traded for the defect."""
    proj = _anti_scribe_kit(tmp_path, chip_gds="scribe")
    rc, rep = _handoff_report(proj, tmp_path)

    assert rc == 1
    joined = " ".join(rep["missing"])
    assert "corner_test_vectors.json" in joined, rep["missing"]
    assert "scribe_line_layout" in joined, rep["missing"]
    assert any(f["rule"] == "REQUIRED_FILES_MISSING" for f in rep["findings"]), (
        f"the absent members are not disclosed in the FAIL: {rep['findings']}")


def test_incomplete_kit_with_a_sound_chip_gds_still_skips(tmp_path):
    """DIRECTION-1 guard: the SKIP branch is REORDERED, not deleted.

    Incomplete kit, nothing wrong with what IS there → still rc=2. (Step 38
    declares all four members as required_outputs, so the absence is reported
    as MISSING by the step-level check regardless of this rc.)
    """
    proj = _anti_scribe_kit(tmp_path, chip_gds="chip")
    rc, rep = _handoff_report(proj, tmp_path)

    assert rc == 2, rep
    assert rep["verdict"] == "SKIP", rep


def test_waiver_still_outranks_the_chip_gds_fail(tmp_path):
    """DIRECTION-1 guard: a declared waiver still resolves WAIVED/rc=0 on the
    same fixture — the reordering changes precedence between FAIL and SKIP,
    not the waiver contract."""
    proj = _anti_scribe_kit(tmp_path, chip_gds="scribe")
    (proj / "waivers.json").write_text(json.dumps({"waived_steps": [
        {"id": "foundry_handoff", "ticket": "TKT-1",
         "reason": "kit assembler not shipped"}]}) + "\n")
    rc, rep = _handoff_report(proj, tmp_path)

    assert rc == 0, rep
    assert rep["verdict"] == "WAIVED", rep


# ─────────────────────────────────────────────────────────────────────
# 3 — power_report_check must honour the flags the flow declares
# ─────────────────────────────────────────────────────────────────────

def _power_project(tmp_path: Path) -> Path:
    proj = tmp_path / "pwr"
    rp = proj / "reports/phase3"
    rp.mkdir(parents=True)
    (rp / "power.rpt").write_text(
        "OpenROAD 2.0\n"
        "Power Report\n"
        "Group    Internal Switching Leakage Total\n"
        "Total    1.0e-3  2.0e-4    3.0e-6   1.2e-3\n"
        "Total Power 1.2e-3\n"
        "Switching Power 2.0e-4\n"
        "Leakage Power 3.0e-6\n")
    return proj


def test_power_report_check_writes_the_declared_audit_trail(tmp_path):
    """`--json <path>` must produce a report at that path.

    The wrapper used to rebuild argv as [project_dir, --mode, power] and drop
    everything else, so the flow's declared --json was dead: nothing was
    written anywhere and the gate left no audit trail.
    """
    proj = _power_project(tmp_path)
    out = tmp_path / "gates" / "power_report.json"
    rc, _ = _run("power_report_check.py", str(proj), "--mode", "power",
                 "--json", str(out))

    assert out.is_file(), "--json was dropped: no audit trail written"
    rep = json.loads(out.read_text())
    assert rep.get("program") == "eda_report_audit:power"
    assert rc in (0, 1)


def test_power_report_check_audit_trail_is_a_separate_file(tmp_path):
    """The audit report and the runner's power summary are different schemas —
    which is why the flow's --json target had to move off power.json at the
    same time the wrapper started honouring the flag."""
    proj = _power_project(tmp_path)
    out = tmp_path / "power_audit.json"
    _run("power_report_check.py", str(proj), "--mode", "power",
         "--json", str(out))
    assert "program" in json.loads(out.read_text())


def test_power_report_check_never_writes_the_runner_summary(tmp_path):
    """DIRECTION-1 guard: the checker must not touch reports/phase3/power.json,
    the runner-authored data it audits. Must hold on both trees."""
    proj = _power_project(tmp_path)
    runner_summary = proj / "reports/phase3/power.json"
    runner_summary.write_text(json.dumps(
        {"tool": "opensta", "verdict": "PASS"}) + "\n")
    before = runner_summary.read_bytes()
    _run("power_report_check.py", str(proj), "--mode", "power",
         "--json", str(tmp_path / "power_audit.json"))
    assert runner_summary.read_bytes() == before


def test_power_report_check_pins_power_mode(tmp_path):
    """DIRECTION-1 guard: the wrapper still pins power mode — a caller passing
    a different --mode cannot turn this into some other audit. Read off stdout
    so this holds on both trees."""
    proj = _power_project(tmp_path)
    _, stdout = _run("power_report_check.py", str(proj), "--mode", "drc")
    assert json.loads(stdout)["program"] == "eda_report_audit:power"


def test_power_report_check_pins_power_mode_in_the_equals_spelling(tmp_path):
    """`--mode=lvs` must be pinned away too.

    Only the space-separated form was dropped by the splitter. `--mode=lvs`
    starts with "-", so it was forwarded, arrived AFTER the pinned pair, and
    argparse's last-wins turned Step 33's power gate into an LVS audit.
    Measured before the fix: program == "eda_report_audit:lvs".
    """
    proj = _power_project(tmp_path)
    _, stdout = _run("power_report_check.py", str(proj), "--mode=lvs")
    assert json.loads(stdout)["program"] == "eda_report_audit:power"


def test_power_report_check_finds_the_project_after_a_flag_value(tmp_path):
    """A value-taking flag BEFORE the positional must not eat the project dir.

    `--json out.json <proj>` resolved the project dir to `out.json` (the first
    bare token) and handed `<proj>` to --json as its value; the run then died
    with IsADirectoryError and wrote no audit at all.
    """
    proj = _power_project(tmp_path)
    out = tmp_path / "gates" / "power_report.json"
    rc, stdout = _run("power_report_check.py", "--json", str(out), str(proj))

    assert out.is_file(), "no audit written: the --json value was misparsed"
    rep = json.loads(out.read_text())
    assert rep["program"] == "eda_report_audit:power"
    assert not any(f["rule"] == "PROJECT_DIR_EXISTS" for f in rep["findings"]), (
        f"the wrong path was audited as the project dir: {rep['findings']}")
    assert rc in (0, 1), stdout


def test_power_report_check_splits_argv_without_stealing_the_flag_value():
    """The splitter itself, on the shape above: the project dir is `.`, and the
    flag keeps its own argument."""
    mod = importlib.import_module("power_report_check")
    proj, passthrough = mod.split_argv(["--json", "out.json", "."])
    assert proj == "."
    assert passthrough == ["--json", "out.json"]


def test_power_report_check_defaults_project_dir(tmp_path, monkeypatch):
    """DIRECTION-1 guard: bare invocation still defaults the project dir to
    '.' and still exits without a usage error."""
    proj = _power_project(tmp_path)
    monkeypatch.chdir(proj)
    proc = subprocess.run(
        [sys.executable, str(PROGRAMS / "power_report_check.py")],
        capture_output=True, text=True)
    assert proc.returncode in (0, 1), proc.stderr


# ─────────────────────────────────────────────────────────────────────
# 4 — metal fill: "density_checked" must not stand in for a per-layer
#     CMP verification that never happened
# ─────────────────────────────────────────────────────────────────────

def _fill_project(tmp_path: Path, density: dict) -> Path:
    proj = tmp_path / "fill"
    pnr = proj / "phase3/stage3/pnr"
    pnr.mkdir(parents=True)
    (pnr / "routed.def").write_text("VERSION 5.8 ;\nEND DESIGN\n")
    (pnr / "filled.def").write_text("VERSION 5.8 ;\nFILL\nEND DESIGN\n")
    (pnr / "metal_fill.done").write_text("metal_fill_done\n")
    rep = proj / "reports"
    rep.mkdir(parents=True)
    (rep / "density.json").write_text(json.dumps(density) + "\n")
    (rep / "density.rpt").write_text("# openroad filler_placement\n")
    return proj


_ROW_ONLY = {"tool": "openroad-filler_placement", "filler_instances": 0,
             "row_utilization_pct": 100.0, "core_utilization_pct": 21.0}


def _fill_report(proj: Path, tmp_path: Path):
    out = tmp_path / "fill_audit.json"
    rc, _ = _run("metal_fill_density_check.py", str(proj), "--json", str(out))
    return rc, json.loads(out.read_text())


def test_row_utilization_only_is_not_a_per_layer_density_verification(tmp_path):
    """A report carrying only row/core utilization verified NO layer.

    This is the real run's exact shape: pass=true with zero layer values ever
    compared against the [20,80] window.
    """
    proj = _fill_project(tmp_path, _ROW_ONLY)
    rc, rep = _fill_report(proj, tmp_path)
    summary = rep["summary"]

    assert rc == 0 and summary["pass"] is True
    assert summary["per_layer_density_verified"] is False, (
        "0 layer values were examined; the summary must not claim otherwise")
    assert summary["density_artefact_read"] is True
    assert any(f["category"] == "PER_LAYER_DENSITY_NOT_VERIFIED_HERE"
               for f in rep["findings"]), (
        "the report must SAY the per-layer rule was not applied here")


def _not_verified_msg(tmp_path: Path) -> str:
    proj = _fill_project(tmp_path, _ROW_ONLY)
    _, rep = _fill_report(proj, tmp_path)
    return " ".join(f["message"] for f in rep["findings"]
                    if f["category"] == "PER_LAYER_DENSITY_NOT_VERIFIED_HERE")


def test_named_disclosure_says_who_does_judge_per_layer_density(tmp_path):
    """The disclosure has to be useful: it must name where the rule IS judged,
    not just note an absence."""
    msg = _not_verified_msg(tmp_path)
    assert "metal_density.json" in msg
    assert "met_min_ca_density" in msg


def _flow_wired_gate_programs():
    """Every program NAME the flow declares in a gate, walked structurally."""
    fcc = importlib.import_module("flow_compliance_check")
    wired = set()
    for st in _flow_steps():
        wired.update(fcc._declared_gate_commands(st.get("gate")))
        for extra in ("program_exit_zero", "optional_program_exit_zero",
                      "advisory_program_exit_zero"):
            if extra in st:
                wired.update(fcc._declared_gate_commands({extra: st[extra]}))
    return wired


def test_the_per_layer_judge_is_not_wired_into_any_flow_step():
    """The measured fact the disclosure rests on.

    `metal_layer_density_check` judges reports/phase3/metal_density.json
    correctly, but it is called by `signoff_ladder_run` alone and no flow step
    invokes either. `tapeout_checklist_gen` NAMES it as the row's authority in
    a note and never executes it.

    This test exists to BREAK when that changes: wiring either program is
    exactly the moment the disclosure below stops being true and has to be
    rewritten. It is not a claim that leaving it unwired is right.
    """
    wired = _flow_wired_gate_programs()
    assert "metal_layer_density_check" not in wired, (
        "the per-layer judge is now wired into the flow — update the "
        "PER_LAYER_DENSITY_NOT_VERIFIED_HERE disclosure, which states it is not")
    assert "signoff_ladder_run" not in wired, (
        "signoff_ladder_run is now wired — it carries metal_layer_density_check "
        "with it; update the disclosure")


def test_the_disclosure_does_not_imply_a_flow_gate_catches_this(tmp_path):
    """DIRECTION-2 guard: the finding must not leave a reader believing some
    downstream flow gate applies the per-layer window. It says the opposite,
    because that is what is true (see the test above)."""
    msg = _not_verified_msg(tmp_path)
    assert "signoff_ladder_run" in msg, (
        f"the disclosure does not say where the judge actually lives: {msg}")
    assert "no flow step" in msg, (
        f"the disclosure does not admit the wiring gap: {msg}")


_IN_WINDOW_LAYERS = {
    "tool": "openroad-filler_placement", "filler_instances": 900,
    "row_utilization_pct": 62.0,
    "layers": [{"name": "met1", "density_pct": 45.0},
               {"name": "met2", "density_pct": 51.0}]}


def test_in_window_per_layer_density_still_passes(tmp_path):
    """DIRECTION-1 guard: real in-window per-layer numbers are examined and
    still PASS, with both layers counted. Holds on both trees."""
    proj = _fill_project(tmp_path, _IN_WINDOW_LAYERS)
    rc, rep = _fill_report(proj, tmp_path)
    assert rc == 0 and rep["summary"]["pass"] is True
    assert rep["summary"]["layers_ok"] == 2
    assert rep["summary"]["layers_bad"] == 0


def test_in_window_per_layer_density_is_reported_as_verified(tmp_path):
    """When per-layer values WERE examined the summary says so, and the
    not-verified-here disclosure is correctly absent."""
    proj = _fill_project(tmp_path, _IN_WINDOW_LAYERS)
    _, rep = _fill_report(proj, tmp_path)
    assert rep["summary"]["per_layer_density_verified"] is True
    assert not any(f["category"] == "PER_LAYER_DENSITY_NOT_VERIFIED_HERE"
                   for f in rep["findings"])


def test_out_of_window_layer_still_fails(tmp_path):
    """DIRECTION-1 guard: the real check is untouched — an OOB layer is still
    an ERROR and still rc=1 on both trees."""
    proj = _fill_project(tmp_path, {
        "tool": "openroad-filler_placement", "filler_instances": 900,
        "row_utilization_pct": 62.0,
        "layers": [{"name": "met1", "density_pct": 4.0}]})
    rc, rep = _fill_report(proj, tmp_path)
    assert rc == 1
    assert any(f["category"] == "DENSITY_OOB" for f in rep["findings"])


def _no_fill_report(tmp_path: Path):
    proj = tmp_path / "nofill"
    (proj / "phase3/stage3/pnr").mkdir(parents=True)
    out = tmp_path / "nofill.json"
    rc, _ = _run("metal_fill_density_check.py", str(proj), "--json", str(out))
    return rc, json.loads(out.read_text())


def test_no_fill_marker_still_fails(tmp_path):
    """DIRECTION-1 guard: the NO_FILL early return still fails. Both trees."""
    rc, rep = _no_fill_report(tmp_path)
    assert rc == 1
    assert any(f["category"] == "NO_FILL" for f in rep["findings"])


def test_no_fill_report_still_carries_the_summary_fields(tmp_path):
    """The summary must be well-formed on the EARLY-RETURN path too — the
    per-layer field has to be initialised, not set only where the parse runs."""
    _, rep = _no_fill_report(tmp_path)
    assert rep["summary"]["per_layer_density_verified"] is False
    assert rep["summary"]["density_artefact_read"] is False


# ─────────────────────────────────────────────────────────────────────
# 5 — a declared gate that does not run must be disclosed as such
# ─────────────────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def fcc():
    return importlib.import_module("flow_compliance_check")


def test_declared_gate_commands_walks_nested_gate_shapes(fcc):
    """The gate-name extraction is a structural walk of the same shapes
    `_evaluate_gate` executes — including `any_of: true` used as a MODIFIER on
    a files_exist block, which is not a nested gate list."""
    gate = {"all_of": [
        {"files_exist": ["a.log", "b.flag"], "any_of": True},
        {"program_exit_zero": "post_layout_sim_check . --json out.json"},
        {"optional_program_exit_zero": {
            "command": "eco_loop_audit . --json eco.json",
            "condition_files_exist": ["eco_log.json"]}},
    ]}
    assert fcc._declared_gate_commands(gate) == [
        "post_layout_sim_check", "eco_loop_audit"]


def test_declared_gate_commands_names_programs_only(fcc):
    """DIRECTION-1 guard: no gate, no names, no crash — and a predicate-only
    gate yields no PROGRAM names, because it declares no program.

    NOT a statement that such a step is gateless. That reading is what silenced
    the disclosure; `_declared_gate_summary` is the question the caller has.
    """
    assert fcc._declared_gate_commands(None) == []
    assert fcc._declared_gate_commands({"files_exist": ["x"]}) == []


def test_a_files_exist_only_step_is_not_gateless(fcc):
    """The distinction the ADVISORY turns on.

    Over the corpus the #675-strict self-skip resolves only on steps whose gate
    is `files_exist: [...]` — no program. Keying the disclosure off the program
    list therefore fired it 0 times on the entire population it was written
    for. The summary names the gate that did not run; only a step with NO gate
    at all summarises to nothing.
    """
    assert fcc._declared_gate_summary(None) == ""
    assert fcc._declared_gate_summary({}) == ""

    summary = fcc._declared_gate_summary(_step(12)["gate"])
    assert summary, "step 12 declares a gate; the summary must describe it"
    assert "post_dft_netlist.v" in summary, summary
    assert fcc._declared_gate_commands(_step(12)["gate"]) == [], (
        "precondition: step 12's gate declares no program")


def test_declared_gate_summary_covers_the_predicate_kinds(fcc):
    """Both non-program predicate kinds are described, and program gates keep
    being named by program (the useful identifier)."""
    gate = {"all_of": [
        {"files_exist": ["a.log", "b.flag"], "any_of": True},
        {"json_field_true": {"file": "r.json", "field": "all_ok",
                             "expect": True}},
        {"program_exit_zero": "post_layout_sim_check . --json out.json"},
    ]}
    summary = fcc._declared_gate_summary(gate)
    assert "post_layout_sim_check" in summary
    assert "files_exist[a.log, b.flag]" in summary
    assert "json_field_true[r.json:all_ok]" in summary


def _self_skip_project(tmp_path: Path) -> Path:
    proj = tmp_path / "skipproj"
    d = proj / "phase3/stage3/sim_postlayout"
    d.mkdir(parents=True)
    (d / "sdf_sim_skipped.json").write_text(json.dumps({
        "verdict": "SKIPPED-CONDITION",
        "reason": "no SDF-annotated gate-level re-simulation ran",
        "capability_flag": "cap:sdf_annotated_gatelevel_sim",
        "skips_required_output": [
            "phase3/stage3/sim_postlayout/results.log",
            "phase3/stage3/sim_postlayout/pass.flag"],
    }) + "\n")
    return proj


def test_self_skip_step_discloses_the_gate_it_did_not_run(fcc, tmp_path):
    """A step resolved by the #675-strict sibling self-skip never reaches its
    gate. The verdict is right; staying silent about the un-run gate was not —
    a reader could not tell the gate from an agreeing gate."""
    proj = _self_skip_project(tmp_path)
    step = _step(29)
    res = fcc.check_step(proj, step, {})

    assert res.status == "SKIPPED-CONDITION"
    assert any("post_layout_sim_check" in r and "NOT evaluated" in r
               for r in res.reasons), (
        f"the un-run declared gate is not disclosed: {res.reasons}")


def test_self_skip_disclosure_does_not_change_the_verdict(fcc, tmp_path):
    """DIRECTION-1 guard: disclosing the un-run gate must not turn an honestly
    disclosed capability gap into a FAIL, and must not create a PASS."""
    proj = _self_skip_project(tmp_path)
    res = fcc.check_step(proj, _step(29), {})
    assert res.status == "SKIPPED-CONDITION"
    assert res.self_skip_disclosed is True


def _predicate_gate_self_skip_project(tmp_path: Path) -> Path:
    """A step-12-shaped self-skip: the ONLY population the #675-strict path
    resolves on across the corpus, and the one whose gate is `files_exist`."""
    proj = tmp_path / "predgate"
    d = proj / "phase2/stage2/synth"
    d.mkdir(parents=True)
    (d / "post_dft_netlist_skipped.json").write_text(json.dumps({
        "verdict": "SKIPPED-CONDITION",
        "reason": "scan insertion was disclosed-skipped upstream",
        "capability_flag": "cap:scan_chain_insertion",
        "skips_required_output": ["phase2/stage2/synth/post_dft_netlist.v"],
    }) + "\n")
    return proj


def test_self_skip_discloses_a_gate_that_declares_no_program(fcc, tmp_path):
    """The fix, END-TO-END on the shape it was written for.

    Step 12's gate is `files_exist: [post_dft_netlist.v]`. The disclosure used
    to be conditional on the gate naming a PROGRAM, so on this — the only
    population the #675-strict self-skip resolves on across the corpus — the
    ADVISORY was never emitted.
    """
    proj = _predicate_gate_self_skip_project(tmp_path)
    res = fcc.check_step(proj, _step(12), {})

    assert res.status == "SKIPPED-CONDITION", res.reasons
    advisory = [r for r in res.reasons if "NOT evaluated" in r]
    assert advisory, f"no ADVISORY for the un-run gate: {res.reasons}"
    assert "post_dft_netlist.v" in advisory[0], advisory[0]


def test_self_skip_on_a_truly_gateless_step_invents_no_advisory(fcc, tmp_path):
    """DIRECTION-1 guard: a step that declares NO gate must not gain a
    disclosure about a gate that does not exist."""
    proj = _predicate_gate_self_skip_project(tmp_path)
    step = dict(_step(12))
    step.pop("gate", None)
    res = fcc.check_step(proj, step, {})

    assert res.status == "SKIPPED-CONDITION", res.reasons
    assert not any("NOT evaluated" in r for r in res.reasons), res.reasons


def test_undisclosed_absence_is_still_missing(fcc, tmp_path):
    """DIRECTION-1 guard: no sibling marker → still MISSING, and no advisory
    is invented for a step that simply did not run."""
    proj = tmp_path / "bare"
    (proj / "phase3/stage3/sim_postlayout").mkdir(parents=True)
    res = fcc.check_step(proj, _step(29), {})
    assert res.status == "MISSING"
    assert not any("NOT evaluated" in r for r in res.reasons)


# ─────────────────────────────────────────────────────────────────────
# 6 — the artefacts these steps produce are now DECLARED, so a run that
#     loses one is MISSING instead of silently unverified
# ─────────────────────────────────────────────────────────────────────

def _touch(project: Path, rel: str, body: str = "x\n") -> Path:
    p = project / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(body)
    return p


@pytest.mark.parametrize("sid,files,dropped", [
    # Step 28 PERC: the runner writes all three together; only the .json was
    # declared, so the .rpt and the sign-off memo were verified by nobody.
    (28, ["reports/phase3/perc_equivalent.json",
          "reports/phase3/perc_equivalent.rpt",
          "reports/phase3/PERC_SIGNOFF_MEMO.md"],
     "reports/phase3/PERC_SIGNOFF_MEMO.md"),
    # Step 32 ECO: the trigger decision is written on EVERY branch, including
    # the one that writes neither eco_log.json nor no_eco_needed.flag.
    (32, ["phase3/stage3/eco/no_eco_needed.flag",
          "phase3/stage3/eco/eco_trigger_decision.json"],
     "phase3/stage3/eco/eco_trigger_decision.json"),
    # Step 34 metal fill: reports/density.{json,rpt} come off the same success
    # path as filled.def, and TWO gates read them (this step's and Step 31's).
    (34, ["phase3/stage3/pnr/filled.def",
          "reports/density.json", "reports/density.rpt"],
     "reports/density.json"),
])
def test_declared_outputs_are_all_required(fcc, tmp_path, sid, files, dropped):
    """Dropping any ONE declared artefact must be reported as MISSING.

    required_outputs is ALL-of-N (PR #455), so this is what a declaration buys:
    before these entries existed, the artefacts were produced by every run and
    verified by none.
    """
    proj = tmp_path / f"step{sid}"
    for rel in files:
        _touch(proj, rel)
    step = dict(_step(sid))
    step.pop("gate", None)          # isolate the required_outputs verdict
    assert fcc.check_step(proj, step, {}).status != "MISSING"

    (proj / dropped).unlink()
    res = fcc.check_step(proj, step, {})
    assert res.status == "MISSING", (
        f"step {sid} still {res.status} without {dropped}")
    assert any(dropped.rsplit("/", 1)[-1] in r for r in res.reasons)


def test_step33_gate_audit_trail_is_not_written_over_its_own_input():
    """Step 33's gate must not point --json at reports/phase3/power.json.

    That path is the step's declared required_output and holds the runner's
    power summary; the checker writes a different schema, so honouring the flag
    (which the wrapper now does) would overwrite the power data with an audit
    of it.
    """
    gate = _step(33)["gate"]
    cmd = gate["program_exit_zero"]
    assert "power_report_check" in cmd
    assert "--json" in cmd
    assert "reports/phase3/power.json" not in cmd
    assert "reports/phase3/power.json" in _step(33)["required_outputs"]


def _all_missing_results(fcc, waived=(), failed=()):
    """One StepResult per real flow step, all MISSING except as directed."""
    out = []
    for st in _flow_steps():
        sid = st.get("id")
        if sid is None or str(sid) == "P0":
            continue
        status = ("WAIVED" if sid in waived
                  else "FAIL" if sid in failed else "MISSING")
        out.append(fcc.StepResult(id=sid, name=st.get("name", ""),
                                  stage=st.get("stage", ""), status=status))
    return out


def test_step39_inherits_a_step6_waiver_as_deferred_by_upstream(fcc):
    """DISCLOSED SECOND EFFECT of `blocks_on: [6, 13]`.

    blocks_on is also the waiver-inheritance graph (#502): a MISSING step whose
    ancestry reaches a WAIVED step becomes DEFERRED-BY-UPSTREAM, and
    `total_required` subtracts that bucket. So a waiver written for step 6
    alone now moves step 39 out of the final sign-off's required denominator.
    Measured on an empty project waiving step 6 only: MISSING 39 -> 38 with
    DEFERRED-BY-UPSTREAM=1.

    That is the intended reading (39 signs off the bitstream 6 builds — one
    waiver, one deduction), which is exactly why it must be pinned: it is the
    ordering edge's cost, and a later change to either graph should have to
    come past this test.
    """
    results = _all_missing_results(fcc, waived=(6,))
    info = fcc._attribute_cascade_verdicts(
        results, _flow_steps(), {6: {"ticket": "TKT-FPGA-6"}})
    by_id = {r.id: r for r in results}

    assert by_id[39].status == "DEFERRED-BY-UPSTREAM", by_id[39].status
    assert "TKT-FPGA-6" in by_id[39].cascade_note, by_id[39].cascade_note
    deferred = sorted(str(sid) for sid, _p, _t in info["deferred_by_upstream"])
    assert deferred == ["39"], (
        f"a step-6 waiver defers more than the one step it should: {deferred}")


def test_no_waiver_leaves_step39_in_the_denominator(fcc):
    """DIRECTION-1 guard: without a waiver the edge deducts nothing."""
    results = _all_missing_results(fcc)
    info = fcc._attribute_cascade_verdicts(results, _flow_steps(), {})
    by_id = {r.id: r for r in results}
    assert by_id[39].status == "MISSING"
    assert info["deferred_by_upstream"] == []


def test_a_step6_fail_does_not_deduct_step39(fcc):
    """DIRECTION-1 guard: real counter-evidence never converts (#502).

    A FAILED step 6 must leave 39 MISSING — the denominator moves only for a
    WAIVER, never for a failure.
    """
    results = _all_missing_results(fcc, failed=(6,))
    info = fcc._attribute_cascade_verdicts(results, _flow_steps(), {})
    by_id = {r.id: r for r in results}
    assert by_id[39].status == "MISSING", by_id[39].status
    assert info["deferred_by_upstream"] == []


def test_step39_blocks_on_the_step_that_builds_the_bitstream():
    """FPGA final sign-off must not be judged done while the only step that
    compiles a .sof has failed.

    Asserted through the ordering analyser the audit actually uses, not by
    reading the blocks_on list: with Step 6 FAIL and Step 39 PASS there must be
    a violation naming both.
    """
    import flow_step_execution_coverage_check as cov
    steps = _flow_steps()
    graph = {str(st["id"]): [str(e) for e in (st.get("blocks_on") or [])]
             for st in steps if st.get("id") is not None}
    report = {"steps": [
        {"id": st["id"], "name": st.get("name", ""),
         "stage": st.get("stage", ""),
         "status": "FAIL" if st.get("id") == 6 else "PASS"}
        for st in steps]}
    violations = cov.analyze(report, graph)["ordering_violations"]
    assert any(str(v["terminal_id"]) == "39" and str(v["signoff_id"]) == "6"
               for v in violations), (
        "step 39 does not depend on step 6: "
        f"{[(v['terminal_id'], v['signoff_id']) for v in violations]}")
