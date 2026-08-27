#!/usr/bin/env python3
"""Falsifiability tests for the gates that were extended to read the artefacts
their steps DECLARE (steps 9, 11, 14, 32).

WHY THIS FILE EXISTS
--------------------
Each of those gates gained a new rule, and a new rule with no test is a claim,
not a check. An adversarial pass on the first cut of that work found the two
opposite failures a rule can have, and both of them are tested here in BOTH
directions, because fixing one by causing the other is not progress:

  * the rule fires on a LEGITIMATE run (step 9 failed a converged project on
    an mtime ordering the runner creates by construction, and could never
    recover because the FAIL returned before the artefact was refreshed; step
    14 failed any tree holding a phase-3 yosys script, which is necessarily
    newer than a phase-2 handoff netlist);
  * the rule cannot fire on the DEFECT (step 11's requirement was opt-in by
    the very document under audit — deleting one field from a hand-authored
    coverage.json turned it off; step 32's rule was correct but its gate was
    unreachable in exactly the project state it targets).

So every test below is one of two shapes: a DEFECT input that must produce a
non-zero rc / a red verdict, or a LEGITIMATE input that must stay green. A
test file that only held the first shape would be the same mistake again.

chip-AGNOSTIC: every fixture is a synthetic tree built here. No design name,
no PDK, no cell literal — the netlists instantiate a placeholder cell type
whose name carries no library identity.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

import pytest
import yaml

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))

import _yosys_stat as ys                      # noqa: E402
import dft_signoff_check as dft               # noqa: E402
import flow_compliance_check as fcc           # noqa: E402
import synth_netlist_check as snc             # noqa: E402
import yosys_script_template_check as ystc    # noqa: E402

FLOW_YAML = PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml"

# A yosys `stat` capture. Format only — the numbers are this file's own.
STAT_LOG = (
    "\n=== top ===\n\n"
    "   Number of wires:                 60\n"
    "   Number of cells:                 24\n"
    "     SEQ_CELL                       24\n"
)


# ══════════════════════════════════════════════════════════════════════
# fixtures
# ══════════════════════════════════════════════════════════════════════
def _netlist_text(n_cells: int = 24, tag: str = "a") -> str:
    lines = ["module top(clk, rst_n, d, q);",
             "  input clk; input rst_n; input d; output q;"]
    for i in range(n_cells):
        lines.append(f"  SEQ_CELL _{tag}{i}_ (.CLK(clk), .D(d), .Q(n{i}));")
    lines += ["  assign q = n0;", "endmodule"]
    return "\n".join(lines) + "\n"


def _project(root: Path, *, canonical_alias: bool = True,
             tag: str = "a") -> Path:
    """A tree shaped like the one `step_yosys_synth` leaves behind."""
    rtl = root / "phase2/stage1/rtl"
    synth = root / "phase2/stage2/synth"
    rtl.mkdir(parents=True, exist_ok=True)
    synth.mkdir(parents=True, exist_ok=True)
    (rtl / "top.v").write_text(
        "module top(input clk, input rst_n, input d, output reg q);\n"
        "  always @(posedge clk or negedge rst_n)\n"
        "    if(!rst_n) q <= 1'b0; else q <= d;\n"
        "endmodule\n")
    text = _netlist_text(tag=tag)
    (synth / "netlist_yosys.v").write_text(text)
    if canonical_alias:
        (synth / "netlist.v").write_text(text)
    return root


def _run_synth_check(project: Path, netlist: Path):
    r = subprocess.run(
        [sys.executable, str(PROGRAMS / "synth_netlist_check.py"),
         "--netlist", str(netlist),
         "--rtl", str(project / "phase2/stage1/rtl/top.v")],
        capture_output=True, text=True)
    try:
        report = json.loads(r.stdout)
    except ValueError:  # pragma: no cover - only on a crash
        report = {"findings": []}
    return r.returncode, [(f["severity"], f["category"])
                          for f in report["findings"]]


def _emit(project: Path, *, capture: str = STAT_LOG):
    synth = project / "phase2/stage2/synth"
    canon = synth / "netlist.v"
    return ys.emit_stats_json(
        synth, capture,
        netlist_path=canon if canon.is_file() else synth / "netlist_yosys.v",
        log_rel="phase2/stage2/synth/yosys.log",
        netlist_rel="phase2/stage2/synth/netlist.v",
        tool="yosys")


# ══════════════════════════════════════════════════════════════════════
# STEP 9 — the area/stats accounting must describe THIS netlist
# ══════════════════════════════════════════════════════════════════════
def test_step9_rejects_an_area_claim_measured_on_a_different_netlist(tmp_path):
    """THE DEFECT. stats.json records the digest of the netlist it measured and
    names that very path; the file at that path has since been replaced by a
    different design and the accounting was not refreshed. That is a real lie
    about a real number, and nothing legitimate produces it."""
    p = _project(tmp_path / "wrong")
    _emit(p)
    nl = p / "phase2/stage2/synth/netlist.v"
    nl.write_text(_netlist_text(tag="b"))          # different design
    rc, findings = _run_synth_check(p, nl)
    assert rc == 1, findings
    assert ("ERROR", "AREA_ARTEFACT_WRONG_NETLIST") in findings


def test_step9_discloses_an_accounting_for_another_netlist_beside_it(tmp_path):
    """NO FALSE ALARM, and the trap this rule nearly walked into.

    The synthesis directory legitimately holds more than one netlist, and the
    two producers of step 9's ONE declared area artefact disagree about which:
    `design_one_shot_runner` writes stats.json for `netlist.v`, while
    `phase3_one_shot_runner.step_synth` writes `<top>_synth.v` into the SAME
    directory and its emitter overwrites the same stats.json for THAT file —
    and the canonical `netlist.v` alias is only created when absent, so on a
    phase2-then-phase3 run the accounting really is about the other netlist.
    Blocking on that would redden step 9 on every full run. Passing it in
    silence would let a reader quote the number as this netlist's area."""
    p = _project(tmp_path / "twoproducers")
    synth = p / "phase2/stage2/synth"
    other = synth / "top_synth.v"
    other.write_text(_netlist_text(tag="b"))       # a different synthesis
    assert other.read_bytes() != (synth / "netlist.v").read_bytes()
    (synth / "stats.json").write_text(json.dumps({
        "schema": "vibe-ic/synth-stats/1",
        "netlist": "phase2/stage2/synth/top_synth.v",
        ys.NETLIST_DIGEST_FIELD: ys.netlist_digest(other),
        "top_module": "top", "chip_area": 10.0, "cell_count": 24}))
    rc, findings = _run_synth_check(p, synth / "netlist.v")
    assert rc == 0, findings
    assert ("WARNING", "AREA_ARTEFACT_DESCRIBES_ANOTHER_NETLIST") in findings


