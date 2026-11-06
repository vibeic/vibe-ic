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
    # The property this test exists to protect: an ambiguous block is NEVER a
    # detection (fail-safe). That still holds for every input below.
    for body in ("ERROR: minisat timed out", "", "Timeout reached while solving."):
        assert tdf.parse_sat_verdict(body) != "DET"

    # A block with NO verdict and NO fatal diagnostic is a genuine per-fault
    # ABORT: the solver attempted the fault and left it undecided. It counts as
    # undetected and sits in the coverage denominator — anti-gaming intact.
    assert tdf.parse_sat_verdict("") == "ABORT"
    assert tdf.parse_sat_verdict("Timeout reached while solving.") == "ABORT"

    # A block carrying a FATAL yosys `ERROR:` is a TOOL failure, not a
    # per-fault outcome (yosys `log_error` aborts the whole batch; a per-fault
    # `sat -timeout` prints no `ERROR:` line). Classifying it ABORT is what let
    # ONE crash on the first fault be rendered as "0.0% test coverage" — a
    # graded DESIGN failure for a tool that never ran. It is now strictly MORE
    # conservative: it propagates ERROR instead of entering the denominator, so
    # no coverage number is computed at all. See
    # test_dt1_tool_crash_is_not_a_coverage_number.py.
    assert tdf.parse_sat_verdict("ERROR: minisat timed out") == "TOOL_ERROR"


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
    s = tdf._build_batch_script("flat.v", "miter.v", "core", faults, ["clk"])
    # The faulty copy + hierarchy + flatten + snapshot happen EXACTLY ONCE.
    assert s.count("copy core core_f") == 1
    assert s.count("\nflatten\n") == 1
    assert s.count("design -save baseflat") == 1
    assert s.count(tdf._SETUP_MARKER) == 1
    # Per fault: reload the flat snapshot + inject on the FLAT faulty-instance
    # net `fb.<net>` (NOT a per-fault copy/hierarchy/flatten).
    assert s.count("design -load baseflat") == 2
    assert "connect -nomap -set fb._14803_ 1'b0" in s
    assert "connect -nomap -set fb._21044_ 1'b1" in s
    assert "sat -prove trig 0 -set f1._14803_ 1'b0" in s
    assert "-timeout" not in s
    # the OLD per-fault re-flatten idiom is gone.
    assert "cd core_f" not in s


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
