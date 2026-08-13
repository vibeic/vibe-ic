#!/usr/bin/env python3
"""Tests for checker_execution_wiring_audit (vibe-ic#381).

Bidirectional by construction: every case that must FIRE is paired with the
same tree made clean, because either assertion alone proves nothing.

Two of these pin bugs this program actually had while it was being written,
and both were the SAME shape — a matcher whose own assumption produced a
confident false accusation:

  * `".git" in path` also swallows `.github/`, emptying the CI haystack, so
    every CI-wired checker was reported as unwired.
  * matching only the QUOTED stem missed the flow definition, which writes
    gate names bare, so 12 wired gates were reported as wired nowhere.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / "checker_execution_wiring_audit.py"
sys.path.insert(0, str(PROG.parent))
import checker_execution_wiring_audit as M  # noqa: E402


def _tree(root: Path, *, ci="", flow="", skill="", prog="", test="", index=""):
    """Build a minimal repo whose only checker is `sample_check.py`."""
    plugin = root / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
    for d in ("programs/tests", "flow", "skills", "agents", "commands", "tests"):
        (plugin / d).mkdir(parents=True, exist_ok=True)
    (root / ".github" / "workflows").mkdir(parents=True, exist_ok=True)
    (root / "tools").mkdir(parents=True, exist_ok=True)
    (plugin / "programs" / "sample_check.py").write_text("def main():\n    return 0\n")
    (root / ".github" / "workflows" / "ci.yml").write_text(ci or "name: CI\n")
    (plugin / "flow" / "flow.yaml").write_text(flow or "steps: []\n")
    (plugin / "skills" / "s.md").write_text(skill or "# skill\n")
    (plugin / "programs" / "other.py").write_text(prog or "x = 1\n")
    (plugin / "programs" / "tests" / "test_sample.py").write_text(test or "pass\n")
    (plugin / "programs" / "INDEX.md").write_text(index or "# index\n")
    return plugin


def _run(root: Path):
    return M.audit(root / "vibe-ic-marketplace" / "plugins" / "vibe-ic", root)


def test_test_only_checker_is_a_finding(tmp_path):
    """Only its own unit test runs it -> zero coverage of real inputs."""
    _tree(tmp_path, test="import sample_check\n")
    rep = _run(tmp_path)
    assert "sample_check.py" in rep["test_only"]
    assert rep["no_runner_at_all"] == []


def test_same_checker_wired_into_ci_is_clean(tmp_path):
    """The paired half: add a real runner and the finding must disappear."""
    _tree(tmp_path,
          test="import sample_check\n",
          ci="name: CI\njobs:\n  a:\n    steps:\n"
             "      - run: python3 programs/sample_check.py\n")
    rep = _run(tmp_path)
    assert rep["test_only"] == []
    assert rep["no_runner_at_all"] == []


def test_dot_github_is_not_eaten_by_the_dot_git_exclusion(tmp_path):
    """REGRESSION: `".git" in path` also matches `.github/`.

    With a substring exclusion the CI haystack is EMPTY, so a CI-wired
    checker is reported as unwired — a confident finding manufactured by
    the scanner's own filter. Assert the haystack is populated, not merely
    that the verdict is clean, so the reason stays pinned.
    """
    _tree(tmp_path, ci="run: python3 sample_check.py\n")
    hay = M._haystacks(tmp_path / "vibe-ic-marketplace/plugins/vibe-ic", tmp_path)
    assert hay["CI"], "the .github haystack must not be excluded as '.git'"


def test_bare_unquoted_flow_reference_counts(tmp_path):
    """REGRESSION: the flow definition writes gate names BARE.

    A matcher that only accepts the quoted stem or the `.py` filename
    reports wired gates as wired nowhere.
    """
    _tree(tmp_path, test="import sample_check\n",
          flow="steps:\n  - gate: sample_check\n")
    assert _run(tmp_path)["test_only"] == []


def test_catalogue_listing_is_not_a_runner(tmp_path):
    """INDEX.md NAMES checkers and runs none.

    Counting a catalogue would let a checker be 'wired' by being listed —
    the exact paper-only wiring this gate exists to find.
    """
    _tree(tmp_path, test="import sample_check\n",
          index="- sample_check.py — does a thing\n")
    assert "sample_check.py" in _run(tmp_path)["test_only"]


def test_substring_neighbour_does_not_count_as_a_reference(tmp_path):
    """`sample_check_extra` must not satisfy `sample_check`."""
    _tree(tmp_path, test="import sample_check\n",
          ci="run: python3 sample_check_extra.py\n")
    assert "sample_check.py" in _run(tmp_path)["test_only"]


def test_prose_inside_a_program_is_not_a_runner(tmp_path):
    """REGRESSION: a docstring / comment NAMES a checker, it never runs one.

    Adding a docstring to the audit itself that named a recorded checker
    while explaining why it is hard to wire made that entry look wired and
    silently removed it from a register that may only shrink for a real
    reason. Measured over the repo, prose accounted for 20+ entries wrongly
    counted as wired.
    """
    _tree(tmp_path, test="import sample_check\n",
          prog='"""Docs mention sample_check here."""\n'
               "# and a comment: sample_check\n"
               "y = 2\n")
    assert "sample_check.py" in _run(tmp_path)["test_only"]


def test_a_string_literal_invocation_still_counts(tmp_path):
    """The paired half: only BARE-EXPRESSION strings are dropped.

    `subprocess.run([..., "foo_check.py"])` is a real invocation and must
    survive prose-stripping, otherwise the fix trades a false PASS for a
    false accusation.
    """
    _tree(tmp_path, test="import sample_check\n",
          prog='import subprocess\n'
               'subprocess.run(["python3", "sample_check.py"])\n')
    assert _run(tmp_path)["test_only"] == []


def test_yaml_comment_is_not_a_runner(tmp_path):
    """A commented-out gate entry is a gate that does not run."""
    _tree(tmp_path, test="import sample_check\n",
          flow="steps:\n  # - gate: sample_check\n")
    assert "sample_check.py" in _run(tmp_path)["test_only"]


def test_growth_needs_a_reason_and_records_the_previous_size(tmp_path):
    """A wider scope finding pre-existing debt is not a regression — but it
    must be recorded, not assumed, and a one-word excuse is not a reason."""
    _tree(tmp_path)
    bl = tmp_path / "bl.json"
    bl.write_text(json.dumps({"known": []}) + "\n")
    common = [sys.executable, str(PROG), "--repo-root", str(tmp_path),
              "--baseline", str(bl), "--write-baseline"]
    short = subprocess.run(common + ["--scope-expanded", "because"],
                           capture_output=True, text=True)
    assert short.returncode == 1
    assert "needs a real reason" in short.stdout
    ok = subprocess.run(common + [
        "--scope-expanded",
        "comments and docstrings no longer count as runners, so prose-only "
        "references are now correctly reported"], capture_output=True, text=True)
    assert ok.returncode == 0, ok.stdout
    d = json.loads(bl.read_text())
    assert d["known"] == ["sample_check.py"]
    assert d["previous_size"] == 0
    assert "prose-only" in (d["scope_expanded"] or "")


def test_refresh_triage_measures_by_running(tmp_path):
    """Triage must be REGENERABLE, not a one-off someone typed in."""
    _tree(tmp_path)
    (tmp_path / "vibe-ic-marketplace/plugins/vibe-ic/programs/sample_check.py"
     ).write_text("import sys\nprint('needs an input')\nsys.exit(2)\n")
    bl = tmp_path / "bl.json"
    r = subprocess.run(
        [sys.executable, str(PROG), "--repo-root", str(tmp_path),
         "--baseline", str(bl), "--write-baseline", "--refresh-triage"],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stdout
    tri = json.loads(bl.read_text())["triage"]["sample_check.py"]
    assert tri.startswith("rc=2"), tri
    assert "needs an input" in tri


def test_checker_referenced_by_nothing_is_reported_separately(tmp_path):
    _tree(tmp_path)
    rep = _run(tmp_path)
    assert rep["no_runner_at_all"] == ["sample_check.py"]
    assert rep["test_only"] == []


def test_baseline_refuses_to_grow(tmp_path):
    """A checker LOSING its only real runner is a regression, not a fact."""
    _tree(tmp_path)
    bl = tmp_path / "bl.json"
    bl.write_text(json.dumps({"known": []}) + "\n")
    rc = subprocess.run(
        [sys.executable, str(PROG), "--repo-root", str(tmp_path),
         "--baseline", str(bl), "--write-baseline"],
        capture_output=True, text=True)
    assert rc.returncode == 1, rc.stdout
    assert "refusing to GROW" in rc.stdout


def test_baseline_shrink_is_accepted_and_triage_survives(tmp_path):
    """The paired half of the growth refusal, plus: triage is not discarded.

    A register of bare names invites the worst repair — deleting the test so
    the entry disappears — so what was found when an entry was investigated
    has to survive a rewrite.
    """
    _tree(tmp_path, ci="run: python3 sample_check.py\n")
    bl = tmp_path / "bl.json"
    bl.write_text(json.dumps(
        {"known": ["sample_check.py", "gone_check.py"],
         "triage": {"sample_check.py": "why", "gone_check.py": "stale"}}) + "\n")
    rc = subprocess.run(
        [sys.executable, str(PROG), "--repo-root", str(tmp_path),
         "--baseline", str(bl), "--write-baseline"],
        capture_output=True, text=True)
    assert rc.returncode == 0, rc.stdout
    d = json.loads(bl.read_text())
    assert d["known"] == []
    assert d["triage"] == {}


def test_resolved_entry_forces_the_baseline_to_shrink(tmp_path):
    """A recorded entry that gained a runner must FAIL until it is removed,
    so the register can never quietly become permission."""
    _tree(tmp_path, ci="run: python3 sample_check.py\n")
    bl = tmp_path / "bl.json"
    bl.write_text(json.dumps({"known": ["sample_check.py"]}) + "\n")
    rc = subprocess.run(
        [sys.executable, str(PROG), "--repo-root", str(tmp_path),
         "--baseline", str(bl)], capture_output=True, text=True)
    assert rc.returncode == 1, rc.stdout
    assert "now HAVE a real runner" in rc.stdout


def test_real_repo_runs_and_is_deterministic():
    """End-to-end on this repo: two runs must agree."""
    root = PROG.parents[4]
    if not (root / "vibe-ic-marketplace").is_dir():
        pytest.skip("not in the repo layout")
    a = M.audit(PROG.parents[1], root)
    b = M.audit(PROG.parents[1], root)
    assert a == b
    assert a["checkers"] > 100
    # And the answer must be a real measurement, not the all-empty-haystack
    # degenerate one below. See the `.claude/worktrees` regression.
    assert len(a["no_runner_at_all"]) < a["checkers"]


def test_a_checkout_living_under_dot_claude_worktrees_is_not_all_skipped(tmp_path):
    """REGRESSION: the skip set matched the CHECKOUT'S OWN ancestors.

    `_SKIP_PARTS` exists to skip a nested `.claude/worktrees/` copy INSIDE
    the repo. Matched against the ABSOLUTE parts it also matches the repo's
    ancestors, so a checkout at `.../.claude/worktrees/<name>/` has every
    haystack file skipped and the audit reports `no runner at all` for every
    checker in the tree. Measured on a real agent worktree: 494 of 494 — the
    same false-accusation-from-the-matcher's-own-assumption shape as the two
    bugs already pinned above, and it turns this gate into pure noise on the
    checkout shape agents actually run in.

    Paired against the identical tree at a plain path: the two must agree.
    """
    plain = tmp_path / "plain"
    plain.mkdir()
    _tree(plain, ci="run: python3 sample_check.py\n")
    nested = tmp_path / ".claude" / "worktrees" / "agent-1"
    nested.mkdir(parents=True)
    _tree(nested, ci="run: python3 sample_check.py\n")

    a = _run(plain)
    b = _run(nested)
    assert b["no_runner_at_all"] == [], (
        "the checkout's own ancestors must not empty every haystack")
    assert a["test_only"] == b["test_only"]
    assert a["no_runner_at_all"] == b["no_runner_at_all"]


def test_a_nested_worktree_copy_inside_the_repo_is_still_skipped(tmp_path):
    """The paired half — the exclusion must still do its actual job.

    A vendored copy under `.claude/worktrees/` INSIDE the checkout is not a
    runner, and counting it would let a checker look wired by its own stale
    duplicate.
    """
    _tree(tmp_path, ci="name: CI\n")
    stale = tmp_path / ".claude" / "worktrees" / "old" / "tools"
    stale.mkdir(parents=True)
    (stale / "runner.sh").write_text("python3 sample_check.py\n")
    hay = M._haystacks(tmp_path / "vibe-ic-marketplace/plugins/vibe-ic", tmp_path)
    assert not any("worktrees" in p for p in hay["TOOLS"])
    assert _run(tmp_path)["no_runner_at_all"] == ["sample_check.py"]


# ── the JSON verdict must be the verdict the process exits with ──────────────
#
# Every test above drives `M.audit()`, which BUILDS the report — and the report
# is stamped `passed: True` at construction. Nothing here drove `main()`, and
# nothing asserted the field at all, so a hardcoded constant survived: on a run
# that printed `[FAIL]` and exited 1, the `--json` file still said
# `"passed": true`.
#
# Measured 2026-08-13 against vibe-ic#1241's wiring rows. One invocation over
# PR #1151 exited 1 with `[FAIL] bundled_attribution_notice_check.py` while its
# JSON reported `passed: true`; a reader keying on the field called that row
# ANSWERED, which was the wrong verdict on the only unanswered row of six.
#
# The invariant is asserted in BOTH directions on purpose. A one-sided test
# ("a failing run says false") is satisfied by hardcoding the field to False,
# which would break every passing run instead.

def _main_with_json(tmp_path, root):
    """`(rc, parsed_json)` from a real `main()` invocation on `root`."""
    out = tmp_path / "audit.json"
    base = tmp_path / "baseline.json"          # never the repo's own baseline
    base.write_text(json.dumps({"known": [], "unwired_by_decision": {}}) + "\n")
    rc = M.main(["--repo-root", str(root), "--json", str(out),
                 "--baseline", str(base)])
    assert out.is_file(), "main() wrote no --json output"
    return rc, json.loads(out.read_text())


def test_json_passed_is_false_when_the_run_fails(tmp_path):
    """A FAILING run must not report `passed: true` to a machine reader."""
    _tree(tmp_path, test="import sample_check\n")     # only its own test runs it
    rc, rep = _main_with_json(tmp_path, tmp_path)
    assert rc != 0, "precondition: a test-only checker must make main() fail"
    assert rep["passed"] is False, (
        "the run exited nonzero and printed [FAIL], but its JSON says "
        f"passed={rep['passed']!r} — a consumer reading the report sees a "
        "clean run where the gate blocked")


def test_json_passed_is_true_when_the_run_passes(tmp_path):
    """PAIRED: the fix must not simply invert the field."""
    _tree(tmp_path, test="import sample_check\n",
          ci="run: python3 sample_check.py\n")        # a real runner
    rc, rep = _main_with_json(tmp_path, tmp_path)
    assert rc == 0, "precondition: a wired checker must make main() pass"
    assert rep["passed"] is True, rep


@pytest.mark.parametrize("wired", [False, True])
def test_json_passed_always_agrees_with_the_exit_code(tmp_path, wired):
    """The property itself, stated once: the field IS the exit code."""
    _tree(tmp_path, test="import sample_check\n",
          ci="run: python3 sample_check.py\n" if wired else "")
    rc, rep = _main_with_json(tmp_path, tmp_path)
    assert rep["passed"] is (rc == 0), (
        f"exit={rc} but json.passed={rep['passed']!r}; the report and the "
        "process disagree about the same run")
# ---------------------------------------------------------------------------
# The SKILL-only disclosure register must disclose something (vibe-ic#1130).
#
# Measured before this was written: deleting an entry from
# checker_skill_only_reasons.json left the audit at [PASS] exit 0, and setting
# its reason to "" ALSO left it at [PASS] exit 0 while still printing
# "(skill-only, reason recorded)" and counting it in "N carry a written
# reason". Membership was the whole test, so the register could not make a
# disclosure mean anything.
#
# Three-way control, because either arm alone proves nothing:
#   real reason  -> disclosed, not blocking
#   blank claim  -> gestured, BLOCKING
#   no entry     -> neither, not blocking   (pins the policy: silence is
#                   honest and stays non-blocking; 28 checkers rely on it)
# ---------------------------------------------------------------------------
_REAL = ("MEASURED: nothing in the repo produces this checker's input; the "
         "three discriminating schema fields appear in zero files outside its "
         "own unit test, and its CLI takes one positional record with no "
         "corpus loop. Reachable today from the skill that authors the record.")


def test_a_real_reason_is_a_disclosure():
    disclosed, gestured = M.classify_disclosures(["sample_check.py"],
                                                 {"sample_check.py": _REAL})
    assert disclosed == ["sample_check.py"]
    assert gestured == []


@pytest.mark.parametrize("reason", ["", "   ", "\n", "unwired", "see above"])
def test_a_claim_without_a_measurement_is_gestured_not_disclosed(reason):
    """The bug. Each of these used to count as a written reason."""
    disclosed, gestured = M.classify_disclosures(["sample_check.py"],
                                                 {"sample_check.py": reason})
    assert disclosed == []
    assert gestured == ["sample_check.py"], reason


def test_no_entry_at_all_is_neither_and_stays_non_blocking():
    """The paired half that keeps the repair honest.

    Without this, the cheapest way to make the gesture check pass is to make
    ABSENCE blocking too — which would redden the 28 SKILL-only checkers that
    correctly say nothing, and is a different decision from this one.
    """
    disclosed, gestured = M.classify_disclosures(["sample_check.py"], {})
    assert disclosed == []
    assert gestured == []


def test_the_gesture_finding_actually_blocks(tmp_path, monkeypatch, capsys):
    """End to end: a blank claim must reach rc=1, not merely be printed.

    The register path is resolved from the PROGRAM's directory, not from
    --repo-root, so the shipped file is the only one main() can read; the
    register loader is substituted rather than the file, which is what makes
    this testable at all.
    """
    _tree(tmp_path, skill="run programs/sample_check.py\n")
    # THREE shipped registers (skill-only reasons, unwired_by_decision, and
    # the test-only baseline) are read from the PROGRAM's directory
    # regardless of --repo-root, and each describes checkers this tmp tree
    # does not have — any one of them decides rc on its own. All three are
    # substituted so rc answers ONLY the property under test.
    monkeypatch.setattr(M, "_load_decisions", lambda _p: {})
    monkeypatch.setattr(M, "_load_baseline", lambda _p: None)
    monkeypatch.setattr(M, "skill_only_register",
                        lambda _p: {"sample_check.py": ""})
    rc = M.main(["--repo-root", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 1, out
    assert "claim a reason and do not state one" in out, out
    assert "sample_check.py: reason is 0 char(s)" in out, out


def test_the_same_tree_with_a_real_reason_does_not_block(tmp_path, monkeypatch,
                                                          capsys):
    """The paired arm of the test above, on the identical tree."""
    _tree(tmp_path, skill="run programs/sample_check.py\n")
    monkeypatch.setattr(M, "_load_decisions", lambda _p: {})
    monkeypatch.setattr(M, "_load_baseline", lambda _p: None)
    monkeypatch.setattr(M, "skill_only_register",
                        lambda _p: {"sample_check.py": _REAL})
    rc = M.main(["--repo-root", str(tmp_path)])
    out = capsys.readouterr().out
    assert rc == 0, out
    assert "(skill-only, reason recorded) sample_check.py" in out, out


def test_the_gesture_exit_ALSO_agrees_with_the_json(tmp_path, monkeypatch):
    """The exit this branch ADDS must take the `_emit` route, not a bare
    `return 1`.

    vibe-ic#1320 moved the JSON write to the exit specifically so that a
    verdict added afterwards cannot go on reporting `passed: true` while the
    process blocks, and its own text names the hazard: *"any `return 1` added
    below would silently inherit the same lie."* The gesture branch below IS
    the first exit added after that change, so it is exactly that case — and
    it is the arm where the lie would be hardest to spot, because it is the
    newest and fires on the fewest runs.

    Asserting rc alone would not catch it: a bare `return 1` still exits 1.
    Only the JSON distinguishes the two routes.
    """
    root = tmp_path / "repo"
    _tree(root, skill="run programs/sample_check.py\n")
    monkeypatch.setattr(M, "skill_only_register",
                        lambda _p: {"sample_check.py": ""})
    rc, rep = _main_with_json(tmp_path, root)
    assert rc == 1, rep
    assert rep["passed"] is False, (
        "the gesture exit blocked but its JSON still says passed=true — the "
        "new branch bypassed `_emit` and re-introduced vibe-ic#1320")


def test_PAIRED_a_real_reason_leaves_the_json_passing(tmp_path, monkeypatch):
    """The other direction on the identical tree: with a real disclosure the
    gesture branch does not fire, and the JSON must say so rather than being
    hardcoded false."""
    root = tmp_path / "repo"
    _tree(root, skill="run programs/sample_check.py\n")
    monkeypatch.setattr(M, "skill_only_register",
                        lambda _p: {"sample_check.py": _REAL})
    rc, rep = _main_with_json(tmp_path, root)
    assert rc == 0, rep
    assert rep["passed"] is True, rep