def test_step9_accepts_a_byte_identical_alias_under_another_name(tmp_path):
    """NO FALSE ALARM. The runner copies `netlist_yosys.v` to `netlist.v` so
    the canonical name exists; auditing the alias must not be reported as "a
    different design" merely because the record spells the other name."""
    p = _project(tmp_path / "alias")
    _emit(p)
    stats = p / "phase2/stage2/synth/stats.json"
    old = time.time() - 3600
    os.utime(stats, (old, old))                    # older than the netlist too
    rc, findings = _run_synth_check(
        p, p / "phase2/stage2/synth/netlist_yosys.v")
    assert rc == 0, findings
    assert not [f for f in findings if f[0] == "ERROR"], findings


def test_step9_accepts_a_re_emitted_but_unchanged_netlist(tmp_path):
    """NO FALSE ALARM, and the exact shape that bricked the runner: pass N
    rewrites the netlist with identical bytes, so stats.json is now OLDER than
    the file it accounts for while describing it perfectly."""
    p = _project(tmp_path / "reemit")
    _emit(p)
    stats = p / "phase2/stage2/synth/stats.json"
    old = time.time() - 3600
    os.utime(stats, (old, old))
    nl = p / "phase2/stage2/synth/netlist.v"
    nl.write_text(nl.read_text())                  # same bytes, newer mtime
    rc, findings = _run_synth_check(p, nl)
    assert rc == 0, findings
    assert not [f for f in findings if f[0] == "ERROR"], findings


