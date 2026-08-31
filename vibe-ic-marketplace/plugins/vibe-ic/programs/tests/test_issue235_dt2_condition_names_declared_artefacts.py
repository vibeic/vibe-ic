"""DT2 must arm on artefacts the flow DECLARES, not on ones it merely writes.

THE DEFECT, on origin/main c9dacb8275 (v1.14.71)
------------------------------------------------
DT2's condition was an ALL-of over three paths::

    files_exist: ["phase2/stage2/dft/cut_netlist.v",
                  "phase3/stage3/extracted/*.spef",
                  "phase3/stage3/pnr/*_pnr.v"]

so any ONE of them going missing disarmed the step. `flow_condition_
reachability_check.classify()` named exactly which two could go missing in
silence::

    ALL-of: every path must be present, and these do not survive their own
    subject's absence: ['phase2/stage2/dft/cut_netlist.v',
                        'phase3/stage3/pnr/*_pnr.v']

`*.spef` was never part of the hole — it is step 22's SOLE required_output and
already carried a T3 backstop. The other two are artefacts a producer really
writes (`fault_atpg_run` writes the cut netlist; the PnR tcl writes
`{top}_pnr.v`) that NO step in the flow YAML declares, so their absence is loud
nowhere. That is the vibe-ic#235 hole that sat in
`flow/flow_condition_reachability_baseline.json` as the flow's last known-open
self-disabling condition.

THE FIX, AND THE TWO REPAIRS IT REPLACES
----------------------------------------
DT2 now names the DECLARED artefacts of its own `blocks_on: [DT1, 22]` — DT1's
sole required_output plus step 22's SPEF — the same spelling DT3 already used
one step later. Declaring the undeclared two instead was measured and refused:

  * a hard `files_exist` for `*_pnr.v` on step 21 would newly FAIL 29 of the 41
    published routed run roots, which do not carry it;
  * a hard `any_of` of `cut_netlist.v` OR `dft_atpg_not_run.json` on step 11
    would fail a real run root — over 491 dft dirs on a working host, 37 carry
    `scan_netlist.v` with NEITHER, and `_scan/T1` is a real run that disclosed
    only at the DT level.

WHAT MUST NOT REGRESS
---------------------
The 2026-07-28 withdrawal. A dimension-6 change re-armed DT2 on its own
producer's outputs and was withdrawn for moving the self-disable from the input
side to the output side. `test_the_condition_names_no_artefact_dt2_itself_
produces` is the structural guard against that, and
`test_a_pre_route_tree_still_self_skips` is the behavioural one.

chip-AGNOSTIC: the shipped flow YAML, the shipped baseline file, and the guard's
own classifier; no design, PDK, foundry, vendor or process literal appears.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import yaml

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import flow_condition_reachability_check as _g  # noqa: E402

FLOW_YAML = PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml"
BASELINE = PROGRAMS.parent / "flow" / "flow_condition_reachability_baseline.json"


def _step(sid: str) -> dict:
    doc = yaml.safe_load(FLOW_YAML.read_text(encoding="utf-8"))
    for st in doc["steps"]:
        if str(st.get("id")) == sid:
            return st
    raise AssertionError(f"the flow no longer declares step {sid}")


def _dt2_record() -> dict:
    recs = [r for r in _g.classify(FLOW_YAML)
            if r["step"] == "DT2" and r["surface"] == "step"]
    assert len(recs) == 1, recs
    return recs[0]


# ------------------------------------------------------------ the condition
def test_dt2_is_reachable_by_the_guards_own_classifier():
    """The guard, not a paraphrase of it.

    RED WITHOUT THE FIX: verdict "self-disabling", rescued from failing the
    build only by the baseline entry this change deletes.
    """
    rec = _dt2_record()
    assert rec["verdict"] == "legitimate-scoping", rec["detail"]


def test_every_dt2_trigger_is_some_steps_declared_output():
    """Each trigger must survive its own subject's absence BECAUSE a step
    declares it, not because the guard happened to find another excuse.

    This is stronger than the verdict above: it pins the REASON, so a future
    edit that keeps DT2 green through, say, a directory backstop (T5) would
    fail here even though the guard would still say PASS.
    """
    rec = _dt2_record()
    reasons = dict(part.split(": ", 1)
                   for part in rec["detail"].split("; ") if ": " in part)
    assert set(reasons) == set(rec["paths"]), (reasons, rec["paths"])
    for path, why in reasons.items():
        assert why.startswith("T3"), (
            f"{path} is reachable via {why!r}, not because a step declares it "
            f"as its sole required_output")


def test_the_condition_is_this_steps_own_blocks_on_written_as_artefacts():
    """DT2 `blocks_on: [DT1, 22]`. The condition must be exactly those two
    steps' declared outputs — no more, so it cannot self-disable on an
    undeclared intermediate, and no fewer, so it cannot arm on a design whose
    upstream never ran."""
    dt2 = _step("DT2")
    assert sorted(str(b) for b in dt2["blocks_on"]) == ["22", "DT1"], dt2["blocks_on"]
    dt1_out = _step("DT1")["required_outputs"]
    s22_out = _step("22")["required_outputs"]
    assert len(dt1_out) == 1 and len(s22_out) == 1, (dt1_out, s22_out)
    # Step 22 declares ONE pattern with two OR branches
    # (`parasitic.spef OR *.spef`); `_build_backstop_index` indexes every branch
    # of a single pattern, and the glob branch is a SUPERSET of the named one,
    # so the branch DT2 cites cannot go unmatched while step 22 stays green.
    declared = set(_g._or_branches(dt1_out[0])) | set(_g._or_branches(s22_out[0]))
    cond = set(dt2["condition"]["files_exist"])
    assert len(cond) == 2, cond
    assert cond <= declared, (cond - declared, declared)
    assert cond & set(_g._or_branches(dt1_out[0])), (
        "DT2 no longer waits for DT1's declared grade")
    assert cond & set(_g._or_branches(s22_out[0])), (
        "DT2 no longer waits for step 22's declared parasitics")
    assert not dt2["condition"].get("any_of"), (
        "DT2's condition became any-of; a single present trigger would then arm "
        "the step before its other upstream had run")


def test_the_condition_names_no_artefact_dt2_itself_produces():
    """WHAT MUST NOT REGRESS — the 2026-07-28 withdrawal.

    That change armed DT2 on `reports/phase2/dft/path_delay_coverage.json` or
    `phase2/stage2/dft/path_delay_atpg_not_run.json`, i.e. on DT2's OWN outputs,
    which trades an input-side self-disable for an output-side one and lets the
    step leave the executed-PASS denominator entirely.

    MUTATION THIS CATCHES: re-arming DT2 on anything it produces, in either the
    any-of or the mirrored-record form.
    """
    dt2 = _step("DT2")
    own = set(dt2["required_outputs"]) | {
        "phase2/stage2/dft/path_delay_atpg_not_run.json",
        "reports/phase2/dft/path_delay_atpg_not_run.json"}
    overlap = own & set(dt2["condition"]["files_exist"])
    assert not overlap, (
        f"DT2 is conditioned on artefacts it produces itself: {sorted(overlap)}")


def test_dt2_no_longer_names_the_two_undeclared_artefacts():
    """The specific hole, pinned by name so a revert is visible."""
    cond = set(_step("DT2")["condition"]["files_exist"])
    assert "phase2/stage2/dft/cut_netlist.v" not in cond, (
        "cut_netlist.v is a step-11 intermediate that step 11 does not declare; "
        "conditioning DT2 on it is the #235 hole")
    assert "phase3/stage3/pnr/*_pnr.v" not in cond, (
        "*_pnr.v is written by the PnR tcl and declared by no step; "
        "conditioning DT2 on it is the #235 hole")


# ---------------------------------------------------------------- the baseline
def test_the_baseline_carries_no_open_holes():
    """The whole point of shrinking it. `flow_condition_reachability_check`
    already FAILs on a baselined entry that is no longer a hole, so this is the
    complementary assertion: the file may not grow one back silently.

    RED WITHOUT THE FIX: one entry, `DT2`.
    """
    doc = json.loads(BASELINE.read_text(encoding="utf-8"))
    assert doc["holes"] == [], (
        "a self-disabling condition is baselined again; the file exists to be "
        "shrunk, never to be a place to put a new one: "
        + json.dumps(doc["holes"])[:400])


def test_the_closed_dt2_adjudication_is_preserved_not_deleted():
    """A baseline entry is an adjudication naming its evidence. Shrinking the
    file must not destroy the record of what was decided and why — otherwise the
    next reader has to re-derive the 2026-07-28 withdrawal from scratch."""
    doc = json.loads(BASELINE.read_text(encoding="utf-8"))
    detail = doc.get("_closed_detail", {}).get("DT2")
    assert detail, "the DT2 entry was deleted without preserving its note"
    assert "vibe-ic#235" in detail["owner"], detail["owner"]
    assert "2026-07-28" in detail["note"], (
        "the withdrawn dimension-6 measurement is no longer recorded anywhere")
    assert sorted(detail["paths"]) == sorted([
        "phase2/stage2/dft/cut_netlist.v",
        "phase3/stage3/extracted/*.spef",
        "phase3/stage3/pnr/*_pnr.v"]), detail["paths"]
    assert any("DT2" in c and "CLOSED" in c for c in doc["_closed"]), doc["_closed"]


def test_the_guard_passes_with_an_empty_baseline():
    """End to end: the file the build actually runs, at its real exit code."""
    import subprocess
    r = subprocess.run(
        [sys.executable, str(PROGRAMS / "flow_condition_reachability_check.py"),
         str(FLOW_YAML)], capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "known-open (0)" in r.stdout, r.stdout
