#!/usr/bin/env python3
"""vibe-ic — a DFM PASS whose via screen never examined a via (#562).

    advisories = [f for f in findings if f["severity"] == "WARNING"]
    verdict = "PASS_WITH_ADVISORIES" if advisories else "PASS"

When the via-redundancy screen cannot run — `routed.def` has no parseable VIAS
section, or its NETS section references no via — the gate says so, honestly, as
an INFO finding. INFO never reaches `advisories`, so the record carries a plain
PASS that is indistinguishable from a run whose vias were screened and found
redundant.

The skip is honest at the moment it is printed. What is invisible later is that
the PASS covers a check that never ran — which is why a published record needs
re-ADJUDICATING rather than re-reading.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))


def _load(name: str):
    spec = importlib.util.spec_from_file_location(f"dfm_{name}", PROGRAMS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[f"dfm_{name}"] = mod
    spec.loader.exec_module(mod)
    return mod


D = _load("dfm_screen_check")


def _decide(record):
    return D.RECORD_ADJUDICATION.rules[0].decide(record)


def _rec(verdict="PASS", cats=()):
    return {"verdict": verdict,
            "findings": [{"severity": "INFO", "category": c} for c in cats]}


@pytest.mark.parametrize("cat", ["VIA_DEFS_NOT_FOUND", "VIA_USES_NOT_FOUND"])
def test_a_pass_whose_via_screen_did_not_run_is_superseded(cat):
    """THE defect, in both shapes the gate can emit it."""
    sup = _decide(_rec(cats=[cat]))
    assert sup is not None, f"{cat}: a vacuous PASS was left standing"
    assert sup.would_issue == "VACUOUS_PASS"
    assert cat in sup.because


def test_a_pass_that_really_screened_still_stands():
    """No VIA_*_NOT_FOUND means the screen ran. Superseding it would turn every
    clean DFM run into debt and the register would stop meaning anything."""
    assert _decide(_rec(cats=["ADVANCED_NODE_DFM"])) is None
    assert _decide(_rec(cats=[])) is None


def test_pass_with_advisories_is_left_alone():
    """That verdict already says more than a plain PASS; re-adjudicating it would
    be noise, and the reader is already being told to look."""
    assert _decide(_rec(verdict="PASS_WITH_ADVISORIES",
                        cats=["VIA_DEFS_NOT_FOUND"])) is None


def test_a_malformed_finding_does_not_crash_the_rule():
    """Records are read from disk and a rule that raises makes the checker report
    an error where it should report a verdict."""
    assert _decide({"verdict": "PASS",
                    "findings": [None, "x", {"category": 3}]}) is None


def test_the_rule_requires_both_fields_it_reads():
    assert set(D.RECORD_ADJUDICATION.rules[0].requires) == {"verdict", "findings"}


def test_the_declaration_points_at_the_deciding_function():
    d = D.RECORD_ADJUDICATION
    assert d.gate == "dfm_screen_check"
    assert d.decision_roots == ("audit",)
    assert hasattr(D, "audit")


def test_the_digest_is_a_real_fingerprint():
    """An empty digest never reports RULES_UNREVIEWED, so a verdict change could
    land with the rules never re-read."""
    dg = D.RECORD_ADJUDICATION.decision_digest
    assert len(dg) == 64 and all(c in "0123456789abcdef" for c in dg), dg


def test_issue1980_metadata_removal_was_readjudicated():
    """#1980 removed `verdict_mode`, which this rule never consumes."""
    before = _rec(cats=["VIA_DEFS_NOT_FOUND"])
    before["verdict_mode"] = "ADVISES"
    after = _rec(cats=["VIA_DEFS_NOT_FOUND"])
    assert _decide(before) == _decide(after)
    assert D.RECORD_ADJUDICATION.drift() is None


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
