#!/usr/bin/env python3
"""vibe-ic#1446 — the scratch root is part of the suite's verdict.

WHAT IS PINNED HERE, AND WHY IT IS PINNED BY RUNNING RATHER THAN BY READING
==========================================================================
`programs/scratch_root_guard.py` makes two claims, and a claim about a pytest
hook is only worth what an actual pytest session says about it:

    DECLARES  every run states the scratch root it used, whether it is inside a
              git work tree, and whether it is under the host account home
    REFUSES   a root inside a git work tree stops the session, once, by name;
              and the preflight CLI additionally refuses a root under the
              account home, which is the condition the hermetic lane refuses
              anyway, silently, arm by arm

Both halves need their own arm, and the SECOND half is the one that can be
faked. A guard is trivially "fixed" by refusing more, so the refusal tests are
paired with tests that a normal run STILL RUNS — outside a repo, and under the
disclosed allowance. If a future change makes the guard refuse everything, the
paired arms go red and say so.

Every arm spawns a real pytest against a MINIMAL tree built in `tmp_path`
(the guard plus a one-line test), never against the plugin's own suite: the
subject here is what pytest does at configure time, and 3000 tests is a slow
way to observe it. The minimal tree also keeps the arms honest — a failure in
one of them cannot be inherited from an unrelated red elsewhere.

INNER BOUNDS. Every subprocess in this file is bounded at 30 s, half the 60 s
inner ceiling `ci_harness_timeout_ceiling_check` derives from the harness's
`--timeout=180`. A bound at or above the harness's does not fail a test; it
outlives the harness and takes the session down.
"""
from __future__ import annotations

import os
import re
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import scratch_root_guard as G  # noqa: E402

import _progress_run as _pr  # noqa: E402

#: Half the 60 s inner ceiling. See the module docstring.
_BOUND = 30

_MINI_CONFTEST = """\
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent))
pytest_plugins = ("scratch_root_guard",)
"""

_MINI_TEST = """\
def test_the_session_reached_a_test():
    assert True
"""


def _mini_tree(tmp_path: Path) -> Path:
    """A pytest rootdir that loads the guard the way the plugin's conftest does.

    The guard is COPIED rather than imported from the plugin so the spawned
    session needs nothing on its path but this directory — the arms then differ
    only in `--basetemp`, which is the whole point of the comparison.

    `project_outputs_in_tree_check.py` travels with it because the guard reads
    the volatile prefixes OUT OF that gate rather than holding a copy. Without
    it the third condition answers UNKNOWN in every mini session — which is not
    a refusal — so both volatile arms below would run to completion and prove
    nothing. Measured: the refusal arm passed its `--basetemp` and still
    reported `1 passed`.
    """
    root = tmp_path / "mini"
    root.mkdir()
    src = Path(G.__file__).resolve()
    (root / "scratch_root_guard.py").write_text(src.read_text(encoding="utf-8"),
                                                encoding="utf-8")
    authority = src.with_name("project_outputs_in_tree_check.py")
    (root / authority.name).write_text(authority.read_text(encoding="utf-8"),
                                       encoding="utf-8")
    (root / "conftest.py").write_text(_MINI_CONFTEST, encoding="utf-8")
    (root / "test_mini.py").write_text(_MINI_TEST, encoding="utf-8")
    return root


def _a_work_tree(tmp_path: Path) -> Path:
    """A real git work tree, and a directory inside it to use as a scratch root.

    `git init` rather than a hand-made `.git`, because the property under test
    is what `git rev-parse --show-toplevel` answers, not what a fixture asserts
    it would answer.

    Built beside `_outside`'s root, and NOT under `tmp_path`, for that
    function's reason: the arms that use this one assert that THE WORK TREE is
    what the guard objects to, and a root that is also non-volatile draws a
    second finding the arm never asked about. `--allow` waives the work-tree
    refusal and nothing else, so `test_the_cli_preflight_answers_the_same_
    question_as_the_hook` measured rc 1 on its waived arm under a relocated
    `TMPDIR` and reported it as the waiver failing.
    """
    repo = _outside(tmp_path).parent / "a_repo"
    repo.mkdir()
    _pr.run(["git", "init", "-q"], cwd=repo, check=True,
                   capture_output=True, text=False)
    inside = repo / "scratch"
    inside.mkdir()
    return inside


#: Directories `_outside` made, removed after each test. `_outside` cannot use
#: `tmp_path` — see its docstring — so it cleans up after itself.
_MADE_OUTSIDE: list = []


@pytest.fixture(autouse=True)
def _remove_the_scratch_roots_this_file_makes():
    yield
    while _MADE_OUTSIDE:
        shutil.rmtree(_MADE_OUTSIDE.pop(), ignore_errors=True)


def _outside(tmp_path: Path) -> Path:
    """A scratch root this guard has NOTHING to say about: outside any git work
    tree, outside the host account home, and under one of the four volatile
    prefixes.

    IT DELIBERATELY DOES NOT USE `tmp_path`, and that is the whole point.
    Every arm that calls this is measuring ONE axis — the work tree, the
    account home, git-absent — and asserting that a root clean on that axis is
    accepted. `tmp_path` is clean on the work-tree axis only by accident of
    where the operator put `TMPDIR`, and under a relocated `TMPDIR` (the #2014
    census lane, `run_suite_in_eda_image.sh --scratch`, any scratch under
    `$HOME`) it is NOT under a volatile prefix — so the preflight refuses it on
    the volatile axis and SIX arms in this file report "a legitimate root was
    refused" about a root that was not legitimate. MEASURED on ded6aa231a68,
    one bind mount, only `TMPDIR` different: 6 failed with `TMPDIR=/w/tmp`,
    0 failed with pytest's own default.

    That is the same defect `test_issue146_collect_external_outputs.py` fixed
    in fc32402c8 with its `volatile_dir` fixture, and it is fixed here the same
    way: build the precondition, ASSERT it, and fail on the PREMISE — never on
    the subject — when a lane cannot provide it.

    The four prefixes are read from the guard, which reads them from the gate,
    so this fixture cannot drift from what the gate matches.
    """
    prefixes, why = G.volatile_prefixes()
    assert prefixes, f"the guard could not state its volatile prefixes: {why}"
    tried = []
    for prefix in prefixes:
        root = Path(prefix)
        if not (root.is_dir() and os.access(root, os.W_OK)):
            tried.append(f"{root} (not a writable directory)")
            continue
        made = Path(tempfile.mkdtemp(
            prefix=f"vibeic1446-{tmp_path.name[:32]}-", dir=str(root)))
        _MADE_OUTSIDE.append(made)
        d = made / "outside"
        d.mkdir()
        if G.enclosing_work_tree(d) is not None:
            tried.append(f"{root} (inside the work tree "
                         f"{G.enclosing_work_tree(d)})")
            continue
        if G.home_state(d)[0] == G.INSIDE:
            tried.append(f"{root} (under the account home {G.home_state(d)[1]})")
            continue
        assert G.volatile_state(d)[0] == G.INSIDE, (d, G.volatile_state(d))
        return d
    pytest.fail(
        "no volatile root here yields a scratch root outside every work tree "
        "and outside the account home, so the arms that use one would not mean "
        "what they say. This is the PREMISE failing, not the guard:\n  "
        + "\n  ".join(tried))


