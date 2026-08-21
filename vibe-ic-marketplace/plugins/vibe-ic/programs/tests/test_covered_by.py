"""Paired guards for covered_by. Every test states the wrong answer it forbids."""
import json
import sys
from pathlib import Path

#: The module under test lives in `tools/core_agent/`, but this test lives in
#: `programs/tests/` — because `pytest.ini` sets `testpaths = programs/tests`,
#: and a test outside that tree is NEVER COLLECTED. Measured on this PR's own
#: first push: the plugin suite collected 32700 with the test file sitting in
#: `tools/core_agent/`, and 32700 without it. It contributed nothing.
#:
#: `ci_targeted_test_select.py` says the same thing from the other side — it
#: reported both of this PR's paths UNMAPPED, so the targeted gate could not
#: select them either. A test that never runs is exactly the vacuous pass this
#: module exists to refuse, so it would have been the wrong file to ship.
#: Located by WALKING UP for `tools/core_agent`, not by a parent index. A fixed
#: depth is a second place the layout is written down, and it breaks silently
#: the day the plugin moves — the same class of defect as a pytest.ini naming a
#: tree that does not exist (vibe-ic#1308).
def _tool_dir() -> Path:
    for parent in Path(__file__).resolve().parents:
        cand = parent / "tools" / "core_agent"
        if cand.is_dir():
            return cand
    raise AssertionError(
        "tools/core_agent is not above this test; the module under test cannot "
        "be located, and a skipped import here would silently stop measuring")


sys.path.insert(0, str(_tool_dir()))

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


# ── enumeration, parsed offline ───────────────────────────────────────────
def test_pr_files_are_parsed_into_a_candidate_index():
    payload = ('[{"number": 1077, "files": [{"path": "a/test_d7.py"}]},'
               ' {"number": 1264, "files": [{"path": "b/other.py"}]}]')
    got = C.parse_pr_files(payload)
    assert got == {1077: ["a/test_d7.py"], 1264: ["b/other.py"]}
    assert C.candidates(got, "test_d7.py") == [1077]


def test_a_broken_enumeration_yields_no_candidates_rather_than_a_crash():
    """gh returning an error sentence must not read as 'no PR touches this'."""
    for bad in ("", "gh: API rate limit exceeded", '{"message": "Not Found"}'):
        assert C.parse_pr_files(bad) == {}


def test_an_empty_enumeration_decides_UNKNOWN_not_UNCOVERED():
    """The join of the two guards: no candidates is never 'the work is yours'."""
    assert C.decide(C.parse_pr_files("")) [0] == 2


def test_a_pr_row_without_files_is_unresolved_not_an_empty_diff():
    """`files: []` is the sub-query answering nothing — no real PR changes zero
    files. Recording it as an empty diff excludes the PR from every candidate
    set on the strength of a list that was never populated."""
    got = C.parse_pr_files('[{"number": 7, "files": []}]')
    assert got == {7: None}, "`files: []` must not be recorded as an empty diff"
    assert C.candidates(got, "test_x.py") == [7], (
        "a PR whose diff could not be read must be MEASURED, not dropped from "
        "the denominator")


def test_a_missing_files_key_is_unresolved_too():
    got = C.parse_pr_files('[{"number": 7}]')
    assert got == {7: None} and C.candidates(got, "test_x.py") == [7]


def test_the_unresolved_sentinel_is_absence_not_an_empty_claim():
    assert getattr(C, "UNRESOLVED", "missing") is None


# ── the truncated page: gh's `files(first: 100)` ──────────────────────────
def _payload(n: int, paths):
    return json.dumps([{"number": n,
                        "files": [{"path": p} for p in paths]}])


