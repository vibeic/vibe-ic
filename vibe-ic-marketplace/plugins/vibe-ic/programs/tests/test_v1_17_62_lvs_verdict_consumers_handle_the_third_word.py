"""CZT-19, the consumer half — `lvs_verdict.json` is a CONTRACT, and one of its
readers turned every word it did not recognise into a certification.

`postroute_timing_repair_decision` decides whether Step 32 may write
`no_repair_needed.flag`.  It consulted `reports/phase3/lvs_verdict.json`
through a table of HARD-FAIL tokens.  `FAIL` was in that table; `INCOMPLETE`,
`BLOCKED` and `STALLED` were not — so a run whose LVS compare NEVER COMPLETED
scored exactly the same as a run with no LVS record at all, and Step 32
certified "no post-route repair needed" over it.

MEASURED on the tree before this change, one synthetic record per word:

    status=PASS        -> repair_needed False   (correct)
    status=FAIL        -> repair_needed True    (correct)
    status=INCOMPLETE  -> repair_needed False   <-- and #477 has been writing
    status=BLOCKED     -> repair_needed False       INCOMPLETE since 2026-06
    status=STALLED     -> repair_needed False

That is the vibe-ic#925 shape — an unrecognised word falling through to green
— one contract over.

THE DISTINCTION THIS FIX PRESERVES.  A stopped domain is NOT a failed domain.
Both withhold the certification, but only one is a finding about the design,
so they land in two different keys and the reason names them differently.  A
fix that simply added the words to `_HARD_FAIL_VERDICTS` would have made the
flow report a mismatch that nothing measured.

WHAT IS DELIBERATELY NOT CHANGED.  An ABSENT or UNPARSEABLE artefact still
scores nothing: that is this module's own documented rule and it is about
silence, which is a different fact from a record that speaks.  And
`ENV_UNAVAILABLE` is left alone — it is an established waiver tier
(`_aggregate_verdict` -> PASS_WITH_WAIVERS) and moving it is an owner call.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import eda_report_audit as ERA  # noqa: E402

#: The full status vocabulary `_write_lvs_verdict` can persist, enumerated from
#: its own call sites.  A word missing from this list is a word no test drives.
LVS_STATUS_VOCABULARY = ("PASS", "FAIL", "INCOMPLETE", "BLOCKED",
                         "ENV_UNAVAILABLE")


def _write_lvs(project: Path, status: str, finding: str = "X",
               **extra) -> Path:
    d = project / "reports" / "phase3"
    d.mkdir(parents=True, exist_ok=True)
    doc = {"status": status, "result": status, "finding": finding,
           "message": "synthetic record"}
    doc.update(extra)
    p = d / "lvs_verdict.json"
    p.write_text(json.dumps(doc, indent=2) + "\n")
    return p


# ---------------------------------------------------------------------------
# THE DEFECT
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# CONTROLS — what must NOT move
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# The audit gate must not name a cause the evidence does not support
# ---------------------------------------------------------------------------
def test_the_audit_names_a_stop_as_a_stop_not_as_an_incapable_input(tmp_path):
    p = tmp_path / "stalled"
    _write_lvs(p, "BLOCKED", finding="LVS_EXTRACTION_STALLED",
               stopped_as="STALLED",
               supervision={"watched": "output+log+cpu",
                            "since_last_progress_s": 1803.4})
    r = ERA._check_lvs(p)
    assert r.passed is False
    rules = [f.rule for f in r.findings]
    assert rules == ["LVS_BLOCKED_RUN_STOPPED"], rules
    assert "output+log+cpu" in r.findings[0].message, r.findings[0].message
    assert r.summary.get("blocked_stopped_as") == "STALLED", r.summary


def test_the_original_blocked_cause_keeps_its_own_token(tmp_path):
    """The pre-existing BLOCKED cause — an input that cannot support extraction
    — must keep `LVS_BLOCKED_INPUT_INCAPABLE`.  Splitting a token by widening
    it would silently retire a rule another test already asserts."""
    p = tmp_path / "incapable"
    _write_lvs(p, "BLOCKED", finding="LVS_INPUT_TECH_INCAPABLE",
               tech_file="pdk/x.tech")
    r = ERA._check_lvs(p)
    assert r.passed is False
    assert [f.rule for f in r.findings] == ["LVS_BLOCKED_INPUT_INCAPABLE"]
