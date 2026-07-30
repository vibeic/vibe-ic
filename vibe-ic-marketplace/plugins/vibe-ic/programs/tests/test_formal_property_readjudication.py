#!/usr/bin/env python3
"""vibe-ic — a formal PASS that was only ever proved BOUNDED (vibe-ic#562).

`published_record_staleness_check` re-adjudicates published records against
current rules, but it could only decide 7 of 224 because 28 publishing gates
declared no rules. This is the first declaration, and it is on the gate with the
fewest records (1) so the mechanism is proven before it is repeated.

THE DRIFT IT CATCHES. `unbounded_proved` means "holds for all reachable states";
a bounded BMC result only means "no counterexample within the bound". A record
carrying PASS on bounded-only strength invites a reader to over-trust it — the
same distinction `assert_bound_honesty` enforces at run time, applied after the
fact to a record already on disk.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(
        f"fpr_{name}", PROGRAMS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[f"fpr_{name}"] = mod
    spec.loader.exec_module(mod)
    return mod


F = _load("formal_property_run")
RA = _load("_record_adjudication")


def _decide(record):
    """Run the declared rule the way the checker would."""
    return F.RECORD_ADJUDICATION.rules[0].decide(record)


def test_a_bounded_only_pass_is_superseded():
    """THE defect. Every property proved BOUNDED, verdict recorded as PASS."""
    s = _decide({"verdict": "PASS", "unbounded_proved": False})
    assert s is not None, "a bounded-only PASS was left standing"
    assert s.would_issue == "PARTIAL"
    assert "bounded" in s.because.lower()


def test_a_real_unbounded_proof_still_stands():
    """The rule must not supersede a proof that IS for all reachable states —
    otherwise it converts every formal PASS into debt."""
    assert _decide({"verdict": "PASS", "unbounded_proved": True}) is None


def test_a_non_pass_verdict_is_left_alone():
    """Only a PASS can over-claim. FAIL/PARTIAL/INCONCLUSIVE already say less
    than they proved, so re-adjudicating them would be noise."""
    for v in ("FAIL", "PARTIAL", "INCONCLUSIVE", "SKIPPED-CONDITION"):
        assert _decide({"verdict": v, "unbounded_proved": False}) is None, v


def test_the_rule_declares_the_fields_it_reads():
    """`requires` is the contract that makes undecidability explicit: a record
    missing these is reported UNDECIDABLE rather than quietly passed over, and
    `decide` is only called once they are present — so the body needs no
    defensive read, and an under-declared `requires` would make it crash on a
    real record instead."""
    r = F.RECORD_ADJUDICATION.rules[0]
    assert set(r.requires) == {"verdict", "unbounded_proved"}


def test_the_declaration_names_the_gate_and_its_decision_root():
    """A declaration pointed at the wrong function fingerprints someone else's
    logic. `build_results` is where this gate's verdict is decided — the first
    draft said `build_report`, copied from another gate, and the checker refused
    it with 'decision root(s) not found'."""
    d = F.RECORD_ADJUDICATION
    assert d.gate == "formal_property_run"
    assert d.decision_roots == ("build_results",)
    assert hasattr(F, "build_results")


def test_the_digest_is_a_real_fingerprint_not_a_placeholder():
    """An empty or truncated digest makes the drift guard silently useless: it
    would never report RULES_UNREVIEWED, so a verdict change could land with the
    rules never re-read. The first attempt wrote the whole CLI line here
    (`formal_property_run roots=[...] digest=...`) instead of the field."""
    d = F.RECORD_ADJUDICATION.decision_digest
    assert len(d) == 64 and all(c in "0123456789abcdef" for c in d), d


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
