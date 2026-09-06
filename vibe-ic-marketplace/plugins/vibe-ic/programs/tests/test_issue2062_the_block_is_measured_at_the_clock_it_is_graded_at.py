"""The clock a block is GRADED at and the clock its testbench RUNS at are one.

vibe-ic#2062, owner rulings (1) and (2), 2026-09-07.

RULING (1). The entry requirement `settling_time_constants` is evaluated at
`fclk` — the operating point the declaration NAMES — and the bias resistor is
derived at `fclk` too. The emitted testbench, however, built its clock period
and its whole transient span from `fclk_max`, the top of the declared range. So
the block was HELD to one clock and EXERCISED at another, and the density that
deck measured was never a measurement of the thing the bound had admitted. The
ruling closes the mismatch in the direction of the grade: the block is measured
at the clock it is graded at.

THE COST, MEASURED ONCE ON EACH BLOCK, because it is a cost and not a reason:
the transient span goes as 1/clock, so the ratio is exactly `fclk_max / fclk`.

    ldo          1.0000x   its deck is an `op` analysis — no transient at all
    delta_sigma  1.2823x   399282.5 ns -> 512000.0 ns

No deadline exists for that to trip: `analog_real_corner_sweep` runs every
corner to completion (#2062 R12).

RULING (2). `fclk_max` was declared 1.2824 MHz; the exact break-even is
1.2823956, so rounding UP left a ceiling-graded bound short by 3.6e-5 counts.
Corrected to 1.2823 in benchmark-data. The ceiling figure stays PUBLISHED and
NON-BLOCKING either way — what the correction buys is that the declaration now
stands on its own.

Both are pinned STRUCTURALLY where possible: a test that hardcodes 1.2823 would
go stale the next time a declaration moves, so what is asserted is the
RELATIONSHIP — the grade and the deck name the same clock — and the arithmetic
is asserted on synthesized declarations that carry their own numbers.
"""
import json
import re
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))

import analog_a2_topology_emit as a2  # noqa: E402

ENTRY = a2.LIBRARY["delta_sigma"]
_UNITS = {"order": "", "vdd": "V", "osr": "", "enob": "bit", "vref": "V",
          "fclk": "MHz", "fclk_max": "MHz"}


def _measured():
    reg = json.loads((_PROGRAMS / "pdk_registry.json").read_text())
    p = [x for x in reg["pdks"] if x["name"] == "ihp-sg13g2"][0]
    m = p["analog_device_params"]["measured"]["corners"]["typ"]["params"]
    return {k: v for k, v in m.items() if isinstance(v, (int, float))}


def _spec(**over):
    s = {"order": 2.0, "vdd": 1.2, "osr": 256.0, "enob": 14.0, "vref": 1.0,
         "fclk": 1.0, "fclk_max": 1.0}
    s.update(over)
    return s


# ── ruling (1): one clock, structurally ───────────────────────────────────
_CLOCK_TERMS = ("tper_ns", "thigh_ns", "twin_ns", "tmeas_ns", "twin2_ns",
                "tstop_ns", "tstep_ns")


def test_the_testbench_runs_at_the_clock_the_entry_GRADES():
    """THE INVARIANT, and it is structural: every timing term of the emitted
    stimulus is written against the SAME clock name the blocking settling
    bound is written against. Neither number is hardcoded here — the two
    expressions are compared to each other."""
    graded = [d for d in ENTRY["requires_derived"]
              if d["name"] == "settling_time_constants"][0]["expr"]
    assert "fclk_max" not in graded, graded
    assert re.search(r"\bfclk\b", graded), graded

    env_exprs = ENTRY["testbench"]["env_exprs"]
    for term in _CLOCK_TERMS:
        assert term in env_exprs, term
        assert "fclk_max" not in env_exprs[term], (term, env_exprs[term])
        assert re.search(r"\bfclk\b", env_exprs[term]), (term, env_exprs[term])


def test_the_operating_clock_is_a_BOUND_row_and_a_declaration_without_it_is_refused_BY_NAME():
    """Everything this entry decides is evaluated at `fclk`: the bias length,
    the settling bound, and now the deck. It was NOT in `requires_bound` while
    the deck ran at `fclk_max`, and `spec_row_values`'s own docstring records
    the measured shape of that gap in the other direction — A2 admitting a
    block and A3 then failing to render it. A2 must refuse first, by name."""
    assert "fclk" in ENTRY["requires_bound"]
    sp = _spec()
    del sp["fclk"]
    refusals = a2.entry_admission(ENTRY, sp, {k: _UNITS[k] for k in sp},
                                  _measured())
    named = [r for r in refusals
             if r.get("field") == "fclk" and r.get("requirement") == "spec_bound"]
    assert named, refusals


