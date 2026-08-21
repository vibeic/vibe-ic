"""test_landing_collateral_revert_check.py — proofs for the collateral-revert guard.

THE NEGATIVE CONTROL IS THE POINT
=================================
`test_bad_land_fires` and `test_good_land_is_clean` build the SAME tree, from
the SAME branch, with the SAME author, onto the SAME parent. They differ in
exactly ONE thing: the LANDING METHOD.

    bad :  git checkout <branch> -- F && git commit    (file taken wholesale)
    good:  git diff <merge-base>..<branch> | git apply (the branch's own delta)

A test that passed in both directions would prove nothing about this guard. This
pair cannot.

THE THRESHOLDS ARE PINNED, NOT DECORATIVE
=========================================
A first draft of this guard was measured with three suppression stages
(in-hunk-replacement pairing, a minimum erased-line count, and a minimum erased
FRACTION), and a verification suite that discriminated on stage 1 alone. A
degenerate build with the later stages disabled — pair nothing, fire at one line,
require no fraction — passed that whole suite while costing 14 false positives
per 300 landings. Every stage below therefore has a test that FAILS if that stage
is removed:

    in-hunk pairing   -> test_in_place_edit_is_not_a_revert
    --min-frac        -> test_partial_deletion_is_not_a_revert
    --min-reverted    -> test_single_line_removal_is_not_a_revert
    absent-from-file  -> test_moved_lines_are_not_a_revert

`test_degenerate_thresholds_are_rejected_by_this_suite` asserts the property
directly: run the checker with the degenerate parameters and at least one
must-not-fire fixture DOES fire.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve()
_PLUGIN_ROOT = _HERE.parents[2]
_PROGRAMS = _PLUGIN_ROOT / "programs"
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import landing_collateral_revert_check as guard  # noqa: E402

_CHECKER = _PROGRAMS / "landing_collateral_revert_check.py"

# A file whose lines are long enough to be substantive and distinct enough not
# to pair with each other — the shape of real source, not of boilerplate.
BASE_LINES = [f"original_configuration_entry_{i} = compute_default({i})"
              for i in range(12)]
MAIN_ADDED = [f"landed_on_main_gate_{i} = register_gate('gate_number_{i}')"
              for i in range(20)]
BRANCH_ADDED = ["branch_side_addition = register_gate('branch_only_gate')"]


def _git(repo: Path, *args):
    return subprocess.run(["git", "-C", str(repo), *args],
                          capture_output=True, text=True, check=True)


def _run(args):
    p = subprocess.run([sys.executable, str(_CHECKER), *args],
                       capture_output=True, text=True)
    return p.returncode, p.stdout, p.stderr


def _write(repo: Path, name: str, lines):
    (repo / name).write_text("\n".join(lines) + "\n")


def _scenario(tmp_path: Path) -> Path:
    """base B -> branch adds a line (NO deletions) -> main advances by 20 lines.

    This is the incident in miniature: a branch cut at B, and work landed on the
    base after the fork. Neither commit deletes anything.
    """
    r = tmp_path / "r"
    r.mkdir()
    _git(r, "init", "-q", "-b", "main")
    _git(r, "config", "user.email", "t@t")
    _git(r, "config", "user.name", "t")
    _write(r, "F.py", BASE_LINES)
    _git(r, "add", "."); _git(r, "commit", "-qm", "base")

    # The branch adds at the TOP, main appends at the BOTTOM: two disjoint
    # regions, so the branch's own delta applies to the advanced main WITHOUT a
    # conflict. That is deliberate — it isolates the variable under test. If the
    # good land needed conflict resolution, a failure could be blamed on the
    # resolution rather than on the landing method, and the negative control
    # would no longer be a control.
    _git(r, "branch", "pr")
    _git(r, "checkout", "-q", "pr")
    _write(r, "F.py", BRANCH_ADDED + BASE_LINES)
    _git(r, "add", "."); _git(r, "commit", "-qm", "pr: one addition, no deletion")

    _git(r, "checkout", "-q", "main")
    _write(r, "F.py", BASE_LINES + MAIN_ADDED)
    _git(r, "add", "."); _git(r, "commit", "-qm", "main: land 20 gates")
    return r


def _range(r: Path) -> str:
    """The push range: everything after the very first commit."""
    root = _git(r, "rev-list", "--max-parents=0", "HEAD").stdout.split()[0]
    return f"{root}..HEAD"


# ── the negative control: identical trees, one differing landing method ──────

def _land_bad(r: Path):
    """`git checkout <branch> -- F` — the method the guard exists to catch."""
    _git(r, "checkout", "-q", "main")
    _git(r, "checkout", "pr", "--", "F.py")
    _git(r, "add", "F.py"); _git(r, "commit", "-qm", "land pr (blind checkout)")


def _land_good(r: Path):
    """The branch's OWN delta — what the remedy text prescribes."""
    _git(r, "checkout", "-q", "main")
    mb = _git(r, "merge-base", "main", "pr").stdout.strip()
    diff = _git(r, "diff", mb, "pr", "--", "F.py").stdout
    # --3way: main has advanced, so the delta needs a real merge rather than a
    # positional patch. This is precisely what a correct land does and what the
    # blind checkout above skips.
    p = subprocess.run(["git", "-C", str(r), "apply", "--3way", "-"],
                       input=diff, text=True, capture_output=True)
    assert p.returncode == 0, p.stderr
    _git(r, "add", "F.py"); _git(r, "commit", "-qm", "land pr (own delta)")


