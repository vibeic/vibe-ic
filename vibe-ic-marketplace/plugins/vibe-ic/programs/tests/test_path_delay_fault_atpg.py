"""Unit tests for path_delay_fault_atpg_run.py + path_delay_coverage_check.py.

The heavy path (OpenSTA + Yosys `sat` in Docker) is validated end-to-end on spm
(recorded in the gatekeeper report), not re-run here. These tests cover the PURE
helpers, which carry the soundness guarantees:
  - OpenSTA report parsing (start/end kind, launch/capture edge, arrival, slack,
    hop cell sequence) for reg→reg, reg→PO, and PI-launched paths
  - launch initial-value from edge (^ rise → 0, v fall → 1)
  - top-K selection (LOC-launchable only, ranked by arrival; PI paths set aside)
  - PDF miter shape (2 frames, ok = launch ∧ endpoint-transition; robust = SIC
    launch where only the start flop toggles; PO-endpoint wiring)
  - classify_path (covered ONLY on nr==DET; robust ONLY on r==DET; RED/ABORT
    never covered)
  - PDF coverage math + the gate's FALSE-CLEAN-PROOF recount
  - NOT_APPLICABLE passthrough, zero-evidence FAIL, floor never relaxed
"""
import sys
from pathlib import Path

import pytest

PROG_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG_DIR))

import path_delay_fault_atpg_run as pdf  # noqa: E402
import path_delay_coverage_check as gate  # noqa: E402


# A real-shape OpenSTA `report_checks -format full_clock_expanded` fragment:
# one reg→PO path, one reg→reg path, and one PI-launched path.
STA_RPT = """\
Startpoint: _392_ (rising edge-triggered flip-flop clocked by clk)
Endpoint: p (output port clocked by clk)
Path Group: clk
Path Type: max

      Cap      Slew     Delay      Time   Description
-------------------------------------------------------------------------------
             0.0000    0.0000    0.0000   clock clk (rise edge)
             0.0000    0.0000    0.0000 ^ _392_/CK (DFFHQD1)
   0.0010    0.0489    0.2075    0.2075 ^ _392_/Q (DFFHQD1)
             0.0489    0.0000    0.2075 ^ p (out)
                                 0.2075   data arrival time

                      -2.0000    8.0000   output external delay
                                 8.0000   data required time
-------------------------------------------------------------------------------
                                 8.0000   data required time
                                -0.2075   data arrival time
-------------------------------------------------------------------------------
                                 7.7925   slack (MET)


Startpoint: _419_ (rising edge-triggered flip-flop clocked by clk)
Endpoint: _418_ (rising edge-triggered flip-flop clocked by clk)
Path Group: clk
Path Type: max

      Cap      Slew     Delay      Time   Description
-------------------------------------------------------------------------------
             0.0000    0.0000    0.0000   clock clk (rise edge)
             0.0000    0.0000    0.0000 ^ _419_/CK (DFFHQD1)
   0.0159    0.1728    0.2873    0.2873 ^ _419_/Q (DFFHQD1)
             0.1728    0.0002    0.2875 ^ _389_/B (XNOR2D1)
   0.0088    0.0822    0.1927    0.4801 v _389_/Y (XNOR2D1)
             0.0822    0.0003    0.4804 v _390_/A1 (OAI21D1)
   0.0038    0.1296    0.1152    0.5957 ^ _390_/Y (OAI21D1)
   0.0024    0.0751    0.0582    0.6540 v _418_/D (DFFHQD1)
                                 0.6540   data arrival time

                                10.0000 ^ _418_/CK (DFFHQD1)
                      -0.2206    9.7794   library setup time
                                 9.7794   data required time
-------------------------------------------------------------------------------
                                 9.7794   data required time
                                -0.6540   data arrival time
-------------------------------------------------------------------------------
                                 9.1254   slack (MET)


Startpoint: x[31] (input port clocked by clk)
Endpoint: _455_ (rising edge-triggered flip-flop clocked by clk)
Path Group: clk
Path Type: max

      Cap      Slew     Delay      Time   Description
-------------------------------------------------------------------------------
                       2.0000    2.0000 v x[31] (in)
   0.0100    0.1000    0.4300    2.4300 v _455_/D (DFFHQD1)
                                 2.4300   data arrival time

                                 9.7800   data required time
-------------------------------------------------------------------------------
                                 7.3500   slack (MET)
"""


