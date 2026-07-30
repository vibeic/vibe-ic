#!/usr/bin/env python3
"""vibe-ic — an FMEDA PASS at 0% diagnostic coverage (vibe-ic#562).

    def dc_verdict(dc_pct, floor):
        if floor is None:
            return True, f"advisory: DC={dc_pct:.2f}% measured; ASIL has no ..."

ASIL-A / QM state no quantitative DC floor, so the branch passes ANY number
including zero. That gating decision is right — inventing a floor the standard
does not state would be fabrication. What it leaves behind is a record whose
`verdict` field says PASS for a run that injected nothing, or injected and
detected nothing. The `reason` string says "advisory"; the verdict does not, and
the verdict is the field a consumer reads.

`compute_dc` already states the principle for the numerator — "injected==0 -> 0.0
(no evidence is NOT full coverage)". This rule carries it to the verdict.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"fm_{name}", PROGRAMS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[f"fm_{name}"] = mod
    spec.loader.exec_module(mod)
    return mod


F = _load("fmeda_fault_injection_coverage")


def _decide(record):
    return F.RECORD_ADJUDICATION.rules[0].decide(record)


def _rec(verdict="PASS", dc=0.0, injected=0):
    return {"verdict": verdict, "diagnostic_coverage_pct": dc,
            "injected_faults": injected}


def test_the_gating_branch_really_does_pass_zero():
    """The premise, asserted rather than assumed: with no floor, dc_verdict
    returns True for 0%. If this ever stops being true the rule below is dead
    code and should go, not linger."""
    assert F.dc_verdict(0.0, None)[0] is True
    assert F.dc_verdict(0.0, 60.0)[0] is False
    assert F.compute_dc(0, 0) == 0.0


def test_a_pass_that_injected_nothing_is_superseded():
    """THE defect. No fault was injected, so nothing was measured."""
    sup = _decide(_rec(dc=0.0, injected=0))
    assert sup is not None
    assert sup.would_issue == "VACUOUS_PASS"
    assert "injected no fault at all" in sup.because


def test_a_pass_that_detected_nothing_is_superseded():
    """Injected faults, detected none — measured, and measured to be useless."""
    sup = _decide(_rec(dc=0.0, injected=128))
    assert sup is not None
    assert "detected none" in sup.because


def test_a_pass_with_real_coverage_still_stands():
    """Superseding a measured PASS would make every ASIL-A run read as debt."""
    assert _decide(_rec(dc=97.5, injected=128)) is None
    assert _decide(_rec(dc=0.1, injected=1000)) is None


def test_a_non_pass_verdict_is_left_alone():
    for v in ("FAIL", "NOT_APPLICABLE", "UNMEASURED_NO_RTL_READ"):
        assert _decide(_rec(verdict=v, dc=0.0, injected=0)) is None, v


def test_an_unreadable_field_is_not_a_finding():
    """A record whose fields will not parse is UNDECIDABLE, not stale. Guessing
    here would publish a supersession from a record nobody could read."""
    assert _decide({"verdict": "PASS", "diagnostic_coverage_pct": "n/a",
                    "injected_faults": None}) is None


def test_the_rule_requires_every_field_it_reads():
    assert set(F.RECORD_ADJUDICATION.rules[0].requires) == {
        "verdict", "diagnostic_coverage_pct", "injected_faults"}


def test_the_digest_is_a_real_fingerprint():
    d = F.RECORD_ADJUDICATION.decision_digest
    assert len(d) == 64 and all(c in "0123456789abcdef" for c in d), d


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