def test_bad_land_fires(tmp_path):
    r = _scenario(tmp_path)
    _land_bad(r)
    rc, out, err = _run(["--repo", str(r), "--rev-range", _range(r)])
    assert rc == 1, f"blind-checkout land must FAIL\n{out}\n{err}"
    assert "COLLATERAL REVERT" in err


def test_good_land_is_clean(tmp_path):
    """Same tree content intent, same parent, same author — only the method
    differs. If this also failed, the guard would be measuring something other
    than the landing method."""
    r = _scenario(tmp_path)
    _land_good(r)
    rc, out, err = _run(["--repo", str(r), "--rev-range", _range(r)])
    assert rc == 0, f"delta-apply land must PASS\n{out}\n{err}"
    # and it really did land the branch's work
    assert BRANCH_ADDED[0] in (r / "F.py").read_text()
    # and it really did keep main's work
    assert MAIN_ADDED[0] in (r / "F.py").read_text()


def test_bad_land_names_the_file_and_the_victim(tmp_path):
    r = _scenario(tmp_path)
    _land_bad(r)
    rc, _out, err = _run(["--repo", str(r), "--rev-range", _range(r)])
    assert rc == 1
    assert "F.py" in err
    victim = _git(r, "log", "--format=%H", "-1", "--skip=1", "main").stdout.strip()
    assert victim[:9] in err, f"the erased commit must be named\n{err}"


# ── the repair control: re-adding the lost work is not itself a revert ───────

def test_repair_commit_is_clean(tmp_path):
    r = _scenario(tmp_path)
    _land_bad(r)
    _write(r, "F.py", BRANCH_ADDED + BASE_LINES + MAIN_ADDED)
    _git(r, "add", "F.py"); _git(r, "commit", "-qm", "reconcile: restore both")
    rc, out, err = _run(["--repo", str(r), "--rev-range", "HEAD~1..HEAD"])
    assert rc == 0, f"a repair must not itself be a finding\n{out}\n{err}"


# ── the deliberate-deletion control ─────────────────────────────────────────

def test_deliberate_deletion_outside_the_range_is_clean(tmp_path):
    """Removing work that landed in an EARLIER push is out of scope by design —
    the window is this push. The guard must not invent a finding there."""
    r = _scenario(tmp_path)
    _land_good(r)
    published = _git(r, "rev-parse", "HEAD").stdout.strip()
    _write(r, "F.py", BRANCH_ADDED + BASE_LINES)      # drop all 20 of main's
    _git(r, "add", "F.py"); _git(r, "commit", "-qm", "remove the 20 gates on purpose")
    rc, out, err = _run(["--repo", str(r), "--rev-range", f"{published}..HEAD"])
    assert rc == 0, f"out-of-range deletion must not fire\n{out}\n{err}"


# ── the stage-pinning tests: each kills one degenerate build ─────────────────

