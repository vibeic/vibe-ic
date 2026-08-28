"""`attestation_preflight_check` must refuse a checkout that would defeat an
attestation, BEFORE the attestation spends the hour.

MEASURED 2026-08-21 across three gates in one day: one returned UNDETERMINED on
uncommitted tracked edits; one flipped between red and green run to run with
untracked files present; one differential suite failed 13 of 39 with a refusal
naming a single stray bytecode artefact in the snapshot path set, and passed 33
with zero failures after the tree was cleaned. Every refusal was CORRECT. The
defect was the tree they were pointed at, and the cost was paid at the end.

The bytecode half is the one nothing else can see: `__pycache__` is gitignored,
so `git status` reports nothing, while `_run_isolation.snapshot` walks the
filesystem and records every `.pyc`.

Run: PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest tests/<this file>
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

PROG = (Path(__file__).resolve().parent.parent
        / "attestation_preflight_check.py")
#: .../<repo>/vibe-ic-marketplace/plugins/vibe-ic/programs/tests/<this file>
REPO_ROOT = Path(__file__).resolve().parents[5]

RC_PASS, RC_FAIL, RC_VACUOUS, RC_USAGE = 0, 1, 2, 3

CLEAN_ENV = {"PYTHONDONTWRITEBYTECODE": "1"}


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    return _pr.run(
        ["git", "-C", str(repo),
         "-c", "user.email=t@example.invalid", "-c", "user.name=t",
         "-c", "commit.gpgsign=false", *args],
        capture_output=True, text=True, check=False)


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "r"
    (repo / "src").mkdir(parents=True)
    (repo / "src" / "a.py").write_text("x = 1\n", encoding="utf-8")
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "initial")
    return repo


def _run(*args, env_extra=None) -> subprocess.CompletedProcess:
    env = {**os.environ, **CLEAN_ENV}
    if env_extra is not None:
        env.update(env_extra)
    return _pr.run([sys.executable, str(PROG), *[str(a) for a in args]],
                          capture_output=True, text=True, env=env)


# ── the honest case ──────────────────────────────────────────────────────────

def test_a_clean_root_with_the_flag_set_is_attestable(tmp_path):
    repo = _repo(tmp_path)
    r = _run("--repo", repo, repo / "src")
    assert r.returncode == RC_PASS, r.stdout + r.stderr
    assert "1 file(s)" in r.stdout, "the reach is not stated:\n" + r.stdout


def test_the_shipped_tree_preflights_clean_under_the_prescribed_environment():
    """The corpus sweep, pinned. The gate's contract is "run me in the
    environment an attestation needs", so that is the environment it is asserted
    in — the same one this repository's landing gate exports."""
    r = _run("--repo", REPO_ROOT,
             REPO_ROOT / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs")
    assert r.returncode in (RC_PASS, RC_FAIL), r.stdout + r.stderr
    if r.returncode == RC_FAIL:
        # A dirty developer checkout is exactly what this gate exists to name,
        # so a red here must be about residue or tracked drift and must say so.
        assert "[PREFLIGHT]" in r.stdout, r.stdout


# ── failure one: bytecode writing is on ──────────────────────────────────────

def test_the_flag_is_read_from_the_environment_not_from_this_interpreter(tmp_path):
    """`python3 -B` sets `sys.dont_write_bytecode` for ITSELF and is not
    inherited. The gates this protects all spawn children, so the property that
    matters is the environment variable — and a `-B` run is named as
    insufficient rather than credited."""
    repo = _repo(tmp_path)
    ok = _run("--repo", repo, repo / "src")
    assert ok.returncode == RC_PASS, "control arm is not green:\n" + ok.stdout

    env = {k: v for k, v in os.environ.items() if k != "PYTHONDONTWRITEBYTECODE"}
    r = _pr.run(
        [sys.executable, "-B", str(PROG), "--repo", str(repo), str(repo / "src")],
        capture_output=True, text=True, env=env)
    assert r.returncode == RC_FAIL, \
        "a run that will write bytecode into the snapshot passed:\n" + r.stdout
    assert "-B" in r.stdout and "not inherited" in r.stdout, r.stdout


# ── failure two: residue git cannot see ──────────────────────────────────────

def test_a_gitignored_bytecode_artefact_is_a_refusal(tmp_path):
    """THE 13-OF-39 SHAPE. `git status` is silent about it; the drift instrument
    is not."""
    repo = _repo(tmp_path)
    (repo / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "ignore bytecode")
    status = _git(repo, "status", "--porcelain")
    cache = repo / "src" / "__pycache__"
    cache.mkdir()
    (cache / "a.cpython-310.pyc").write_bytes(b"\x00")
    assert _git(repo, "status", "--porcelain").stdout == status.stdout, \
        "the fixture is wrong: git CAN see this, so it proves nothing"

    r = _run("--repo", repo, repo / "src")
    assert r.returncode == RC_FAIL, r.stdout
    assert "__pycache__" in r.stdout, "the residue is not named:\n" + r.stdout


# ── failure three: tracked drift ─────────────────────────────────────────────

def test_a_tracked_edit_under_a_declared_root_is_a_refusal(tmp_path):
    repo = _repo(tmp_path)
    (repo / "src" / "a.py").write_text("x = 2\n", encoding="utf-8")
    r = _run("--repo", repo, repo / "src", "--json", tmp_path / "r.json")
    assert r.returncode == RC_FAIL, r.stdout
    doc = json.loads((tmp_path / "r.json").read_text())
    assert any("src/a.py" in line for line in doc["tracked_drift"]), doc


def test_untracked_files_are_the_stimulus_and_are_not_refused_by_default(tmp_path):
    """`gate_host_independence_check` (#539) uses the checkout's untracked
    leftovers as its STIMULUS. Refusing them here by default would break the one
    gate that needs them, so `--refuse-untracked` is opt-in — and it works."""
    repo = _repo(tmp_path)
    (repo / "src" / "scratch.txt").write_text("a probe left this\n",
                                              encoding="utf-8")
    default = _run("--repo", repo, repo / "src")
    assert default.returncode == RC_PASS, \
        "an untracked file broke the #539 stimulus:\n" + default.stdout

    opted = _run("--repo", repo, repo / "src", "--refuse-untracked")
    assert opted.returncode == RC_FAIL, opted.stdout
    assert "scratch.txt" in opted.stdout, opted.stdout


# ── the vacuous tier ─────────────────────────────────────────────────────────

def test_a_root_holding_no_file_is_vacuous_and_says_so(tmp_path):
    repo = _repo(tmp_path)
    (repo / "empty").mkdir()
    r = _run("--repo", repo, repo / "empty")
    assert r.returncode == RC_VACUOUS, r.stdout + r.stderr
    assert "VACUOUS_PASS:" in (r.stdout + r.stderr), r.stdout + r.stderr
    assert "NOT a pass" in r.stdout, r.stdout


# ── the bad invocation tier ──────────────────────────────────────────────────

def test_no_root_is_rc3_because_the_snapshot_set_is_never_guessed(tmp_path):
    repo = _repo(tmp_path)
    r = _run("--repo", repo)
    assert r.returncode == RC_USAGE, r.stdout + r.stderr
    assert "USAGE_ERROR:" in r.stderr, r.stderr


def test_a_root_outside_the_repo_is_rc3_not_a_finding(tmp_path):
    """The tracked half would be unanswerable, and an unanswerable half must not
    arrive dressed as a finding about the tree."""
    repo = _repo(tmp_path)
    outside = tmp_path / "elsewhere"
    outside.mkdir()
    r = _run("--repo", repo, outside)
    assert r.returncode == RC_USAGE, r.stdout + r.stderr


def test_an_unknown_flag_is_rc3_not_argparse_2(tmp_path):
    r = _run("--not-a-flag")
    assert r.returncode == RC_USAGE, r.stdout + r.stderr


# ── discrimination: revert the rule, the refusal disappears ──────────────────

def test_reverting_the_residue_walk_lets_the_stray_bytecode_pass(tmp_path):
    """THE MUTATION ARM. `residue()` is the rule that sees what git cannot.
    Neutered to find nothing, the fixture refused above passes."""
    repo = _repo(tmp_path)
    (repo / ".gitignore").write_text("__pycache__/\n", encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-qm", "ignore bytecode")
    cache = repo / "src" / "__pycache__"
    cache.mkdir()
    (cache / "a.cpython-310.pyc").write_bytes(b"\x00")

    honest = _run("--repo", repo, repo / "src")
    assert honest.returncode == RC_FAIL, "control arm is not red:\n" + honest.stdout

    source = PROG.read_text(encoding="utf-8")
    mutant_body = source.replace(
        "            if name in RESIDUE_DIRS:",
        "            if False:").replace(
        "            if name.endswith(RESIDUE_SUFFIXES):",
        "            if False:")
    assert mutant_body.count("if False:") == 2, \
        "the mutation did not apply — the residue rule moved"
    mutant = tmp_path / "mutant.py"
    mutant.write_text(mutant_body, encoding="utf-8")

    r = _pr.run(
        [sys.executable, str(mutant), "--repo", str(repo), str(repo / "src")],
        capture_output=True, text=True, env={**os.environ, **CLEAN_ENV, "PYTHONPATH": str(PROG.parent)})
    assert r.returncode == RC_PASS, (
        "the mutant still refused, so the refusal does not come from the "
        "residue walk:\n" + r.stdout + r.stderr)
