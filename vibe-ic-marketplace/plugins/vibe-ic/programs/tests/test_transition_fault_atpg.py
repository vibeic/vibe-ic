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

def test_parse_batch_log_missing_verdict_and_unreached():
    faults = [("_000_", "STR", "1'b0", "1'b0"),
              ("_000_", "STF", "1'b1", "1'b1"),
              ("_001_", "STR", "1'b0", "1'b0")]
    # fault 1 got a verdict; fault 2 got a marker but no verdict (attempted,
    # undecided); fault 3 has NO marker at all (yosys never reached it).
    log = ("VIBEICTDF_SETUP_DONE\n"
           "VIBEICTDF _000_ STR\nSAT proof finished - model found: FAIL!\n"
           "VIBEICTDF _000_ STF\nInterrupted SAT solver: TIMEOUT!\n")
    results, example, setup_done = tdf._parse_batch_log(log, faults, ["clk"])
    vmap = {(n, k): v for n, k, v in results}
    assert setup_done is True                  # the one-time setup marker fired
    assert vmap[("_000_", "STR")] == "DET"
    assert vmap[("_000_", "STF")] == "ABORT"    # marker but undecided → attempted
    # #154: a fault with NO marker is UNREACHED (excluded from the graded
    # sample), NOT counted as an undetected ABORT — that reclassification is
    # what stops a wall-truncated batch from scoring a real design 0 %.
    assert vmap[("_001_", "STR")] == "UNREACHED"


def test_parse_batch_log_setup_absent():
    faults = [("_000_", "STR", "1'b0", "1'b0")]
    results, _example, setup_done = tdf._parse_batch_log(
        "VIBEICTDF _000_ STR\nSAT proof finished - no model found: SUCCESS!\n",
        faults, ["clk"])
    assert setup_done is False
    assert results[0][2] == "RED"


# ── #154 FLATTEN-ONCE batch shape ─────────────────────────────────────────
def test_build_batch_script_flattens_once_and_injects_on_flat_net():
    faults = [("_14803_", "STR", "1'b0", "1'b0"),
              ("_21044_", "STF", "1'b1", "1'b1")]
    # 60 and not 90: `_build_batch_script` returns a STRING, so nothing is
    # launched here and the measured worst case is the cost of formatting text.
    # 90 sat above `ci_harness_timeout_ceiling_check`'s 60 s per-call ceiling,
    # on the advisory list of bounds that gate cannot resolve — an exemption
    # this call never needed.
    s = tdf._build_batch_script("flat.v", "miter.v", "sha256", faults, ["clk"],
                                sat_timeout=60)
    # The faulty copy + hierarchy + flatten + snapshot happen EXACTLY ONCE.
    assert s.count("copy sha256 sha256_f") == 1
    assert s.count("\nflatten\n") == 1
    assert s.count("design -save baseflat") == 1
    assert s.count(tdf._SETUP_MARKER) == 1
    # Per fault: reload the flat snapshot + inject on the FLAT faulty-instance
    # net `fb.<net>` (NOT a per-fault copy/hierarchy/flatten).
    assert s.count("design -load baseflat") == 2
    assert "connect -nomap -set fb._14803_ 1'b0" in s
    assert "connect -nomap -set fb._21044_ 1'b1" in s
    # sat still sets the launch frame on f1 and carries the per-fault -timeout.
    assert "sat -prove trig 0 -timeout 60 -set f1._14803_ 1'b0" in s
    # the OLD per-fault re-flatten idiom is gone.
    assert "cd sha256_f" not in s


def test_parse_time_spent_reads_yosys_breakdown():
    log = ("...\nTime spent: 92% 8x sat (194 sec), 3% 8x flatten (7 sec), "
           "5% 1x read_verilog (0 sec)\n")
    sat_calls, sat_sec, flat_sec = tdf._parse_time_spent(log)
    assert (sat_calls, sat_sec, flat_sec) == (8, 194, 7)
    # absent line → all zero (caller then uses the graded-count fallback).
    assert tdf._parse_time_spent("no timing here") == (0, 0, 0)


def test_rightsize_sample_fits_wall_budget():
    # 20 s/fault, 25 s setup, 1800 s wall, 0.85 safety →
    # (1800*0.85 - 25)/20 = 75.25 → 75 faults; capped by --max-faults / avail.
    assert tdf._rightsize_sample(20.0, 25.0, 1800, 400, 99858) == 75
    assert tdf._rightsize_sample(20.0, 25.0, 1800, 50, 99858) == 50   # --max cap
    assert tdf._rightsize_sample(20.0, 25.0, 1800, 400, 10) == 10     # availability
    # never returns 0 — an honest tiny partial beats a fail-safe zero.
    assert tdf._rightsize_sample(5000.0, 25.0, 1800, 400, 99858) == 1
    # unknown per-fault cost (probe gave nothing) → fall back to the caps.
    assert tdf._rightsize_sample(0.0, 25.0, 1800, 400, 99858) == 400


def test_spread_order_prefix_is_representative():
    items = list(range(64))
    out = tdf._spread_order(items)
    assert sorted(out) == items          # a permutation (no loss/dup)
    # any short prefix spans the whole range (not a low-index cluster).
    assert max(out[:8]) - min(out[:8]) >= 32
    assert tdf._spread_order([1, 2]) == [1, 2]   # <3 unchanged


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
    """NOT_APPLICABLE is honoured — but only once it is EARNED.

    This test used to assert that a bare `NOT_APPLICABLE` + `scan_flops: 0`
    passed straight through. That unconditional passthrough was the hole: it is
    what let a run that detected 0 of 65 flops, cut no scan chain, and measured
    no coverage score a clean self-skip. The producer now records
    `sequential_evidence` derived from the design's own Liberty, and the gate
    honours the self-skip on the strength of that evidence rather than on the
    producer's say-so. The uncorroborated form is covered by
    test_dft_atpg_zero_flop_and_absent_artifact.py."""
    blob = {"verdict": "NOT_APPLICABLE", "scan_flops": 0,
            "reasons": ["combinational design"],
            "sequential_evidence": {
                "verdict": "NO_SEQUENTIAL", "authoritative": True,
                "method": "liberty_ff_group",
                "liberty_sequential_cells_declared": 12,
                "sequential_cells_instantiated": [],
                "reasons": ["the design's own Liberty declares 12 cell(s) with "
                            "an `ff` group and the netlist instantiates none"]}}
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


