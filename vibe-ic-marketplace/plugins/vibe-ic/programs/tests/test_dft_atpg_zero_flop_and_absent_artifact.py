"""DFT/ATPG: a hollow at-speed result must never read as a pass.

Two defects, one area.

  1. ABSENT ARTEFACT. The transition-delay-fault coverage artefact was simply
     missing, and nothing anywhere distinguished "the step never ran" from "it
     ran and wrote nothing" from "it ran and self-skipped" — three different
     repairs, one silence. An absent artefact is now BLOCKED when the step left
     a record of why, and FAIL when it left nothing at all. Never a pass.

  2. VACUOUS PASS ON ZERO FLOPS. The ATPG flop detector matched cell NAMES, so a
     library whose flops are spelled with a single underscore separator yielded
     0 of 65 flops detected, no scan chain cut, and `scan_flops: 0` scored PASS
     via a NOT_APPLICABLE self-skip. Flop identification now comes from the `ff`
     groups of the Liberty the flow already reads — a cell's `ff` group is
     authoritative, its name is not — and a zero-flop result on a design that
     has flops FAILs.

Everything here tests PUBLIC behaviour: the gate's `main()` exit status and the
verdict in its report, on fixtures built out of files on disk. No naming
convention, no PDK name, no chip name appears in any assertion — the cell names
in the fixtures are deliberately synthetic and are never matched against.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))

import fault_atpg_run as far                  # noqa: E402
import transition_coverage_check as tcc       # noqa: E402
import flow_compliance_check as fcc           # noqa: E402


# --------------------------------------------------------------------------
# Fixture material. Two libraries with DIFFERENT separator conventions and a
# third with none at all, to make the point that the identification must not
# care. Each declares one combinational cell and one cell with an `ff` group.
# --------------------------------------------------------------------------
LIB_SINGLE_SEP = """
library (fixture_single) {
  cell (xx13g2_and2_1) { area : 1; pin (X) { function : "A*B"; } }
  cell (xx13g2_qreg_1) {
    area : 5;
    ff (IQ,IQN) { next_state : "D"; clocked_on : "CLK"; }
    pin (Q) { function : "IQ"; }
  }
  cell (xx13g2_dlhq_1) { latch (IQ,IQN) { enable : "G"; } }
}
"""

LIB_DOUBLE_SEP = """
library (fixture_double) {
  cell (yylib__and2_1) { area : 1; pin (X) { function : "A*B"; } }
  cell (yylib__dfxtp_1) {
    area : 5;
    ff (IQ,IQN) { next_state : "D"; clocked_on : "CLK"; }
  }
}
"""

LIB_NO_SEP_AT_ALL = """
library (fixture_bare) {
  cell (AN2) { pin (X) { function : "A*B"; } }
  cell (REGISTERCELL) { ff (IQ,IQN) { next_state : "D"; } }
}
"""

NETLIST_WITH_FLOPS = """
module dut (clk, a, b, y);
  input clk, a, b;
  output y;
  wire w;
  xx13g2_and2_1 g1 (.A(a), .B(b), .X(w));
  xx13g2_qreg_1 \\state_reg[0]  (.D(w), .CLK(clk), .Q(y));
  xx13g2_qreg_1 \\state_reg[1]  (.D(w), .CLK(clk), .Q(y2));
endmodule
"""

NETLIST_COMBINATIONAL = """
module dut (a, b, y);
  input a, b;
  output y;
  xx13g2_and2_1 g1 (.A(a), .B(b), .X(y));
