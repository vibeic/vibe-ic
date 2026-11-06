"""A sweep must report how much of the guard it REACHED, not only its verdict.

THE FINDING THIS PINS
=====================
A corpus sweep published as the acceptance evidence for a guard reported
``exit 0, clean`` over 756 ordered pairs. Every one of the 756 had returned
rc 2 / NOT_COMPARABLE, because no pre-existing artefact carried the digest the
guard compares, so the guard's decision point was never entered once. In its
output, in its exit code and in the PR body that quoted it, that sweep was
indistinguishable from one that ran the guard 756 times and found nothing.

The per-item disclosure existed — each child returned rc 2, the shipped
``_vacuous_exit`` "I examined nothing" code. It was discarded at the layer that
aggregated and published the number. ``_sweep_reach`` is that missing layer.

WHAT EACH TEST BELOW IS FOR
===========================
* ``TestBidirectionalControl`` — the guard fires on a zero-reach sweep AND
  stays silent on a sweep that reached something. A one-directional control
  proves only that a check can say one word.
* ``TestReverseCaseMustStillPass`` — the over-correction control. A PARTIAL
  sweep (1 target of many reached; a declared decision point never hit) is
  legitimate and must pass. A rule demanding total coverage would fire on
  nearly every honest sweep in this tree and would be worse than the silence.
* ``TestLoadBearing`` — mutation controls. If the reach accounting is removed
  from the firing path, or the sentinel gate is loosened, a test here must
  fail. A control that passes against a disabled check is not a control.
* ``TestCorpusSweepOfTheAdopters`` — this file's own corpus sweep, over the
  real programs that adopt the contract, running their real CLIs. It accounts
  for and asserts its OWN reach, because a sweep shipped as the evidence for
  "a sweep must prove it fired" that could not prove it fired would be the
  finding rather than the fix.

Fixtures are PUBLIC (sky130 cell names) or invented grammar. No PDK under NDA.
"""
import json
import sys
from pathlib import Path

import pytest

import _gate_denominator as gd
import _sweep_reach as sr
import _vacuous_exit as vx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402


# A minimal routed DEF built from PUBLIC sky130 standard-cell names — the same
# shape test_perc_corpus_sweep.py already uses.
_ROUTED_DEF = """VERSION 5.8 ;
DESIGN chip_top ;
UNITS DISTANCE MICRONS 1000 ;
DIEAREA ( 0 0 100000 100000 ) ;
COMPONENTS 3 ;
- _1_ sky130_fd_sc_hd__nor3_1 + PLACED ( 0 0 ) N ;
- _2_ sky130_fd_sc_hd__and3_1 + PLACED ( 100 0 ) N ;
- _3_ sky130_fd_sc_hd__dfxtp_1 + PLACED ( 200 0 ) N ;
END COMPONENTS
SPECIALNETS 2 ;
    - VPWR ( _1_ VPB ) + USE POWER ;
    - VGND ( _1_ VNB ) + USE GROUND ;
END SPECIALNETS
END DESIGN
"""


def _live_dir(root: Path, name: str) -> Path:
    """A design directory the PERC chain CAN reach (carries a routed DEF)."""
    d = root / name / "phase3" / "stage3" / "pnr"
    d.mkdir(parents=True)
    (d / "routed.def").write_text(_ROUTED_DEF)
    return root / name


def _dead_dir(root: Path, name: str) -> Path:
    """A design directory the PERC chain CANNOT reach — present, readable, no DEF.

    Deliberately NOT an empty/absent directory: the populated-but-unreachable
    corpus is the shape the finding is about, and the shape the pre-existing
    ``_gate_denominator`` / ``_vacuous_exit`` work does not cover.
    """
    d = root / name / "phase3" / "stage3" / "pnr"
    d.mkdir(parents=True)
    (d / "NOTES.txt").write_text("routing has not run for this block yet\n")
    return root / name


def _sentinel_lines(proc) -> int:
    return sum(1 for ln in (proc.stdout + "\n" + proc.stderr).splitlines()
               if ln.lstrip().startswith(vx.VACUOUS_STDOUT_SENTINEL))


# =====================================================================


# =====================================================================
class TestReverseCaseMustStillPass:
    """The over-correction control: partial sweeps are legitimate."""


    def test_an_unreached_declared_decision_point_is_reported_not_failed(self):
        """Declaring three decision points and hitting one is a PASS.

        The report says which point was never entered — that is the coverage
        signal — but an unhit point is not on its own a defect, because a rule
        with branches for cases this corpus does not contain is a normal rule.
        """
        reach = sr.SweepReach(unit="pair", decision_points=("cmp", "classify", "ratio"))
        reach.reached("p1", point="cmp")
        reach.not_reached("p2", reason="NOT_COMPARABLE")
        rep = reach.report()
        assert rep["decision_points"] == {"classify": 0, "cmp": 1, "ratio": 0}
        assert rep["is_vacuous"] is False
        assert reach.exit_code(passed=True) == vx.RC_PASS
        assert sr.reach_violations({sr.REACH_KEY: rep}) == []

    def test_an_empty_corpus_must_be_explained_but_a_partial_one_need_not(self):
        empty = sr.SweepReach(unit="pair")
        with pytest.raises(ValueError, match="why the corpus was empty"):
            empty.report()
        empty.declare_empty_corpus("the project filter matched no design")
        assert empty.report()["targets"] == 0
        partial = sr.SweepReach(unit="pair")
        partial.reached("a")
        partial.not_reached("b", reason="no artefact")
        partial.report()          # no empty-corpus declaration needed


