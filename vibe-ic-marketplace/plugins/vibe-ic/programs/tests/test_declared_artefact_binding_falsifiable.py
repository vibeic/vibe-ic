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
import synth_netlist_check as snc             # noqa: E402

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


def _step32_audit_clause() -> dict:
    return next(c for c in _step32_gate()["all_of"]
                if isinstance(c.get("program_exit_zero"), dict)
                and "postroute_timing_repair_audit" in c["program_exit_zero"]["command"])


def _repair_project(root: Path, files: dict) -> Path:
    repair = root / "phase3/stage3/postroute_timing_repair"
    repair.mkdir(parents=True, exist_ok=True)
    for name, payload in files.items():
        repair.joinpath(name).write_text(
            payload if isinstance(payload, str)
            else json.dumps(payload, indent=2))
    return root
