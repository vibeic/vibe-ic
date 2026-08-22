"""vibe-ic#1424 — a test tree can be wired into every runner a human uses and
still be invisible to the gate that decides a landing.

WHAT IS GUARDED
===============
The landing gate's pytest run is selector-driven and the selector is rooted at
`programs/tests` alone, so 109 tracked files / 827 pytest nodes across
`skills/*/tests`, `mcp-eda`, `tools/phase1_engine/tests` and `_shared` could
never block a landing. This file pins the property that closes it:

    every tracked test file in the repo is either RUN by a named stage of
    tools/gatekeeper-land.sh, or DECLARED out with a stated reason.

and, just as importantly, that the property cannot be bought cheaply:

  * `test_the_new_stage_is_actually_wired` is the NEGATIVE CONTROL. It reads
    `gatekeeper-land.sh` and fails against the pre-fix file, where the stage
    does not exist. A census program nothing invokes proves nothing.
  * `test_a_covered_tree_whose_stage_vanished_is_a_finding` drives the audit on
    a gate script with `run_repo_tools_pytest` removed. The complement must NOT
    quietly grow a hole where a deleted stage used to be.
  * `test_an_exclusion_that_matches_nothing_is_a_finding` is the roster-rot
    control: a declared exclusion that stops describing the tree is exactly the
    recorded-register defect, and it shrinks the corpus in the direction that
    still prints PASS.
  * `test_an_undeclared_new_tree_lands_in_the_complement` proves the set is a
    COMPLEMENT and not a roster — a tree nobody has heard of is in it.

Nothing here greps for a function name and calls it wiring: every assertion
either runs the program or reads the gate script's own dispatch.
"""
from __future__ import annotations

import importlib.util
import re
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent
_PLUGIN = _PROGRAMS.parent
_REPO = _PLUGIN.parent.parent.parent
_PROG = _PROGRAMS / "landing_unselectable_pytest_corpus.py"
_LAND = _REPO / "tools" / "gatekeeper-land.sh"

# The stage this issue adds. Named once; every assertion below reads it.
_STAGE = "run_unselectable_pytest"

# Every inner subprocess in this file is bounded well under the harness's own
# --timeout=180 / 3 ceiling (programs/ci_harness_timeout_ceiling_check.py), so
# a hang here fails ONE test instead of taking the session down unnamed.
_BOUND = 60


def _mod():
    name = "landing_unselectable_pytest_corpus_under_test"
    spec = importlib.util.spec_from_file_location(name, _PROG)
    assert spec and spec.loader
    m = importlib.util.module_from_spec(spec)
    # REGISTERED BEFORE exec. The module declares `from __future__ import
    # annotations`, so `@dataclass` resolves its field types by name through
    # `sys.modules[cls.__module__]` — absent that entry it raises at import,
    # which reads as a broken test rather than a broken subject.
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


@pytest.fixture(scope="module")
def mod():
    return _mod()


@pytest.fixture(scope="module")
def land_text() -> str:
    assert _LAND.is_file(), f"{_LAND} is absent — the gate cannot be read"
    return _LAND.read_text(encoding="utf-8", errors="replace")


def _run(args, cwd=None):
    return subprocess.run([sys.executable, str(_PROG), *args],
                          capture_output=True, text=True,
                          timeout=_BOUND, cwd=str(cwd) if cwd else None)


# ── the property ────────────────────────────────────────────────────────────