def test_step9_three_consecutive_passes_stay_green(tmp_path):
    """The self-perpetuation, tested end to end in the runner's own order:
    refresh the netlist, emit the accounting, gate on it. Pass 1 used to be the
    only green one because the FAIL returned before the emit, so the artefact
    could never catch up."""
    p = _project(tmp_path / "loop")
    synth = p / "phase2/stage2/synth"
    for _ in range(3):
        (synth / "netlist.v").write_text((synth / "netlist_yosys.v").read_text())
        _emit(p)
        rc, findings = _run_synth_check(p, synth / "netlist.v")
        assert rc == 0, findings


def test_step9_discloses_a_record_it_cannot_bind(tmp_path):
    """An artefact with no digest cannot be tied to any netlist. That is a gap
    to state, not a defect to block on — but it must not pass in silence."""
    p = _project(tmp_path / "unbound")
    _emit(p)
    stats = p / "phase2/stage2/synth/stats.json"
    rec = json.loads(stats.read_text())
    rec.pop(ys.NETLIST_DIGEST_FIELD)
    stats.write_text(json.dumps(rec))
    rc, findings = _run_synth_check(p, p / "phase2/stage2/synth/netlist.v")
    assert rc == 0, findings
    assert ("WARNING", "AREA_ARTEFACT_UNBOUND") in findings


def test_step9_rejects_a_zeroed_measurement(tmp_path):
    """THE DEFECT the emitter's anti-fabrication contract forbids writing."""
    p = _project(tmp_path / "zeroed")
    _emit(p)
    stats = p / "phase2/stage2/synth/stats.json"
    rec = json.loads(stats.read_text())
    rec["cells"] = 0
    stats.write_text(json.dumps(rec))
    rc, findings = _run_synth_check(p, p / "phase2/stage2/synth/netlist.v")
    assert rc == 1, findings
    assert ("ERROR", "ZEROED_AREA_ARTEFACT") in findings


def test_step9_rejects_a_zeroed_measurement_in_the_other_producers_schema(tmp_path):
    """THE DEFECT, and it is the "measures something adjacent" shape. Step 9's
    ONE declared area artefact has TWO writers with two payload schemas —
    `_yosys_stat` writes `cells`, `synth_area_stats_emit` writes `cell_count`
    (programs/synth_area_stats_emit.py:428). Reading only the first spelling
    made the ZEROED_AREA_ARTEFACT refusal — the "unmeasured is not zero" guard
    this cell rests on — blind on every artefact the second producer writes."""
    p = _project(tmp_path / "otherschema")
    synth = p / "phase2/stage2/synth"
    nl = synth / "netlist.v"
    (synth / "stats.json").write_text(json.dumps({
        "schema": "vibe-ic/synth-stats/1",
        "netlist": "phase2/stage2/synth/netlist.v",
        ys.NETLIST_DIGEST_FIELD: ys.netlist_digest(nl),
        "chip_area": 10.0, "cell_count": 0}))
    rc, findings = _run_synth_check(p, nl)
    assert rc == 1, findings
    assert ("ERROR", "ZEROED_AREA_ARTEFACT") in findings


