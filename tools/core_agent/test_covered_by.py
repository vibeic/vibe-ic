"""Paired guards for covered_by. Every test states the wrong answer it forbids."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import covered_by as C  # noqa: E402

# ── the false zero ────────────────────────────────────────────────────────
#: A real pytest tail. Its summary line is what makes the run believable.
_WITH_SUMMARY = "..F\nFAILED programs/tests/test_x.py::test_y\n1 failed, 4 passed in 2.10s\n"
_GREEN = "....\n5 passed in 1.30s\n"
#: A session killed mid-run: a traceback and NO summary line. Grepping this for
#: `FAILED` yields zero, which reads exactly like "nothing failed" (vibe-ic#1277).
_KILLED = ('  File "/usr/lib/python3.10/subprocess.py", line 2021, in _communicate\n'
           "    ready = selector.select(timeout)\n"
           "+++++++++++++++++++++ Timeout +++++++++++++++++++++\n")


def test_a_run_with_no_summary_line_is_unmeasured_not_green():
    """The 188.61s session-kill. Reading this as PASSED is the whole bug."""
    assert C.classify_run(_KILLED, 0) == C.UNMEASURED
    assert C.classify_run(_KILLED, 1) == C.UNMEASURED


def test_a_believable_run_is_classified_by_its_summary():
    assert C.classify_run(_GREEN, 0) == C.PASSED
    assert C.classify_run(_WITH_SUMMARY, 1) == C.FAILED


def test_no_tests_ran_is_a_failure_not_a_pass():
    """`no tests ran` exits 5 and matched nothing — it must never read as clear."""
    assert C.classify_run("no tests ran in 0.01s\n", 5) == C.FAILED


# ── the decision ──────────────────────────────────────────────────────────
def test_one_covering_branch_stops_a_second_author():
    code, cov, unk = C.decide({1077: C.PASSED, 1159: C.FAILED})
    assert (code, cov, unk) == (0, [1077], [])


def test_unmeasured_is_never_folded_into_uncovered():
    """The load-bearing refusal: 'we could not look' is not 'nobody has it'."""
    code, cov, unk = C.decide({1159: C.FAILED, 1274: C.UNMEASURED})
    assert code == 2, "an unmeasured candidate must not be reported as UNCOVERED"
    assert unk == [1274]


def test_uncovered_only_when_every_candidate_was_measured_and_failed():
    code, cov, unk = C.decide({1159: C.FAILED, 1274: C.FAILED})
    assert (code, cov) == (1, [])


def test_no_candidates_at_all_is_unknown_not_uncovered():
    """Zero candidates means the FILTER found nothing, which is not evidence."""
    assert C.decide({})[0] == 2


def test_covered_wins_over_unmeasured():
    code, cov, unk = C.decide({1077: C.PASSED, 1274: C.UNMEASURED})
    assert code == 0 and cov == [1077] and unk == [1274]


# ── candidate selection ───────────────────────────────────────────────────
def test_candidates_are_chosen_by_file_not_by_prose():
    """#1077's title never named the test; its DIFF is what makes it a candidate."""
    files = {
        1077: ["vibe-ic-marketplace/plugins/vibe-ic/programs/tests/test_d7.py"],
        1264: ["vibe-ic-marketplace/plugins/vibe-ic/programs/tests/test_other.py"],
    }
    assert C.candidates(files, "programs/tests/test_d7.py") == [1077]


def test_a_pr_that_only_mentions_the_test_in_prose_is_not_a_candidate():
    files = {1264: ["docs/NOTES.md"]}
    assert C.candidates(files, "programs/tests/test_d7.py") == []


# ── the report says which, not just how many ──────────────────────────────
def test_the_report_names_the_covering_branches():
    msg = C.report(0, [1077], [], "test_x::test_y")
    assert "#1077" in msg and "Do NOT author a second fix" in msg


def test_the_unknown_report_refuses_to_sound_like_uncovered():
    msg = C.report(2, [], [1274], "test_x::test_y")
    assert "NOT 'uncovered'" in msg and "#1274" in msg


# ── end to end, with IO injected ──────────────────────────────────────────
def test_measure_marks_a_failed_checkout_unmeasured_rather_than_clear():
    got = C.measure([1], "n", checkout=lambda n: None)
    assert got == {1: C.UNMEASURED}


def test_measure_classifies_each_branch_from_its_own_run():
    runs = {"wt1077": (_GREEN, 0), "wt1159": (_WITH_SUMMARY, 1)}
    got = C.measure([1077, 1159], "node",
                    checkout=lambda n: f"wt{n}",
                    runner=lambda wt, node: runs[wt])
    assert got == {1077: C.PASSED, 1159: C.FAILED}