def test_the_span_ratio_is_exactly_the_clock_ratio():
    """The cost, stated as the relationship rather than as last week's number:
    the transient goes as 1/clock, so moving the deck from the ceiling to the
    operating point multiplies it by fclk_max/fclk exactly."""
    for fmax in (1.0, 1.2823, 2.0, 10.0):
        env = {"window_clocks": 256.0, "fclk": 1.0, "fclk_max": fmax}
        at_fclk = a2._safe_eval(ENTRY["testbench"]["env_exprs"]["tstop_ns"],
                                env)
        at_ceiling = a2._safe_eval(
            ENTRY["testbench"]["env_exprs"]["tstop_ns"].replace(
                "fclk", "fclk_max"), env)
        assert at_fclk == pytest.approx(at_ceiling * fmax, rel=1e-12), fmax


# ── ruling (2): the ceiling is reported, never blocking ───────────────────
def test_a_declaration_whose_CEILING_also_meets_the_bound_is_admitted_by_both():
    """The state the corrected declaration is in: the block is admitted at the
    operating point (which is what decides), AND the published ceiling figure
    reads MET, so the declaration stands on its own without leaning on the
    ruling. Synthesized: the fixture computes the break-even from the entry's
    own expressions rather than restating a declared number."""
    env = a2.admission_env(ENTRY, _spec(), _measured())
    at_target = a2._safe_eval(a2._SETTLING_TC_AT_FCLK_EXPR, env)
    need = a2._safe_eval(a2._SETTLING_TC_REQUIRED_EXPR, env)
    breakeven = at_target / need              # the fclk_max/fclk that just meets it

    ok = _spec(fclk_max=breakeven * 0.999)    # a hair BELOW the break-even
    assert a2.entry_admission(ENTRY, ok, {k: _UNITS[k] for k in ok},
                              _measured()) == []
    info = [r for r in a2.entry_informational(ENTRY, ok, _measured())
            if r["field"] == "settling_time_constants_at_fclk_max"][0]
    assert info["state"] == "MET", info
    assert info["blocking"] is False


def test_a_ceiling_that_does_NOT_meet_the_bound_is_still_only_REPORTED():
    """The other direction, and the half the ruling turns on: a declaration
    whose RANGE does not close is still ADMITTED at its operating point, and
    the shortfall is published rather than refused."""
    env = a2.admission_env(ENTRY, _spec(), _measured())
    breakeven = (a2._safe_eval(a2._SETTLING_TC_AT_FCLK_EXPR, env)
                 / a2._safe_eval(a2._SETTLING_TC_REQUIRED_EXPR, env))
    bad = _spec(fclk_max=breakeven * 1.001)   # a hair ABOVE it
    assert a2.entry_admission(ENTRY, bad, {k: _UNITS[k] for k in bad},
                              _measured()) == []
    info = [r for r in a2.entry_informational(ENTRY, bad, _measured())
            if r["field"] == "settling_time_constants_at_fclk_max"][0]
    assert info["state"] == "NOT_MET", info
    assert info["blocking"] is False


# ── the real declaration, read from the repo rather than retyped ──────────
def test_the_shipped_entry_grades_and_runs_at_one_clock_end_to_end():
    """A real-artefact arm: the SHIPPED library entry, not a fixture authored
    beside this file. If the two clock names ever diverge again this fails
    without anyone having to remember why."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "a2_shipped", _PROGRAMS / "analog_a2_topology_emit.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    # READ THE STRUCTURED ENTRY, NOT THE SOURCE TEXT. A grep over the file
    # matches the rationale COMMENTS that deliberately preserve the superseded
    # argument — the same "a guard reading its own citation" shape this lane
    # has already tripped over twice. The entry is the artefact; the prose
    # around it is not.
    entry = mod.LIBRARY["delta_sigma"]
    for term in _CLOCK_TERMS:
        assert "fclk_max" not in entry["testbench"]["env_exprs"][term], term
    graded = [d for d in entry["requires_derived"]
              if d["name"] == "settling_time_constants"][0]
    assert "fclk_max" not in graded["expr"], graded["expr"]
    # ...and the ceiling is still REPORTED, non-blocking, on the same entry
    ceiling = [d for d in entry["requires_derived"]
               if d["name"] == "settling_time_constants_at_fclk_max"][0]
    assert ceiling.get("informational") is True
    assert "fclk_max" in ceiling["expr"]