def test_step9_accepts_a_real_measurement_in_the_other_producers_schema(tmp_path):
    """NO FALSE ALARM: the same schema carrying a REAL count stays rc 0, and
    the count is reported rather than shown as "not recorded"."""
    p = _project(tmp_path / "otherschema_ok")
    synth = p / "phase2/stage2/synth"
    nl = synth / "netlist.v"
    (synth / "stats.json").write_text(json.dumps({
        "schema": "vibe-ic/synth-stats/1",
        "netlist": "phase2/stage2/synth/netlist.v",
        ys.NETLIST_DIGEST_FIELD: ys.netlist_digest(nl),
        "chip_area": 10.0, "cell_count": 24}))
    rc, findings = _run_synth_check(p, nl)
    assert rc == 0, findings
    assert not [f for f in findings if f[1] == "ZEROED_AREA_ARTEFACT"]
    import synth_netlist_check as _snc
    _, info = _snc.audit_area_stats(nl)
    assert info["recorded_cells"] == 24, info
    assert info["recorded_cells_field"] == "cell_count", info


def test_emit_removes_its_own_artefact_when_the_binding_is_broken(tmp_path):
    """THE DEFECT. No measurement, and the netlist the earlier record describes
    has since been REPLACED — the record now reads as this pass's accounting
    for a design it never measured. That is the ghost, and it is worse than
    absence, because absence is what step 9's required_outputs reports."""
    p = _project(tmp_path / "ghost")
    assert _emit(p) is not None
    stats = p / "phase2/stage2/synth/stats.json"
    assert stats.is_file()
    (p / "phase2/stage2/synth/netlist.v").write_text(_netlist_text(tag="b"))
    assert _emit(p, capture="") is None            # empty capture
    assert not stats.exists()


def test_emit_keeps_an_artefact_that_still_binds_to_the_netlist(tmp_path):
    """NO FALSE ALARM, and the tier the first cut of this rule measured on the
    wrong side. An empty capture is the documented docker-fallback shape: rc 0
    with no stdout, on a tree nobody touched. Removing the record there took
    step 9 from PASS to MISSING for an accounting that was still TRUE — the
    netlist beside it is byte-identical and still hashes to the recorded
    digest — and it is self-perpetuating, because every later pass takes the
    same path. Removal is therefore keyed on the CONTENT binding, not on the
    fact that a pass produced no numbers."""
    p = _project(tmp_path / "stillbinds")
    assert _emit(p) is not None
    stats = p / "phase2/stage2/synth/stats.json"
    before = stats.read_bytes()
    assert _emit(p, capture="") is None            # empty capture, tree untouched
    assert stats.is_file(), (
        "an empty capture deleted a stats.json whose recorded netlist_sha256 "
        "still matches the netlist beside it")
    assert stats.read_bytes() == before
    assert _emit(p, capture="") is None            # and again — no drift
    assert stats.is_file()
    rc, findings = _run_synth_check(p, p / "phase2/stage2/synth/netlist.v")
    assert rc == 0, findings


def test_emit_removes_a_record_it_cannot_bind_at_all(tmp_path):
    """A record with no ``netlist_sha256`` cannot be shown to describe anything
    on disk, so an unmeasured pass may not leave it standing as this pass's
    accounting. This is the one case where removal is unconditional."""
    p = _project(tmp_path / "unbindable")
    stats = p / "phase2/stage2/synth/stats.json"
    stats.write_text(json.dumps({
        "measured_from": "phase2/stage2/synth/yosys.log",
        "netlist": "phase2/stage2/synth/netlist.v",
        "cells": 24, "chip_area": 10.0}))
    assert _emit(p, capture="") is None
    assert not stats.exists()


def test_emit_never_deletes_another_writer_s_artefact(tmp_path):
    """The removal above is scoped to this module's own schema. A file that
    does not carry it belongs to someone else and is left where it is."""
    p = _project(tmp_path / "foreign")
    stats = p / "phase2/stage2/synth/stats.json"
    stats.write_text(json.dumps({"schema": "someone-elses/1", "chip_area": 12}))
    assert _emit(p, capture="") is None
    assert stats.is_file()
    assert json.loads(stats.read_text())["schema"] == "someone-elses/1"