def _run_pytest(root: Path, basetemp: Path, *extra: str, env_extra=None):
    env = dict(os.environ)
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    env.pop("VIBE_IC_ALLOW_SCRATCH_ROOT_IN_REPO", None)
    if env_extra:
        env.update(env_extra)
    return _pr.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
         f"--basetemp={basetemp}", *extra, "test_mini.py"],
        cwd=root, capture_output=True, text=True, env=env)


# ── the refusal ─────────────────────────────────────────────────────────────

def test_a_scratch_root_inside_a_work_tree_is_refused(tmp_path):
    root = _mini_tree(tmp_path)
    r = _run_pytest(root, _a_work_tree(tmp_path))
    assert r.returncode != 0, (
        f"a scratch root inside a work tree was accepted:\n{r.stdout}{r.stderr}")


def test_the_refusal_names_the_root_and_the_work_tree(tmp_path):
    """The cause must be IN the output. That is the entire complaint of #1446:
    46 failures each named their own subject and none named the root."""
    root = _mini_tree(tmp_path)
    inside = _a_work_tree(tmp_path)
    r = _run_pytest(root, inside)
    blob = r.stdout + r.stderr
    assert str(inside) in blob, f"refusal did not name the scratch root:\n{blob}"
    top = G.enclosing_work_tree(inside)
    assert top and top in blob, f"refusal did not name the work tree:\n{blob}"
    assert "1446" in blob, f"refusal did not cite the issue:\n{blob}"


def test_the_refusal_happens_before_any_test_reports_a_verdict(tmp_path):
    """A refused run must not LOOK like a measurement of the tree.

    The failure this guard exists to stop is a run that produces a plausible
    passed/failed tally under conditions that falsify it. So the check is not
    "did it exit non-zero" — it is "did it decline to produce a tally at all".
    """
    root = _mini_tree(tmp_path)
    r = _run_pytest(root, _a_work_tree(tmp_path))
    blob = r.stdout + r.stderr
    assert " passed" not in blob and " failed" not in blob, (
        f"a refused run still reported a pass/fail tally:\n{blob}")
    assert "test_the_session_reached_a_test" not in blob, (
        f"a refused run still ran a test:\n{blob}")


# ── the paired guards: a guard that refuses everything is not a fix ─────────

def test_a_scratch_root_outside_any_work_tree_runs_normally(tmp_path):
    root = _mini_tree(tmp_path)
    r = _run_pytest(root, _outside(tmp_path))
    assert r.returncode == 0, f"a legitimate run was refused:\n{r.stdout}{r.stderr}"
    assert "1 passed" in r.stdout, f"the session did not reach its test:\n{r.stdout}"


def test_an_explicit_allowance_runs_and_discloses_itself(tmp_path):
    """The escape hatch exists for a container whose only writable tmp is inside
    the checkout. It must RUN — and it must say it was used, so a count lifted
    out of that run carries the reason not to trust it."""
    root = _mini_tree(tmp_path)
    r = _run_pytest(root, _a_work_tree(tmp_path), "--allow-scratch-root-in-repo")
    assert r.returncode == 0, f"the allowance did not run:\n{r.stdout}{r.stderr}"
    assert "1 passed" in r.stdout, f"the session did not reach its test:\n{r.stdout}"
    assert "ALLOWED BY FLAG" in r.stdout, (
        f"the allowance ran without disclosing itself:\n{r.stdout}")
    assert "not trustworthy" in r.stdout, (
        f"the disclosure did not state the consequence:\n{r.stdout}")


def test_the_environment_allowance_also_runs_and_discloses_itself(tmp_path):
    root = _mini_tree(tmp_path)
    r = _run_pytest(root, _a_work_tree(tmp_path),
                    env_extra={"VIBE_IC_ALLOW_SCRATCH_ROOT_IN_REPO": "1"})
    assert r.returncode == 0, f"the env allowance did not run:\n{r.stdout}{r.stderr}"
    assert "ALLOWED BY FLAG" in r.stdout, (
        f"the env allowance ran without disclosing itself:\n{r.stdout}")


def test_the_guard_never_relocates_the_scratch_root(tmp_path):
    """Silently moving the root would make the guard the thing shaping the
    answer, which is the failure #1446 is about. Under the allowance the run
    proceeds — and `tmp_path` must still be where the operator put it."""
    root = _mini_tree(tmp_path)
    inside = _a_work_tree(tmp_path)
    (root / "test_mini.py").write_text(
        "def test_where_is_tmp_path(tmp_path):\n"
        "    print('TMP_PATH_IS', tmp_path)\n", encoding="utf-8")
    r = _run_pytest(root, inside, "--allow-scratch-root-in-repo", "-s")
    assert r.returncode == 0, f"{r.stdout}{r.stderr}"
    line = [x for x in r.stdout.splitlines() if x.startswith("TMP_PATH_IS ")]
    assert line, f"the test did not report its tmp_path:\n{r.stdout}"
    got = Path(line[0].split(" ", 1)[1].strip())
    assert str(got).startswith(str(inside)), (
        f"the guard relocated the scratch root: asked for {inside}, got {got}")


# ── the declaration ─────────────────────────────────────────────────────────

def test_every_run_states_the_scratch_root_it_used(tmp_path):
    root = _mini_tree(tmp_path)
    outside = _outside(tmp_path)
    r = _run_pytest(root, outside)
    assert "scratch_root_guard:" in r.stdout, (
        f"a passing run did not state its scratch root:\n{r.stdout}")
    assert str(outside) in r.stdout, (
        f"the declaration did not name the root:\n{r.stdout}")


def test_the_declaration_survives_dash_q(tmp_path):
    """`pytest_report_header` is SUPPRESSED under `-q`, and `-q` is the shape
    `tools/gatekeeper-land.sh` runs on every landing. A guard about runs that do
    not state their own conditions, silent in the only invocation shape that
    matters, would be this issue's defect wearing this issue's fix.

    Both shapes are run, because "it prints under -q" is only interesting
    next to "it printed at all": if the verbose arm were silent too, the
    quiet arm would be pinning a guard that never speaks.
    """
    root = _mini_tree(tmp_path)
    outside = _outside(tmp_path)
    verbose = _run_pytest(root, outside, "-v")
    quiet = _run_pytest(root, outside)
    assert "scratch_root_guard:" in verbose.stdout, (
        f"the declaration did not appear at all:\n{verbose.stdout}")
    assert "scratch_root_guard:" in quiet.stdout, (
        f"the declaration did not survive -q:\n{quiet.stdout}")


