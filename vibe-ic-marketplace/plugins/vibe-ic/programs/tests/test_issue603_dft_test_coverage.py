"""#603 — the COVERAGE half of TEST coverage: raw FAULT vs sign-off TEST.

`atpg_untestable_fault_classify` answers WHICH nets carry no test; this module
(`dft_test_coverage` + the bit-expander it drives) answers what that does to the
number: ``test = detected / (total - untestable)``, keeping the raw and test
numbers distinguishable and never letting one stand in for the other.

WHICH WAY IT MUST ERR. Removing a TESTABLE fault from the denominator inflates
coverage — a false PASS. The controls below are the flow-change-acceptance
bidirectional negative control:

  * a FULLY testable design excludes NOTHING → test == raw   (the empty control)
  * a WIDE-FRAME design (unused input bits + a tied output) excludes exactly the
    frame → test > raw, and never exceeds 100 %                (the lift control)
  * a COVERED fault is NEVER removed, even when the coarse net-classifier calls
    its net untestable                                         (the polarity guard)
  * ``test_coverage_pct`` is bounded at 100 % by construction  (the hard invariant)
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]


def _load(name):
    spec = importlib.util.spec_from_file_location(name, _PROGRAMS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


bx = _load("_dft_bit_expand")
au = _load("atpg_untestable_fault_classify")
tc = _load("dft_test_coverage")

# A minimal liberty: an identity buffer, a 2-input AND, and a TIE cell that
# declares NO input pin (so `constant_cells` picks it up structurally, by name
# to nobody). Directions come from here, never from a pin name.
LIBERTY = """
library(mini) {
  cell (BUF) { pin (A) { direction : input; } pin (Y) { direction : output; } }
  cell (AND2) { pin (A) { direction : input; } pin (B) { direction : input; }
                pin (Y) { direction : output; } }
  cell (TIE) { pin (Y) { direction : output; } }
}
"""


def _write(tmp, name, text):
    p = tmp / name
    p.write_text(text)
    return p


# ── bit-expander units ───────────────────────────────────────────────────
def test_lhs_bits_bus_partselect_scalar():
    w = {"la_in": (3, 0), "s": (0, 0)}
    assert bx.lhs_bits("la_in", w) == ["la_in[3]", "la_in[2]", "la_in[1]", "la_in[0]"]
    assert bx.lhs_bits("la_in[2:1]", w) == ["la_in[2]", "la_in[1]"]
    assert bx.lhs_bits("la_in[0]", w) == ["la_in[0]"]
    assert bx.lhs_bits("s", w) == ["s"]


def test_rhs_bits_concat_replication_const():
    w = {"a": (1, 0), "b": (0, 0)}
    # {a, b} → a[1], a[0], b   ;  a bare scalar b stays scalar
    assert bx.rhs_bits("{a, b}", w) == ["a[1]", "a[0]", "b"]
    # replication {3{b}} → b, b, b
    assert bx.rhs_bits("{3{b}}", w) == ["b", "b", "b"]
    # a sized don't-care constant expands to that many None sentinels
    assert bx.rhs_bits("2'hx", w) == [None, None]
    # mixed concat with a constant field
    assert bx.rhs_bits("{a, 2'b00}", w) == ["a[1]", "a[0]", None, None]


def test_expand_keeps_unelaboratable_assign_coarse():
    # An assign whose RHS width can't be resolved is kept as ONE coarse whole-bus
    # edge, never dropped (dropping it could isolate a connected net).
    text = "module m();\n  assign x = y + z;\nendmodule\n"
    extra, opaque = bx.expand_assignments(text, {}, au._ASSIGN_CELL)
    assert opaque == 1
    assert any(c == au._ASSIGN_CELL and "Y" in cc for c, _i, cc in extra)


# ── coverage: the empty (fully-testable) control ──────────────────────────
FULLY_TESTABLE = """
module top(a, b, out0, out1);
  input a; wire a;
  input b; wire b;
  output out0; wire out0;
  output out1; wire out1;
  BUF _0_ (.A(a), .Y(out0));
  BUF _1_ (.A(b), .Y(out1));
