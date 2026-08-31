"""The invocation that runs every tree must classify as FULL, and only it.

WHAT THIS PINS
==============
`run_tests.sh` line 4 states, unprompted:

    "THIS SCRIPT IS THE FULL SUITE. Bare `pytest` is NOT: `pytest.ini` declares a
     [single testpath] ... every tree below other than programs/tests/ is
     collected HERE and nowhere else."

`full_suite_run_check` did not merely narrow that. MEASURED on e37d10e1e, the
program contained ZERO occurrences of `run_tests` and reported

    [FAIL] full_suite_run_check: NO pytest invocation found — the suite was
           never run.

for the one command that reaches all five trees. At cadence FULL that is a hard
FAIL, so the agent that ran everything was told it ran nothing, and the cheapest
way for it to clear the red was to run a SUBSET instead. A gate wrong in this
direction does not merely fail to catch the shortcut; it recommends it.

THE ACCEPTANCE IS THE DERIVATION, NOT THE FILENAME
==================================================
This file is the RED test shipped on
`hold/DO-NOT-ASSEMBLE-cadence-gate-red-until-ruled`, rebased onto the ruling and
TIGHTENED. As shipped it asserted `_classify("./run_tests.sh") == 0`, which a
check that greps for the string "run_tests.sh" would satisfy — and such a check
stays green on the day someone edits `run_tests.sh` to quietly drop a tree,
which is the failure the gate is for. So the two load-bearing cases here are

  * `test_a_runner_that_drops_a_tree_is_not_full` — the CHEAT arm. A runner
    that no longer discovers one tree is a SUBSET, and its unmutated twin in
    the same fixture is FULL. Neither verdict is reachable by name.
  * `test_recognition_is_of_the_ANSWER_not_of_the_name` — a runner called
    something else entirely, which covers the population, is FULL; a script
    called `run_tests.sh`, which covers nothing, is NOT.

RULING 2 FALLS OUT OF THE SAME SUBTRACTION
==========================================
The hold-branch version deliberately declined to reopen
`test_only_programs_tests_is_full_since_the_v0219_merge`, because in the
TWO-TREE world that decision was made in (top-level `tests/` versus
`programs/tests`, both collecting 19504) it was correct. The owner-level ruling
of 2026-08-31 settles it the other way for the FIVE-tree world that outran it:
one tree cannot speak for five. It needs no special case — `programs/tests`
leaves 141 of 3117 tracked test files unrun (MEASURED at e37d10e1e: `skills` 82,
`mcp-eda/test` 48, `tools/phase1_engine/tests` 8, `_shared` 3) and the same
subtraction that clears `run_tests.sh` refuses it.
"""
from __future__ import annotations

import importlib.util
import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
_PLUGIN = _PROGRAMS.parent
_PROG = _PROGRAMS / "full_suite_run_check.py"
_spec = importlib.util.spec_from_file_location("full_suite_run_check", _PROG)
fsr = importlib.util.module_from_spec(_spec)
sys.modules["full_suite_run_check"] = fsr
_spec.loader.exec_module(fsr)


def _classify(cmd: str, root: Path = None) -> int:
    """0 == the checker calls `cmd` a full-suite invocation, 1 == a subset,
    2 == it refused to answer. The EXIT CODE, because that is what
    `gatekeeper_review.test_cadence_gate` and the landing act on."""
    argv = ["--command", cmd]
    if root is not None:
        argv += ["--plugin-root", str(root)]
    return fsr.main(argv)


def _reason(cmd: str, root: Path = None) -> str:
    """The stated reason, or "" — DEFENSIVELY, because this helper only ever
    builds an assertion MESSAGE. A helper that raises inside the message of a
    failing assertion replaces the finding with its own traceback, and the
    pre-fix run of this file is exactly when that happens."""
    try:
        rep = fsr.scan_commands([cmd], root=root) if root is not None \
            else fsr.scan_commands([cmd])
        return " | ".join(i.reason for i in rep.invocations)
    except Exception as e:                                  # pragma: no cover
        return f"<no reason available: {e.__class__.__name__}: {e}>"


@pytest.fixture(scope="module")
def live():
    """This repository, or a SKIP.

    The real-tree cases below are about THIS plugin's real trees, and the
    population is derived from git. On a flattened install cache there is no
    repository above the plugin; that refusal is asserted on purpose in its own
    case, and here it is a skip.

    THE CONDITION IS ASKED OF THE TREE, NOT OF THE PROGRAM. Calling the fix's
    own new entry point here would turn every case in this file into "the
    function does not exist yet" when run against the PRE-FIX program, and a
    control whose every failure is an AttributeError has observed no value and
    proves nothing about the verdict.
    """
    if not any((anc / ".git").exists() for anc in (_PLUGIN, *_PLUGIN.parents)):
        pytest.skip("no repository above the plugin (flattened install cache) — "
                    "the refusal path is covered by its own case")
    return _PLUGIN