def test_a_root_that_could_not_be_classified_is_not_reported_as_outside():
    """"I could not look" and "I looked and there is nothing" are two answers
    this repo keeps apart. `enclosing_work_tree` folds them both to None — so
    the WORDING must not claim the clean one."""
    text = G.declaration(None, verdict=(Path("/nowhere"), None, False))
    assert "git could not be asked" in text, text


# ── the preflight CLI ───────────────────────────────────────────────────────

def test_the_cli_preflight_answers_the_same_question_as_the_hook(tmp_path):
    """The landing asks this before building a selection, so it must agree with
    the in-process hook rather than approximate it."""
    prog = str(Path(G.__file__).resolve())
    env = dict(os.environ)
    env.pop("VIBE_IC_ALLOW_SCRATCH_ROOT_IN_REPO", None)

    ok = _pr.run([sys.executable, prog, "--scratch-root",
                         str(_outside(tmp_path))],
                        capture_output=True, text=True, env=env)
    assert ok.returncode == 0, f"{ok.stdout}{ok.stderr}"
    assert "[PASS]" in ok.stdout, ok.stdout

    inside = _a_work_tree(tmp_path)
    bad = _pr.run([sys.executable, prog, "--scratch-root", str(inside)],
                         capture_output=True, text=True, env=env)
    # RENUMBERED from 2 to 1, deliberately, and pinned here rather than
    # loosened: rc 2 in this repo is the disclosed-SKIP convention
    # (`_vacuous_exit`: "rc 2 -> VACUOUS_PASS ... the gate examined NOTHING"),
    # and this file was the one place spending it on a FINDING. Holding both
    # meanings on one code is what the section below now forbids by test.
    assert bad.returncode == G.RC_FINDING == 1, (
        f"expected the finding rc 1, got {bad.returncode}:\n"
        f"{bad.stdout}{bad.stderr}")
    assert str(inside) in bad.stdout, bad.stdout

    waived = _pr.run([sys.executable, prog, "--scratch-root",
                             str(inside), "--allow"],
                            capture_output=True, text=True, env=env)
    assert waived.returncode == 0, f"{waived.stdout}{waived.stderr}"
    assert "[ALLOWED]" in waived.stdout, waived.stdout


# ── the wiring, and the bound ───────────────────────────────────────────────

def test_the_plugin_tree_actually_loads_the_guard():
    """A guard nothing loads is a guard nobody has. Pinned against the rootdir
    conftest itself, not against a copy of its text."""
    conftest = Path(G.__file__).resolve().parents[1] / "conftest.py"
    text = conftest.read_text(encoding="utf-8")
    assert "scratch_root_guard" in text, (
        f"{conftest} does not load scratch_root_guard through pytest_plugins")


def test_the_landing_harness_asks_the_preflight():
    """`gatekeeper-land.sh` must ask before it spends an hour. If the wiring is
    ever dropped, the in-process hook still refuses — but only after the
    selection has been built, which is the cost this preflight removes."""
    sh = Path(G.__file__).resolve().parents[4] / "tools" / "gatekeeper-land.sh"
    if not sh.is_file():                                   # pragma: no cover
        pytest.skip(f"{sh} not present in this checkout")
    assert "scratch_root_guard.py" in sh.read_text(encoding="utf-8"), (
        f"{sh} does not run the scratch-root preflight")


def test_the_inner_git_bound_is_under_the_harness_ceiling():
    """`ci_harness_timeout_ceiling_check` derives 60 s from the harness's
    `--timeout=180`. An inner bound at or above it does not fail a test — it
    outlives the harness and takes the whole session down."""
    assert G._GIT_TIMEOUT <= 60, G._GIT_TIMEOUT
    assert _BOUND <= 60, _BOUND


# ══════════════════════════════════════════════════════════════════════════════
# THE SECOND CONDITION: a root under the host account home
# ══════════════════════════════════════════════════════════════════════════════
#
# The guard above refuses ONE way a scratch root manufactures failures. There is
# a second, and it costs the same half hour:
# `hermetic_candidate_runner._resolve_mount` refuses ANY mount under the account
# home — "subject would expose the host HOME to the candidate" — and the subject
# a landing mounts comes from `mktemp -d`, i.e. from this same root. A root under
# the account home is not in a work tree, so it passed everything above, and then
# made every hermetic arm NORECORD.
#
# BOTH DIRECTIONS ARE PINNED, for the reason the paired arms above exist: a guard
# is trivially "fixed" by refusing more. Each arm that asserts a refusal is
# matched by one asserting that the legitimate root is still accepted.


def _home() -> Path:
    """The host account home, or skip.

    Asked through the guard's own accessor so this file cannot test a home
    different from the one the guard uses. It is unresolvable inside the pinned
    candidate image (`pwd.getpwuid(65534).pw_dir` is `/nonexistent`), which is a
    real, measured environment for this suite — hence a skip and not a failure.
    """
    home, why = G.host_account_home()
    if home is None:
        pytest.skip(f"no resolvable host account home here: {why}")
    return home


def _cli(*args, env_extra=None):
    prog = str(Path(G.__file__).resolve())
    env = dict(os.environ)
    env.pop("VIBE_IC_ALLOW_SCRATCH_ROOT_IN_REPO", None)
    if env_extra:
        env.update(env_extra)
    return _pr.run([sys.executable, prog, *args], capture_output=True,
                          text=True, env=env)


def _a_root_under_the_home(tmp_path: Path) -> Path:
    """A directory under the account home, removed again by the caller's teardown.

    It is created UNDER the real account home rather than faked, because the
    property under test is what `Path.relative_to` answers about the actual home
    `pwd` reports — the same question `_resolve_mount` asks. A fixture asserting
    what it would answer would pass against a guard that reads `$HOME` instead,
    which is the specific wrong subject this change had to avoid.
    """
    d = _home() / f".vibeic-scratch-root-arm-{os.getpid()}-{tmp_path.name}"
    d.mkdir(parents=True, exist_ok=True)
    return d


# ── direction 1: a root UNDER the account home is declared, and refused ─────

def test_a_root_under_the_account_home_is_a_finding(tmp_path):
    d = _a_root_under_the_home(tmp_path)
    try:
        r = _cli("--scratch-root", str(d))
    finally:
        d.rmdir()
    assert r.returncode == G.RC_FINDING, (
        f"a root under the account home was accepted (rc {r.returncode}):\n"
        f"{r.stdout}{r.stderr}")


def test_the_home_finding_names_the_root_and_the_home(tmp_path):
    """The cause must be IN the output. This is the whole complaint: an operator
    had to work backwards from a NORECORD arm to find out which condition it
    was, because nothing said."""
    d = _a_root_under_the_home(tmp_path)
    try:
        r = _cli("--scratch-root", str(d))
    finally:
        d.rmdir()
    blob = r.stdout + r.stderr
    assert str(d) in blob, f"the finding did not name the scratch root:\n{blob}"
    assert str(_home()) in blob, f"the finding did not name the home:\n{blob}"
    assert "expose the host HOME to the candidate" in blob, (
        f"the finding did not quote the refusal it predicts:\n{blob}")