def test_in_place_edit_is_not_a_revert(tmp_path):
    """PINS --similarity. Rewriting an earlier in-range commit's lines in place
    deletes them, but adds their replacement in the SAME hunk. With pairing
    disabled (similarity > 1) this fires — which is the degenerate build."""
    r = _scenario(tmp_path)
    _land_good(r)
    edited = [ln.replace("register_gate(", "register_gate_v2(") for ln in MAIN_ADDED]
    _write(r, "F.py", BRANCH_ADDED + BASE_LINES + edited)
    _git(r, "add", "F.py"); _git(r, "commit", "-qm", "rename the registrar")
    rc, out, err = _run(["--repo", str(r), "--rev-range", _range(r)])
    assert rc == 0, f"an in-place edit is not a revert\n{out}\n{err}"

    rc2, _o, _e = _run(["--repo", str(r), "--rev-range", _range(r),
                        "--similarity", "1.01"])
    assert rc2 == 1, ("with in-hunk pairing disabled this fixture MUST fire — "
                      "otherwise the test does not pin --similarity")


def test_partial_deletion_is_not_a_revert(tmp_path):
    """PINS --min-frac. Removing 2 of 20 lines is an edit, not an erasure."""
    r = _scenario(tmp_path)
    _land_good(r)
    _write(r, "F.py", BRANCH_ADDED + BASE_LINES + MAIN_ADDED[2:])
    _git(r, "add", "F.py"); _git(r, "commit", "-qm", "drop two gates")
    rc, out, err = _run(["--repo", str(r), "--rev-range", _range(r)])
    assert rc == 0, f"2/20 removed is not an erasure\n{out}\n{err}"

    rc2, _o, _e = _run(["--repo", str(r), "--rev-range", _range(r),
                        "--min-frac", "0.0"])
    assert rc2 == 1, ("with --min-frac 0 this fixture MUST fire — otherwise the "
                      "test does not pin the fraction stage")


def test_single_line_removal_is_not_a_revert(tmp_path):
    """PINS --min-reverted."""
    r = _scenario(tmp_path)
    _git(r, "checkout", "-q", "main")
    _write(r, "F.py", BASE_LINES + ["solo_added_line = register_gate('solo_gate')"])
    _git(r, "add", "F.py"); _git(r, "commit", "-qm", "add one gate")
    _write(r, "F.py", BASE_LINES)
    _git(r, "add", "F.py"); _git(r, "commit", "-qm", "drop it again")
    rng = _range(r)
    rc, out, err = _run(["--repo", str(r), "--rev-range", rng])
    assert rc == 0, f"one line is below the floor\n{out}\n{err}"

    rc2, _o, _e = _run(["--repo", str(r), "--rev-range", rng, "--min-reverted", "1"])
    assert rc2 == 1, ("with --min-reverted 1 this fixture MUST fire — otherwise "
                      "the test does not pin the count stage")


def test_moved_lines_are_not_a_revert(tmp_path):
    """PINS the absent-from-file clause. Lines relocated within the file are
    still in the file; a rule reading only the diff would call this an erasure."""
    r = _scenario(tmp_path)
    _land_good(r)
    _write(r, "F.py", BRANCH_ADDED + MAIN_ADDED + BASE_LINES)   # moved to top
    _git(r, "add", "F.py"); _git(r, "commit", "-qm", "reorder the file")
    rc, out, err = _run(["--repo", str(r), "--rev-range", _range(r)])
    assert rc == 0, f"a move is not a removal\n{out}\n{err}"


def test_declared_revert_restoring_the_previous_state_is_clean(tmp_path):
    """PINS the exact-rewind clause. A commit that restores the file to the
    state it had before the earlier commit is a REVERT — the change is that
    commit's exact inverse and a reader can verify it against a commit that
    exists. A stale-branch land cannot do this: it leaves the file holding the
    branch's own additions AND missing the intervening work, a composite state
    the file has never had."""
    r = _scenario(tmp_path)
    before = _git(r, "rev-parse", "HEAD~1:F.py").stdout.strip()
    _write(r, "F.py", BASE_LINES)                      # exactly undo main's 20
    _git(r, "add", "F.py"); _git(r, "commit", "-qm", "revert: the 20 gates were a mistake")
    assert _git(r, "rev-parse", "HEAD:F.py").stdout.strip() == before, \
        "fixture must be an exact rewind"
    rc, out, err = _run(["--repo", str(r), "--rev-range", _range(r)])
    assert rc == 0, f"a declared, exact revert is not collateral\n{out}\n{err}"


