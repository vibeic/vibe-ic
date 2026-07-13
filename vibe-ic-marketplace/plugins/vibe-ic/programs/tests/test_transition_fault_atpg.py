"""Unit tests for transition_fault_atpg_run.py + transition_coverage_check.py.

The heavy path (Yosys `sat` in Docker) is validated by the end-to-end proof
(synthetic circuit soundness + spm bounded-core measurement) recorded in the
gatekeeper report, not re-run here. These tests cover the PURE helpers:
  - cut-port classification (primary vs pseudo-PI/PO pairing)
  - fault-site enumeration (scalar internal nets only)
  - TDF fault enumeration (STR SA0/init0 + STF SA1/init1)
  - disclosed sampling (never a silent cap)
  - SAT verdict parsing (DET / RED / ABORT)
  - coverage math (redundant excluded, aborted NOT detected)
  - LOC miter builder shape (3 instances, shared PI, launch wiring)
  - the gate's FALSE-CLEAN-PROOF recount (redundant/aborted never detected)
  - NOT_APPLICABLE passthrough
"""
import sys
from pathlib import Path

import pytest

PROG_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG_DIR))

import transition_fault_atpg_run as tdf  # noqa: E402
import transition_coverage_check as gate  # noqa: E402


# ── cut-port classification ────────────────────────────────────────────────

CUT = """\
module spm(clk, rst, x, y, p);
  input clk;
  input rst;
  input [31:0] x;
  input y;
  output p;
  input _392_;
  output \\_392_.d ;
  input _393_;
  output \\_393_.d ;
  wire _000_;
  wire _001_;
  wire [3:0] busnet;
endmodule
"""


def test_parse_cut_ports_classifies_primary_and_pseudo():
    top, prim_in, prim_out, pairs = tdf.parse_cut_ports(CUT)
    assert top == "spm"
    assert {n for n, _ in prim_in} == {"clk", "rst", "x", "y"}
    assert {n for n, _ in prim_out} == {"p"}
    # 2 flops → 2 pseudo pairs; base==Q-input name, po==`base.d`
    bases = {b for b, _, _ in pairs}
    assert bases == {"_392_", "_393_"}
    for b, pi, po in pairs:
        assert pi.lstrip("\\") == b
        assert po.lstrip("\\").endswith(".d")
    # primary input x keeps its bus range
    x_range = dict((n, r) for n, r in prim_in)["x"]
    assert "[31:0]" in x_range


def test_enumerate_fault_sites_scalar_internal_only():
    sites = tdf.enumerate_fault_sites(CUT)
    raw = {s.lstrip("\\") for s in sites}
    assert "_000_" in raw and "_001_" in raw
    assert "busnet" not in raw          # buses excluded
    assert "p" not in raw and "clk" not in raw  # ports excluded
    assert "_392_" not in raw           # pseudo-PI port excluded


def test_combinational_design_has_no_pairs():
    comb = "module c(a, b, y);\n input a; input b; output y;\n wire _000_;\nendmodule\n"
    _t, _pi, _po, pairs = tdf.parse_cut_ports(comb)
    assert pairs == []   # → NOT_APPLICABLE downstream


# ── TDF fault enumeration ──────────────────────────────────────────────────

def test_enumerate_tdf_faults_two_per_net():
    faults = tdf.enumerate_tdf_faults(["_000_", "_001_"])
    assert len(faults) == 4
    d = {(n, k): (s, i) for n, k, s, i in faults}
    # STR = slow-to-rise ⇒ SA0 launch, init 0
    assert d[("_000_", "STR")] == ("1'b0", "1'b0")
    # STF = slow-to-fall ⇒ SA1 launch, init 1
    assert d[("_000_", "STF")] == ("1'b1", "1'b1")


# ── disclosed sampling ─────────────────────────────────────────────────────