# ── OpenSTA path parsing ────────────────────────────────────────────────────

def test_parse_sta_paths_three_paths():
    paths = pdf.parse_sta_paths(STA_RPT)
    assert len(paths) == 3
    ends = [p["endpoint"] for p in paths]
    assert ends == ["p", "_418_", "_455_"]


def test_parse_sta_reg_to_po():
    p = pdf.parse_sta_paths(STA_RPT)[0]
    assert p["startpoint"] == "_392_" and p["start_kind"] == "ff"
    assert p["endpoint"] == "p" and p["end_kind"] == "output"
    assert p["start_edge"] == "^" and p["end_edge"] == "^"
    assert p["arrival"] == 0.2075
    assert p["slack"] == 7.7925 and p["slack_met"] is True


def test_parse_sta_reg_to_reg_edges_and_hops():
    p = pdf.parse_sta_paths(STA_RPT)[1]
    assert p["startpoint"] == "_419_" and p["endpoint"] == "_418_"
    assert p["start_kind"] == "ff" and p["end_kind"] == "ff"
    # launch is the _419_/Q edge (rise); capture is the _418_/D edge (fall)
    assert p["start_edge"] == "^" and p["end_edge"] == "v"
    assert p["arrival"] == 0.6540
    # ordered cell hops include the intermediate combinational gates
    cells = [c for (_pin, c, _e, _t) in p["hops"]]
    assert "XNOR2D1" in cells and "OAI21D1" in cells


def test_parse_sta_pi_launched():
    p = pdf.parse_sta_paths(STA_RPT)[2]
    assert p["start_kind"] == "input"       # x[31] — NOT LOC-launchable
    assert p["endpoint"] == "_455_" and p["end_kind"] == "ff"
    assert p["arrival"] == 2.4300


def test_start_from_value():
    assert pdf.start_from_value("^") == 0    # rise → starts from 0
    assert pdf.start_from_value("v") == 1    # fall → starts from 1


# ── top-K selection ─────────────────────────────────────────────────────────

def test_select_topk_loc_only_ranked_by_arrival():
    paths = pdf.parse_sta_paths(STA_RPT)
    sel, meta = pdf.select_topk_paths(paths, 8)
    # only the 2 flop-start paths are LOC-launchable; the PI path is set aside
    assert meta["loc_launchable_paths"] == 2
    assert meta["pi_launched_paths"] == 1
    assert [p["endpoint"] for p in sel] == ["_418_", "p"]   # 0.654 > 0.2075
    assert meta["longest_arrival_ns"] == 0.6540
    # the overall longest (incl. PI path) is disclosed separately
    assert meta["overall_longest_arrival_ns"] == 2.4300


def test_select_topk_respects_k():
    paths = pdf.parse_sta_paths(STA_RPT)
    sel, meta = pdf.select_topk_paths(paths, 1)
    assert meta["k_selected"] == 1 and sel[0]["endpoint"] == "_418_"


# ── PDF miter shape ─────────────────────────────────────────────────────────

CUT = """\
module spm(clk, rst, x, y, p, _418_, \\_418_.d , _419_, \\_419_.d );
  input clk;
  input rst;
  input [31:0] x;
  input y;
  output p;
  input _418_;
  output \\_418_.d ;
  input _419_;
  output \\_419_.d ;
  wire _000_;
endmodule
"""


def _cut():
    return pdf._tdf.parse_cut_ports(CUT)


def test_build_pdf_miter_nonrobust_full_loc():
    top, pin, pout, pairs = _cut()
    m = pdf.build_pdf_miter(top, pin, pout, pairs, "_419_", "_418_",
                            end_is_po=False, from_val=0, robust=False,
                            mod_name="pdf_0_nr")
    assert "module pdf_0_nr(" in m
    assert "spm f1 (" in m and "spm g2 (" in m   # exactly two frames
    assert "spm fb" not in m                      # no faulty copy (not a fault)
    # ok = launch(rise from 0) ∧ endpoint transition
    assert "assign ok = (~s_419__q & s_419__f1d) & (s_418__f1d ^ s_418__g2d);" in m
    # full LOC: g2's OTHER flop (_418_) is launched (uses f1's D, not held)
    assert "._418_(s_418__f1d)" in m