# --------------------------------------------------------------------------
# (a) THE RUNNER -> FULL.
# --------------------------------------------------------------------------
def test_the_runner_is_the_full_suite(live):
    """The script that says it IS the full suite must not read as a subset."""
    assert _classify("./run_tests.sh") == 0, (
        "run_tests.sh is the only invocation that reaches skills/*/tests, "
        "tools/phase1_engine/tests, mcp-eda/test and _shared; classifying it "
        "as anything less tells the honest agent it ran less than it did — "
        f"reason: {_reason('./run_tests.sh')}")


def test_the_runner_is_full_however_it_is_spelled(live):
    """`bash run_tests.sh` and a path-qualified form are the same invocation."""
    for cmd in ("bash run_tests.sh",
                "cd $PLUGIN_ROOT && ./run_tests.sh",
                "sh ./run_tests.sh"):
        assert _classify(cmd) == 0, f"{cmd!r} classified as a subset"


def test_the_full_verdict_is_earned_against_the_whole_population(live):
    """FULL is not a label: it means zero tracked test files were left out.

    Asserted so that a future edit which widens the acceptance without widening
    the coverage cannot pass this file — the reason has to state the population
    it covered, and that population has to be the real one."""
    assert _classify("./run_tests.sh") == 0, _reason("./run_tests.sh")
    rep = fsr.scan_commands(["./run_tests.sh"])
    assert rep.undetermined is None
    assert rep.population > 1000, (
        f"the population is {rep.population} — this tree has thousands of "
        "tracked test files, so a small number means the derivation, not the "
        "tree, is what shrank")
    assert rep.full_suite_found is True
    assert str(rep.population) in rep.invocations[0].reason


# --------------------------------------------------------------------------
# (b) programs/tests ALONE -> NOT FULL, naming what it missed. (RULING 2)
# --------------------------------------------------------------------------
def test_programs_tests_alone_is_not_full(live):
    """One tree cannot speak for five."""
    for cmd in ("python3 -m pytest -q programs/tests/",
                "python3 -m pytest -q programs/tests",
                "pytest programs/tests"):
        assert _classify(cmd) == 1, (
            f"{cmd!r} was accepted as the full suite; it reaches one of the "
            "five trees run_tests.sh discovers")


def test_a_bare_pytest_is_not_full_either(live):
    """`pytest` with no path resolves to `pytest.ini`'s testpaths, and that key
    has declared ONE tree since v1.0.0 (`single_testpath_guard.py` pins it).
    The old acceptance granted a bare `pytest` FULL unconditionally, with the
    reason "pytest.ini testpaths runs both trees" — describing a config that
    does not exist in this repository."""
    for cmd in ("pytest", "python3 -m pytest -q"):
        assert _classify(cmd) == 1, (
            f"{cmd!r} was accepted as the full suite — {_reason(cmd)}")


def test_the_single_testpath_is_read_from_the_config_not_assumed(live):
    """The bare-pytest verdict above follows `pytest.ini`, in either direction."""
    assert fsr.testpaths(_PLUGIN) == ["programs/tests"]


def test_the_reason_names_the_MISSING_TREES(live):
    """A verdict of 'subset' that does not say what was skipped sends the
    reader back to guess, and the cheapest guess is that nothing was."""
    why = _reason("python3 -m pytest -q programs/tests")
    for tree in ("mcp-eda", "skills", "_shared", "phase1_engine"):
        assert tree in why, f"the reason does not name {tree!r}: {why}"


# --------------------------------------------------------------------------
# (c) THE CHEAT ARM — a runner mutated to drop a tree, with its control.
# --------------------------------------------------------------------------
def _fake_repo(tmp_path: Path, tiers, files) -> Path:
    """A minimal git repo holding a minimal plugin. Returns the plugin root.

    The population is derived from `git ls-files`, so the fixture must be a
    real repository with real tracked files — a directory of loose files would
    yield an empty population and every arm below would go green on nothing.
    """
    repo = tmp_path / "repo"
    plug = repo / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
    (plug / "programs").mkdir(parents=True)
    for rel in files:
        p = plug / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("def test_x():\n    assert True\n", encoding="utf-8")
    (plug / "pytest.ini").write_text("[pytest]\ntestpaths = programs/tests\n",
                                     encoding="utf-8")
    runner = plug / "run_tests.sh"
    runner.write_text(
        "#!/bin/bash\n"
        'if [[ "${1:-}" == "--list-tiers" ]]; then\n'
        + "".join(f"  echo {t}\n" for t in tiers)
        + "  exit 0\nfi\nexit 0\n", encoding="utf-8")
    runner.chmod(0o755)
    env = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@t",
               GIT_COMMITTER_NAME="t", GIT_COMMITTER_EMAIL="t@t")
    subprocess.run(["git", "init", "-q", str(repo)], check=True, env=env)
    subprocess.run(["git", "-C", str(repo), "add", "-A"], check=True, env=env)
    subprocess.run(["git", "-C", str(repo), "commit", "-qm", "f"],
                   check=True, env=env)
    return plug