def test_runner_writes_the_area_stats_before_it_gates_on_them():
    """THE ORDERING, pinned. The gate reads an artefact the synth step writes,
    so the write must precede the gate; when it did not, a converged project
    failed forever. A source-order assertion because driving yosys needs the
    container."""
    import inspect
    import design_one_shot_runner as dr
    src = inspect.getsource(dr.step_yosys_synth)
    emit_at = src.index("emit_stats_json")
    gate_at = src.index("synth_netlist_check.py")
    assert emit_at < gate_at, (
        "step_yosys_synth must emit stats.json BEFORE invoking "
        "synth_netlist_check: the check compares the accounting against the "
        "netlist, and the netlist is rewritten at the top of every pass, so a "
        "stats.json written after the gate is judged on the NEXT pass while "
        "describing the PREVIOUS one — and the gate's FAIL returns before the "
        "emit, so the project can never recover")


# ══════════════════════════════════════════════════════════════════════
# STEP 14 — the handoff netlist, and staleness only against a PRODUCER
# ══════════════════════════════════════════════════════════════════════
_SYNTH_YS = ("read_verilog -sv ../../stage1/rtl/top.v\n"
             "synth -top top -flatten\n"
             "hilomap -hicell TIEHI Y -locell TIELO Y\n"
             "write_verilog -noattr netlist.v\n")
# A post-synthesis equivalence script: it CONSUMES the handoff netlist and
# never writes it, so it is not its producer.
_LATER_YS = ("read_verilog -sv ../../phase2/stage2/synth/netlist.v\n"
             "synth -top top -flatten\n"
             "hilomap -hicell TIEHI Y -locell TIELO Y\n")


def _ys_project(root: Path, *, later_script_newer: bool,
                producer_newer: bool = False, stub: bool = False) -> Path:
    p = _project(root)
    synth = p / "phase2/stage2/synth"
    (synth / "synth.ys").write_text(_SYNTH_YS)
    later = p / "phase3/lec"
    later.mkdir(parents=True, exist_ok=True)
    (later / "post.ys").write_text(_LATER_YS)
    if stub:
        (synth / "netlist.v").write_text("// nothing here\n")
    old = time.time() - 4 * 3600
    for f in (synth / "synth.ys", synth / "netlist.v", synth / "netlist_yosys.v"):
        os.utime(f, (old, old))
    os.utime(later / "post.ys",
             (time.time(), time.time()) if later_script_newer
             else (old - 60, old - 60))
    if producer_newer:
        os.utime(synth / "synth.ys", (time.time(), time.time()))
    return p


def _run_ys_check(project: Path):
    r = subprocess.run(
        [sys.executable, str(PROGRAMS / "yosys_script_template_check.py"),
         str(project), "--json", str(project / "ys.json")],
        capture_output=True, text=True)
    return r.returncode, json.loads((project / "ys.json").read_text())


def test_step14_rejects_a_handoff_older_than_its_own_producer(tmp_path):
    """THE DEFECT. The script that declares itself the writer of
    phase2/stage2/synth/netlist.v has been edited since the netlist was
    produced, so PnR would consume the product of a recipe nobody ran."""
    p = _ys_project(tmp_path / "prod", later_script_newer=False,
                    producer_newer=True)
    rc, report = _run_ys_check(p)
    assert rc == 1, report
    assert report["handoff_netlist_audit"]["stale_vs_scripts"], report


def test_step14_ignores_a_script_that_does_not_write_the_handoff(tmp_path):
    """NO FALSE ALARM. Phase 3 runs after phase 2 by construction, so a yosys
    script under phase3/ is ALWAYS newer than the phase-2 handoff netlist. It
    consumes that netlist; its clock says nothing about whether the netlist is
    the product of the synthesis recipe."""
    p = _ys_project(tmp_path / "later", later_script_newer=True)
    rc, report = _run_ys_check(p)
    assert rc == 0, report
    assert report["handoff_netlist_audit"]["stale_vs_scripts"] == []
    assert [Path(s).name for s
            in report["handoff_netlist_audit"]["producer_scripts"]] == ["synth.ys"]