def test_build_pdf_miter_robust_single_input_change():
    top, pin, pout, pairs = _cut()
    m = pdf.build_pdf_miter(top, pin, pout, pairs, "_419_", "_418_",
                            end_is_po=False, from_val=0, robust=True,
                            mod_name="pdf_0_r")
    # ROBUST: only the start flop _419_ is launched; every OTHER flop HOLDS its
    # frame-1 state → g2's _418_ Q is driven by the held init s_418__q.
    assert "._418_(s_418__q)" in m          # held (single-input-change)
    assert "._419_(s_419__f1d)" in m        # start flop launched


def test_build_pdf_miter_po_endpoint_and_fall_edge():
    top, pin, pout, pairs = _cut()
    m = pdf.build_pdf_miter(top, pin, pout, pairs, "_419_", "p",
                            end_is_po=True, from_val=1, robust=False,
                            mod_name="pdf_1_nr")
    # falling launch from 1: (start_f1 & ~start_f2); PO endpoint uses p_f1/p_g2
    assert "assign ok = (s_419__q & ~s_419__f1d) & (p_f1 ^ p_g2);" in m


# ── classify_path (soundness core) ──────────────────────────────────────────

def test_classify_robust():
    c = pdf.classify_path("DET", "DET")
    assert c == {"covered": True, "robust": True, "status": "robust"}


def test_classify_non_robust():
    c = pdf.classify_path("DET", "RED")
    assert c["covered"] is True and c["robust"] is False
    assert c["status"] == "non_robust"


def test_classify_false_path_not_covered():
    # nr UNSAT (RED) = functionally false / held path → NEVER covered
    c = pdf.classify_path("RED", "RED")
    assert c["covered"] is False and c["status"] == "false_or_held"


def test_classify_abort_not_covered():
    c = pdf.classify_path("ABORT", "ABORT")
    assert c["covered"] is False and c["status"] == "aborted"


def test_classify_robust_requires_own_det():
    # a path may be non-robust-SAT but robust-UNSAT → must NOT be robust
    assert pdf.classify_path("DET", "ABORT")["robust"] is False


# ── PDF coverage math ───────────────────────────────────────────────────────

def _rec(idx, loc, covered, robust, status, arrival):
    return {"idx": idx, "loc_testable": loc, "covered": covered,
            "robust": robust, "status": status, "arrival": arrival}


def test_pdf_coverage_math_excludes_redundant_keeps_aborted():
    # TEST-coverage convention (DT1 parity): SAT-proven-redundant (false/held)
    # paths are excluded from the DENOMINATOR; ABORTED paths stay as non-covered.
    # Both are excluded from the NUMERATOR (never counted covered).
    recs = [
        _rec(0, True, True, True, "robust", 4.0),
        _rec(1, True, True, False, "non_robust", 2.0),
        _rec(2, True, False, False, "false_or_held", 5.0),   # redundant → excl. denom
        _rec(3, True, False, False, "aborted", 1.0),          # non-covered, in denom
        _rec(4, False, False, False, "unmappable", 9.0),      # not graded
    ]
    c = pdf.pdf_coverage_math(recs, period_ns=10.0, timing_fraction=0.30)
    assert c["graded_paths"] == 4          # the unmappable one is not graded
    assert c["testable_paths"] == 3        # 4 graded − 1 redundant (false/held)
    assert c["sensitised_paths"] == 2      # only the 2 DET paths
    assert c["robust_paths"] == 1
    assert c["non_robust_paths"] == 1
    assert c["false_or_held_paths"] == 1
    assert c["aborted_paths"] == 1
    # test-coverage = sensitised / testable = 2/3 (redundant out, aborted in)
    assert c["pdf_sensitised_coverage_pct"] == round(100.0 * 2 / 3, 4)
    # fault-coverage (over all graded, redundant IN) reported for transparency
    assert c["pdf_sensitised_fault_coverage_pct"] == 50.0   # 2/4
    # of the 2 sensitised, only arrival 4.0/10=0.40 clears the 0.30 fraction
    # (the non-robust one at 2.0/10=0.20 does not)
    assert c["at_speed_meaningful_paths"] == 1