_FILES = ("programs/tests/test_a.py", "mcp-eda/test/test_b.py",
          "_shared/test_c.py")
_ALL_TIERS = ("programs/tests", "mcp-eda/test", "_shared")


def test_the_control_arm_of_the_cheat_is_green(tmp_path):
    """CONTROL. The unmutated fixture runner IS full — so the mutated arm below
    is measuring the mutation and not the fixture."""
    plug = _fake_repo(tmp_path, _ALL_TIERS, _FILES)
    assert _classify("./run_tests.sh", root=plug) == 0, \
        _reason("./run_tests.sh", root=plug)


def test_a_runner_that_drops_a_tree_is_not_full(tmp_path):
    """THE CHEAT. Identical to the control but for one tier the runner stops
    discovering. A check that recognised the FILENAME would call this FULL."""
    plug = _fake_repo(tmp_path, ("programs/tests", "_shared"), _FILES)
    assert _classify("./run_tests.sh", root=plug) == 1, (
        "a runner that no longer discovers mcp-eda/test was still accepted as "
        "the full suite — the acceptance is keyed on the name, not on what the "
        "runner actually runs")
    assert "mcp-eda" in _reason("./run_tests.sh", root=plug)


def test_recognition_is_of_the_ANSWER_not_of_the_name(tmp_path):
    """Both halves, in one fixture: a runner under another name that covers the
    population is FULL, and a `run_tests.sh` that covers nothing is not."""
    plug = _fake_repo(tmp_path, _ALL_TIERS, _FILES)
    (plug / "run_tests.sh").rename(plug / "ci_entrypoint.sh")
    assert _classify("./ci_entrypoint.sh", root=plug) == 0, (
        "a runner that covers every tracked test file was refused because of "
        "what it is called")

    plug2 = _fake_repo(tmp_path / "two", ("programs/tests",), _FILES)
    assert _classify("./run_tests.sh", root=plug2) == 1, (
        "a script called run_tests.sh was accepted while covering one tree of "
        "three — the name is being read instead of the answer")


# --------------------------------------------------------------------------
# NEGATIVE CONTROLS. Widening must not turn the gate into a rubber stamp.
# --------------------------------------------------------------------------
def test_a_genuinely_narrowed_run_is_still_a_subset(live):
    """A -k selector and a single file must STILL read as subset, or this file
    has bought its green by disabling the check it is repairing."""
    assert _classify("pytest -k version") == 1
    assert _classify("pytest programs/tests/test_flow_compliance_check.py") == 1
    assert _classify("python3 -m pytest -q -m slow") == 1


def test_a_script_that_is_not_the_runner_is_not_full(live):
    """Recognition must be of A RUNNER, not of any .sh — matching 'runs a shell
    script' would pass anything a caller cares to name."""
    assert _classify("./tools/ci/repo_hygiene_gates.sh") == 1
    assert _classify("./some_other_script.sh") == 1
    assert _classify("git push origin main") == 1


def test_a_script_that_answers_list_tiers_with_junk_is_not_a_runner(tmp_path):
    """`--list-tiers` answered with directories that do not exist buys nothing.

    Without this, any script that prints two lines and exits 0 would be read as
    a tier list, and a `--list-tiers` it ignores prints its own help."""
    plug = _fake_repo(tmp_path, _ALL_TIERS, _FILES)
    liar = plug / "liar.sh"
    liar.write_text("#!/bin/bash\necho usage:\necho '  --help'\nexit 0\n",
                    encoding="utf-8")
    liar.chmod(0o755)
    assert _classify("./liar.sh", root=plug) == 1


def test_population_underivable_is_rc2_and_never_a_verdict(tmp_path):
    """REFUSAL IS NOT FAILURE, and it is certainly not a pass. With no git
    above it the corpus cannot be derived, and both a PASS and a FAIL would be
    a claim this program is not entitled to make."""
    plug = tmp_path / "loose" / "vibe-ic-marketplace" / "plugins" / "vibe-ic"
    (plug / "programs").mkdir(parents=True)
    (plug / "run_tests.sh").write_text("#!/bin/bash\necho programs/tests\n",
                                       encoding="utf-8")
    # Only meaningful if nothing above tmp_path is a repository.
    if fsr.population(plug) is not None:      # pragma: no cover
        pytest.skip("tmp_path lies inside a git repository on this host")
    assert _classify("./run_tests.sh", root=plug) == 2


def test_the_gate_still_refuses_an_empty_command_log(tmp_path, live):
    """Empty input is an honest FAIL: the suite demonstrably was not run."""
    f = tmp_path / "cmds.txt"
    f.write_text("# nothing but a comment\n", encoding="utf-8")
    assert fsr.main([str(f)]) == 1
    assert fsr.main([str(tmp_path / "absent.txt")]) == 2
