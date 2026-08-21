#!/usr/bin/env python3
"""Tests for corner_yield_vs_spec_check.py."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "corner_yield_vs_spec_check.py"


def _run(proj: Path):
    return subprocess.run(
        [sys.executable, str(PROG), str(proj),
         "--json", str(proj / "report.json")],
        capture_output=True, text=True)


def _report(proj: Path) -> dict:
    return json.loads((proj / "report.json").read_text())


def _block(proj: Path, name="ldo"):
    d = proj / "phase3" / "analog" / name
    d.mkdir(parents=True, exist_ok=True)
    return d


def _write(d: Path, spec, corners, design_content="structure_and_geometry"):
    """`design_content` is the corner artefact's own record of WHAT circuit
    produced the numbers.

    It has a default because every test below except the two that vary it is
    about the yield arithmetic, and a fixture that said nothing would make each
    of them assert something extra and false: that a gate may re-derive a
    verdict from numbers without knowing what the numbers describe. Pass
    `None` to build the artefact that declines to say.
    """
    if spec is not None:
        (d / "spec.json").write_text(json.dumps(spec))
    if corners is not None:
        doc = {"corners": corners}
        if design_content is not None:
            doc["design_content"] = design_content
        (d / "corner_results.json").write_text(json.dumps(doc))


# -- PASS: all corners satisfy spec.json limits, worst corner identified --
def test_pass_all_corners_satisfy(tmp_path):
    d = _block(tmp_path)
    _write(d,
           {"specs": {"gain_db": {"min": 55}, "power_uw": {"max": 100}}},
           [{"name": "tt_25C", "measured": {"gain_db": 60, "power_uw": 80}},
            {"name": "ss_-40C", "measured": {"gain_db": 56, "power_uw": 95}},
            {"name": "ff_125C", "measured": {"gain_db": 70, "power_uw": 70}}])
    r = _run(tmp_path)
    assert r.returncode == 0, r.stderr
    rep = _report(tmp_path)
    assert rep["passed"] is True
    det = rep["summary"]["details"][0]
    # ss_-40C has the tightest gain margin → worst corner
    assert det["worst_corner"] == "ss_-40C"
    assert det["violations"] == 0


# -- FAIL: a corner violates the min limit (status field could lie) --
def test_fail_corner_violates_min(tmp_path):
    d = _block(tmp_path)
    _write(d,
           {"specs": {"gain_db": {"min": 55}}},
           [{"name": "tt_25C", "measured": {"gain_db": 60}},
            {"name": "ss_-40C", "measured": {"gain_db": 48}}])  # < 55
    r = _run(tmp_path)
    assert r.returncode == 1
    rep = _report(tmp_path)
    assert rep["passed"] is False
    assert any(f["rule"] == "SPEC_VIOLATED_AT_CORNER" for f in rep["findings"])


# -- FAIL: spec.json declares limits but no corner_results.json --
def test_fail_missing_corner_evidence(tmp_path):
    d = _block(tmp_path)
    _write(d, {"specs": {"gain_db": {"min": 55}}}, None)
    r = _run(tmp_path)
    assert r.returncode == 1
    rep = _report(tmp_path)
    assert any(f["rule"] == "MISSING_CORNER_EVIDENCE" for f in rep["findings"])


# -- FAIL (no vacuous PASS): spec.json with no numeric limits --
def test_fail_no_numeric_limits(tmp_path):
    d = _block(tmp_path)
    _write(d, {"specs": {"gain_db": {"description": "high"}}},
           [{"name": "tt_25C", "measured": {"gain_db": 60}}])
    r = _run(tmp_path)
    assert r.returncode == 1
    rep = _report(tmp_path)
    assert any(f["rule"] == "NO_NUMERIC_LIMITS" for f in rep["findings"])


# -- FAIL: corner data never overlaps the spec names --
def test_fail_no_overlap(tmp_path):
    d = _block(tmp_path)
    _write(d, {"specs": {"gain_db": {"min": 55}}},
           [{"name": "tt_25C", "measured": {"bandwidth_mhz": 10}}])
    r = _run(tmp_path)
    assert r.returncode == 1
    rep = _report(tmp_path)
    assert any(f["rule"] == "NO_OVERLAP" for f in rep["findings"])


# ══════════════════════════════════════════════════════════════════════════
# WHAT THE RE-DERIVED YIELD IS A YIELD OF
#
# This gate re-derives PASS/FAIL from the spec's own min/max limits, so its
# verdict is a claim about the circuit those numbers came from. The three
# tests below pin the ranking that makes disclosure the cheap answer:
#
#   design-bound  -> [PASS]                  (test_pass_all_corners_satisfy)
#   structure-only-> [PASS_STRUCTURE_ONLY]   disclosed, certifies in its tier
#   undisclosed   -> rc 1                    does not certify at all
#
# Reverse any two of those and the gate pays a producer to say less.
# ══════════════════════════════════════════════════════════════════════════

_SPEC = {"specs": {"gain_db": {"min": 55}}}
_CLEAN = [{"name": "tt_25C", "measured": {"gain_db": 60}},
          {"name": "ss_-40C", "measured": {"gain_db": 56}}]


def test_a_library_default_is_not_reported_as_this_designs_yield(tmp_path):
    """Every corner inside the band, and the artefact says the circuit that
    produced them is a library nominal. Pre-fix this printed a bare `[PASS]`,
    indistinguishable from a design whose yield actually closed."""
    _write(_block(tmp_path), _SPEC, _CLEAN, design_content="structure_only")
    r = subprocess.run([sys.executable, str(PROG), str(tmp_path)],
                       capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr     # not a FAIL: it disclosed
    line = r.stdout.splitlines()[0]
    assert line.startswith("[PASS_STRUCTURE_ONLY]"), line
    assert "YIELD_STRUCTURE_ONLY" in r.stdout, r.stdout
    assert "STRUCTURE_ONLY:" in r.stderr, r.stderr


def test_the_two_trees_do_not_print_the_same_line(tmp_path):
    """The negative control: identical in every byte except the one recorded
    value. If the printed lines match, the distinction does not exist for
    anyone who does not open a JSON file."""
    a, b = tmp_path / "so", tmp_path / "sized"
    _write(_block(a), _SPEC, _CLEAN, design_content="structure_only")
    _write(_block(b), _SPEC, _CLEAN, design_content="structure_and_geometry")
    out = [subprocess.run([sys.executable, str(PROG), str(p)],
                          capture_output=True, text=True).stdout.splitlines()[0]
           for p in (a, b)]
    assert out[0] != out[1], out
    assert out[1] == "[PASS] corner_yield_vs_spec_check", out[1]


def test_an_artefact_that_will_not_say_what_it_graded_does_not_certify(
        tmp_path):
    """Silence must not be the cheap answer. Same clean corners, same limits,
    one field removed — and removing it is exactly the shape of every artefact
    written before the field existed, and of every stale one."""
    _write(_block(tmp_path), _SPEC, _CLEAN, design_content=None)
    r = _run(tmp_path)
    assert r.returncode == 1, (
        "a yield re-derived from an artefact that will not say what circuit "
        "produced the numbers was certified as this design's")
    rep = _report(tmp_path)
    assert any(f["rule"] == "YIELD_SUBJECT_UNDECLARED" for f in rep["findings"])
    assert rep["summary"]["blocks_design_bound_pass"] == 0


def test_a_value_failure_is_still_diagnosed_as_a_value_failure(tmp_path):
    """Ordering control. An artefact that both violates a limit AND says
    nothing must be reported for the violation: a reader told to "say what it
    contains" about a corner that is out of spec fixes the wrong thing."""
    _write(_block(tmp_path), _SPEC,
           [{"name": "tt_25C", "measured": {"gain_db": 60}},
            {"name": "ss_-40C", "measured": {"gain_db": 48}}],
           design_content=None)
    r = _run(tmp_path)
    assert r.returncode == 1
    rules = [f["rule"] for f in _report(tmp_path)["findings"]]
    assert "SPEC_VIOLATED_AT_CORNER" in rules, rules
    assert "YIELD_SUBJECT_UNDECLARED" not in rules, rules