def test_non_rewind_erasure_still_fires(tmp_path):
    """The other side of the clause: erase the same lines but ALSO leave content
    of your own, so the file lands in a state it never had. That is the stale-
    branch signature and it must still FAIL. Without this test the rewind clause
    could be widened into a blanket excuse for any deletion."""
    r = _scenario(tmp_path)
    before = _git(r, "rev-parse", "HEAD~1:F.py").stdout.strip()
    _write(r, "F.py", BASE_LINES + ["stale_branch_own_addition = register_gate('x')"])
    _git(r, "add", "F.py"); _git(r, "commit", "-qm", "land a stale branch wholesale")
    assert _git(r, "rev-parse", "HEAD:F.py").stdout.strip() != before
    rc, out, err = _run(["--repo", str(r), "--rev-range", _range(r)])
    assert rc == 1, f"a composite state that never existed must FAIL\n{out}\n{err}"


def test_degenerate_thresholds_are_rejected_by_this_suite(tmp_path):
    """The property SERIOUS-4 asks for, asserted directly: the degenerate build
    (pair nothing, fire at one line, require no fraction) must NOT survive this
    suite."""
    r = _scenario(tmp_path)
    _land_good(r)
    _write(r, "F.py", BRANCH_ADDED + BASE_LINES + MAIN_ADDED[2:])
    _git(r, "add", "F.py"); _git(r, "commit", "-qm", "drop two gates")
    degenerate = ["--similarity", "1.01", "--min-reverted", "1", "--min-frac", "0.0"]
    rc, _o, _e = _run(["--repo", str(r), "--rev-range", _range(r)] + degenerate)
    assert rc == 1, ("a build with every suppression stage disabled must be "
                     "distinguishable from the real one by this suite")


# ── the date-independence proof (the reason this is range-scoped) ────────────

def test_fires_when_author_date_equals_committer_date(tmp_path):
    """The first draft of this guard keyed on `committer_time(r) > author_time(C)`
    — "work the author cannot have seen". A land that stamps a fresh author date
    empties that window by construction, and 171 of the last 300 commits on
    `main` have author time == committer time. The range-scoped rule must not
    care."""
    r = _scenario(tmp_path)
    _git(r, "checkout", "-q", "main")
    _git(r, "checkout", "pr", "--", "F.py")
    _git(r, "add", "F.py")
    stamp = "2030-01-01T00:00:00"
    subprocess.run(["git", "-C", str(r), "commit", "-qm", "land, at==ct"],
                   env={**__import__("os").environ,
                        "GIT_AUTHOR_DATE": stamp, "GIT_COMMITTER_DATE": stamp},
                   check=True, capture_output=True)
    at = _git(r, "log", "-1", "--format=%at").stdout.strip()
    ct = _git(r, "log", "-1", "--format=%ct").stdout.strip()
    assert at == ct, "fixture must reproduce the at==ct shape"
    rc, out, err = _run(["--repo", str(r), "--rev-range", _range(r)])
    assert rc == 1, f"a fresh author date must not blind this guard\n{out}\n{err}"


# ── scope honesty: a clean result must carry its own scope ──────────────────

def test_single_commit_range_reports_zero_pairs(tmp_path):
    r = _scenario(tmp_path)
    _land_good(r)
    rc, out, _err = _run(["--repo", str(r), "--rev-range", "HEAD~1..HEAD"])
    assert rc == 0
    assert "0 in-range predecessor pair(s)" in out
    assert "ABSENCE of a question" in out, \
        "a range with nothing to compare must not read as a pass"


def test_empty_range_is_rc2_not_a_pass(tmp_path):
    r = _scenario(tmp_path)
    _land_good(r)
    rc, _out, err = _run(["--repo", str(r), "--rev-range", "HEAD..HEAD"])
    assert rc == 2, "a clean result over an empty range is not a clean result"
    assert "selects no commit" in err