#: The measured shape of vibe-ic#1028 (2026-08-18): `gh pr view 1028 --json
#: files` hands back exactly 100 paths, all `README.md` or under
#: `benchmark-data/`, while `repos/.../pulls/1028/files` pages past 3000. Not
#: one path under `programs/` is visible, so the PR that the #1278 thread names
#: as touching `test_matrix_d3_outputs_produced.py` could never be selected for
#: it — or for any other test in this repository.
#: Spelled as a literal, not as `C.GH_FILES_PAGE`, so that these guards fail as
#: ASSERTIONS naming the wrong answer when the fix is reverted, rather than as a
#: collection error that says only "the module is different".
_GH_PAGE = 100
_1028_AS_GH_SHOWS_IT = ["README.md"] + [
    f"benchmark-data/evaluation/phase1_parity/arm_aix/r{i:03d}.json"
    for i in range(_GH_PAGE - 1)]


def test_the_page_cap_the_guards_assume_is_the_one_the_module_uses():
    assert getattr(C, "GH_FILES_PAGE", None) == _GH_PAGE


def test_a_page_capped_file_list_is_never_read_as_a_complete_diff():
    """The whole defect: 100 entries is indistinguishable from page 1 of many,
    so the parser must refuse to conclude the test file is absent from it."""
    assert len(_1028_AS_GH_SHOWS_IT) == _GH_PAGE
    got = C.parse_pr_files(_payload(1028, _1028_AS_GH_SHOWS_IT))
    assert got == {1028: None}, "a page-capped list must not be kept as a diff"
    assert C.candidates(
        got, "programs/tests/test_matrix_d3_outputs_produced.py") == [1028], (
        "#1028's gh file list is 100 paths of benchmark-data; concluding from "
        "it that #1028 misses the d3 test is reading a truncation as a diff")


def test_a_file_list_under_the_page_cap_is_believed_and_still_excludes():
    """The other direction. The fix must not make EVERY PR a candidate — a
    short list is a complete list, and a complete list that misses the file is
    real evidence that the PR does not touch it."""
    short = _1028_AS_GH_SHOWS_IT[:_GH_PAGE - 1]
    got = C.parse_pr_files(_payload(1028, short))
    assert got == {1028: short}, "a sub-page list must be kept verbatim"
    assert C.candidates(
        got, "programs/tests/test_matrix_d3_outputs_produced.py") == []


def test_a_believed_list_still_selects_on_a_real_hit():
    got = C.parse_pr_files(_payload(1077, ["a/b/test_d7.py", "c/other.py"]))
    assert C.candidates(got, "test_d7.py") == [1077]


def test_unresolved_pRs_are_named_rather_than_folded_in_silently():
    got = C.parse_pr_files(json.dumps([
        {"number": 7, "files": []},
        {"number": 8, "files": [{"path": "a/b.py"}]},
    ]))
    assert getattr(C, "unresolved", lambda _: "no such helper")(got) == [7], (
        "the report must be able to say WHICH candidates are there only because "
        "their diff could not be read")


# ── a bound that fired is not a measurement ───────────────────────────────
def test_a_subprocess_bound_overrun_is_a_refusal_not_an_exception(monkeypatch):
    """An escaping `TimeoutExpired` aborts main with Python's exit code 1 —
    which is this module's code for UNCOVERED, 'the work is yours'."""
    def boom(*a, **k):
        raise C.subprocess.TimeoutExpired(cmd="pytest", timeout=1800)
    monkeypatch.setattr(C.subprocess, "run", boom)
    out, rc = C._run(["pytest"])
    assert rc != 0 and out == ""
    assert C.classify_run(out, rc) == C.UNMEASURED, (
        "a run killed by its own bound printed no summary; it must be "
        "UNMEASURED, never a measured verdict")


def test_a_partial_enumeration_that_gh_reported_as_FAILED_is_not_believed(
        monkeypatch):
    """gh can print a parseable but incomplete list and still exit non-zero (the
    504/CANCEL family this query draws). Parsing it anyway turns a broken
    enumeration into a short, confident board."""
    partial = '[{"number": 7, "files": [{"path": "a.py"}]}]'
    monkeypatch.setattr(C, "_run", lambda *a, **k: (partial, 1))
    assert C.open_pr_files("owner/name") == {}, (
        "a non-zero gh is a BLOCKED enumeration, not a board with one PR on it")
    assert C.decide(C.open_pr_files("owner/name"))[0] == 2