endmodule
"""


def _project(tmp_path: Path, coverage: dict | None = None,
             not_run: dict | None = None) -> Path:
    p = tmp_path / "proj"
    (p / "reports" / "phase2" / "dft").mkdir(parents=True, exist_ok=True)
    (p / "phase2" / "stage2" / "dft").mkdir(parents=True, exist_ok=True)
    if coverage is not None:
        (p / "reports/phase2/dft/transition_coverage.json").write_text(
            json.dumps(coverage))
    if not_run is not None:
        (p / "phase2/stage2/dft/transition_atpg_not_run.json").write_text(
            json.dumps(not_run))
    return p


def _real_result(scan_flops: int = 64, n_det: int = 96, n_red: int = 2,
                 n_abort: int = 2, **extra) -> dict:
    """A complete, honest ATPG result: real per-fault verdicts, coverage well
    over the floor, and authoritative evidence that the design has flops."""
    fl = ([{"net": f"n{i}", "verdict": "DET"} for i in range(n_det)]
          + [{"net": f"r{i}", "verdict": "RED"} for i in range(n_red)]
          + [{"net": f"a{i}", "verdict": "ABORT"} for i in range(n_abort)])
    blob = {
        "verdict": "PASS", "scan_flops": scan_flops,
        "detected": n_det, "redundant": n_red, "aborted": n_abort,
        "fault_list": fl, "floor_pct": 90.0,
        "sequential_evidence": far.sequential_evidence(NETLIST_WITH_FLOPS,
                                                       LIB_SINGLE_SEP),
    }
    blob.update(extra)
    return blob


# ==========================================================================
# The authoritative identification itself: the `ff` group, not the name.
# ==========================================================================
def test_flop_identified_from_ff_group_whatever_the_name_convention():
    for lib, flop, comb in ((LIB_SINGLE_SEP, "xx13g2_qreg_1", "xx13g2_and2_1"),
                            (LIB_DOUBLE_SEP, "yylib__dfxtp_1", "yylib__and2_1"),
                            (LIB_NO_SEP_AT_ALL, "REGISTERCELL", "AN2")):
        seq = far.liberty_sequential_cells(lib)
        assert flop in seq, f"{flop} declares an ff group and must be found"
        assert comb not in seq, f"{comb} has no ff group and must not be"


def test_latch_cell_is_not_a_flop_unless_asked_for():
    assert "xx13g2_dlhq_1" not in far.liberty_sequential_cells(LIB_SINGLE_SEP)
    assert "xx13g2_dlhq_1" in far.liberty_sequential_cells(
        LIB_SINGLE_SEP, include_latches=True)


def test_cut_dff_list_is_derived_from_the_library_not_the_spelling():
    # The historical name pattern is given no chance to help: `xx13g2_qreg_1`
    # carries none of the DFF/SDFF/`[s][e]df` shape the name heuristic keys on,
    # so it matches nothing in this netlist. The Liberty still identifies the
    # flop from its `ff` group.
    assert far.detect_dff_cells(NETLIST_WITH_FLOPS) == ""
    got = far.detect_dff_cells(NETLIST_WITH_FLOPS,
                               far.liberty_sequential_cells(LIB_SINGLE_SEP))
    assert got == "xx13g2_qreg_1"


def test_evidence_distinguishes_absent_flops_from_unchecked():
    has = far.sequential_evidence(NETLIST_WITH_FLOPS, LIB_SINGLE_SEP)
    assert has["verdict"] == far.SEQ_PRESENT and has["authoritative"]

    none = far.sequential_evidence(NETLIST_COMBINATIONAL, LIB_SINGLE_SEP)
    assert none["verdict"] == far.SEQ_ABSENT and none["authoritative"]

    # No Liberty at all: the design was never checked. That is UNKNOWN, and it
    # must not be confused with "no flops" — the whole defect in one assertion.
    unchecked = far.sequential_evidence(NETLIST_COMBINATIONAL, None)
    assert unchecked["verdict"] == far.SEQ_UNKNOWN
    assert not unchecked["authoritative"]


# ==========================================================================
# FIXTURE A — a design that HAS flops, zero detected. Must FAIL.
# ==========================================================================
def test_zero_flops_on_a_design_with_flops_fails(tmp_path):
    blob = {
        "verdict": "NOT_APPLICABLE", "scan_flops": 0,
        "reasons": ["no sequential (scan-cut) flops found in the core"],
        "sequential_evidence": far.sequential_evidence(NETLIST_WITH_FLOPS,
                                                       LIB_SINGLE_SEP),
    }
    proj = _project(tmp_path, coverage=blob)
    rep = tcc.audit(proj)
    assert rep["verdict"] == "FAIL", rep
    assert rep["verdict"] != "PASS"
    assert tcc.main([str(proj)]) == 1
    assert any("inserted nothing" in r for r in rep["reasons"]), rep["reasons"]


def test_zero_flops_claim_with_no_evidence_at_all_is_blocked(tmp_path):
    # The artefact exactly as the un-augmented producer wrote it: a bare
    # NOT_APPLICABLE on scan_flops 0, with nothing behind it. Not a pass.
    proj = _project(tmp_path, coverage={"verdict": "NOT_APPLICABLE",
                                        "scan_flops": 0})
    rep = tcc.audit(proj)
    assert rep["verdict"] == "BLOCKED", rep
    assert tcc.main([str(proj)]) == 1


def test_zero_flops_is_not_rescued_by_a_coverage_number(tmp_path):
    # A numeric result over a core into which nothing was cut measures nothing.
    blob = _real_result(scan_flops=0)
    blob["sequential_evidence"] = far.sequential_evidence(NETLIST_WITH_FLOPS,
                                                          LIB_SINGLE_SEP)
    proj = _project(tmp_path, coverage=blob)
    assert tcc.audit(proj)["verdict"] == "FAIL"


# ==========================================================================
# FIXTURE B — a genuinely flop-free design. Must NOT false-FAIL.
# ==========================================================================
def test_genuinely_combinational_design_still_self_skips(tmp_path):
    blob = {
        "verdict": "NOT_APPLICABLE", "scan_flops": 0,
        "reasons": ["combinational design has no launch-off-capture faults"],
        "sequential_evidence": far.sequential_evidence(NETLIST_COMBINATIONAL,
                                                       LIB_SINGLE_SEP),
    }
    proj = _project(tmp_path, coverage=blob)
    rep = tcc.audit(proj)
    assert rep["verdict"] == "NOT_APPLICABLE", rep
    assert tcc.main([str(proj)]) == 0


# ==========================================================================
# FIXTURE C — the coverage artefact is absent. Must FAIL or BLOCK, never pass.
# ==========================================================================
def test_absent_artifact_with_no_record_fails(tmp_path):
    proj = _project(tmp_path)  # nothing on disk at all
    rep = tcc.audit(proj)
    assert rep["verdict"] == "FAIL", rep
    assert tcc.main([str(proj)]) == 1
    assert any("ran at all" in r for r in rep["reasons"]), rep["reasons"]


def test_absent_artifact_with_a_not_run_record_is_blocked_with_the_reason(tmp_path):
    for stage, why in (
            ("precondition_unmet",
             "transition-delay-fault ATPG NEVER RAN — precondition unmet: "
             "phase2/stage2/dft/cut_netlist.v absent"),
            ("producer_wrote_no_artifact",
             "transition-delay-fault ATPG RAN but wrote no "
             "transition_coverage.json (producer exit 1)"),
            ("producer_execution_error",
             "transition ATPG execution error: timed out")):
        proj = _project(tmp_path / stage, not_run={
            "verdict": "SKIPPED-CONDITION", "reason": why,
            "not_run_stage": stage})
        rep = tcc.audit(proj)
        assert rep["verdict"] == "BLOCKED", rep
        assert rep["not_run_stage"] == stage, rep
        # The reason survives to the gate verdict, so the three states stay
        # distinguishable in the report instead of collapsing into silence.
        assert why[:40] in " ".join(rep["reasons"]), rep["reasons"]
        assert tcc.main([str(proj)]) == 1


def test_producer_blocked_verdict_is_not_a_pass(tmp_path):
    proj = _project(tmp_path, coverage={
        "verdict": "BLOCKED", "scan_flops": 0,
        "reasons": ["could not establish whether the design has flops"]})
    assert tcc.audit(proj)["verdict"] == "BLOCKED"
    assert tcc.main([str(proj)]) == 1


# ==========================================================================
# FIXTURE D — a real, complete ATPG result. Must still PASS.
# A gate that cannot return clean is an alarm, not a gate.
# ==========================================================================
def test_real_complete_result_still_passes(tmp_path):
    proj = _project(tmp_path, coverage=_real_result())
    rep = tcc.audit(proj)
    assert rep["verdict"] == "PASS", rep
    assert rep["tdf_test_coverage_pct"] >= 90.0
    assert tcc.main([str(proj)]) == 0


def test_real_result_passes_even_with_a_stale_not_run_record(tmp_path):
    # A real measurement is evidence; a leftover record from an earlier attempt
    # must not block it.
    proj = _project(tmp_path, coverage=_real_result(),
                    not_run={"verdict": "SKIPPED-CONDITION",
                             "reason": "stale record from a prior attempt"})
    assert tcc.audit(proj)["verdict"] == "PASS"
    assert tcc.main([str(proj)]) == 0


def test_real_result_below_floor_still_fails(tmp_path):
    # The floor gate is untouched by any of this.
    proj = _project(tmp_path, coverage=_real_result(n_det=50, n_red=0,
                                                    n_abort=50))
    assert tcc.audit(proj)["verdict"] == "FAIL"


# ==========================================================================
# Flow visibility: a step whose only trigger is its own input disappears when
# that input is missing. Its not-run record must be able to reach the gate.
# ==========================================================================
def test_condition_any_of_lets_a_not_run_record_reach_the_gate(tmp_path):
    cond = {"any_of": True,
            "files_exist": ["phase2/stage2/dft/cut_netlist.v",
                            "reports/phase2/dft/transition_coverage.json",
                            "phase2/stage2/dft/transition_atpg_not_run.json"]}
    proj = _project(tmp_path, not_run={"verdict": "SKIPPED-CONDITION",
                                       "reason": "cut netlist absent"})
    assert fcc._check_condition(proj, cond) is True
    # Nothing at all present → the step legitimately does not run.
    assert fcc._check_condition(tmp_path / "empty", cond) is False


def test_condition_all_of_semantics_are_unchanged_by_default(tmp_path):
    proj = _project(tmp_path, not_run={"verdict": "SKIPPED-CONDITION",
                                       "reason": "x"})
    cond = {"files_exist": ["phase2/stage2/dft/cut_netlist.v",
                            "phase2/stage2/dft/transition_atpg_not_run.json"]}
    assert fcc._check_condition(proj, cond) is False