def test_unresolvable_range_fails_loud(tmp_path):
    r = _scenario(tmp_path)
    rc, _out, err = _run(["--repo", str(r), "--rev-range", "nope..alsonope"])
    assert rc == 2
    assert "error:" in err


def test_revlist_only_range_form_is_resolved(tmp_path):
    """vibe-ic#640: `pre-push` builds a new branch's range as
    `<sha> --not --remotes`. Handed to a command expecting one token that is
    exit 128, which is how a gate silently stops gating."""
    r = _scenario(tmp_path)
    _land_bad(r)
    head = _git(r, "rev-parse", "HEAD").stdout.strip()
    rc, _out, err = _run(["--repo", str(r), "--rev-range",
                          f"{head} --not --remotes"])
    assert rc == 1, f"the rev-list-only range form must resolve\n{err}"


# ── real-artefact backing: the four named commits of the incident ────────────

_GROUND_TRUTH_FIRE = ["c5ee7c780", "5d771d420", "dd74a8a34"]
_GROUND_TRUTH_CLEAN = ["28093c14a"]
_INCIDENT_RANGE = "e5effb125..5d771d420"


def _repo_root() -> Path:
    # .../<repo>/vibe-ic-marketplace/plugins/vibe-ic -> <repo>
    return _PLUGIN_ROOT.parents[2]


def _has(sha: str) -> bool:
    p = subprocess.run(["git", "-C", str(_repo_root()), "cat-file", "-e",
                        f"{sha}^{{commit}}"], capture_output=True)
    return p.returncode == 0


_NEED = _GROUND_TRUTH_FIRE + _GROUND_TRUTH_CLEAN + ["e5effb125"]
_missing = [s for s in _NEED if not _has(s)]
_reason = ("needs the 2026-08-03 incident commits in this clone "
           f"(missing: {', '.join(_missing)}); a shallow clone will not have them")


@pytest.mark.skipif(bool(_missing), reason=_reason)
def test_real_incident_range_fires_on_exactly_the_three():
    """Not a fixture the author typed: the actual push that caused this guard."""
    res = guard.analyze(_repo_root(), _INCIDENT_RANGE)
    assert res.rc == 1
    fired = {f.commit[:9] for f in res.findings}
    assert fired == set(_GROUND_TRUTH_FIRE), fired
    files = {f.path for f in res.findings}
    assert "tools/ci/repo_hygiene_gates.sh" in files
    assert any(p.endswith("phase3_one_shot_runner.py") for p in files)


@pytest.mark.skipif(bool(_missing), reason=_reason)
def test_real_repair_commit_does_not_fire():
    """28093c14a is the commit that REBUILT the two reverted files. A guard that
    flagged the repair would be unusable."""
    res = guard.analyze(_repo_root(), "28093c14a~1..28093c14a")
    assert res.rc == 0, [f.path for f in res.findings]


@pytest.mark.skipif(bool(_missing), reason=_reason)
def test_real_incident_range_from_a_subdirectory_still_fires():
    """A pathspec is resolved relative to the working directory; `git diff
    --name-status` prints repo-relative paths. Run from a subdirectory, an
    earlier build of this checker matched no file and reported the incident
    range itself as `CLEAN, 0 pairs examined`."""
    res = guard.analyze(_PLUGIN_ROOT, _INCIDENT_RANGE)
    assert res.rc == 1, "the repo root must be resolved, not assumed"
    assert {f.commit[:9] for f in res.findings} == set(_GROUND_TRUTH_FIRE)


@pytest.mark.skipif(bool(_missing), reason=_reason)
def test_real_correct_lands_do_not_fire():
    """02f1aa8bb (PR#665) and c1e87413f (PR#674) landed correctly in the SAME
    push. They must be clean as their own single-commit ranges — the guard must
    separate the two good lands from the three bad ones inside one batch."""
    for sha in ("02f1aa8bb", "c1e87413f"):
        if not _has(sha):
            pytest.skip(f"{sha} absent")
        res = guard.analyze(_repo_root(), f"{sha}~1..{sha}")
        assert res.rc == 0, (sha, [f.path for f in res.findings])