def test_sample_faults_all_when_under_cap():
    faults = tdf.enumerate_tdf_faults([f"_{i:03d}_" for i in range(5)])  # 10
    got, sampled = tdf.sample_faults(faults, 400)
    assert sampled is False and len(got) == 10


def test_sample_faults_bounded_and_disclosed():
    faults = tdf.enumerate_tdf_faults([f"_{i:03d}_" for i in range(500)])  # 1000
    got, sampled = tdf.sample_faults(faults, 100)
    assert sampled is True and len(got) == 100
    # deterministic + spread (not just a prefix)
    again, _ = tdf.sample_faults(faults, 100)
    assert got == again


def test_sample_faults_all_when_cap_nonpositive():
    faults = tdf.enumerate_tdf_faults([f"_{i:03d}_" for i in range(10)])
    got, sampled = tdf.sample_faults(faults, 0)
    assert sampled is False and len(got) == len(faults)


# ── SAT verdict parsing ────────────────────────────────────────────────────

def test_parse_sat_verdict_detected():
    assert tdf.parse_sat_verdict("SAT proof finished - model found: FAIL!") == "DET"


def test_parse_sat_verdict_redundant():
    assert tdf.parse_sat_verdict(
        "SAT proof finished - no model found: SUCCESS!") == "RED"


def test_parse_sat_verdict_abort_on_ambiguous():
    # a timeout / error block is NEVER a detection (fail-safe)
    assert tdf.parse_sat_verdict("ERROR: minisat timed out") == "ABORT"
    assert tdf.parse_sat_verdict("") == "ABORT"


# ── coverage math (the soundness core) ─────────────────────────────────────

def test_coverage_math_excludes_redundant_and_never_counts_aborted():
    # 8 detected, 2 redundant, 2 aborted → testable = 10, test_cov = 80%
    c = tdf.coverage_math(detected=8, redundant=2, aborted=2)
    assert c["sampled_faults"] == 12
    assert c["testable_faults"] == 10
    assert c["tdf_test_coverage_pct"] == 80.0     # 8/10
    assert round(c["tdf_fault_coverage_pct"], 2) == round(8 / 12 * 100, 2)


def test_coverage_math_all_detected_is_100():
    c = tdf.coverage_math(detected=80, redundant=0, aborted=0)
    assert c["tdf_test_coverage_pct"] == 100.0


def test_coverage_math_aborted_lowers_coverage():
    # aborted must count as undetected → NOT 100%
    c = tdf.coverage_math(detected=9, redundant=0, aborted=1)
    assert c["tdf_test_coverage_pct"] == 90.0


# ── LOC miter builder shape ────────────────────────────────────────────────

def test_build_loc_miter_shape():
    top, prim_in, prim_out, pairs = tdf.parse_cut_ports(CUT)
    m = tdf.build_loc_miter(top, prim_in, prim_out, pairs)
    # three instances: frame1 good, frame2 good, frame2 faulty
    assert " f1 (" in m and " g2 (" in m and " fb (" in m
    assert "spm f1" in m and "spm g2" in m and "spm_f fb" in m
    # launch wiring: frame2 Q driven by frame1 D (…_f1d)
    assert "_f1d" in m
    # trig ORs frame-2 pseudo-PO diffs
    assert "assign trig =" in m and "^" in m
    # escaped dotted pseudo-PO port appears
    assert "\\_392_.d " in m


def test_esc_id_escapes_dotted_names_only():
    assert tdf.esc_id("clk") == "clk"
    assert tdf.esc_id("_392_") == "_392_"
    assert tdf.esc_id("_392_.d") == "\\_392_.d "
    assert tdf.esc_id("\\_392_.d ") == "\\_392_.d "


# ── batch-log parsing: aborted faults are NOT detected ─────────────────────

