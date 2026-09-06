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
import postroute_timing_repair_decision as D  # noqa: E402
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


def _decide(project):
    # single_corner_clean=True and no stance ⇒ NO timing reason to repair, so
    # `repair_needed` can only be moved by the non-timing tiers.  Without this
    # the assertion below would pass for the wrong reason.
    return D.decide({}, True, project=project)


# ---------------------------------------------------------------------------
# THE DEFECT
# ---------------------------------------------------------------------------
def test_a_stopped_lvs_withholds_the_no_repair_certification(tmp_path):
    for word in ("BLOCKED", "INCOMPLETE", "STALLED"):
        p = tmp_path / word
        _write_lvs(p, word, finding="LVS_EXTRACTION_STALLED",
                   stopped_as="STALLED")
        out = _decide(p)
        assert out["repair_needed"] is True, (word, out)
        # It is NOT filed as a failure — that would assert a mismatch.
        assert out["nontiming_failures"] == [], (word, out)
        nd = out["nontiming_not_determined"]
        assert [r["domain"] for r in nd] == ["lvs_verdict"], (word, out)
        assert "stopped_as=STALLED" in nd[0]["signal"], nd
        assert "never completed" in out["reason"], out["reason"]
        assert "NOTHING is known" in out["reason"], out["reason"]


# ---------------------------------------------------------------------------
# CONTROLS — what must NOT move
# ---------------------------------------------------------------------------
def test_a_clean_lvs_still_certifies(tmp_path):
    p = tmp_path / "clean"
    _write_lvs(p, "PASS", finding="LVS_MATCH")
    out = _decide(p)
    assert out["repair_needed"] is False, out
    # `.get` on purpose: this is a CONTROL and must be readable on BOTH arms.
    # Indexing a key the pre-fix tree does not have would turn it red for a
    # reason that is not the defect, which is how a control stops controlling.
    assert out.get("nontiming_not_determined", []) == [], out


def test_a_real_lvs_failure_is_still_a_FAILURE_not_a_not_determined(tmp_path):
    p = tmp_path / "mismatch"
    _write_lvs(p, "FAIL", finding="LVS_MISMATCH")
    out = _decide(p)
    assert out["repair_needed"] is True, out
    assert [r["domain"] for r in out["nontiming_failures"]] == ["lvs_verdict"]
    assert out.get("nontiming_not_determined", []) == [], out


def test_an_absent_record_still_scores_nothing(tmp_path):
    """Silence is not failure — this module's own rule, unchanged.  Reading an
    absent artefact as a stop would deadlock Step 32 on every run that has not
    reached LVS yet."""
    p = tmp_path / "empty"
    (p / "reports" / "phase3").mkdir(parents=True)
    out = _decide(p)
    assert out["repair_needed"] is False, out
    assert out["nontiming_failures"] == [] and \
        out.get("nontiming_not_determined", []) == [], out


def test_an_unparseable_record_still_scores_nothing(tmp_path):
    p = tmp_path / "junk"
    d = p / "reports" / "phase3"
    d.mkdir(parents=True)
    (d / "lvs_verdict.json").write_text("{not json")
    out = _decide(p)
    assert out["repair_needed"] is False, out
    assert out.get("nontiming_not_determined", []) == [], out


def test_env_unavailable_is_deliberately_left_alone(tmp_path):
    """ENV_UNAVAILABLE is an established waiver tier, and moving it changes the
    verdict of every run on a host that simply lacks a tool.  Left for an owner
    ruling, and PINNED here so the decision is visible rather than forgotten."""
    p = tmp_path / "env"
    _write_lvs(p, "ENV_UNAVAILABLE", finding="LVS_NO_CELL_GDS")
    out = _decide(p)
    assert out["repair_needed"] is False, out
    assert out.get("nontiming_not_determined", []) == [], out


def test_the_two_tiers_are_disjoint_over_the_whole_vocabulary(tmp_path):
    """MEMBERSHIP, not counts.  No word may score in BOTH tiers — a word that
    did would make `nontiming_failures` and `nontiming_not_determined`
    two names for one list, and the distinction this fix exists to draw
    would be decorative."""
    for word in LVS_STATUS_VOCABULARY + ("STALLED",):
        both = (D._hard_failure_signal({"status": word}) is not None
                and D._not_determined_signal({"status": word}) is not None)
        assert not both, word


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
