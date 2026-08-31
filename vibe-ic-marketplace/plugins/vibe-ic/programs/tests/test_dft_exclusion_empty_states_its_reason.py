"""#772 — `untestable_faults_excluded: 0` must say WHICH of two facts it is.

A record that reports "N nets are untestable" beside "0 faults excluded" is
ambiguous between two situations that demand OPPOSITE actions:

  * the site->net mapping failed to meet the engine's fault names, so a real
    exclusion was missed                                   → fix the mapping;
  * the untestable nets carry no enumerated fault site at all, so there was
    never anything to exclude                              → fix nothing here,
    the shortfall is on faults the engine DID enumerate.

Both print the same two numbers. This was measured as a real cost: a reviewer
reading such a record could only write down "either those nets carry none of
the uncovered faults, or the two name-spaces do not meet — that is a lead, not
a finding", and resolving it took a separate instrumented re-run of the engine
against the shipped artefacts. Every datum needed to answer it was already in
the function's own scope at write time.

WHICH WAY IT MUST ERR. This is a DISCLOSURE change: it must add fields and
never move a number. The controls below are the flow-change-acceptance
bidirectional negative control —

  * the two ambiguous cases are distinguished by name         (the RED cases)
  * a run that DID exclude something states no reason  (no excuse when unneeded)
  * every pre-existing number is byte-identical           (the no-drift guard)
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]


def _load(name):
    spec = importlib.util.spec_from_file_location(name, _PROGRAMS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)
    return mod


tc = _load("dft_test_coverage")

LIBERTY = """
library(mini) {
  cell (BUF) { pin (A) { direction : input; } pin (Y) { direction : output; } }
  cell (TIE) { pin (Y) { direction : output; } }
}
"""

# ── fixture 1: untestable nets that carry NO fault site ──────────────────
# `dead[3:0]` is an assign-network wire with no reader and no cell pin on it.
# The classifier calls it unobservable; the engine faults CELL PINS, so it
# enumerates no site there. This is the shape that produced the ambiguity.
DEAD_ASSIGN_NET = """
module top(a, out);
  input a; wire a;
  output out; wire out;
  wire [3:0] dead;
  assign dead = {4{a}};
  BUF _0_ (.A(a), .Y(out));
endmodule
"""
DEAD_COVERAGE = """ratio: 7.5e-1
faultPoints:
- a
- out
sa0Covered:
- a
- out
sa1Covered:
- a
sa0Uncovered: []
sa1Uncovered:
- out
"""

# ── fixture 2: untestable nets that DO carry fault sites ─────────────────
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
WF_POINTS = """ratio: 4.0e-1
faultPoints:
- la_in [0]
- la_in [1]
- la_in [2]
- la_in [3]
- out
- tied
"""
# frame faults left UNCOVERED → they are excludable → exclusion is non-empty
WF_UNCOVERED = WF_POINTS + """sa0Covered:
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
# the SAME frame, every fault DETECTED → nothing left to exclude, but the
# untestable nets plainly do carry sites. A different fact, a different reason.
WF_ALL_COVERED = WF_POINTS + """sa0Covered:
- la_in [0]
- la_in [1]
- la_in [2]
- la_in [3]
- out
- tied
sa1Covered:
- la_in [0]
- la_in [1]
- la_in [2]
- la_in [3]
- out
- tied
sa0Uncovered: []
sa1Uncovered: []
"""

# ── fixture 3: nothing untestable at all ─────────────────────────────────
FULLY_TESTABLE = """
module top(a, out);
  input a; wire a;
  output out; wire out;
  BUF _0_ (.A(a), .Y(out));
endmodule
"""
FT_COVERAGE = """ratio: 5.0e-1
faultPoints:
- a
- out
sa0Covered:
- a
sa1Covered:
- out
sa0Uncovered:
- out
sa1Uncovered:
- a
"""


def _run(tmp, netlist, coverage):
    (tmp / "cut.v").write_text(netlist)
    (tmp / "coverage.yml").write_text(coverage)
    (tmp / "mini.lib").write_text(LIBERTY)
    r = tc.compute(tmp / "cut.v", tmp / "coverage.yml", [str(tmp / "mini.lib")])
    assert r["computed"] is True, r.get("reason")
    return r


# ── RED: the two ambiguous cases must be told apart ──────────────────────
def test_untestable_nets_carrying_no_fault_site_say_exactly_that(tmp_path):
    r = _run(tmp_path, DEAD_ASSIGN_NET, DEAD_COVERAGE)
    assert r["untestable_faults_excluded"] == 0
    assert r["unobservable_nets"] > 0, "fixture must produce untestable nets"
    # the load-bearing datum: the engine enumerated no site on any of them.
    assert r["untestable_nets_carrying_fault_sites"] == 0
    reason = r["exclusion_empty_reason"]
    assert reason and "NO fault site" in reason
    # and it must say the mapping is not the culprit, so nobody re-opens it.
    assert "mapping would not change it" in reason


def test_untestable_nets_that_do_carry_detected_faults_say_that_instead(tmp_path):
    r = _run(tmp_path, WIDE_FRAME, WF_ALL_COVERED)
    assert r["untestable_faults_excluded"] == 0
    assert r["untestable_nets_carrying_fault_sites"] > 0
    reason = r["exclusion_empty_reason"]
    assert reason and "DETECTED" in reason
    # the two empty-exclusion reasons must NOT be the same sentence.
    other = _run(tmp_path, DEAD_ASSIGN_NET, DEAD_COVERAGE)["exclusion_empty_reason"]
    assert reason != other


def test_nothing_untestable_is_its_own_reason(tmp_path):
    r = _run(tmp_path, FULLY_TESTABLE, FT_COVERAGE)
    assert r["untestable_faults_excluded"] == 0
    assert r["untestable_nets_carrying_fault_sites"] == 0
    assert "nothing to exclude" in r["exclusion_empty_reason"]


def test_a_run_that_excluded_something_states_no_reason(tmp_path):
    r = _run(tmp_path, WIDE_FRAME, WF_UNCOVERED)
    assert r["untestable_faults_excluded"] > 0
    assert r["exclusion_empty_reason"] is None, \
        "a non-empty exclusion needs no excuse; a line on every run trains the reader to skip it"


def test_the_denominator_of_the_claim_is_published(tmp_path):
    # "0 of the untestable nets carry a site" is only readable beside how many
    # nets DO carry one, and how many sites mapped to no net at all.
    r = _run(tmp_path, DEAD_ASSIGN_NET, DEAD_COVERAGE)
    assert r["fault_carrying_nets"] > 0
    assert r["fault_sites_unmapped_to_a_net"] >= 0
    assert r["untestable_nets_carrying_fault_sites"] <= r["fault_carrying_nets"]


# ── guards that must pass in BOTH directions (no over-shoot) ─────────────
def test_disclosure_moves_no_number(tmp_path):
    """The lift control from #603 must still hold exactly: 4 frame sites x 2
    polarities = 8 faults excluded, test > raw, bounded at 100 %."""
    r = _run(tmp_path, WIDE_FRAME, WF_UNCOVERED)
    assert r["untestable_faults_excluded"] == 8
    assert r["test_coverage_pct"] > r["raw_coverage_pct"]
    assert r["test_coverage_pct"] <= 100.0


def test_empty_control_still_excludes_nothing(tmp_path):
    r = _run(tmp_path, FULLY_TESTABLE, FT_COVERAGE)
    assert r["untestable_faults_excluded"] == 0
    assert r["test_coverage_pct"] == r["raw_coverage_pct"]