endmodule
"""
# every fault site is on an observable, controllable net; Fault detected some
# and missed some (by effort) but NONE is untestable.
FT_COVERAGE = """ratio: 5.0e-1
faultPoints:
- a
- b
- out0
- out1
sa0Covered:
- a
- out0
sa1Covered:
- b
sa0Uncovered:
- b
sa1Uncovered:
- a
"""


def test_fully_testable_excludes_nothing(tmp_path):
    net = _write(tmp_path, "cut.v", FULLY_TESTABLE)
    cov = _write(tmp_path, "coverage.yml", FT_COVERAGE)
    lib = _write(tmp_path, "mini.lib", LIBERTY)
    r = tc.compute(net, cov, [str(lib)])
    assert r["computed"] is True
    assert r["untestable_faults_excluded"] == 0
    # test == raw: nothing removed from the denominator.
    assert r["test_coverage_pct"] == r["raw_coverage_pct"]
    assert r["covered_on_unobservable_net"] == 0


# ── coverage: the wide-frame lift control ─────────────────────────────────
WIDE_FRAME = """
module top(la_in, out, tied);
  input [3:0] la_in; wire [3:0] la_in;
  output out; wire out;
  output tied; wire tied;
  wire [3:0] internal;
  assign internal = la_in;
  BUF _0_ (.A(internal[0]), .Y(out));
  TIE _1_ (.Y(tied));
endmodule
"""
# la_in[0] feeds `out` (testable, detected); la_in[1..3] dead (unobservable);
# `tied` driven by a constant (uncontrollable). Fault detects the reachable
# faults and leaves the frame uncovered.
WF_COVERAGE = """ratio: 4.0e-1
faultPoints:
- la_in [0]
- la_in [1]
- la_in [2]
- la_in [3]
- out
- tied
sa0Covered:
- la_in [0]
- out
sa1Covered:
- la_in [0]
- out
sa0Uncovered:
- la_in [1]
- la_in [2]
- la_in [3]
- tied
sa1Uncovered:
- la_in [1]
- la_in [2]
- la_in [3]
- tied
"""


def test_wide_frame_excludes_only_the_frame(tmp_path):
    net = _write(tmp_path, "cut.v", WIDE_FRAME)
    cov = _write(tmp_path, "coverage.yml", WF_COVERAGE)
    lib = _write(tmp_path, "mini.lib", LIBERTY)
    r = tc.compute(net, cov, [str(lib)])
    assert r["computed"] is True
    # the unused input bits la_in[1..3] (unobservable) + tied (uncontrollable):
    # each carries an sa0 and sa1 Fault left uncovered → 4 sites × 2 = 8 faults.
    assert r["untestable_faults_excluded"] == 8
    assert r["test_coverage_pct"] > r["raw_coverage_pct"]
    assert r["test_coverage_pct"] <= 100.0
    assert r["opaque_assignments"] == 0
    assert r["covered_on_unobservable_net"] == 0


def test_covered_fault_is_never_excluded(tmp_path):
    # Move la_in[1] into the DETECTED set while leaving it structurally on the
    # dead frame. The coarse net-view still calls its net unobservable, but a
    # detected fault is testable by demonstration and must stay in the
    # denominator: excluding it would inflate coverage.
    cov_text = WF_COVERAGE.replace("sa1Covered:\n- la_in [0]\n- out\n",
                                   "sa1Covered:\n- la_in [0]\n- out\n- la_in [1]\n")
    net = _write(tmp_path, "cut.v", WIDE_FRAME)
    cov = _write(tmp_path, "coverage.yml", cov_text)
    lib = _write(tmp_path, "mini.lib", LIBERTY)
    r = tc.compute(net, cov, [str(lib)])
    # la_in[1] sa1 is now covered → it is NOT in the excluded set (7, not 8).
    assert ("la_in[1]" not in r["excluded_sa1_sites"]
            and "la_in [1]" not in r["excluded_sa1_sites"])
    assert r["test_coverage_pct"] <= 100.0


def test_refuses_without_liberty(tmp_path):
    net = _write(tmp_path, "cut.v", WIDE_FRAME)
    cov = _write(tmp_path, "coverage.yml", WF_COVERAGE)
    r = tc.compute(net, cov, [])
    assert r["computed"] is False
    assert "liberty" in r["reason"].lower()


def test_cli_json_and_rc(tmp_path):
    net = _write(tmp_path, "cut.v", WIDE_FRAME)
    cov = _write(tmp_path, "coverage.yml", WF_COVERAGE)
    lib = _write(tmp_path, "mini.lib", LIBERTY)
    out = tmp_path / "tc.json"
    rc = tc.main(["--cut-netlist", str(net), "--coverage-yml", str(cov),
                  "--liberty", str(lib), "--json", str(out)])
    assert rc == 0
    d = json.loads(out.read_text())
    assert d["test_coverage_pct"] > d["raw_coverage_pct"]
