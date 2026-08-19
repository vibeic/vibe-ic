#!/usr/bin/env python3
"""vibe-ic#1446 — the scratch root is part of the suite's verdict.

WHAT IS PINNED HERE, AND WHY IT IS PINNED BY RUNNING RATHER THAN BY READING
==========================================================================
`programs/scratch_root_guard.py` makes two claims, and a claim about a pytest
hook is only worth what an actual pytest session says about it:

    DECLARES  every run states the scratch root it used
    REFUSES   a root inside a git work tree stops the session, once, by name

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
    """
    root = tmp_path / "mini"
    root.mkdir()
    src = Path(G.__file__).resolve()
    (root / "scratch_root_guard.py").write_text(src.read_text(encoding="utf-8"),
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
    assert bad.returncode == 2, (
        f"expected the disclosed-refusal rc 2, got {bad.returncode}:\n"
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


# ── the SECOND refusal: a control character in the interpolated identity ─────
#
# The root can be outside every checkout and still falsify the run, because
# pytest does not use it directly: with no `--basetemp` it builds
# `temproot / f"pytest-of-{getpass.getuser()}"` and only backs off to
# `pytest-of-unknown` when that mkdir RAISES. A newline is a legal filename
# character here, so it does not raise.

_NEWLINE_IDENTITY = "1000\nsomebody"


def _run_pytest_no_basetemp(root: Path, tmpdir: Path, *extra: str,
                            env_extra=None):
    """The arm that MATTERS: no `--basetemp`, so pytest interpolates.

    Every other arm in this file pins `--basetemp`, which is exactly the
    condition under which the identity never enters the path — so none of them
    could ever have seen this.
    """
    env = dict(os.environ)
    env["PYTEST_DISABLE_PLUGIN_AUTOLOAD"] = "1"
    env.pop("VIBE_IC_ALLOW_SCRATCH_ROOT_IN_REPO", None)
    env.pop("VIBE_IC_ALLOW_SCRATCH_IDENTITY", None)
    env["TMPDIR"] = str(tmpdir)
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, "-m", "pytest", "-q", "-p", "no:cacheprovider",
         *extra, "test_mini.py"],
        cwd=root, capture_output=True, text=True, timeout=_BOUND, env=env)


def test_an_identity_with_a_control_character_is_refused(tmp_path):
    """MEASURED in the pinned EDA container image: `getpass.getuser()` there is
    `'1000\\ndesigner'` (USER is a two-line value, uid 1000 has no passwd
    entry), and three dimension-2 cells fail because of it while naming their
    own subject and never the root."""
    root = _mini_tree(tmp_path)
    r = _run_pytest_no_basetemp(root, _outside(tmp_path),
                                env_extra={"USER": _NEWLINE_IDENTITY})
    blob = r.stdout + r.stderr
    assert r.returncode != 0, (
        f"an identity carrying a newline was accepted:\n{blob}")
    assert "control character" in blob.lower(), (
        f"the refusal did not name the cause:\n{blob}")
    assert "--basetemp" in blob, (
        f"the refusal did not name the one-word fix:\n{blob}")
    assert "test_the_session_reached_a_test" not in blob, (
        f"the session ran tests before refusing, so a count could be taken "
        f"from it:\n{blob}")


def test_the_same_identity_with_basetemp_given_runs(tmp_path):
    """The negative control, and it is the load-bearing one.

    pytest uses an explicit `--basetemp` VERBATIM and interpolates nothing, so
    the identity cannot reach the path and there is nothing to refuse. Without
    this arm the guard could be refusing on `USER` itself — a property of the
    environment rather than of the run — and no assertion here would notice.
    """
    root = _mini_tree(tmp_path)
    bt = _outside(tmp_path) / "bt"
    r = _run_pytest(root, bt, env_extra={"USER": _NEWLINE_IDENTITY})
    assert r.returncode == 0, (
        f"a run that pins --basetemp was refused over an identity that never "
        f"enters its path:\n{r.stdout}{r.stderr}")


def test_an_ordinary_identity_is_not_refused(tmp_path):
    """Non-degeneracy: the refusal must not fire on every interpolating run,
    or the arm above would prove nothing about control characters."""
    root = _mini_tree(tmp_path)
    r = _run_pytest_no_basetemp(root, _outside(tmp_path),
                                env_extra={"USER": "ordinary"})
    assert r.returncode == 0, (
        f"an ordinary one-line identity was refused:\n{r.stdout}{r.stderr}")


def test_the_identity_refusal_has_a_disclosed_escape_hatch(tmp_path):
    root = _mini_tree(tmp_path)
    r = _run_pytest_no_basetemp(
        root, _outside(tmp_path),
        env_extra={"USER": _NEWLINE_IDENTITY,
                   "VIBE_IC_ALLOW_SCRATCH_IDENTITY": "1"})
    blob = r.stdout + r.stderr
    assert r.returncode == 0, f"the hatch did not let the run through:\n{blob}"
    assert "not trustworthy" in blob, (
        f"the allowed run did not disclose the allowance, so a count lifted "
        f"out of it carries no caveat:\n{blob}")


def test_a_slash_is_left_to_pytests_own_back_off():
    """`/` is excluded ON PURPOSE. pytest's `rootdir.mkdir` raises on it and
    pytest falls back to `pytest-of-unknown` by itself, so refusing here would
    stop a session pytest was already going to make safe."""
    assert G.control_characters("a/b") == ()
    assert G.control_characters("a\nb") == (repr("\n"),)
    assert G.control_characters("plain") == ()
    assert G.control_characters(None) == ()