def test_pdf_coverage_math_all_sensitised():
    recs = [_rec(i, True, True, True, "robust", 5.0) for i in range(4)]
    c = pdf.pdf_coverage_math(recs, period_ns=10.0, timing_fraction=0.30)
    assert c["pdf_sensitised_coverage_pct"] == 100.0
    assert c["pdf_robust_coverage_pct"] == 100.0


# ── gate: FALSE-CLEAN-PROOF ─────────────────────────────────────────────────

def _grec(idx, loc, nr, rv):
    return {"idx": idx, "loc_testable": loc, "nr_verdict": nr,
            "robust_verdict": rv}


def test_gate_recount_ignores_inflated_sensitised():
    # producer LIES: sensitised_paths=6 but only 4 records are DET
    blob = {
        "verdict": "PASS", "floor_pct": 80.0, "sensitised_paths": 6,
        "path_records": (
            [_grec(i, True, "DET", "DET") for i in range(4)]
            + [_grec(4, True, "RED", "RED"), _grec(5, True, "RED", "RED")]  # 2 false
            + [_grec(6, True, "ABORT", "ABORT"), _grec(7, True, "ABORT", "ABORT")]
        ),
    }
    r = gate.evaluate(blob, floor=80.0)
    assert r["sensitised_count_mismatch"] is True
    assert r["sensitised_paths"] == 4            # recount, not the lied 6
    assert r["false_or_held_paths"] == 2 and r["aborted_paths"] == 2
    assert r["graded_paths"] == 8 and r["testable_paths"] == 6  # 8 − 2 redundant
    # honest test-coverage 4/6 = 66.7% < 80 → FAIL (the lie can't rescue it)
    assert r["verdict"] == "FAIL"


def test_gate_robust_requires_own_det():
    blob = {"verdict": "PASS", "floor_pct": 80.0,
            "path_records": [_grec(0, True, "DET", "RED"),
                             _grec(1, True, "DET", "DET")]}
    r = gate.evaluate(blob, floor=80.0)
    assert r["sensitised_paths"] == 2 and r["robust_paths"] == 1
    assert r["pdf_sensitised_coverage_pct"] == 100.0
    assert r["verdict"] == "PASS"


def test_gate_false_path_never_counted_covered():
    # every graded path is a FALSE path (RED) → 0 testable → cannot pass on zero
    # testable evidence → FAIL (a false path is NEVER counted covered).
    blob = {"verdict": "PASS", "floor_pct": 80.0,
            "path_records": [_grec(i, True, "RED", "RED") for i in range(5)]}
    r = gate.evaluate(blob, floor=80.0)
    assert r["sensitised_paths"] == 0 and r["false_or_held_paths"] == 5
    assert r["testable_paths"] == 0
    assert r["pdf_sensitised_coverage_pct"] is None   # 0 testable → undefined, not a pass
    assert r["verdict"] == "FAIL"


def test_gate_unmappable_not_graded():
    blob = {"verdict": "PASS", "floor_pct": 80.0,
            "path_records": [_grec(0, True, "DET", "DET"),
                             {"idx": 1, "loc_testable": False,
                              "status": "unmappable"}]}
    r = gate.evaluate(blob, floor=80.0)
    assert r["graded_paths"] == 1 and r["pdf_sensitised_coverage_pct"] == 100.0


def test_gate_zero_evidence_fails():
    assert gate.evaluate({"verdict": "PASS", "path_records": []},
                         floor=80.0)["verdict"] == "FAIL"


def test_gate_not_applicable_passthrough():
    blob = {"verdict": "NOT_APPLICABLE", "scan_flops": 0,
            "reasons": ["no SPEF"]}
    assert gate.evaluate(blob, floor=80.0)["verdict"] == "NOT_APPLICABLE"