def test_step14_records_that_staleness_was_not_compared(tmp_path):
    """Unmeasured is recorded as unmeasured. When no audited script claims to
    write the handoff netlist there is nothing to compare, and the report must
    say so rather than present a bare pass."""
    p = _project(tmp_path / "nonproducer")
    later = p / "phase3/lec"
    later.mkdir(parents=True, exist_ok=True)
    (later / "post.ys").write_text(_LATER_YS)
    rc, report = _run_ys_check(p)
    assert rc == 0, report
    assert report["handoff_netlist_audit"]["producer_scripts"] == []
    assert any("staleness not compared" in m
               for m in report["handoff_netlist_messages"]), report


def test_step14_still_rejects_a_stub_handoff_netlist(tmp_path):
    """The substantive half of the gate, unchanged by the narrowing above."""
    p = _ys_project(tmp_path / "stub", later_script_newer=False, stub=True)
    rc, report = _run_ys_check(p)
    assert rc == 1, report
    assert report["handoff_netlist_audit"]["has_module"] is False


# ══════════════════════════════════════════════════════════════════════
# STEP 11 — the DOCUMENTED tier must have a document
# ══════════════════════════════════════════════════════════════════════
_ENGINE_LIMITED_REASON = "the open-source ATPG engine has no at-speed mode"


def _coverage(named_plan: bool) -> dict:
    block = {"fault_model": "transition", "supported": False,
             "engine_limited": True, "coverage_pct": None,
             "target_pct": 90.0, "reason": _ENGINE_LIMITED_REASON}
    if named_plan:
        block["plan_file"] = dft.TRANSITION_PLAN_REL
    return {"transition": block}


def _write_plan(project: Path, size: int = 1500) -> Path:
    plan = project / dft.TRANSITION_PLAN_REL
    plan.parent.mkdir(parents=True, exist_ok=True)
    plan.write_text("# at-speed mechanism plan\n" + ("x" * size))
    return plan


@pytest.mark.parametrize("names_plan", [True, False])
def test_step11_engine_limited_without_the_plan_fails(tmp_path, names_plan):
    """THE DEFECT, and specifically its opt-out. The requirement must not be
    switchable off by deleting `plan_file` from the very document under audit:
    with the field and without it, an absent plan is the same missing
    deliverable."""
    project = tmp_path / f"noplan_{names_plan}"
    project.mkdir()
    out = dft.evaluate_transition(_coverage(names_plan), 90.0, project=project)
    assert out["status"] == "FAIL", out
    assert out["plan_present"] is False


@pytest.mark.parametrize("names_plan", [True, False])
def test_step11_engine_limited_with_the_plan_is_accepted(tmp_path, names_plan):
    """NO FALSE ALARM. The tier is legitimate when the document the flow
    declares is actually there, whether or not the record names it."""
    project = tmp_path / f"plan_{names_plan}"
    project.mkdir()
    _write_plan(project)
    out = dft.evaluate_transition(_coverage(names_plan), 90.0, project=project)
    assert out["status"] == "ENGINE_LIMITED", out
    assert out["plan_present"] is True


def test_step11_rejects_a_placeholder_at_the_declared_path(tmp_path):
    """THE DEFECT, one step subtler: a file exists but carries no plan."""
    project = tmp_path / "stubplan"
    project.mkdir()
    _write_plan(project, size=3)
    out = dft.evaluate_transition(_coverage(True), 90.0, project=project)
    assert out["status"] == "FAIL", out


def test_step11_pure_dict_callers_are_unaffected(tmp_path):
    """NO FALSE ALARM for a caller that supplies no project root: there is no
    disk to look at, so nothing is asserted about a document."""
    out = dft.evaluate_transition(_coverage(True), 90.0)
    assert out["status"] == "ENGINE_LIMITED", out


