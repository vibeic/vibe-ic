"""#564 — a gate can disclose a zero denominator and still return success.

`gate_discloses_denominator_check` already drove every `*_check.py` against an
absent project and required the output to be HONEST about it. What it did not
ask is what the gate RETURNED. Its absent-project loop read:

    if res["disclosed"]:
        continue        # honest -> nothing to report

so a gate printing `analyzed 0 file(s)` and exiting 0 passed. That is how three
were shipped and then fixed by hand:

    interface_encoding_audit  "0 interfaces analyzed"   rc 0   v1.8.85
    fpga_qsf_lint             (no scope at all)         rc 1   v1.8.86
    oe_pattern_check          "analyzed 0 file(s)"      rc 0   v1.8.88

The message is not what aggregates. The P0 umbrella reads the EXIT CODE, so a
gate that says "0" in prose and returns 0 in rc contributes a silent pass to a
project-level verdict.

REPORTED, NOT ENFORCED, and the tests below pin that choice rather than assume
it. The predicate finds 17 gates today, and some are certainly correct — a gate
answering `PASS — no L4_REGMAP.json (gate not applicable)` is making a true
statement a reader can act on. Separating those from the defect shape needs one
measurement per gate, not a regex over the wording: a text proxy standing in for
the property is the family this program exists to catch. Turning all 17 into
FAIL today would block every landing on an unmade judgement, and a gate that
blocks every landing gets switched off rather than answered.
"""
from __future__ import annotations

import importlib.util
import pathlib
import sys

import pytest

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]


def _load():
    spec = importlib.util.spec_from_file_location(
        "gate_discloses_denominator_check",
        _PROGRAMS / "gate_discloses_denominator_check.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


G = _load()

#: Per-gate probe budget. 45s, not the 120s this started at: the CI harness
#: ceiling is harness//3 = 60s, and an inner bound above it can outlive the
#: harness and kill the SESSION instead of failing the test. Measured cost of a
#: full `audit_project_gates` run over 493 gates is 3.1s, so 45 is fifteen
#: times the whole sweep for what is a PER-GATE budget.
#:
#: Caught by `test_the_advisory_residual_does_not_grow_unreviewed`, which is a
#: ratchet on exactly this — the third time I have written an over-wide inner
#: timeout this session, and the first time a gate caught it rather than a
#: landing run.
_PROBE_BUDGET_S = 45


def test_the_honest_zero_predicate_accepts_the_shapes_that_were_fixed():
    """The two rc-0 defects were HONEST by the existing standard.

    If this ever returns False, the census below stops finding them and the
    reason for #564 has evaporated — which would need explaining, not
    celebrating.
    """
    interface = ("ERROR: RTL directory not found: /nonexistent/x\n"
                 "interface_encoding_audit: 0 MISMATCH, 0 MATCH, 0 UNKNOWN "
                 "(0 interfaces analyzed)")
    oe = ("WARNING: file not found: /absent.v\n"
          "oe_pattern_check: analyzed 0 file(s), found 0 OE signal(s)")
    assert G._honest_about_an_absent_project(interface) is True
    assert G._honest_about_an_absent_project(oe) is True


def test_a_non_zero_count_over_an_absent_project_is_still_dishonest():
    """The pre-existing standard must survive this change.

    `checked 1 project(s)` asserts one project was opened when none was; that
    is the finding the absent-project fixture was built for, and it must not be
    reclassified into the new report-only census.
    """
    assert G._honest_about_an_absent_project(
        "checked 1 project(s) -- ALL_PASS") is False


def test_census_is_reported_and_does_not_move_the_verdict():
    """Run the real audit: 493 gates, PASS, with a non-empty census.

    Asserting BOTH halves is the point. A census that is empty proves nothing,
    and a verdict that moved would mean this landed as an enforcement change
    while its docstring says otherwise.
    """
    verdict, findings, stats = G.audit_project_gates(_PROGRAMS, timeout=_PROBE_BUDGET_S)
    assert verdict == "PASS", [f.get("gate") for f in findings]
    assert not findings, findings
    census = stats.get("absent_rc_zero_honest_but_passing", 0)
    assert census > 0, (
        "the census is empty; either every gate now refuses on a zero "
        "denominator — which would be worth checking rather than assuming — "
        "or the predicate stopped firing")
    named = stats.get("absent_rc_zero_honest_but_passing_gates", [])
    assert len(named) == census, (census, len(named))


def test_each_census_entry_carries_its_evidence():
    """A name with no output is a list nobody can act on."""
    _, _, stats = G.audit_project_gates(_PROGRAMS, timeout=_PROBE_BUDGET_S)
    for entry in stats.get("absent_rc_zero_honest_but_passing_gates", []):
        assert entry["gate"], entry
        assert entry["kind"] == "HONEST_ZERO_BUT_EXIT_ZERO", entry
        assert entry["output_tail"].strip(), entry
        assert entry["detail"].strip(), entry


def test_the_three_fixed_gates_are_no_longer_in_the_census():
    """The ratchet direction.

    v1.8.85/86/88 made these three return rc 2 over an absent input, so the
    absent-project loop skips them before the census is reached. If one comes
    back, its fix regressed.
    """
    _, _, stats = G.audit_project_gates(_PROGRAMS, timeout=_PROBE_BUDGET_S)
    named = {e["gate"] for e in
             stats.get("absent_rc_zero_honest_but_passing_gates", [])}
    for gate in ("interface_encoding_audit", "oe_pattern_check",
                 "fpga_qsf_lint"):
        assert gate not in named, (
            f"{gate} is back in the honest-zero census; its rc-2 fix regressed")