def test_the_new_stage_is_actually_wired(land_text):
    """NEGATIVE CONTROL — fails against the pre-fix gate script.

    A corpus program that no stage invokes is a census, not coverage. Three
    things must all hold, because any one alone is satisfiable without the
    other two: the function is DEFINED, it is CALLED at top level, and it
    invokes THIS program.
    """
    assert f"{_STAGE}()" in land_text, (
        f"{_STAGE} is not defined in tools/gatekeeper-land.sh — the "
        f"unselectable trees are still unreachable by a landing (#1424)")
    # CALLED -- not called IN A PARTICULAR SHAPE. This used to anchor on
    # the name at the start of a line, optionally behind `if`. The full tier's
    # independent stages now run at the same time, so the stage is called from
    # inside the lane body the window launches
    # (`fn_capture "full:unselectable-tests" run_unselectable_pytest`) and the
    # column-zero anchor matched nothing at all -- a rule that cannot fail is
    # not a weaker version of the one it replaced, it is an absent one.
    #
    # That the call is REACHED from the top level is not dropped, it is owned
    # once, by `ci_harness_timeout_ceiling_check`'s execution-prefix digest; a
    # second copy of that rule here is the drift shape this repo keeps
    # deleting. What is asserted here is what this file is about: exactly one
    # call site exists outside the definition.
    _lines = land_text.splitlines()
    _define = next(i for i, line in enumerate(_lines)
                   if line.startswith(f"{_STAGE}() {{"))
    _close = next(i for i in range(_define + 1, len(_lines))
                  if _lines[i] == "}")
    _callers = [i + 1 for i, line in enumerate(_lines)
                if not (_define <= i <= _close)
                and not line.lstrip().startswith("#")
                and re.search(rf"(?<![\w./-]){_STAGE}(?![\w(])", line)]
    assert len(_callers) == 1, (
        f"{_STAGE} is defined but is called {len(_callers)} times outside its "
        f"definition; a stage that does not run cannot block anything, and a "
        f"stage that runs twice is two lanes where the landing record expects "
        f"one")
    assert _PROG.name in land_text, (
        f"{_STAGE} does not invoke {_PROG.name}; whatever corpus it runs is "
        f"not the one this issue measures")


def test_every_tracked_test_file_is_run_or_declared(mod):
    """The whole of #1424, executed.

    The complement is what the new stage runs, so this asserts the partition
    is TOTAL and that its three parts do not overlap — the arithmetic that
    makes "nothing is invisible" a fact rather than a hope.
    """
    files = mod.tracked_test_files(_REPO)
    assert files is not None, "git ls-files did not answer — NOT a zero"
    part = mod.partition(files, mod.plugin_rel(_REPO))
    covered = sum(len(v) for v in part["covered"].values())
    excluded = sum(len(v) for v in part["excluded"].values())
    unselectable = len(part["unselectable"])
    assert covered + excluded + unselectable == part["total"] == len(files), (
        "the partition is not total — some tracked test file is in no bucket, "
        "which is precisely the state #1424 reports")
    assert unselectable > 0, (
        "the complement is empty; if that is genuinely true the trees should "
        "be DECLARED covered, not silently absent")


@pytest.mark.parametrize("tree", [
    "skills", "mcp-eda", "tools/phase1_engine/tests", "_shared",
])
def test_the_four_trees_named_by_the_issue_are_in_the_corpus(mod, tree):
    """Every tracked test file of each named tree, not merely one of them.

    Asserted against the TREE rather than a count: a hardcoded 67/31/8/3 is the
    roster defect one level up, and it would go stale the next time a skill is
    added.
    """
    files = mod.tracked_test_files(_REPO)
    assert files is not None
    part = mod.partition(files, mod.plugin_rel(_REPO))
    prefix = f"{mod.plugin_rel(_REPO)}/{tree}/"
    expected = {f for f in files if f.startswith(prefix)}
    assert expected, f"{prefix} has no tracked test files — the premise moved"
    missing = expected - set(part["unselectable"])
    assert not missing, (
        f"{len(missing)} file(s) under {prefix} are not in the corpus the "
        f"landing stage runs: {sorted(missing)[:3]}")


def test_the_selector_still_cannot_emit_anything_in_the_corpus(mod):
    """The premise, re-measured instead of quoted.

    If `ci_targeted_test_select.py` ever grew the ability to emit these paths,
    this stage would be running them twice and the issue would be stale. Read
    the selector's own filter rather than running it, so the assertion does not
    depend on which base a checkout happens to have.
    """
    sel = (_PROGRAMS / "ci_targeted_test_select.py").read_text(
        encoding="utf-8", errors="replace")
    assert '_TESTS_REL = "programs/tests"' in sel, (
        "the selector's root moved — re-measure #1424 before trusting this "
        "stage's corpus, it may now overlap the targeted run")


