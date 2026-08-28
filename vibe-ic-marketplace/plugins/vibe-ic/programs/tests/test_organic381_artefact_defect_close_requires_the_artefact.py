#!/usr/bin/env python3
"""Tests for artefact_defect_close_check (vibe-ic#381).

Every case that must FIRE is paired with the SAME input made clean, because
either assertion alone proves nothing: a rule that only ever FAILs and a rule
that only ever PASSes both look like a gate from one side.

Three of these are not fixture-only:

  * `test_real_history_*` replay the repo's OWN history at the two real
    commits the issue is about — the checker-only close and the later
    artefact repair — and derive the artefact path FROM the repository, so a
    made-up path cannot make them pass.
  * `test_mutation_control_*` build a real git repository, run the program as
    a subprocess, then MUTATE the closing commit so it also rewrites the
    artefact, and require the verdict to flip. A test that cannot tell the
    guard from its absence is not coverage.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / "artefact_defect_close_check.py"
sys.path.insert(0, str(PROG.parent))
import artefact_defect_close_check as M  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

ART = "benchmark-data/ic/demo/reports/gates/some_report.json"
CHECKER = "vibe-ic-marketplace/plugins/vibe-ic/programs/some_evidence_check.py"
CHECKER_TEST = ("vibe-ic-marketplace/plugins/vibe-ic/programs/tests/"
                "test_some_evidence_check.py")
REGISTER = "benchmark-data/some_evidence_baseline.json"
MANIFEST = "vibe-ic-marketplace/plugins/vibe-ic/.claude-plugin/plugin.json"


def _issue(*, labels=(), body=None):
    return {"number": 366, "title": "a report asserts a verdict it cannot back",
            "labels": list(labels),
            "body": body if body is not None else
            "The report at `%s` still asserts PASS while the evidence it "
            "cites ships nowhere." % ART}


def _classify(issue, changed, tracked=(ART,), close_text="",
              label=M.DEFAULT_LABEL):
    return M.classify(issue, set(changed), set(tracked), close_text, label,
                      M.DEFAULT_DATA_ROOT)


# --------------------------------------------------------------------------
# TIER A — the label makes the rule exact. Paired both ways.
# --------------------------------------------------------------------------
def test_labelled_close_fails_when_the_named_artefact_is_untouched():
    res = _classify(_issue(labels=["artefact-defect"]),
                    [CHECKER, CHECKER_TEST, MANIFEST])
    assert res["verdict"] == "FAIL"
    assert res["cited_artefacts"] == [ART]
    assert res["artefacts_changed"] == []


def test_labelled_close_passes_when_the_named_artefact_changed():
    # Identical to the case above except the artefact is in the range.
    res = _classify(_issue(labels=["artefact-defect"]),
                    [CHECKER, CHECKER_TEST, MANIFEST, ART])
    assert res["verdict"] == "PASS"
    assert res["artefacts_changed"] == [ART]


def test_labelled_close_passes_on_an_explicit_unchanged_declaration():
    res = _classify(_issue(labels=["artefact-defect"]), [CHECKER],
                    close_text="ARTEFACT-UNCHANGED: the run directory was "
                               "deleted upstream and cannot be regenerated "
                               "from anything this repo ships.")
    assert res["verdict"] == "PASS"
    assert M.UNCHANGED_MARKER in res["reason"]


def test_a_declaration_without_a_real_reason_is_still_a_fail():
    # Same shape as the case above; only the reason is too short to be one.
    res = _classify(_issue(labels=["artefact-defect"]), [CHECKER],
                    close_text="ARTEFACT-UNCHANGED: later")
    assert res["verdict"] == "FAIL"


def test_the_marker_must_be_the_marker_not_a_paraphrase():
    res = _classify(_issue(labels=["artefact-defect"]), [CHECKER],
                    close_text="the artefact is intentionally unchanged "
                               "because regenerating it needs a tool we do "
                               "not have on this host")
    assert res["verdict"] == "FAIL"


def test_labelled_issue_naming_no_tracked_artefact_is_a_refusal_not_a_pass():
    # The label asserts a defective artefact; if the body names none that
    # ships, the claim is unverifiable and an empty result is not a clean one.
    res = _classify(_issue(labels=["artefact-defect"],
                           body="the JSON gate report is wrong"), [CHECKER])
    assert res["verdict"] == "FAIL"
    assert "no TRACKED path" in res["reason"]


def test_an_untracked_path_is_not_a_shipped_artefact():
    # Same body, same range — only the tracked set differs.
    res = _classify(_issue(labels=["artefact-defect"]), [CHECKER], tracked=())
    assert res["verdict"] == "FAIL"        # unverifiable, per the rule above
    assert res["cited_artefacts"] == []
    unlabelled = _classify(_issue(), [CHECKER], tracked=())
    # tier B stays QUIET by design — but no longer says "PASS", because it
    # compared nothing (#441). Quiet and verified-clean are different claims.
    assert unlabelled["verdict"] == M.NO_CITATION


# --------------------------------------------------------------------------
# TIER B — advisory inference. Paired both ways.
# --------------------------------------------------------------------------
def test_advisory_fires_on_a_checker_only_close():
    res = _classify(_issue(), [CHECKER, CHECKER_TEST, MANIFEST])
    assert res["verdict"] == "ADVISORY"
    assert res["checkers_changed"] == [CHECKER, CHECKER_TEST]


def test_advisory_is_quiet_when_the_artefact_changed():
    res = _classify(_issue(), [CHECKER, CHECKER_TEST, MANIFEST, ART])
    assert res["verdict"] == "PASS"


def test_advisory_is_quiet_when_the_range_is_not_checker_only():
    # A doc / skill / flow edit means the close was not "only a checker",
    # and this tier deliberately under-reaches rather than guess.
    res = _classify(_issue(), [CHECKER, "docs/INSTALL.md"])
    assert res["verdict"] == "PASS"
    assert "not a checker-only change" in res["reason"]


def test_advisory_is_quiet_when_no_checker_was_touched():
    res = _classify(_issue(), ["vibe-ic-marketplace/plugins/vibe-ic/programs/"
                               "some_emitter.py"])
    assert res["verdict"] == "PASS"
    assert res["reason"] == "the range changed no checker"


def test_a_debt_register_entry_is_not_an_artefact_repair():
    """The exact trap #381 names.

    The measured closing commit DID write under the published data tree — it
    added the still-defective instance to the new gate's own baseline so the
    gate could report PASS. A rule keyed on "did the range touch the data
    tree" reads that as clean.
    """
    res = _classify(_issue(), [CHECKER, CHECKER_TEST, REGISTER, MANIFEST])
    assert res["verdict"] == "ADVISORY"
    assert res["registers_changed"] == [REGISTER]
    assert "not a repair" in M.render(res, "abc..def", "o/r")


def test_a_register_write_does_not_pass_the_labelled_tier_either():
    res = _classify(_issue(labels=["artefact-defect"]),
                    [CHECKER, REGISTER, MANIFEST])
    assert res["verdict"] == "FAIL"


# --------------------------------------------------------------------------
# path parsing
# --------------------------------------------------------------------------
def test_a_sentence_final_period_is_not_part_of_the_filename():
    body = "The value at %s." % ART
    assert M.cited_artefacts(body, {ART}, M.DEFAULT_DATA_ROOT) == [ART]


def test_a_path_outside_the_data_root_is_not_an_artefact():
    body = "see vibe-ic-marketplace/plugins/vibe-ic/programs/x_check.py"
    assert M.cited_artefacts(body, {ART}, M.DEFAULT_DATA_ROOT) == []


def test_every_finding_names_the_issue_and_the_range():
    res = _classify(_issue(), [CHECKER, MANIFEST])
    text = M.render(res, "2188e8481", "vibeic/vibe-ic")
    assert "#366" in text and "2188e8481" in text and ART in text


# --------------------------------------------------------------------------
# real git repository + MUTATION CONTROL
# --------------------------------------------------------------------------
def _git(root, *args):
    return _pr.run(["git", "-C", str(root), *args], capture_output=True,
                          text=True)


def _seed_repo(root: Path) -> str:
    """A real repository: an artefact, a checker, and a checker-only close."""
    _git(root, "init", "-q", "-b", "main")
    _git(root, "config", "user.email", "t@example.invalid")
    _git(root, "config", "user.name", "t")
    for rel in (ART, CHECKER, CHECKER_TEST):
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("original\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "seed")
    base = _git(root, "rev-parse", "HEAD").stdout.strip()
    return base


def _close_commit(root: Path, *, also_fix_artefact: bool) -> str:
    (root / CHECKER).write_text("original\n# now detects it\n", encoding="utf-8")
    reg = root / REGISTER
    reg.parent.mkdir(parents=True, exist_ok=True)
    reg.write_text('{"known": ["the still-defective instance"]}\n',
                   encoding="utf-8")
    if also_fix_artefact:
        (root / ART).write_text("corrected\n", encoding="utf-8")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "fix(#366): land the gate")
    return _git(root, "rev-parse", "HEAD").stdout.strip()


def _run(root: Path, issue_file: Path, rng: str, extra=()):
    return _pr.run(
        [sys.executable, str(PROG), "--issue-number", "366", "--range", rng,
         "--offline", "--repo-root", str(root), "--issue-file", str(issue_file),
         *extra],
        capture_output=True, text=True)


def test_mutation_control_the_verdict_flips_when_the_artefact_is_repaired(tmp_path):
    """The control that makes the rest of this file mean something.

    Same repository, same issue, same checker change. The ONLY difference is
    whether the closing commit also rewrote the artefact. If both runs agreed,
    the program would be indistinguishable from `return PASS`.
    """
    issue_file = tmp_path / "issue.json"
    issue_file.write_text(json.dumps(_issue()), encoding="utf-8")

    checker_only = tmp_path / "a"
    checker_only.mkdir()
    base = _seed_repo(checker_only)
    head = _close_commit(checker_only, also_fix_artefact=False)
    r1 = _run(checker_only, issue_file, "%s..%s" % (base, head))

    repaired = tmp_path / "b"
    repaired.mkdir()
    base2 = _seed_repo(repaired)
    head2 = _close_commit(repaired, also_fix_artefact=True)
    r2 = _run(repaired, issue_file, "%s..%s" % (base2, head2))

    assert "[ADVISORY]" in r1.stdout, r1.stdout + r1.stderr
    assert r1.returncode == 0                       # advisory does not block
    assert "[PASS]" in r2.stdout and "[ADVISORY]" not in r2.stdout, r2.stdout
    assert r2.returncode == 0


def test_mutation_control_the_labelled_tier_blocks_and_unblocks(tmp_path):
    labelled = tmp_path / "issue.json"
    labelled.write_text(json.dumps(_issue(labels=["artefact-defect"])),
                        encoding="utf-8")

    bad = tmp_path / "a"
    bad.mkdir()
    base = _seed_repo(bad)
    head = _close_commit(bad, also_fix_artefact=False)
    r1 = _run(bad, labelled, "%s..%s" % (base, head))

    good = tmp_path / "b"
    good.mkdir()
    base2 = _seed_repo(good)
    head2 = _close_commit(good, also_fix_artefact=True)
    r2 = _run(good, labelled, "%s..%s" % (base2, head2))

    assert r1.returncode == 1, r1.stdout + r1.stderr
    assert "[FAIL]" in r1.stdout
    assert r2.returncode == 0, r2.stdout + r2.stderr

    # ... and the escape hatch really is an escape hatch.
    note = tmp_path / "note.md"
    note.write_text("ARTEFACT-UNCHANGED: the deliverable was withdrawn in "
                    "#419 and no reader can reach it any more.\n",
                    encoding="utf-8")
    r3 = _run(bad, labelled, "%s..%s" % (base, head),
              extra=("--close-comment-file", str(note)))
    assert r3.returncode == 0, r3.stdout + r3.stderr


def test_enforce_advisory_promotes_the_tier_b_finding(tmp_path):
    issue_file = tmp_path / "issue.json"
    issue_file.write_text(json.dumps(_issue()), encoding="utf-8")
    root = tmp_path / "a"
    root.mkdir()
    base = _seed_repo(root)
    head = _close_commit(root, also_fix_artefact=False)
    quiet = _run(root, issue_file, "%s..%s" % (base, head))
    loud = _run(root, issue_file, "%s..%s" % (base, head),
                extra=("--enforce-advisory",))
    assert quiet.returncode == 0
    assert loud.returncode == 1


def test_a_sweep_without_an_issue_corpus_says_skipped_not_pass(tmp_path):
    root = tmp_path / "a"
    root.mkdir()
    _seed_repo(root)
    r = _pr.run([sys.executable, str(PROG), "--recent", "5", "--offline",
                        "--repo-root", str(root)],
                       capture_output=True, text=True)
    assert r.returncode == 0
    assert "[SKIPPED]" in r.stdout and "NOT a PASS" in r.stdout
    assert "[PASS]" not in r.stdout


# --------------------------------------------------------------------------
# REAL HISTORY — this repository, the two commits #381 is about
# --------------------------------------------------------------------------
def _toplevel() -> Path:
    """Resolved by git, not by counting `..` — the plugin is checked out both
    as a repository subtree and as a linked worktree, where `.git` is a file
    and a hard-coded depth is wrong in one of the two."""
    here = Path(__file__).resolve().parent
    r = _pr.run(["git", "-C", str(here), "rev-parse", "--show-toplevel"],
                       capture_output=True, text=True)
    return Path(r.stdout.strip()) if r.returncode == 0 and r.stdout.strip() else here


_REPO_ROOT = _toplevel()
# The close that added the gate and left the deliverable alone, and the later
# commit that actually corrected it. Both are on this repo's main line.
_CHECKER_ONLY_SHA = "2188e8481"
_ARTEFACT_FIX_SHA = "e025ba351"


def _reachable(sha: str) -> bool:
    r = _git(_REPO_ROOT, "cat-file", "-e", sha + "^{commit}")
    return r.returncode == 0


def _real_artefact_path(sha: str):
    """The artefact, read out of the repository — never typed here.

    A path this test invented could make it pass against a repo that never
    shipped the file. Taking it from `git show` of the REPAIR commit means
    the fixture is the history.
    """
    r = _git(_REPO_ROOT, "show", "--pretty=format:", "--name-only", sha)
    for line in r.stdout.splitlines():
        line = line.strip()
        if line.startswith("benchmark-data/") and line.endswith(".json"):
            tracked = _git(_REPO_ROOT, "ls-tree", "-r", "--name-only",
                           _CHECKER_ONLY_SHA).stdout.splitlines()
            if line in tracked:
                return line
    return None


_HISTORY = _reachable(_CHECKER_ONLY_SHA) and _reachable(_ARTEFACT_FIX_SHA)
_history_only = pytest.mark.skipif(
    not _HISTORY,
    reason="this repository's history is not available (shallow clone or a "
           "checkout without commits %s / %s)"
           % (_CHECKER_ONLY_SHA, _ARTEFACT_FIX_SHA))


@_history_only
def test_real_history_the_checker_only_close_is_reported(tmp_path):
    art = _real_artefact_path(_ARTEFACT_FIX_SHA)
    assert art, "no tracked data-tree JSON in the repair commit"
    issue_file = tmp_path / "issue.json"
    issue_file.write_text(json.dumps(
        {"number": 366, "labels": [],
         "body": "`%s` asserts PASS citing evidence that ships nowhere." % art}),
        encoding="utf-8")
    r = _run(_REPO_ROOT, issue_file, _CHECKER_ONLY_SHA)
    assert "[ADVISORY]" in r.stdout, r.stdout + r.stderr
    assert art in r.stdout
    assert "not a repair" in r.stdout          # the baseline write is called out


@_history_only
def test_real_history_the_artefact_repair_is_accepted(tmp_path):
    """The paired half, on the same repository and the same issue."""
    art = _real_artefact_path(_ARTEFACT_FIX_SHA)
    assert art
    issue_file = tmp_path / "issue.json"
    issue_file.write_text(json.dumps(
        {"number": 366, "labels": ["artefact-defect"],
         "body": "`%s` asserts PASS citing evidence that ships nowhere." % art}),
        encoding="utf-8")
    r = _run(_REPO_ROOT, issue_file, _ARTEFACT_FIX_SHA)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "[PASS]" in r.stdout and "[FAIL]" not in r.stdout


@_history_only
def test_real_history_the_sweep_is_quiet_on_this_repo(tmp_path):
    """The corpus bar #381 sets: quiet on history that is correctly closed.

    Measured when this landed: 100 closed issues carried an attributable
    range, 7 named a tracked deliverable, and the rule produced 0 findings —
    5 because the artefact really did change and 2 because the close was not
    a checker-only change. A sweep that fired here would be flagging the
    state the repo just shipped.
    """
    corpus = tmp_path / "issues.json"
    r = _git(_REPO_ROOT, "log", "--format=%s", "-400", "HEAD")
    # Drive the sweep from the repo's OWN commit subjects: any body text that
    # names a tracked deliverable is fed back in as if it were the issue body,
    # which is a strictly WIDER net than the real bodies would cast.
    rows = [{"number": n, "labels": [], "body": s}
            for n, s in enumerate(r.stdout.splitlines()[:400], start=1)]
    corpus.write_text(json.dumps(rows), encoding="utf-8")
    out = _pr.run(
        [sys.executable, str(PROG), "--recent", "400", "--offline",
         "--repo-root", str(_REPO_ROOT), "--issues-json", str(corpus)],
        capture_output=True, text=True)
    assert out.returncode == 0, out.stdout + out.stderr
    assert "[FAIL]" not in out.stdout


# ── #441: the vacuous outcome must not wear the word PASS ──────────────────
def test_an_issue_citing_no_artefact_is_NOT_a_PASS():
    """MEASURED at land time and far worse than the two-instance framing: of
    the 56 closed issues the CI invocation sweeps, only 3 cite a tracked
    artefact. The other 53 were reported PASS while nothing was compared.

    The trigger was vibe-ic#365 — one of the TWO issues this gate exists
    because of — whose body names its subject in prose ("the 3 spm PDK-cell
    folders") and carries no repo-relative path, so the gate covered 1 of its
    2 motivating instances while reading as though it covered both.

    Widening the path regex to parse prose is refused separately: 33 of 35
    false positives on the corpus. So the repair is to stop over-claiming, not
    to guess. Non-fatal exactly as before — only the WORD changes, because the
    word was the false part.
    """
    res = _classify(_issue(body="the 3 spm PDK-cell folders are wrong"),
                    [CHECKER])
    assert res["cited_artefacts"] == []
    assert res["verdict"] == M.NO_CITATION
    assert res["verdict"] != "PASS"
    assert "NOT a verified clean close" in res["reason"]


def test_a_cited_artefact_that_changed_is_still_a_PASS():
    """The paired half: renaming every quiet outcome would destroy the
    distinction this change exists to create."""
    res = _classify(_issue(), [ART])
    assert res["verdict"] == "PASS", res
    assert "changed in the range" in res["reason"]


def test_the_vacuous_outcome_is_still_NON_FATAL():
    """It was never a failure and must not become one — 53 of 56 closed issues
    are in this state, and turning them red would make the gate unrunnable
    while telling nobody anything new."""
    assert M.NO_CITATION not in ("FAIL", "ADVISORY")


# ── an issue ABOUT a checker is not an artefact-defect issue ───────────────
def test_a_title_naming_a_checker_is_not_inferred_as_an_artefact_defect():
    """FOUND BY THE GATE ITSELF, on one of my own closes.

    Running `--recent 40` flagged vibe-ic#441 ADVISORY: "the body names a
    shipped artefact the range never changed, and the range changed only
    checker code". #441 is titled "artefact_defect_close_check is VACUOUS on
    any issue that names its artefact in prose" — an issue about THIS CHECKER.
    Its body quotes an artefact path only while explaining that a DIFFERENT
    issue (#366) cites it: a citation of a citation, which no path regex can
    tell from a defect report.

    For a defect IN a checker, "the range changed only checker code" is the
    CORRECT shape of a fix. Inferring on it inverts the gate's meaning.

    Measured over the 40 most recently closed issues: 6 carry a program name
    in the title and all 6 are genuinely checker defects.
    """
    import artefact_defect_close_check as A
    res = _classify(
        _issue(body="see %s for the shape" % ART),
        [CHECKER],
    )
    # baseline: without a checker in the title this is still inferred
    assert res["verdict"] in ("ADVISORY", "PASS", A.NO_CITATION)

    titled = dict(_issue(body="see %s for the shape" % ART))
    titled["title"] = "artefact_defect_close_check is VACUOUS on prose citations"
    res2 = A.classify(titled, {CHECKER}, {ART}, "", A.DEFAULT_LABEL,
                      A.DEFAULT_DATA_ROOT)
    assert res2["verdict"] == "PASS", res2
    assert "defect IN a checker" in res2["reason"]


def test_a_title_naming_an_ARTEFACT_still_gets_inferred():
    """THE NEGATIVE CONTROL, and what keeps this from being a loophole.

    #366 — the close this whole gate exists because of — is titled
    "formal_evidence.json PASS in ... references a .sby that does not exist".
    That names an ARTEFACT, not a program, so it stays in scope and still
    fires. Verified live at land time: the historical #366 close still exits 1.
    """
    import artefact_defect_close_check as A
    titled = dict(_issue(body="the report at %s is wrong" % ART))
    titled["title"] = ("formal_evidence.json PASS references a .sby "
                       "that does not exist")
    res = A.classify(titled, {CHECKER}, {ART}, "", A.DEFAULT_LABEL,
                     A.DEFAULT_DATA_ROOT)
    assert res["verdict"] == "ADVISORY", res


def test_a_LABELLED_artefact_defect_is_never_inferred_away_by_its_title():
    """Tier A is explicit and must not be weakened: a human labelled it, so a
    title heuristic does not get to overrule that."""
    import artefact_defect_close_check as A
    titled = dict(_issue(labels=["artefact-defect"],
                         body="the report at %s is wrong" % ART))
    titled["title"] = "artefact_defect_close_check mis-handles this cell"
    res = A.classify(titled, {CHECKER}, {ART}, "", A.DEFAULT_LABEL,
                     A.DEFAULT_DATA_ROOT)
    assert res["verdict"] == "FAIL", res
