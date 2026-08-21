#!/usr/bin/env python3
"""vibe-ic — a spare-cell PASS whose keep-attribute half never ran (#562).

`evaluate_preservation` returns PASS iff nothing was removed AND every survivor
carries its keep attribute. The second half only runs when some artefact CAN
carry that attribute; when none can, `all_keep_attr_intact` is vacuously true and
the PASS is indistinguishable on paper from one that checked and found everything
tagged.

That is the shape this whole issue is about — an absence rendering as a pass — so
the rule re-adjudicates it to VACUOUS_PASS rather than leaving a reader to infer
it from a field they would have to know to look for.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"scp_{name}", PROGRAMS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[f"scp_{name}"] = mod
    spec.loader.exec_module(mod)
    return mod


S = _load("spare_cell_preservation_check")


def _decide(record):
    return S.RECORD_ADJUDICATION.rules[0].decide(record)


def test_a_pass_whose_keep_check_never_ran_is_superseded():
    """THE defect: PASS on a run where no artefact could carry a keep attribute."""
    sup = _decide({"verdict": "PASS", "keep_check_applied": False})
    assert sup is not None, "a vacuous PASS was left standing"
    assert sup.would_issue == "VACUOUS_PASS"
    assert "keep_check_applied" in sup.because


def test_a_pass_that_DID_check_still_stands():
    """The rule must not supersede a real PASS — otherwise every preserved run
    becomes debt and the register stops meaning anything."""
    assert _decide({"verdict": "PASS", "keep_check_applied": True}) is None


def test_a_fail_is_left_alone():
    """Only a PASS can over-claim; a FAIL already says less than it proved."""
    for v in ("FAIL", "VACUOUS_PASS", "SKIPPED-CONDITION"):
        assert _decide({"verdict": v, "keep_check_applied": False}) is None, v


def test_the_rule_requires_both_fields_it_reads():
    """`requires` makes undecidability explicit: a record lacking these is
    reported UNDECIDABLE rather than quietly passed over, and `decide` is only
    called once both are present."""
    assert set(S.RECORD_ADJUDICATION.rules[0].requires) == {
        "verdict", "keep_check_applied"}


def test_the_declaration_points_at_the_function_that_decides():
    """A declaration aimed at the wrong function fingerprints someone else's
    logic — and aimed at `main` it would fingerprint the whole CLI, so an
    unrelated flag would report RULES_UNREVIEWED and train the guard to be
    ignored."""
    d = S.RECORD_ADJUDICATION
    assert d.gate == "spare_cell_preservation_check"
    assert d.decision_roots == ("evaluate_preservation",)
    assert hasattr(S, "evaluate_preservation")


def test_the_digest_is_a_real_fingerprint():
    """An empty digest makes the drift guard silently useless: it would never
    report RULES_UNREVIEWED, so a verdict change could land with the rules never
    re-read."""
    d = S.RECORD_ADJUDICATION.decision_digest
    assert len(d) == 64 and all(c in "0123456789abcdef" for c in d), d


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
