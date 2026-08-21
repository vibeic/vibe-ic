"""#726/#727 — a DRC count nobody could read is not a clean one."""
from __future__ import annotations

import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))
import eda_report_audit as E                # noqa: E402
import phase3_verify_aggregate as V        # noqa: E402

def _corpus_report() -> Path:
    """The published report, found by walking UP to the repo root.

    Hard-coding a `parents[N]` got this wrong by one and silently SKIPPED the
    only test here that reads real tracked bytes — the load-bearing one. A skip
    that looks like a pass is the shape this whole file is about."""
    for base in PROGRAMS.parents:
        cand = base / "benchmark-data" / "ic" / "subservient" / "reports" / \
            "phase3" / "drc_router.rpt"
        if cand.is_file():
            return cand
    return Path("/nonexistent")


_REAL = _corpus_report()


# ── #726: a truncated report graded CLEAN by its own progress counter ───────

def test_a_truncated_real_report_is_not_graded_clean():
    """No fixture and no injection: a REAL tracked report, 30 lines removed.

    The anchored summary lives at lines 21-22; below it OpenROAD's
    `detailed_route` emits `Completing 10% with 0 violations.`, present in every
    router report in the corpus. Taking the FIRST loose match anywhere turned a
    72-violation design into a clean one."""
    if not _REAL.is_file():
        import pytest
        pytest.skip("published corpus report not present in this checkout")
    text = _REAL.read_text(errors="replace")
    assert E._drc_real_violation_count(text) == (72, 0)
    truncated = "\n".join(text.splitlines()[30:])
    got = E._drc_real_violation_count(truncated)
    assert got != (0, 0), (
        "a truncated report was graded CLEAN by its own progress counter")
    assert got is None, f"unreadable must be None (unmeasurable), got {got}"


def test_progress_lines_alone_never_produce_a_count():
    assert E._drc_real_violation_count(
        "Completing 10% with 0 violations.\n"
        "Completing 90% with 0 violations.\n") is None


def test_the_loose_fallback_takes_the_maximum_not_the_first():
    """Last resort, reached only when no anchored summary parsed. Under-reporting
    grades a dirty design clean; over-reporting only triggers a look."""
    assert E._drc_real_violation_count(
        "saw 3 violations early\nlater 41 violations\n") == (41, 0)


def test_an_anchored_summary_still_wins():
    assert E._drc_real_violation_count(
        "violation count summary: 72 violation(s) found\n"
        "Completing 10% with 0 violations.\n") == (72, 0)


# ── #727: NOT-MEASURED coded as NOT-FAILING, in the source ─────────────────

def test_an_unmeasurable_drc_count_is_its_own_verdict():
    """`parse_drc_count` returns -1 when it cannot determine a count and carries
    no XML dialect at all, so a KLayout RDB — the format every sign-off
    certificate in this corpus uses — is unparseable BY CONSTRUCTION. The source
    said `# treat -1 (unknown) as not-failing here`, and the comment was the
    defect."""
    r = V.aggregate(Path("/tmp/x"), artifacts=[], checks=[],
                    drc_violations=-1, wns=0.1, tns=0.1)
    assert r.verdict == "UNMEASURED", (
        "an unreadable DRC count must not share a verdict with a clean run")


def test_a_real_zero_is_still_a_pass_and_a_real_count_still_fails():
    assert V.aggregate(Path("/tmp/x"), artifacts=[], checks=[],
                       drc_violations=0, wns=0.1, tns=0.1).verdict == "PASS"
    assert V.aggregate(Path("/tmp/x"), artifacts=[], checks=[],
                       drc_violations=7, wns=0.1, tns=0.1).verdict == "FAIL"


def test_a_real_failure_still_outranks_unmeasured():
    """Order matters: a design with a missing artefact AND an unreadable count
    is FAILING, not merely unmeasured."""
    class _A:
        present = False
        def __init__(self): self.name = "gds"
    r = V.aggregate(Path("/tmp/x"), artifacts=[_A()], checks=[],
                    drc_violations=-1, wns=0.1, tns=0.1)
    assert r.verdict == "FAIL"