def test_the_stage_bound_matches_the_other_pytest_stages(land_text):
    """One harness bound, not two.

    `ci_harness_timeout_ceiling_check` derives every test's inner-subprocess
    ceiling from the harness bound. A stage that bounded its pytest differently
    would make that ceiling ambiguous, and the looser lane is the one that takes
    the session down instead of one test.
    """
    # The bound moved with 7c376e348 (v1.10.69): the stages no longer hand
    # pytest a `--timeout=`, they drive it through `pytest_per_file_junit.py`,
    # whose bound is the DRIVER STALL WINDOW. The property is unchanged — one
    # bound shared by every pytest stage, never a looser lane for this one — so
    # it is asserted on the bound the script actually declares today.
    bounds = set(re.findall(r"--stall-after (\S+)", land_text))
    agg = set(re.findall(r"--aggregate-stall-after (\S+)", land_text))
    assert not re.search(r"--timeout=\d+", land_text), (
        "gatekeeper-land.sh reintroduced a second, per-stage pytest bound "
        "alongside the driver stall window")
    assert len(bounds) == 1 and len(agg) == 1, (
        f"gatekeeper-land.sh now carries more than one pytest bound: "
        f"stall={bounds} aggregate={agg}")


def test_the_stage_writes_no_bytecode_into_the_shipped_skills_tree(land_text):
    """The one hazard this stage adds that NO existing guard can catch.

    67 of the 109 files are `skills/*/tests/` and they import shipped
    `skills/**/programs/*.py`; the import writes `.pyc` into the SHIPPED tree.
    Measured on a fresh worktree, digesting `skills/` by relative path + size:

        clean                       214 files   0 .pyc   b7a2de20…
        stage without the token     283 files  69 .pyc   f6ad615c…
        stage with the token        214 files   0 .pyc   b7a2de20…

    `.pyc` is gitignored, so `git status`, `git add -A`, `gitignore_scratch_guard
    --include-worktree` and the stage's own `suite_write_guard` bracket ALL
    report clean with the 69 present. This assertion is therefore the only thing
    standing between this stage and
    `test_tools_and_integration.py::test_shipped_skills_tree_is_untouched_by_this_session`
    — whose own message predicts exactly this writer, and which fails the whole
    landing (`gatekeeper-land.sh:213`) the moment the two share a session.
    """
    body = land_text.split(f"{_STAGE}() {{", 1)
    assert len(body) == 2, f"{_STAGE} not found"
    body = body[1].split("\n}\n", 1)[0]
    # 7c376e348 (v1.10.69) routed the stage's pytest through
    # `pytest_per_file_junit.py` instead of a bare `python3 -m pytest`, and the
    # command is written across continued lines — so the token and the pytest it
    # guards are no longer on ONE line. Join the continuations first, then assert
    # the same property on the whole command.
    joined = re.sub(r"\\\n\s*", " ", body)
    invocations = [ln for ln in joined.splitlines()
                   if "python3 -m pytest" in ln or "pytest_per_file_junit.py" in ln]
    assert invocations, f"{_STAGE} runs no pytest at all"
    for ln in invocations:
        assert "PYTHONDONTWRITEBYTECODE=1" in ln, (
            "the stage's pytest may write .pyc into the shipped skills/ tree, "
            "and nothing else in the landing sequence can see it: " + ln.strip())


def test_the_stage_label_carries_no_discovery_count(land_text):
    """#1431 — a gate label that varies with the tree renames its own gate.

    `gatekeeper-verify-merge.sh` subtracts the two arms' gate logs BY LABEL, so
    a count in the label turns "this branch added a test file" into "this branch
    silenced a gate". This corpus grows with every new tree, which is exactly
    that branch shape, so the count is printed on its own line.
    """
    body = land_text.split(f"{_STAGE}() {{", 1)
    assert len(body) == 2, f"{_STAGE} not found"
    body = body[1].split("\n}\n", 1)[0]
    verdicts = [ln for ln in body.splitlines()
                if re.search(r"\b(PASS|FAIL)\b\s+unselectable", ln)]
    assert verdicts, "the stage prints no PASS/FAIL line"
    for ln in verdicts:
        assert "${#files[@]}" not in ln and "%s file" not in ln, (
            f"the stage's verdict label carries a discovery count: {ln.strip()}")


# ── the controls: the property must still be refusable ──────────────────────