def test_gate_missing_json_fails():
    assert gate.evaluate(None, floor=80.0)["verdict"] == "FAIL"


def test_gate_error_fails():
    assert gate.evaluate({"verdict": "ERROR", "reasons": ["x"]},
                         floor=80.0)["verdict"] == "FAIL"


def test_gate_floor_never_relaxed_below_producer():
    # producer floor 90 > cli default 80 → effective 90, 80% must FAIL.
    # Use ABORTED paths (which STAY in the denominator as non-covered) so the
    # honest test-coverage is 8/10 = 80% — redundant would be excluded instead.
    recs = ([_grec(i, True, "DET", "DET") for i in range(8)]
            + [_grec(8 + i, True, "ABORT", "ABORT") for i in range(2)])
    blob = {"verdict": "PASS", "floor_pct": 90.0, "path_records": recs}
    r = gate.evaluate(blob, floor=80.0)
    assert r["floor_pct"] == 90.0
    assert r["testable_paths"] == 10                   # no redundant → all graded testable
    assert r["pdf_sensitised_coverage_pct"] == 80.0    # 8/10 (aborts counted non-covered)
    assert r["verdict"] == "FAIL"


# ── DT1-parity: test-coverage denominator excludes SAT-proven-redundant ──────
# v1.4.22 REGRESSION. DT2 previously divided by ALL graded paths (fault-coverage),
# so a design whose long paths are mostly PROVEN-FALSE (nr==RED, no 2-pattern by
# construction) was penalised for un-sensitisable paths — contradicting DT1
# (`transition coverage_math` uses detected/(sampled−redundant)), DT2's own
# `classify_path` docstring ("SOUND exclude"), and its reason strings. The fix
# aligns DT2 to test-coverage: redundant OUT of the denominator, aborted IN.

def test_dt1_parity_redundant_excluded_producer_and_gate_agree():
    # spm-shaped: 11 real (DET) + 5 SAT-proven-false (RED) long paths, 0 abort.
    recs = ([_grec(i, True, "DET", "DET") for i in range(11)]
            + [_grec(11 + i, True, "RED", "RED") for i in range(5)])
    # producer side (records carry covered/robust/status the producer writes)
    prec = ([_rec(i, True, True, True, "robust", 5.0) for i in range(11)]
            + [_rec(11 + i, True, False, False, "false_or_held", 5.0)
               for i in range(5)])
    c = pdf.pdf_coverage_math(prec, period_ns=10.0, timing_fraction=0.30)
    assert c["graded_paths"] == 16 and c["testable_paths"] == 11
    assert c["pdf_sensitised_coverage_pct"] == 100.0          # 11/11 testable
    assert c["pdf_sensitised_fault_coverage_pct"] == 68.75    # 11/16 (transparency)
    # gate independently agrees
    g = gate.evaluate({"verdict": "PASS", "floor_pct": 80.0,
                       "path_records": recs}, floor=80.0)
    assert g["testable_paths"] == 11 and g["false_or_held_paths"] == 5
    assert g["pdf_sensitised_coverage_pct"] == 100.0
    assert g["verdict"] == "PASS"


def test_dt1_parity_aborts_still_penalise_no_gaming():
    # ANTI-GAMING invariant: excluding redundant must NOT let an under-tested
    # design pass. Aborted (SAT-undecided) paths stay in the denominator, so a
    # design that can't sensitise its paths still FAILs — the fix only forgives
    # PROVABLY-false paths, never merely-unsolved ones.
    recs = ([_grec(i, True, "DET", "DET") for i in range(6)]
            + [_grec(6 + i, True, "RED", "RED") for i in range(1)]     # 1 redundant
            + [_grec(7 + i, True, "ABORT", "ABORT") for i in range(4)])  # 4 aborted
    g = gate.evaluate({"verdict": "PASS", "floor_pct": 80.0,
                       "path_records": recs}, floor=80.0)
    assert g["graded_paths"] == 11 and g["testable_paths"] == 10  # 11 − 1 redundant
    assert g["pdf_sensitised_coverage_pct"] == 60.0              # 6/10, aborts counted
    assert g["verdict"] == "FAIL"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