def test_the_home_condition_is_declared_even_when_it_is_the_only_finding(tmp_path):
    """DECLARE is not optional and not conditional on refusing. A run that
    refuses without saying WHICH of the two conditions it refused on sends the
    next reader back to the half hour this change exists to stop."""
    d = _a_root_under_the_home(tmp_path)
    try:
        r = _cli("--scratch-root", str(d))
    finally:
        d.rmdir()
    lines = [x for x in r.stdout.splitlines() if x.startswith("[INFO] ")]
    assert any("git work tree" in x for x in lines), (
        f"the work-tree condition was not declared:\n{r.stdout}")
    assert any("host account home" in x for x in lines), (
        f"the account-home condition was not declared:\n{r.stdout}")


def test_the_home_finding_has_no_waiver(tmp_path):
    """Deliberately unwaivable, and pinned so nobody adds one by reflex.

    `--allow` exists for the work-tree condition because a run under it can
    still be MADE and merely carries a caveat. This one cannot: waiving it would
    not make `_resolve_mount` accept the mount, so the flag would buy a green
    preflight and an identical NORECORD ten minutes later.
    """
    d = _a_root_under_the_home(tmp_path)
    try:
        flagged = _cli("--scratch-root", str(d), "--allow")
        envd = _cli("--scratch-root", str(d),
                    env_extra={"VIBE_IC_ALLOW_SCRATCH_ROOT_IN_REPO": "1"})
    finally:
        d.rmdir()
    assert flagged.returncode == G.RC_FINDING, (
        f"--allow waived the account-home finding:\n{flagged.stdout}")
    assert envd.returncode == G.RC_FINDING, (
        f"the env allowance waived the account-home finding:\n{envd.stdout}")


# ── direction 2: a root OUTSIDE it is not, and still declares ───────────────

def test_a_root_outside_the_account_home_is_not_a_finding(tmp_path):
    """The paired arm. Without it, a guard that refused every root would pass
    every test above and break the landing lane instead of protecting it."""
    _home()                       # no account home here -> no OUTSIDE answer
    outside = _outside(tmp_path)
    assert G.home_state(outside)[0] == G.OUTSIDE, (
        f"this test's own scratch root is under the account home "
        f"({G.home_state(outside)}) — the arm below would not mean what it "
        f"says. Run with a scratch root outside the account home.")
    r = _cli("--scratch-root", str(outside))
    assert r.returncode == G.RC_PASS, (
        f"a legitimate root was refused:\n{r.stdout}{r.stderr}")
    assert "[PASS]" in r.stdout, r.stdout


def test_a_passing_run_still_declares_the_home_it_checked_against(tmp_path):
    """Declared on EVERY run, not only on the refusing ones — a count is
    re-derivable only if the run that produced it says what it ran under."""
    _home()                           # no account home here -> no OUTSIDE answer
    outside = _outside(tmp_path)
    r = _cli("--scratch-root", str(outside))
    assert "outside the host account home" in r.stdout, (
        f"a passing run did not declare the home condition:\n{r.stdout}")
    assert str(_home()) in r.stdout, (
        f"the declaration did not NAME the home:\n{r.stdout}")


# ── the pytest hook declares it and, deliberately, does not refuse on it ────

def test_the_pytest_hook_declares_the_home_condition(tmp_path):
    root = _mini_tree(tmp_path)
    outside = _outside(tmp_path)
    r = _run_pytest(root, outside)
    assert "host account home" in r.stdout, (
        f"the session did not declare the account-home condition:\n{r.stdout}")


def test_the_hook_does_not_refuse_a_measurable_run_under_the_account_home(tmp_path):
    """THE ASYMMETRY, pinned because it is a choice and not an oversight.

    A pytest session whose `tmp_path` is under the account home is not falsified
    by that fact: `git ls-files` answers the same, the fixtures are
    discoverable, the tally is real. What breaks is the HERMETIC lane, and the
    hermetic lane asks the preflight CLI — so the block is placed where the harm
    is, and only there. Refusing here would take down runs that are perfectly
    measurable.

    THE CONFOUND, neutralised rather than assumed away. On a host whose
    account home is ITSELF a git work tree — a dotfiles checkout, which is
    ordinary — a root under the home is ALSO inside a work tree, and the
    hook refuses it for THAT condition, correctly and as
    `test_a_scratch_root_inside_a_work_tree_is_refused` pins. The guard's
    own docstring assumes the opposite ("a scratch root under the account
    home is NOT inside a work tree"), and on such a host that assumption is
    simply false, so this test measured the wrong refusal and read as the
    guard blocking real work. Allowing ONLY the work-tree condition — the
    one that has a sanctioned allowance — leaves this test's actual subject
    measured instead of unreachable. It cannot buy a false green: the home
    condition is deliberately unwaivable, pinned by
    `test_the_home_finding_has_no_waiver`, so a hook that ever refuses on
    the home still fails here. On a host whose home is not a work tree,
    nothing below changes.
    """
    root = _mini_tree(tmp_path)
    d = _a_root_under_the_home(tmp_path)
    confound = ({"VIBE_IC_ALLOW_SCRATCH_ROOT_IN_REPO": "1"}
                if G.enclosing_work_tree(_home()) is not None else None)
    try:
        r = _run_pytest(root, d, env_extra=confound)
    finally:
        shutil.rmtree(d, ignore_errors=True)
    assert r.returncode == 0, (
        f"the hook refused a measurable run under the account home:\n"
        f"{r.stdout}{r.stderr}")
    assert "1 passed" in r.stdout, f"the session did not reach its test:\n{r.stdout}"
    assert "UNDER the host account home" in r.stdout, (
        f"the session ran without declaring the condition:\n{r.stdout}")


# ── the guard must ask the question the way the thing it predicts asks it ───