# =====================================================================
class TestLoadBearing:
    """Mutation controls. Each asserts a test above would FAIL if the check were
    removed — a control that survives a disabled check is not a control."""


    def test_fail_beats_vacuous_on_the_rc_AND_on_the_sentinel(self, capsys):
        """A zero-reach sweep that also found a violation must not print
        "examined nothing" — a consumer reading the sentinel would promote the
        run into the vacuous tier and silence the finding."""
        reach = sr.SweepReach(unit="pair")
        reach.not_reached("p", reason="NOT_COMPARABLE")
        assert reach.is_vacuous is True
        assert reach.exit_code(passed=False) == vx.RC_FAIL
        reach.announce("s", passed=False, stream=sys.stdout)
        assert vx.VACUOUS_STDOUT_SENTINEL not in capsys.readouterr().out
        reach.announce("s", passed=True, stream=sys.stdout)
        assert vx.VACUOUS_STDOUT_SENTINEL in capsys.readouterr().out


    def test_an_undeclared_decision_point_is_rejected(self):
        reach = sr.SweepReach(unit="pair", decision_points=("cmp",))
        with pytest.raises(ValueError, match="was not declared"):
            reach.reached("p", point="cpm")          # typo
        with pytest.raises(ValueError, match="must name the one"):
            reach.reached("p")

    def test_not_stated_and_stated_zero_do_not_collapse(self):
        """`None` vs `True` — the distinction a consumer must not lose."""
        assert sr.is_vacuous_report({}) is None
        assert sr.is_vacuous_report({sr.REACH_KEY: {"reached": 0}}) is True
        assert sr.is_vacuous_report({sr.REACH_KEY: {"reached": 3}}) is False
        assert "NOT STATED" in sr.line_of({})

    def test_reach_violations_catches_a_report_that_does_not_add_up(self):
        assert sr.reach_violations({sr.REACH_KEY: {
            "unit": "pair", "targets": 10, "reached": 2, "not_reached": 3,
            "is_vacuous": False, "not_reached_reasons": {"x": 3},
            "decision_points": {}}})
        assert sr.reach_violations({sr.REACH_KEY: {
            "unit": "pair", "targets": 5, "reached": 0, "not_reached": 5,
            "is_vacuous": False, "not_reached_reasons": {"x": 5},
            "decision_points": {}}})
        assert sr.reach_violations({sr.REACH_KEY: {
            "unit": "pair", "targets": 5, "reached": 0, "not_reached": 5,
            "is_vacuous": True, "not_reached_reasons": {},
            "decision_points": {}}})


# =====================================================================
class TestReusesTheExistingConventions:
    """Built ON _gate_denominator / _vacuous_exit, not beside them."""

    def test_as_denominator_is_a_real_denominator_consumers_already_parse(self):
        reach = sr.SweepReach(unit="design directory", decision_points=("perc_chain",))
        reach.reached("a", point="perc_chain")
        reach.not_reached("b", reason="no routed DEF")
        d = reach.as_denominator()
        assert isinstance(d, gd.Denominator)
        assert (d.examined, d.considered) == (1, 2)
        assert gd.disclosure_violations(gd.attach({}, d)) == []

    def test_a_vacuous_sweep_denominator_carries_the_required_reason(self):
        reach = sr.SweepReach(unit="pair")
        reach.not_reached("a", reason="NOT_COMPARABLE")
        d = reach.as_denominator()          # would RAISE if the reason were empty
        assert d.is_vacuous and "NOT_COMPARABLE" in d.not_applicable_reason
        assert gd.disclosure_violations(gd.attach({}, d)) == []


    def test_absorb_child_rc_is_the_bridge_the_756_sweep_lacked(self):
        """756 children each returned rc 2; the wrapper reported clean."""
        reach = sr.SweepReach(unit="ordered audit pair")
        for i in range(756):
            reach.absorb_child_rc(f"pair-{i}", vx.RC_VACUOUS)
        assert reach.is_vacuous is True
        assert reach.exit_code(passed=True) == vx.RC_VACUOUS
        assert reach.report()["coverage"] == "0/756"
        reach.absorb_child_rc("pair-756", vx.RC_PASS)
        assert reach.exit_code(passed=True) == vx.RC_PASS


# =====================================================================
class TestSelfApplication:
    """The checker is itself a sweep and is held to its own rule."""


# =====================================================================


# =====================================================================


# =====================================================================