# -- SKIP: no analog dir → honest self-skip, exit 0 --
def test_skip_no_analog(tmp_path):
    r = _run(tmp_path)
    assert r.returncode == 2      # #521 — VACUOUS (rc 2): the gate examined nothing.
    rep = _report(tmp_path)
    assert rep["summary"]["skipped"] is True


# -- SKIP: deterministic-stub corner data --
def test_stub_skipped(tmp_path):
    d = _block(tmp_path)
    (d / "spec.json").write_text(json.dumps({"specs": {"gain_db": {"min": 55}}}))
    (d / "corner_results.json").write_text(json.dumps(
        {"extraction_strategy": "deterministic_stub", "corners": []}))
    r = _run(tmp_path)
    assert r.returncode == 0
    rep = _report(tmp_path)
    assert any(f["rule"] == "YIELD_STUB_SKIPPED" for f in rep["findings"])


# -- FAIL: garbage (unparsable) corner_results.json --
def test_fail_garbage_corner(tmp_path):
    d = _block(tmp_path)
    (d / "spec.json").write_text(json.dumps({"specs": {"gain_db": {"min": 55}}}))
    (d / "corner_results.json").write_text("{not valid json")
    r = _run(tmp_path)
    assert r.returncode == 1
    rep = _report(tmp_path)
    assert any(f["rule"] == "CORNER_PARSE_ERROR" for f in rep["findings"])