def test_the_guard_resolves_the_same_home_the_hermetic_runner_does():
    """A guard that predicts a refusal must ask about the same subject.

    Pinned by RUNNING the runner's own `_home_path`, not by reading its source:
    the failure this forecloses is the guard drifting onto `$HOME`, which agrees
    with `pwd` on a developer's laptop and disagrees inside the candidate image,
    where the runner sets `HOME=/tmp` and `TMPDIR=/tmp` — so a `$HOME`-based
    check would call the landing's own scratch root a finding.
    """
    _home()          # neither instrument has an answer to compare here
    path = Path(G.__file__).resolve().parents[4] / "tools" / "ci" / \
        "hermetic_candidate_runner.py"
    if not path.is_file():                                 # pragma: no cover
        pytest.skip(f"{path} not present in this checkout")
    import importlib.util
    spec = importlib.util.spec_from_file_location("_hcr_for_home_check", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        assert module._home_path() == G.host_account_home()[0], (
            "the guard and the runner disagree about the account home")
    finally:
        sys.modules.pop(spec.name, None)


def test_the_guard_reads_pwd_and_not_the_environment(monkeypatch):
    """The concrete drift the test above forecloses, exercised directly."""
    before = G.host_account_home()[0]
    monkeypatch.setenv("HOME", "/tmp")
    assert G.host_account_home()[0] == before, (
        "host_account_home moved when $HOME did — it must read pwd")


def test_a_root_the_runner_refuses_is_a_root_this_guard_refuses(tmp_path):
    """End to end over the two instruments: whatever `_resolve_mount` rejects,
    the preflight must reject, and whatever it accepts the preflight must
    accept. Anything else is a preflight that clears a lane which then fails."""
    _home()          # neither instrument has an answer to compare here
    path = Path(G.__file__).resolve().parents[4] / "tools" / "ci" / \
        "hermetic_candidate_runner.py"
    if not path.is_file():                                 # pragma: no cover
        pytest.skip(f"{path} not present in this checkout")
    import importlib.util
    spec = importlib.util.spec_from_file_location("_hcr_for_parity", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        home = module._home_path()
        under = _a_root_under_the_home(tmp_path)
        outside = _outside(tmp_path)
        try:
            with pytest.raises(module.Refusal):
                module._resolve_mount(under, "subject", home)
            module._resolve_mount(outside, "subject", home)   # must NOT raise
            assert G.home_state(under)[0] == G.INSIDE
            assert G.home_state(outside)[0] == G.OUTSIDE
        finally:
            under.rmdir()
    finally:
        sys.modules.pop(spec.name, None)


# ── "I could not look" is not "I looked and there is nothing" ──────────────

def test_an_unresolvable_scratch_root_is_undetermined_and_names_the_path(tmp_path):
    """rc 2, naming the path — never a silent pass. A guard that dies with a
    traceback here has answered nothing while looking like a crash in whatever
    invoked it."""
    a, b = tmp_path / "loopA", tmp_path / "loopB"
    a.symlink_to(b)
    b.symlink_to(a)
    r = _cli("--scratch-root", str(a))
    assert r.returncode == G.RC_UNDETERMINED, (
        f"an unresolvable root did not report UNDETERMINED (rc "
        f"{r.returncode}):\n{r.stdout}{r.stderr}")
    assert str(a) in r.stdout, f"it did not name the path:\n{r.stdout}"
    assert "NOT CHECKED" in r.stdout, r.stdout
    assert "[PASS]" not in r.stdout, f"it passed on a root it could not resolve:\n{r.stdout}"


def test_git_absent_is_undetermined_rather_than_a_clean_outside(tmp_path):
    """The fold this change removes. `enclosing_work_tree` returned None both
    for "git said no" and for "git could not be asked", and the CLI printed
    `[PASS] ... (or git could not be asked)` for both — a pass on a condition
    nobody checked."""
    empty = tmp_path / "no_git_here"
    empty.mkdir()
    r = _cli("--scratch-root", str(_outside(tmp_path)),
             env_extra={"PATH": str(empty)})
    assert r.returncode == G.RC_UNDETERMINED, (
        f"a run that could not ask git reported rc {r.returncode}:\n"
        f"{r.stdout}{r.stderr}")
    assert "NOT CHECKED" in r.stdout, r.stdout
    assert "[PASS]" not in r.stdout, r.stdout


def test_a_work_tree_state_tells_the_three_answers_apart(tmp_path):
    inside = _a_work_tree(tmp_path)
    assert G.work_tree_state(inside)[0] == G.INSIDE
    assert G.work_tree_state(_outside(tmp_path))[0] == G.OUTSIDE


def test_an_unresolvable_account_home_is_declared_not_checked_and_still_passes(
        tmp_path, monkeypatch):
    """THE MEASUREMENT THAT DECIDED THIS, pinned so it cannot be "tidied".

    Inside the pinned candidate image — where `gatekeeper-land.sh`, and so this
    preflight, actually runs as uid 65534 — `pwd.getpwuid(65534).pw_dir` is
    `/nonexistent` and does not resolve. Read literally, an unchecked condition
    is rc 2; but `gatekeeper-land.sh:872` is `if ! out="$(...)"` and treats every
    non-zero rc alike, so the literal reading fails EVERY landing in the
    canonical lane.

    It is also the wrong reading. A host where `_home_path()` raises is a host
    where the runner refuses every mount before it looks at any scratch root, so
    the scratch root is not the finding there; and inside the candidate there is
    no host home to expose. So: DECLARED as NOT CHECKED, and passing.
    """
    monkeypatch.setattr(G, "host_account_home",
                        lambda: (None, "cannot resolve the host account home: "
                                       "[Errno 2] No such file or directory: "
                                       "'/nonexistent'"))
    outside = _outside(tmp_path)
    state, home, why = G.home_state(outside)
    assert state == G.UNKNOWN and home is None
    text = G.home_declaration(outside, verdict=(state, home, why))
    assert "NOT CHECKED" in text, text
    assert "/nonexistent" in text, (
        f"the declaration did not name what it could not determine:\n{text}")
    assert G._main(["--scratch-root", str(outside)]) == G.RC_PASS


def test_require_home_check_turns_that_same_state_into_rc_2(tmp_path,
                                                            monkeypatch):
    """The other side of the decision above: a caller that needs the ANSWER
    rather than the declaration asks for it, and gets UNDETERMINED. The landing
    does not pass this flag — see the test above for why."""
    monkeypatch.setattr(G, "host_account_home",
                        lambda: (None, "cannot resolve the host account home"))
    assert G._main(["--scratch-root", str(_outside(tmp_path)),
                    "--require-home-check"]) == G.RC_UNDETERMINED


# ── the rc contract itself ─────────────────────────────────────────────────

def test_a_bad_invocation_is_rc_3_and_not_the_undetermined_code():
    """argparse exits 2 on a usage error and 2 is UNDETERMINED here. Left alone,
    `--typo` would report itself as "I could not determine something" — a wrong
    answer to a question that was never asked. This is the rc-2-means-two-things
    collision the contract exists to remove, so it is pinned rather than
    assumed."""
    r = _cli("--no-such-flag-exists")
    assert r.returncode == G.RC_BAD_INVOCATION == 3, (
        f"a bad invocation reported rc {r.returncode}:\n{r.stdout}{r.stderr}")


def test_help_is_still_a_clean_exit():
    assert _cli("--help").returncode == 0


def test_the_four_exit_codes_are_distinct():
    """A contract whose codes collide is not a contract. rc 3 also does not
    collide with PASS_WITH_WAIVERS (#651), which per `_vacuous_exit` ("rc 3 IS
    NOT OURS") is honoured only alongside a matching stdout sentinel this file
    never emits."""
    codes = (G.RC_PASS, G.RC_FINDING, G.RC_UNDETERMINED, G.RC_BAD_INVOCATION)
    assert codes == (0, 1, 2, 3), codes
    assert len(set(codes)) == 4
    src = Path(G.__file__).read_text(encoding="utf-8")
    assert "PASS_WITH_WAIVERS" not in src.replace(
        "`PASS_WITH_WAIVERS`", "").replace("PASS_WITH_WAIVERS` (#651)", ""), (
        "this file must never emit the PASS_WITH_WAIVERS sentinel")


def test_a_finding_beats_an_unchecked_condition(tmp_path, monkeypatch):
    """`_vacuous_exit` puts FAIL above VACUOUS for the same reason: a root can be
    under the account home while git is missing, and reporting the unchecked
    half would bury the half that was checked and found."""
    monkeypatch.setattr(G, "work_tree_state",
                        lambda d: (G.UNKNOWN, None, "git could not be asked"))
    d = _a_root_under_the_home(tmp_path)
    try:
        assert G._main(["--scratch-root", str(d)]) == G.RC_FINDING
    finally:
        d.rmdir()


# ── the third condition: a root the external-storage gate cannot see ────────
#
# A NOTIONAL PATH IS USED ON PURPOSE. Every writable directory this suite can
# reach is either under a volatile root (which is the answer being excluded) or
# inside a work tree / under the account home (which are the OTHER two
# conditions, and would decide the run before this one is reached). The
# condition is a pure function of the resolved path, `_nearest_existing` walks
# up to `/` for the git question, and `resolve_scratch_root` does not require
# the path to exist — so a path that is nobody's directory asks exactly this
# condition and nothing else.
_NOT_VOLATILE = "/vibeic-scratch-root-guard-not-a-volatile-root"


def test_the_volatile_prefixes_are_the_gates_own_and_not_a_copy():
    """The guard must ask the question the way the thing it predicts asks it.

    Four string literals are exactly the kind of thing that gets duplicated and
    then drifts, and a drifted copy would make this guard refuse roots the gate
    is perfectly happy with — or, worse, pass roots it cannot see."""
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "_gate_for_prefix_identity",
        Path(G.__file__).resolve().with_name("project_outputs_in_tree_check.py"))
    gate = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(gate)
    prefixes, why = G.volatile_prefixes()
    assert why is None, why
    assert prefixes == tuple(gate._VOLATILE_PREFIXES)


def test_volatile_state_tells_the_three_answers_apart():
    assert G.volatile_state(Path("/tmp/x"))[0] == G.INSIDE
    assert G.volatile_state(Path("/var/tmp"))[0] == G.INSIDE      # the root itself
    assert G.volatile_state(Path("/dev/shm/x"))[0] == G.INSIDE
    assert G.volatile_state(Path("/run/x"))[0] == G.INSIDE
    assert G.volatile_state(Path(_NOT_VOLATILE))[0] == G.OUTSIDE
    # NOT a substring match on the tail: `/var/tmpfoo` is not `/var/tmp/`.
    assert G.volatile_state(Path("/var/tmpfoo"))[0] == G.OUTSIDE


def test_a_root_outside_every_volatile_root_is_declared_and_not_charged_for():
    """This condition shipped as a FINDING and was DEMOTED, by its own numbers.

    It refused because "N tests are falsified by such a root". N was 2 when the
    refusal was written; the v1.16.85 landing gave
    `test_project_outputs_in_tree_check.py` a `volatile_project` fixture and N
    became 0, and the refusal went on standing for six days on a debt somebody
    else had already paid. Re-measured on 4b3843f22c over all 19 files in the
    tree that touch the gate, the collector, this guard or the word "volatile":
    every one measures the same count from a non-volatile root as from `/tmp`.

    A refusal whose cost is zero stops runs the suite can measure perfectly in
    exchange for nothing, which is the guard's own name for the harm it exists
    to prevent. So the root is DECLARED, told what the mechanism is, and let
    through. `test_every_line_of_this_cost_table_fires` keeps measuring the
    number, so the demotion can be argued back on evidence rather than memory.
    """
    r = _cli("--scratch-root", _NOT_VOLATILE)
    assert r.returncode == G.RC_PASS, r.stdout + r.stderr
    assert "NOT under a volatile root" in r.stdout
    assert "[ADVISORY]" in r.stdout
    assert "[FAIL]" not in r.stdout, (
        "the volatile condition is declared, not refused:\n" + r.stdout)
    assert _NOT_VOLATILE in r.stdout


def test_the_volatile_advisory_names_what_it_costs_and_where_to_look():
    """An advisory that does not name the tests it is standing in for sends
    the reader to find them one at a time, which is the half hour this whole
    file exists to stop anyone spending. It has to keep naming them even now
    that the answer is zero — "zero" is only useful to a reader who can see
    WHAT was measured."""
    r = _cli("--scratch-root", _NOT_VOLATILE)
    assert "project_outputs_in_tree_check.py" in r.stdout
    assert "test_issue146_collect_external_outputs.py" in r.stdout
    assert "test_project_outputs_in_tree_check.py" in r.stdout
    for prefix in G.volatile_prefixes()[0]:
        assert prefix in r.stdout


def test_a_root_under_a_volatile_root_draws_no_advisory(tmp_path):
    """The negative control. Both roots are rc 0 now, so the discriminator is
    the ADVISORY, not the code: a volatile root must not draw one."""
    d = _outside(tmp_path)
    assert G.volatile_state(d)[0] == G.INSIDE, (
        f"this test's own scratch root {d} is not under a volatile root — the "
        f"arms above would not mean what they say")
    r = _cli("--scratch-root", str(d))
    assert r.returncode == G.RC_PASS, r.stdout + r.stderr
    assert "NOT under a volatile root" not in r.stdout
    assert "[ADVISORY]" not in r.stdout, r.stdout


def test_the_volatile_condition_is_declared_on_a_passing_run(tmp_path):
    r = _cli("--scratch-root", str(_outside(tmp_path)))
    assert "under a volatile root" in r.stdout


def test_the_volatile_advisory_is_not_something_a_waiver_can_silence():
    """`--allow` waives the WORK-TREE refusal only, and there is nothing here
    for it to waive anyway. The point of this arm after the demotion is that
    the DECLARATION survives the flag: a run that waived its way past a
    different condition must still be told which side of the four prefixes it
    is on, because that line is how its reader classifies whatever goes red."""
    r = _cli("--scratch-root", _NOT_VOLATILE, "--allow",
             env_extra={"VIBE_IC_ALLOW_SCRATCH_ROOT_IN_REPO": "1"})
    assert r.returncode == G.RC_PASS, r.stdout + r.stderr
    assert "NOT under a volatile root" in r.stdout
    assert "[ADVISORY]" in r.stdout


def test_the_pytest_hook_declares_but_does_not_refuse_a_non_volatile_root(
        tmp_path):
    """The asymmetry, asserted rather than argued.

    Every root under a real account home is outside all four volatile prefixes,
    so a blocking hook would refuse every under-home session — which
    `test_the_hook_does_not_refuse_a_measurable_run_under_the_account_home`
    pins as supported, and which is true: two of ~3200 tests are falsified by
    such a root and the rest are measured correctly. So the hook DECLARES, in a
    line that names the root and what cannot see it, and the preflight CLI
    (which is what a landing asks, and a landing is what publishes a count) is
    the half that refuses."""
    root = _mini_tree(tmp_path)
    r = _run_pytest(root, Path(_NOT_VOLATILE) / "bt")
    assert "NOT under a volatile root" in r.stdout + r.stderr, r.stdout + r.stderr
    assert _cli("--scratch-root", _NOT_VOLATILE).returncode == G.RC_PASS


def test_the_pytest_hook_declares_the_volatile_condition(tmp_path):
    root = _mini_tree(tmp_path)
    r = _run_pytest(root, _outside(tmp_path) / "bt")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "under a volatile root" in r.stdout


#: A line of `_VOLATILE_ADVISORY`'s cost table: an indented repo-relative test
#: file followed by the number of failures a non-volatile root costs in it.
#: Prose mentions of a file do not match — they are not followed by a count.
_COST_LINE = re.compile(
    r"^[ \t]+(programs/tests/[A-Za-z0-9_.\-]+\.py)[ \t]+(\d+)[ \t]*$", re.M)


def _can_really_mkdir_in(d: Path) -> bool:
    """Whether this process can actually create a directory in ``d``.

    Asked by doing it. Nothing else is authoritative: a read-only bind mount, a
    full filesystem and a directory whose mode bits are generous to a group
    this process is not in all pass `os.access(d, os.W_OK)`.
    """
    try:
        probe = Path(tempfile.mkdtemp(prefix="vibeic1446-probe-", dir=str(d)))
    except OSError:
        return False
    probe.rmdir()
    return True


def _a_non_volatile_root() -> Path:
    """A writable directory outside every git work tree and outside all four
    volatile prefixes — WALKED TO, never named.

    A named constant does not survive the three shapes this suite runs in: a
    container with one bind mount (`/w`), a host clone (the clone's parent),
    and a hermetic candidate (where `$HOME` is `/tmp` and the account home is
    `/nonexistent`). The first ancestor of the plugin tree that is outside the
    repository is outside it in all three; the account home is the fallback for
    a checkout that itself lives under a volatile root.

    THAT WAS NOT ENOUGH, and the reason is worth stating because it is a fact
    about the mounts and not the tree. `tools/ci/run_suite_in_eda_image.sh`
    binds the repository at its OWN path, which it must do for
    docker-out-of-docker path fidelity, and the daemon then CREATES every
    missing ancestor of that path root-owned 0755. The container user is 1000,
    so EVERY ancestor above the checkout is unwritable, and the account
    home the harness supplies is under `/var/tmp`, therefore volatile. Measured
    2026-09-06 on 8HD-9 against image 0.3.46: this helper walked nine
    candidates,
    rejected all nine, and this arm failed for the mount shape.

    So the walk does not stop at the ancestors. It goes on to ENUMERATE the top
    level of the filesystem and asks each entry the SAME three questions. That
    is still walking rather than naming — nothing here knows what the image
    calls its writable directory, and in that shape the answer turned out to be
    `/headless`. The ancestors are tried FIRST and unchanged, so every shape
    that already had an answer returns exactly the answer it returned
    before and pays nothing for this paragraph.

    The predicate is untouched. The only thing that changed is that the helper
    stops giving up while it still has somewhere to look.
    """
    tried = []
    seen = set()
    candidates = list(Path(G.__file__).resolve().parents)
    try:
        candidates.append(Path.home())
    except (RuntimeError, KeyError):                       # pragma: no cover
        pass
    try:
        candidates.extend(sorted(d for d in Path("/").iterdir() if d.is_dir()))
    except OSError:                                        # pragma: no cover
        pass
    for d in candidates:
        if d in seen:
            continue
        seen.add(d)
        if not d.is_dir():
            continue
        why = []
        if G.enclosing_work_tree(d) is not None:
            why.append("in a work tree")
        if G.volatile_state(d)[0] != G.OUTSIDE:
            why.append("volatile")
        if not os.access(d, os.W_OK):
            why.append("not writable")
        elif not _can_really_mkdir_in(d):
            # `os.access` answers about this uid against the mode bits; it says
            # yes on a read-only bind mount and on a full filesystem. The
            # question this arm needs is the one only `mkdir` answers, and it
            # is asked here rather than left to blow up inside the loop below.
            why.append("not writable (mkdir refused)")
        if not why:
            return d
        tried.append(f"{d} ({', '.join(why)})")
    pytest.fail(
        "no writable directory outside every work tree and outside all four "
        "volatile roots — this arm measures nothing without one, so it says "
        "so rather than passing:\n  " + "\n  ".join(tried))


def _failed_count(out) -> int:
    """The failure tally of an inner pytest run, or a loud failure.

    A run that produced NO tally is not zero failures — it is a run that did
    not happen (`rc 4`, a collection error, an empty selector). Reporting it as
    0 would turn a broken arm into a green one.
    """
    text = out.stdout + out.stderr
    m = re.search(r"\b(\d+) failed\b", text)
    if m:
        return int(m.group(1))
    assert re.search(r"\b\d+ passed\b", text), (
        f"that pytest run produced no tally at all (rc {out.returncode}); it "
        f"did not run:\n{text[-3000:]}")
    return 0


def test_every_line_of_this_cost_table_fires():
    """The cost table inside `_VOLATILE_ADVISORY` is the whole of what the
    refusal offers an operator — where to look — and a table that is READ
    rather than RUN decays without saying so.

    It did. It carried
    `programs/tests/test_issue146_collect_external_outputs.py   4` from
    ae5cc4dbfc3f until fc32402c8 gave that file a `volatile_dir` fixture which
    mkdtemps under one of the four prefixes; from then on the line cost 0 and
    pointed the reader at a file that is clean. MEASURED on ded6aa231a68, one
    pytest invocation per tree, only the tree different: 4 failed at
    fc32402c8^, 0 failed at fc32402c8, and the refusal text unchanged between
    them. The same table never named THIS file, which was costing 6 by a
    second mechanism until `_outside` and `_a_work_tree` were made to build
    their own volatile scratch root.

    So every line is re-measured here, by running the file it names from a
    non-volatile scratch root. That is the only way the number means anything.

    IT FIRED, AND IT IS WHY THIS CONDITION NO LONGER REFUSES. It carried
    `test_project_outputs_in_tree_check.py   2` for six days after the v1.16.85
    landing gave that file a `volatile_project` fixture and made it 0 — "two
    tests that measured the harness's TMPDIR". With that line at 0 the whole
    table is 0, and a refusal whose cost is zero is a ban. The condition is now
    an ADVISORY; this arm is what stands behind the demotion, and what would
    let anyone argue it back on evidence.

    SO A ZERO IS A LEGAL ENTRY HERE. `assert table` still refuses an EMPTY
    table — a reader who is told nothing has nothing to check — but a table of
    zeros is a real answer to a real question, and the arm re-measures it
    exactly as it re-measured the twos.

    NOT PINNED, and said out loud so it is not mistaken for pinned: the
    CONVERSE — a file that becomes affected and never gets added. The
    behavioural population for that direction is the test files that reference
    the gate (11 besides this one on ded6aa231a68), and running all of them
    from a non-volatile root measured 1 m 50 s on 8hd-3 at load 2.4, one of
    them 54 s by itself. That is more than this whole file's budget, so this
    arm holds the direction the decay actually took and names the other. The
    converse WAS swept by hand on 4b3843f22c — all 19 files in the tree that
    reference the gate, the collector, this guard or the word "volatile", run
    twice each with only `--basetemp` different — and every one measured the
    same count under both roots.

    This file is skipped if it is ever named, for the obvious reason: running
    it here would run this test. It is not named today.
    """
    r = _cli("--scratch-root", _NOT_VOLATILE)
    assert r.returncode == G.RC_PASS, r.stdout + r.stderr
    table = _COST_LINE.findall(r.stdout)
    assert table, (
        "the volatile advisory states no cost table at all; there is nothing "
        f"for an operator to look at:\n{r.stdout}")

    plugin = Path(G.__file__).resolve().parents[1]
    mine = Path(__file__).name
    nv = _a_non_volatile_root()
    env = dict(os.environ)
    env.pop("VIBE_IC_ALLOW_SCRATCH_ROOT_IN_REPO", None)

    ran = 0
    for rel, declared in table:
        if Path(rel).name == mine:
            continue
        target = plugin / rel
        assert target.is_file(), (
            f"the cost table names {rel}, which does not exist")
        basetemp = Path(tempfile.mkdtemp(prefix="vibeic1446-nv-", dir=str(nv)))
        try:
            out = _pr.run(
                [sys.executable, "-m", "pytest", rel, "-q",
                 "-p", "no:cacheprovider", f"--basetemp={basetemp}"],
                cwd=str(plugin), capture_output=True, text=True, env=env)
            got = _failed_count(out)
        finally:
            shutil.rmtree(basetemp, ignore_errors=True)
        assert got == int(declared), (
            f"the volatile advisory sends the reader to {rel} for {declared} "
            f"failure(s); from the non-volatile root {basetemp.parent} that "
            f"file measures {got}. A cost table that is wrong is worse than "
            f"none — it spends the half hour this guard exists to save. And "
            f"the number is load-bearing now: this condition is an ADVISORY "
            f"rather than a refusal BECAUSE the table totals 0, so a line that "
            f"leaves 0 is the evidence for arguing the refusal back."
            f"\n{out.stdout[-3000:]}")
        ran += 1
    assert ran, (
        "the cost table named no file this arm could run, so it measured "
        f"nothing:\n{r.stdout}")


# ── the condition that KEPT its refusal, and the number it rests on ─────────


def test_every_line_of_the_work_tree_cost_table_fires(tmp_path):
    """The work-tree refusal is the one BLOCKING thing this guard still does,
    and the number under it is now RUN rather than remembered.

    This arm exists because of what happened to the OTHER table. The volatile
    condition refused for months on "2 tests are falsified by such a root"; the
    2 had been 0 since the v1.16.85 landing, nobody re-ran it, and the refusal
    went on stopping runs for a debt somebody else had paid. The work-tree
    refusal carried its own remembered number — 46, first published on #1446
    and quoted ever since — and had exactly the same nothing behind it.

    So it is measured here, the same way, by running each file the refusal
    names with a scratch root INSIDE a git work tree. MEASURED on 4b3843f22c,
    one pytest process per file, only `--basetemp` different:

        test_published_record_staleness_check.py         35   (0 outside)
        test_issue905_ic_level_layout_contract.py         6   (0 outside)
        test_issue967_empty_ic_unit_examined_nothing.py   5   (0 outside)

    46, over the same three files #1446's own correction named. The refusal is
    justified today, by measurement, and the day it is not this arm says so
    instead of leaving a ban standing on a memory.

    THE WORK TREE IS A THROWAWAY, not this checkout: `_a_work_tree` git-inits a
    repo under a volatile prefix, so the ONLY axis that differs from a clean
    run is the enclosing repository — and nothing is written inside the tree
    under test, which `suite_write_guard` would report.

    The inner runs carry the allowance, because without it the guard refuses
    them in `pytest_configure` and there is no tally to count — which
    `_failed_count` reports as "that run did not happen" rather than as zero.
    """
    r = _cli("--scratch-root", str(_a_work_tree(tmp_path)))
    assert r.returncode == G.RC_FINDING, r.stdout + r.stderr
    table = _COST_LINE.findall(r.stdout)
    assert table, (
        "the work-tree refusal states no cost table at all; it refuses on a "
        f"number the reader cannot check:\n{r.stdout}")

    plugin = Path(G.__file__).resolve().parents[1]
    mine = Path(__file__).name
    env = dict(os.environ)
    env["VIBE_IC_ALLOW_SCRATCH_ROOT_IN_REPO"] = "1"

    ran = 0
    for rel, declared in table:
        if Path(rel).name == mine:
            continue
        target = plugin / rel
        assert target.is_file(), (
            f"the cost table names {rel}, which does not exist")
        basetemp = _a_work_tree(tmp_path) / f"bt-{Path(rel).stem[:24]}"
        out = _pr.run(
            [sys.executable, "-m", "pytest", rel, "-q",
             "-p", "no:cacheprovider", f"--basetemp={basetemp}"],
            cwd=str(plugin), capture_output=True, text=True, env=env)
        got = _failed_count(out)
        assert got == int(declared), (
            f"the work-tree refusal sends the reader to {rel} for {declared} "
            f"failure(s); from the in-repo root {basetemp} that file measures "
            f"{got}. This guard BLOCKS on that number, and a block resting on "
            f"a number nobody re-runs is what the volatile condition became "
            f"before it was demoted.\n{out.stdout[-3000:]}")
        ran += 1
    assert ran, (
        "the work-tree cost table named no file this arm could run, so it "
        f"measured nothing:\n{r.stdout}")


def test_only_the_conditions_that_cost_something_are_refused(tmp_path):
    """The demotion did not turn this guard into a door that opens for anyone.

    Stated as one arm because that is the question the demotion raises, and a
    reader should not have to assemble the answer from four files: the two
    conditions with a measured cost still return rc 1 and print `[FAIL]`, and
    the one whose cost was re-measured at 0 returns rc 0 and prints
    `[ADVISORY]`. Each of the three roots differs from the others on exactly
    one axis.
    """
    in_tree = _cli("--scratch-root", str(_a_work_tree(tmp_path)))
    assert in_tree.returncode == G.RC_FINDING, in_tree.stdout + in_tree.stderr
    assert "INSIDE a git work tree" in in_tree.stdout

    under_home = _a_root_under_the_home(tmp_path)
    try:
        home = _cli("--scratch-root", str(under_home))
    finally:
        under_home.rmdir()
    assert home.returncode == G.RC_FINDING, home.stdout + home.stderr
    assert "UNDER the host account home" in home.stdout

    only_non_volatile = _cli("--scratch-root", _NOT_VOLATILE)
    assert only_non_volatile.returncode == G.RC_PASS, (
        only_non_volatile.stdout + only_non_volatile.stderr)
    assert "[FAIL]" not in only_non_volatile.stdout