def test_parse_batch_log_missing_verdict_is_abort():
    faults = [("_000_", "STR", "1'b0", "1'b0"),
              ("_000_", "STF", "1'b1", "1'b1"),
              ("_001_", "STR", "1'b0", "1'b0")]
    # only the first fault got a verdict; yosys then aborted
    log = ("VIBEICTDF _000_ STR\nSAT proof finished - model found: FAIL!\n"
           "VIBEICTDF _000_ STF\nERROR: solver crashed\n")
    results, example = tdf._parse_batch_log(log, faults, ["clk"])
    vmap = {(n, k): v for n, k, v in results}
    assert vmap[("_000_", "STR")] == "DET"
    assert vmap[("_000_", "STF")] == "ABORT"   # marker but no verdict
    assert vmap[("_001_", "STR")] == "ABORT"   # no marker at all (yosys exited)


# ── gate: FALSE-CLEAN-PROOF (redundant/aborted never detected) ─────────────

def test_gate_recount_ignores_inflated_detected():
    # producer LIES: claims detected=10 but the fault list has only 8 DET,
    # 2 RED. The gate must recount 8/8 testable — and here 100% of testable
    # → but detected_count_mismatch flagged, recomputed governs.
    blob = {
        "verdict": "PASS", "detected": 10, "redundant": 2, "aborted": 0,
        "floor_pct": 90.0,
        "fault_list": ([{"net": f"_{i}_", "kind": "STR", "verdict": "DET"}
                        for i in range(8)]
                       + [{"net": f"_{i}_", "kind": "STF", "verdict": "RED"}
                          for i in range(2)]),
    }
    r = gate.evaluate(blob, floor=90.0)
    assert r["detected_count_mismatch"] is True
    assert r["detected"] == 8            # recounted, not the lied 10
    assert r["redundant"] == 2
    assert r["tdf_test_coverage_pct"] == 100.0  # 8/(10-2)=8/8


def test_gate_fails_when_redundant_inflated_below_floor():
    # 5 DET, 5 RED counted-as-detected by a cheating producer that wrote
    # detected=10. Real testable coverage = 5/5 = 100%? No: 5 DET + 5 RED →
    # testable = 5, detected 5 → 100. Use aborted to force a real miss:
    blob = {
        "verdict": "PASS", "detected": 10, "redundant": 0, "aborted": 5,
        "floor_pct": 90.0,
        "fault_list": ([{"verdict": "DET"} for _ in range(5)]
                       + [{"verdict": "ABORT"} for _ in range(5)]),
    }
    r = gate.evaluate(blob, floor=90.0)
    # recount: 5 DET, 0 RED, 5 ABORT → testable=10, cov=50% < 90 → FAIL
    assert r["detected"] == 5 and r["aborted"] == 5
    assert r["tdf_test_coverage_pct"] == 50.0
    assert r["verdict"] == "FAIL"


def test_gate_zero_evidence_fails():
    blob = {"verdict": "PASS", "detected": 0, "redundant": 0, "aborted": 0}
    r = gate.evaluate(blob, floor=90.0)
    assert r["verdict"] == "FAIL"


def test_gate_not_applicable_passthrough():
    blob = {"verdict": "NOT_APPLICABLE", "scan_flops": 0,
            "reasons": ["combinational design"]}
    r = gate.evaluate(blob, floor=90.0)
    assert r["verdict"] == "NOT_APPLICABLE"


def test_gate_missing_json_fails():
    r = gate.evaluate(None, floor=90.0)
    assert r["verdict"] == "FAIL"


def test_gate_floor_never_relaxed_below_producer():
    # producer floor 95 > cli default 90 → effective 95, 92% must FAIL
    blob = {"verdict": "PASS", "floor_pct": 95.0,
            "fault_list": ([{"verdict": "DET"} for _ in range(92)]
                           + [{"verdict": "ABORT"} for _ in range(8)])}
    r = gate.evaluate(blob, floor=90.0)
    assert r["floor_pct"] == 95.0
    assert r["tdf_test_coverage_pct"] == 92.0
    assert r["verdict"] == "FAIL"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