# ══════════════════════════════════════════════════════════════════════
# STEP 32 — the gate must RUN in the state the cross-check targets
# ══════════════════════════════════════════════════════════════════════
_DECISION_REPAIR_REQUIRED = {"repair_needed": True, "action": "run_repair",
                          "reason": "a hard sign-off domain failed",
                          "nontiming_failures": [{"domain": "ir_drop"}]}
_DECISION_NO_REPAIR = {"repair_needed": False, "action": "none",
                    "reason": "every sign-off domain passed first time"}


def _step32_gate() -> dict:
    doc = yaml.safe_load(FLOW_YAML.read_text())
    return [s for s in doc["steps"] if str(s.get("id")) == "32"][0]["gate"]


def _repair_project(root: Path, files: dict) -> Path:
    repair = root / "phase3/stage3/postroute_timing_repair"
    repair.mkdir(parents=True, exist_ok=True)
    for name, payload in files.items():
        repair.joinpath(name).write_text(
            payload if isinstance(payload, str)
            else json.dumps(payload, indent=2))
    return root


def test_step32_flow_gate_goes_red_on_a_contradicted_no_repair_branch(tmp_path):
    """THE DEFECT, through the REAL evaluator. The decision record says a repair
    was required; the run certified `no_repair_needed.flag`. The program caught it
    from the start — the gate never ran it, because its condition listed the
    repair LOG, which the no-repair branch by definition does not write."""
    p = _repair_project(tmp_path / "contradicted", {
        "no_repair_needed.flag": "no repair needed\n",
        "postroute_timing_repair_decision.json": _DECISION_REPAIR_REQUIRED})
    passed, reasons = fcc._evaluate_gate(p, _step32_gate())
    assert passed is False, reasons
    assert any("postroute_timing_repair_audit" in r for r in reasons), reasons


def test_step32_flow_gate_stays_green_on_a_consistent_no_repair_run(tmp_path):
    """NO FALSE ALARM. Flag plus a decision record that agrees with it is the
    ordinary converged run, and it must not be reddened by making the gate
    reachable."""
    p = _repair_project(tmp_path / "consistent", {
        "no_repair_needed.flag": "no repair needed\n",
        "postroute_timing_repair_decision.json": _DECISION_NO_REPAIR})
    passed, reasons = fcc._evaluate_gate(p, _step32_gate())
    assert passed is True, reasons


def test_step32_flow_gate_stays_green_when_an_repair_really_ran(tmp_path):
    """NO FALSE ALARM on the other branch."""
    p = _repair_project(tmp_path / "ecoran", {
        "repair_log.json": {"changes": [{"type": "buffer_insert", "net": "n0"}],
                         "re_verified": True, "affected_steps": [21]},
        "postroute_timing_repair_decision.json": _DECISION_REPAIR_REQUIRED})
    passed, reasons = fcc._evaluate_gate(p, _step32_gate())
    assert passed is True, reasons


def test_step32_reads_the_record_through_the_path_it_declares(tmp_path):
    """The literal the gate is grounded on must be the literal it OPENS.

    A path constant that appears only inside a message f-string satisfies a
    static "is this gate wired to its step's artefact?" audit on the strength
    of the gate's prose: delete the read, keep the message, and the audit still
    reports wired. Composing the read from the constant is what makes that
    mutation visible — this test fails if `load_trigger_decision` stops
    returning what the declared path holds."""
    import postroute_timing_repair_audit as ela
    p = _repair_project(tmp_path / "declared", {
        "postroute_timing_repair_decision.json": _DECISION_REPAIR_REQUIRED})
    assert (ela.decision_path(p)
            == p / "phase3/stage3/postroute_timing_repair/postroute_timing_repair_decision.json")
    decision, problem = ela.load_trigger_decision(p)
    assert problem is None
    assert decision == _DECISION_REPAIR_REQUIRED