def test_a_covered_tree_whose_stage_vanished_is_a_finding(mod, tmp_path):
    """Deleting a stage must not silently move its tree OUT of the complement.

    Without this, removing `run_repo_tools_pytest` would leave `tools/` claimed
    as covered by a stage that no longer exists — 29 files that neither run.
    """
    fake = tmp_path / "repo"
    (fake / "tools").mkdir(parents=True)
    (fake / ".git").mkdir()
    text = _LAND.read_text(encoding="utf-8", errors="replace")
    (fake / "tools" / "gatekeeper-land.sh").write_text(
        text.replace("run_repo_tools_pytest", "run_something_else"),
        encoding="utf-8")
    files = mod.tracked_test_files(_REPO)
    assert files is not None
    part = mod.partition(files, mod.plugin_rel(_REPO))
    findings = mod.audit(fake, part, mod.plugin_rel(_REPO))
    assert any("run_repo_tools_pytest" in f for f in findings), (
        f"a vanished stage produced no finding: {findings}")
    # And the control on the control: the UNMODIFIED gate script is clean, so
    # the finding above is the deletion and not the fixture.
    assert not [f for f in mod.audit(_REPO, part, mod.plugin_rel(_REPO))
                if "run_repo_tools_pytest" in f]


def test_an_exclusion_that_matches_nothing_is_a_finding(mod, monkeypatch):
    """Roster rot, in the one place this program keeps a roster.

    THIS USED TO ASSERT ON `benchmark-data/` BY NAME, and that coupling broke it.
    The roster held exactly that one entry; when the corpus moved to
    vibeic/benchmark-data the entry was withdrawn, the roster became `()`, and this
    test had nothing left to iterate — it failed not because the mechanism regressed
    but because the example it was written against was gone.

    A guard over a REGISTRY must not depend on any particular member of it. So the
    entry is now synthetic and injected: the mechanism is what is under test, and it
    stays under test whether the shipped roster holds one entry, ten, or none.
    """
    stale = mod.Excluded(
        prefix="a-tree-that-is-not-in-this-repository/",
        why="a synthetic entry, long enough to satisfy any written-reason rule, "
            "existing only so this test measures the staleness MECHANISM rather "
            "than the presence of one particular roster member.")
    monkeypatch.setattr(mod, "_EXCLUDED", (stale,))
    files = mod.tracked_test_files(_REPO) or []
    assert files, "partitioned an empty file list; this is not a measurement"
    part = mod.partition(files, mod.plugin_rel(_REPO))
    findings = mod.audit(_REPO, part, mod.plugin_rel(_REPO))
    assert any("a-tree-that-is-not-in-this-repository/" in f
               and "NO tracked test file" in f for f in findings), (
        f"an exclusion describing nothing raised no finding: {findings}")


def test_an_undeclared_new_tree_lands_in_the_complement(mod):
    """COMPLEMENT, not roster — the whole reason this needs no maintenance."""
    plugin = mod.plugin_rel(_REPO)
    invented = "a_tree_nobody_has_declared/tests/test_it.py"
    part = mod.partition([invented, f"{plugin}/programs/tests/test_a.py"], plugin)
    assert part["unselectable"] == [invented], (
        "a tree nobody declared did not reach the corpus, so the set is "
        "behaving as a roster")
    assert part["covered"][f"{plugin}/programs/tests/"] == [
        f"{plugin}/programs/tests/test_a.py"], (
        "a selector-reachable file leaked into the corpus — it would be run "
        "twice on every landing")


def test_a_refusal_to_measure_is_rc2_and_not_an_empty_list(tmp_path):
    """"I could not look" must never reach the gate as "there was nothing"."""
    out = _run(["--repo", str(tmp_path)])
    assert out.returncode == 2, (
        f"a non-repository answered rc={out.returncode} with stdout "
        f"{out.stdout!r} — an empty list would be read as a clean corpus")
    assert out.stdout.strip() == "", "rc=2 must emit no corpus at all"
    assert "NOT DETERMINED" in out.stderr


def test_audit_is_clean_on_this_tree():
    """The shipped state: rc=0, and the census printed so it can be read."""
    out = _run(["--repo", str(_REPO), "--audit"])
    assert out.returncode == 0, out.stdout + out.stderr
    assert "UNSELECTABLE" in out.stdout


def test_the_list_is_exactly_what_the_census_counts():
    """The gate consumes `--list`; it must not disagree with `--audit`."""
    listed = _run(["--repo", str(_REPO)]).stdout.split()
    census = _run(["--repo", str(_REPO), "--census"]).stdout
    m = re.search(r"UNSELECTABLE\s+(\d+)", census)
    assert m, census
    assert len(listed) == int(m.group(1)) > 0
    assert len(set(listed)) == len(listed), "the corpus lists a file twice"
