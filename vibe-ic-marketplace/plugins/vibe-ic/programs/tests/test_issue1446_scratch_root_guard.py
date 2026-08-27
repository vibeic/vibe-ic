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
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import scratch_root_guard as G  # noqa: E402

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
    """
    repo = tmp_path / "a_repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True,
                   capture_output=True, timeout=_BOUND)
    inside = repo / "scratch"
    inside.mkdir()
    return inside


def _outside(tmp_path: Path) -> Path:
    """A scratch root outside any repository.

    This assertion is not decoration. `tmp_path` is only outside a repository
    because the guard under test refuses the run otherwise — if that ever
    stopped holding, every 'outside' arm below would silently be an 'inside'
    arm and would prove the opposite of what it says.
    """
    d = tmp_path / "outside"
    d.mkdir()
    assert G.enclosing_work_tree(d) is None, (
        f"this test's own scratch root is inside a work tree "
        f"({G.enclosing_work_tree(d)}) — the arms below would not mean what "
        f"they say. See vibe-ic#1446; run with the scratch root outside any "
        f"repository.")
    return d


def _run_pytest(root: Path, basetemp: Path, *extra: str, env_extra=None):
    env = dict(os.environ)
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    env.pop("VIBE_IC_ALLOW_SCRATCH_ROOT_IN_REPO", None)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
         f"--basetemp={basetemp}", *extra, "test_mini.py"],
        cwd=root, capture_output=True, text=True, timeout=_BOUND, env=env)


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

    ok = subprocess.run([sys.executable, prog, "--scratch-root",
                         str(_outside(tmp_path))],
                        capture_output=True, text=True, timeout=_BOUND, env=env)
    assert ok.returncode == 0, f"{ok.stdout}{ok.stderr}"
    assert "[PASS]" in ok.stdout, ok.stdout

    inside = _a_work_tree(tmp_path)
    bad = subprocess.run([sys.executable, prog, "--scratch-root", str(inside)],
                         capture_output=True, text=True, timeout=_BOUND, env=env)
    # RENUMBERED from 2 to 1, deliberately, and pinned here rather than
    # loosened: rc 2 in this repo is the disclosed-SKIP convention
    # (`_vacuous_exit`: "rc 2 -> VACUOUS_PASS ... the gate examined NOTHING"),
    # and this file was the one place spending it on a FINDING. Holding both
    # meanings on one code is what the section below now forbids by test.
    assert bad.returncode == G.RC_FINDING == 1, (
        f"expected the finding rc 1, got {bad.returncode}:\n"
        f"{bad.stdout}{bad.stderr}")
    assert str(inside) in bad.stdout, bad.stdout

    waived = subprocess.run([sys.executable, prog, "--scratch-root",
                             str(inside), "--allow"],
                            capture_output=True, text=True, timeout=_BOUND,
                            env=env)
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
    return subprocess.run([sys.executable, prog, *args], capture_output=True,
                          text=True, timeout=_BOUND, env=env)


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
    """
    root = _mini_tree(tmp_path)
    d = _a_root_under_the_home(tmp_path)
    try:
        r = _run_pytest(root, d)
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


def test_a_root_outside_every_volatile_root_is_a_finding():
    r = _cli("--scratch-root", _NOT_VOLATILE)
    assert r.returncode == G.RC_FINDING, r.stdout + r.stderr
    assert "NOT under a volatile root" in r.stdout
    assert _NOT_VOLATILE in r.stdout


def test_the_volatile_finding_names_what_it_costs_and_where_to_look():
    """A refusal that does not name the six tests it is standing in for sends
    the reader to find them one at a time, which is the half hour this whole
    file exists to stop anyone spending."""
    r = _cli("--scratch-root", _NOT_VOLATILE)
    assert "project_outputs_in_tree_check.py" in r.stdout
    assert "test_issue146_collect_external_outputs.py" in r.stdout
    assert "test_project_outputs_in_tree_check.py" in r.stdout
    for prefix in G.volatile_prefixes()[0]:
        assert prefix in r.stdout


def test_a_root_under_a_volatile_root_is_not_a_finding(tmp_path):
    """The negative control. A guard that refuses every root is a ban."""
    d = _outside(tmp_path)
    assert G.volatile_state(d)[0] == G.INSIDE, (
        f"this test's own scratch root {d} is not under a volatile root — the "
        f"arms above would not mean what they say")
    r = _cli("--scratch-root", str(d))
    assert r.returncode == G.RC_PASS, r.stdout + r.stderr
    assert "NOT under a volatile root" not in r.stdout


def test_the_volatile_condition_is_declared_on_a_passing_run(tmp_path):
    r = _cli("--scratch-root", str(_outside(tmp_path)))
    assert "under a volatile root" in r.stdout


def test_the_volatile_finding_has_no_waiver():
    """`--allow` waives the WORK-TREE refusal only. Waiving this one would not
    change what the gate matches, so it would buy a green preflight and the
    identical six failures a minute later."""
    r = _cli("--scratch-root", _NOT_VOLATILE, "--allow",
             env_extra={"VIBE_IC_ALLOW_SCRATCH_ROOT_IN_REPO": "1"})
    assert r.returncode == G.RC_FINDING, r.stdout + r.stderr
    assert "NOT under a volatile root" in r.stdout


def test_the_pytest_hook_declares_but_does_not_refuse_a_non_volatile_root(
        tmp_path):
    """The asymmetry, asserted rather than argued.

    Every root under a real account home is outside all four volatile prefixes,
    so a blocking hook would refuse every under-home session — which
    `test_the_hook_does_not_refuse_a_measurable_run_under_the_account_home`
    pins as supported, and which is true: six of ~3200 tests are falsified by
    such a root and the rest are measured correctly. So the hook DECLARES, in a
    line that names the root and what cannot see it, and the preflight CLI
    (which is what a landing asks, and a landing is what publishes a count) is
    the half that refuses."""
    root = _mini_tree(tmp_path)
    r = _run_pytest(root, Path(_NOT_VOLATILE) / "bt")
    assert "NOT under a volatile root" in r.stdout + r.stderr, r.stdout + r.stderr
    assert _cli("--scratch-root", _NOT_VOLATILE).returncode == G.RC_FINDING


def test_the_pytest_hook_declares_the_volatile_condition(tmp_path):
    root = _mini_tree(tmp_path)
    r = _run_pytest(root, _outside(tmp_path) / "bt")
    assert r.returncode == 0, r.stdout + r.stderr
    assert "under a volatile root" in r.stdout