def test_step32_discloses_but_does_not_block_on_a_silent_decision(tmp_path):
    """NO FALSE ALARM, deliberately.

    A decision record that states no `repair_needed` says nothing, and that is
    reported — but it does not block. `postroute_timing_repair_decision.decide` sets the
    field on every path, so no run this flow produces reaches this state; the
    trees that do are synthesized ones, and blocking cost step 32 its place in
    `test_matrix_d8_missing_caught.REAL_GATE_PASS_TIER_STEPS` (the only
    production-gate proof that its missing-output downgrade is reachable).
    Measured coverage lost elsewhere is not worth a guard on an unreachable
    state."""
    p = _repair_project(tmp_path / "silent", {
        "no_repair_needed.flag": "no repair needed\n",
        "postroute_timing_repair_decision.json": {}})
    r = subprocess.run(
        [sys.executable, str(PROGRAMS / "postroute_timing_repair_audit.py"), str(p)],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "TRIGGER_DECISION_SILENT" in r.stdout + r.stderr
    passed, reasons = fcc._evaluate_gate(p, _step32_gate())
    assert passed is True, reasons


def test_step32_clause_stays_reddenable_under_the_d2_harness(tmp_path):
    """The gate condition must not be widened into unfalsifiability.

    `test_matrix_d2_falsifiable` proves each blocking clause CAN fail by
    materialising every `condition_files_exist` path as a substanceless file
    and running the clause. If `no_repair_needed.flag` were listed there, that
    materialisation would hand the audit a flag-certified no-repair run and the
    clause could never reach FAIL again. This asserts the property directly, on
    the yaml, so the next widening has to face it."""
    gate = _step32_gate()
    clause = [c for c in gate["all_of"]
              if "optional_program_exit_zero" in c][0]
    conds = clause["optional_program_exit_zero"]["condition_files_exist"]
    assert "phase3/stage3/postroute_timing_repair/postroute_timing_repair_decision.json" in conds, conds
    assert "phase3/stage3/postroute_timing_repair/no_repair_needed.flag" not in conds, conds
    # ... and the materialised state really does still fail.
    p = tmp_path / "d2shape"
    repair = p / "phase3/stage3/postroute_timing_repair"
    repair.mkdir(parents=True)
    for pat in conds:
        (p / pat).write_text("{}\n")
    passed, reasons = fcc._evaluate_gate(p, gate)
    assert passed is False, reasons


def test_step32_absent_decision_record_is_left_to_required_outputs(tmp_path):
    """NO FALSE ALARM. A project with no decision record at all is not this
    gate's to fail — step 32's `required_outputs` is what reports a missing
    artefact, and double-failing it here would make the two disagree."""
    p = _repair_project(tmp_path / "norecord",
                     {"no_repair_needed.flag": "no repair needed\n"})
    r = subprocess.run(
        [sys.executable, str(PROGRAMS / "postroute_timing_repair_audit.py"), str(p)],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr
    passed, reasons = fcc._evaluate_gate(p, _step32_gate())
    assert passed is True, reasons


def test_step32_reports_a_declared_vs_catalogued_path_drift(tmp_path,
                                                            monkeypatch):
    """The drift guard is falsifiable. If `_path_layout` ever moves the repair
    directory away from the spelling the flow declares, this gate would read a
    path nothing writes and report "no decision to cross-check" — a false
    clean. It must say the two disagree instead."""
    import _path_layout as pl
    import postroute_timing_repair_audit as ela
    p = _repair_project(tmp_path / "drift", {
        "postroute_timing_repair_decision.json": _DECISION_REPAIR_REQUIRED})
    monkeypatch.setattr(ela._pl, "postroute_timing_repair_dir",
                        lambda project: Path(project) / "somewhere/else")
    decision, problem = ela.load_trigger_decision(p)
    assert decision is None
    assert problem is not None
    assert problem.category == "TRIGGER_DECISION_PATH_DRIFT"
    assert problem.severity == "ERROR"