def test_tdf_pre_flatten_script_legalizes_memory_before_flatten():
    # v1.4.39 (ic2-sha256 sha256 DT1 floor): proc + memory_collect + memory_map
    # must run BEFORE flatten so a K-ROM $mem_v2 (sha256 round-constant ROM)
    # doesn't abort flatten with "Found processes in selected module".
    s = tdf._tdf_pre_flatten_script("/pdk/x.lib", "cut/core.v", "sha256",
                                    "flat/flat_core.v")
    for cmd in ("proc", "memory_collect", "memory_map", "flatten -separator _"):
        assert cmd in s
    # ORDER is load-bearing: proc + memory_map BEFORE flatten.
    assert s.index("proc") < s.index("memory_map") < s.index("flatten -separator _")
    # still reads liberty-as-logic + the cut netlist + writes the flat core.
    assert "read_liberty -ignore_miss_func /pdk/x.lib" in s
    assert "read_verilog /work/cut/core.v" in s
    assert "hierarchy -top sha256" in s
    assert "write_verilog -noattr /work/flat/flat_core.v" in s



# ---------------------------------------------------------------------------
# discover_mapped_netlist — DT1 must find the flow's CANONICAL synth emit
# (`netlist.v`), not only the DFT-chain `<top>_synth.v`. Regression from
# opentitan_aes × sky130A: synth wrote netlist.v, discovery globbed only
# *_synth.v/synth.v → producer "cannot derive --top" → not-run → gate BLOCKED
# → false FAIL.
# ---------------------------------------------------------------------------
def _mk(project, rel):
    f = project / rel
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("module chip_top(); endmodule\n")
    return f


def test_discover_finds_canonical_netlist_v(tmp_path):
    _mk(tmp_path, "phase2/stage2/synth/netlist.v")
    assert tdf.discover_mapped_netlist(tmp_path) == "phase2/stage2/synth/netlist.v"


def test_discover_finds_netlist_yosys_when_only_that_exists(tmp_path):
    _mk(tmp_path, "phase2/stage2/synth/netlist_yosys.v")
    assert tdf.discover_mapped_netlist(tmp_path) == "phase2/stage2/synth/netlist_yosys.v"


def test_discover_prefers_dft_chain_synth_v_when_present(tmp_path):
    # ORDER: the DFT-chain <top>_synth.v still wins over netlist.v when both exist.
    _mk(tmp_path, "phase2/stage2/synth/chip_top_synth.v")
    _mk(tmp_path, "phase2/stage2/synth/netlist.v")
    assert tdf.discover_mapped_netlist(tmp_path) == "phase2/stage2/synth/chip_top_synth.v"


def test_discover_falls_back_when_nothing_present(tmp_path):
    # NEGATIVE CONTROL: no known emit → the (non-existent) fallback, so the
    # caller still honestly reports "cannot derive --top" rather than inventing one.
    assert tdf.discover_mapped_netlist(tmp_path) == "phase2/stage2/synth/synth.v"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))


# ── ENGINE_LIMITED on generic/unmapped netlist (opentitan_aes × sky130A) ─────
# The OSS `fault` engine cannot detect flops in a GENERIC yosys netlist
# (`$_DFF_*` primitives) — "Failed to detect any flip-flop cells" → 0 pairs even
# with the correct --dff/--clock. That is the SAME disclosed OSS capability gap
# the sibling stuck-at ATPG records; DT1 must treat it as a DOCUMENTED
# engine-limited SKIPPED-CONDITION, never a hard ERROR — but ONLY behind the
# attestation guard (a MAPPED netlist with 0 pairs stays a real ERROR/FAIL).
def _engine_limited_blob():
    return {
        "verdict": "ENGINE_LIMITED", "status": "ENGINE_LIMITED",
        "engine_limited": True, "pdk_detected": "generic_unmapped",
        "capability_flag": "cap:at_speed_timing_graded_atpg", "scan_flops": 0,
        "sequential_evidence": {"verdict": "HAS_SEQUENTIAL",
                                "reasons": ["1 seq cell type"]},
        "reasons": ["generic netlist — fault cannot detect $_DFF_ flops"],
    }


def test_gate_engine_limited_generic_is_skipped_condition():
    r = gate.evaluate(_engine_limited_blob(), floor=90.0)
    assert r["verdict"] == "SKIPPED-CONDITION"


def test_gate_engine_limited_requires_generic_unmapped_attestation():
    bad = _engine_limited_blob(); bad["pdk_detected"] = "sky130"
    assert gate.evaluate(bad, floor=90.0)["verdict"] == "BLOCKED"


def test_gate_engine_limited_requires_sequential_evidence():
    bad = _engine_limited_blob()
    bad["sequential_evidence"] = {"verdict": "SEQ_ABSENT"}
    assert gate.evaluate(bad, floor=90.0)["verdict"] == "BLOCKED"


def test_gate_engine_limited_requires_capability_flag():
    bad = _engine_limited_blob(); bad["capability_flag"] = ""
    assert gate.evaluate(bad, floor=90.0)["verdict"] == "BLOCKED"
