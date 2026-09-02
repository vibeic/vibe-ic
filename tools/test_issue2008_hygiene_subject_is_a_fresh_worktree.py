#!/usr/bin/env python3
"""vibe-ic#2008 — the tier's own pytest lanes left what the tier's own gate refuses.

WHAT WENT WRONG
===============
Every official ``tools/gatekeeper-land.sh`` full-tier run in the week of
2026-09-01 failed ``attestation preflight``::

    [FAIL] attestation_preflight_check: this checkout would make the
    attestation measure itself [15707 file(s) under 1 declared root(s)]

while the hygiene shard — the same ``repo_hygiene_gates.sh`` on a clean clone
of the SAME sha, with no pytest before it — passed. The tier ran its three
pytest lanes and its hygiene lane in ONE checkout; the pytest lanes leave
``__pycache__`` / ``.pytest_cache`` / ``*.pyc`` behind (``suite_write_guard``
lists them as "regenerable cache artefact(s)" and is right not to count them
as a write), and ``attestation_preflight_check`` refuses exactly that residue
under its declared root, first and blocking. ``full:gatekeeper-review`` then
RUNS the hygiene set a second time in the same checkout and fails the same
way. Both gates measured the tier's own policy correctly, so the tier is what
changed.

THE FIX THIS FILE PINS
======================
Each READER of the hygiene set measures its OWN fresh ``git worktree`` of HEAD,
made from the main shell immediately before that reader starts and released
as soon as it has returned: ``gk_hygiene_subject_prepare`` before the window
for ``lane_hygiene``, ``gk_review_subject_prepare`` before
``full:gatekeeper-review`` for the review. TWO subjects, never one shared —
the parked first attempt at this issue made one before the window, pointed
both readers at it, and the review's run still failed the preflight on the
residue the lane's own hygiene run had left in it. In the direct-push shape
the lane runs the SUBJECT's copy of ``repo_hygiene_gates.sh`` against the
subject, because ``gate_host_independence_check._expand`` rebuilds every gate's
argv with ``$PG`` under the subject and reported 114 gates at
``CHECKOUT_ATTESTATION_WRONG_COMMAND`` when the runtime copy was driven at a
subject elsewhere. When a subject cannot be made — tracked drift, a ``git``
that did not answer, an unwritable ``.git`` — the reader falls back to the
checkout and SAYS SO, and the preflight refuses there as before.

EVERY DYNAMIC TEST DRIVES THE REAL FUNCTIONS, extracted by name from
``tools/gatekeeper-land.sh`` the way ``tools/test_gatekeeper_land_lanes.py``
does, against a real git checkout carrying real cache residue, through a
hygiene stub whose only gate is the REAL ``attestation_preflight_check.py``
invoked the way ``tools/ci/repo_hygiene_gates.sh:147`` invokes it. A stub that
asserted PASS itself would prove the stub.

THE CONTROL IS THE PRE-FIX SHAPE. The same checkout, the same residue, the same
real preflight, with no subject prepared — which is byte-for-byte what
``lane_hygiene`` did before #2008 — must FAIL. If it does not, the stimulus was
never real and the pin proves nothing.

chip-AGNOSTIC: repository landing machinery only; no design, PDK, vendor or SKU.
"""
from __future__ import annotations

import os
import re
import shutil
import stat
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest

# `_progress_run` lives in the plugin's `programs/`, which is not a sibling of
# this file. Walk UP until the directory that actually holds it is found, the
# way `tools/test_gatekeeper_land_lanes.py` does.
for _anc in Path(__file__).resolve().parents:
    for _cand in (_anc / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs",
                  _anc / "programs"):
        if (_cand / "_progress_run.py").is_file():
            sys.path.insert(0, str(_cand))
            break
    else:
        continue
    break
import _progress_run as _pr  # noqa: E402

_ROOT = Path(__file__).resolve().parents[1]
_LAND = _ROOT / "tools" / "gatekeeper-land.sh"
_PROGRAMS = _ROOT / "vibe-ic-marketplace" / "plugins" / "vibe-ic" / "programs"
_PREFLIGHT = _PROGRAMS / "attestation_preflight_check.py"

#: The real pieces the drive needs, by name, in definition order.
_REAL = ("lane_write", "lane_reported", "run_capture",
         "gk_subject_prepare", "gk_subject_release",
         "gk_hygiene_subject_prepare", "gk_hygiene_subject_release",
         "gk_review_subject_prepare", "gk_review_subject_release",
         "lane_hygiene")

#: The pytest populations the tier drives; each carries `-p no:cacheprovider`.
_LANES = ("run_pytest", "run_repo_tools_pytest", "run_unselectable_pytest")

#: The hygiene stub: `ROOT` is `VIBEIC_SUBJECT_ROOT`, `PYTHONDONTWRITEBYTECODE`
#: is exported, the one gate is the REAL preflight invoked the way
#: `repo_hygiene_gates.sh:147` invokes it — and it says what it was handed and
#: WHICH COPY of itself ran, so the wiring is asserted and not only the verdict.
_STUB = textwrap.dedent(
    f"""\
    #!/usr/bin/env bash
    set -uo pipefail
    ROOT="${{VIBEIC_SUBJECT_ROOT:?}}"
    export PYTHONDONTWRITEBYTECODE=1
    echo "HYGIENE_SUBJECT=$ROOT"
    echo "HYGIENE_LANES=${{VIBEIC_CHECKOUT_CONCURRENT_LANES:-unset}}"
    echo "HYGIENE_JOBS=${{GATEKEEPER_HYGIENE_JOBS:-unset}}"
    echo "HYGIENE_SCRIPT=${{BASH_SOURCE[0]}}"
    cd "$ROOT" || exit 2
    python3 -B "{_PREFLIGHT}" "$ROOT" --repo "$ROOT"
    """)


def _extract(name: str, text: str) -> str:
    m = re.search(rf"^{re.escape(name)}\(\) \{{.*?^\}}$", text,
                  re.MULTILINE | re.DOTALL)
    assert m, f"{name}() is gone from tools/gatekeeper-land.sh"
    return m.group(0)


@pytest.fixture(scope="module")
def land_text() -> str:
    return _LAND.read_text(encoding="utf-8")


def _git(repo: Path, *args: str) -> str:
    r = _pr.run(["git", "-C", str(repo), *args], capture_output=True,
                text=True)
    assert r.returncode == 0, (args, r.stdout, r.stderr)
    return r.stdout


def _plant_residue(tree: Path) -> None:
    """The residue the pytest lanes leave, invisible to `git status`."""
    (tree / "pkg" / "__pycache__").mkdir(exist_ok=True)
    (tree / "pkg" / "__pycache__" / "mod.cpython-312.pyc").write_bytes(b"\0")
    (tree / ".pytest_cache" / "v" / "cache").mkdir(parents=True, exist_ok=True)
    (tree / ".pytest_cache" / "v" / "cache" / "lastfailed").write_text("{}")


def _checkout_with_residue(root: Path) -> Path:
    """A real repo whose CHECKOUT carries the residue and whose COMMIT does not.

    `.gitignore` covers the residue, exactly as this repository's does, so
    `git status --porcelain` reports nothing — that asymmetry (invisible to the
    cleanliness instrument, visible to the drift instrument) is the whole of
    #2008's stimulus. The hygiene stub is COMMITTED, because in the direct-push
    shape the lane runs the SUBJECT's copy, and a worktree of HEAD only carries
    what HEAD carries.
    """
    repo = root / "checkout"
    repo.mkdir()
    _git(repo, "init", "-q")
    _git(repo, "config", "user.email", "t@example.invalid")
    _git(repo, "config", "user.name", "t")
    _git(repo, "config", "commit.gpgsign", "false")
    (repo / "pkg").mkdir()
    (repo / "pkg" / "mod.py").write_text("X = 1\n", encoding="utf-8")
    (repo / ".gitignore").write_text("__pycache__/\n.pytest_cache/\n*.pyc\n",
                                     encoding="utf-8")
    (repo / "tools" / "ci").mkdir(parents=True)
    (repo / "tools" / "ci" / "repo_hygiene_gates.sh").write_text(
        _STUB, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "subject")
    _plant_residue(repo)
    assert _git(repo, "status", "--porcelain").strip() == "", (
        "the residue must be invisible to git, or this is not #2008's shape")
    return repo


def _runtime_elsewhere(root: Path) -> Path:
    """A SEPARATE runtime root — the verified-arm shape — carrying its own copy
    of the stub, so the test can tell which copy ran."""
    rt = root / "runtime"
    (rt / "tools" / "ci").mkdir(parents=True)
    (rt / "tools" / "ci" / "repo_hygiene_gates.sh").write_text(
        _STUB, encoding="utf-8")
    return rt


def _drive(root: Path, land_text: str, *, prepare: bool,
           runtime: Path | None = None, lane_width: str = "4",
           extra: str = "") -> tuple[int, str]:
    """Run the REAL functions in the shape the tier runs them.

    `prepare=False` is the PRE-FIX shape: no subject, `lane_hygiene` measures
    `$ROOT`, which is exactly the command it issued before #2008. `runtime`
    unset is the direct-push shape (`RUNTIME_ROOT` is the checkout).
    """
    repo = root / "checkout"
    lanes = root / "lanes" / "gk_lanes.abcdef"      # the name gk_cleanup guards
    shutil.rmtree(lanes, ignore_errors=True)         # one drive, one lane dir
    lanes.mkdir(parents=True)
    script = root / "drive.sh"
    body = "\n".join(_extract(n, land_text) for n in _REAL)
    script.write_text(
        "set -uo pipefail\n"
        f'ROOT="{repo}"\nRUNTIME_ROOT="{runtime or repo}"\n'
        f'LANE_DIR="{lanes}"\nLANE_WIDTH="{lane_width}"\nHYGIENE_POOL=1\n'
        "GK_HYG=(); GK_HYG_ENV=()\nFAILED=0\n"
        + body + "\n"
        + ("gk_hygiene_subject_prepare\n" if prepare else "")
        + 'echo "SUBJECT=${GK_HYG_SUBJECT:-}"\n'
        + extra
        + "lane_hygiene\n"
        + 'echo "RC=$(cat "$LANE_DIR/full:repo-hygiene.rc")"\n'
        + 'cat "$LANE_DIR/full:repo-hygiene.out"\n'
        + "gk_hygiene_subject_release\n"
        + 'echo "RELEASED=${GK_HYG_SUBJECT:-}"\n'
        + 'git -C "$ROOT" worktree list --porcelain | grep -c "^worktree " '
          '| sed "s/^/WORKTREES=/"\n',
        encoding="utf-8")
    env = dict(os.environ)
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    for k in ("GK_HYG_SUBJECT", "GK_REVIEW_SUBJECT"):
        env.pop(k, None)
    r = _pr.run(["bash", str(script)], env=env, stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT, text=True, check=False)
    m = re.search(r"^RC=(\d+)$", r.stdout, re.MULTILINE)
    assert m, r.stdout
    return int(m.group(1)), r.stdout


def _field(out: str, key: str) -> str:
    m = re.search(rf"^{key}=(.*)$", out, re.MULTILINE)
    assert m, f"{key} not reported:\n{out}"
    return m.group(1)


_PASS = "[PASS] attestation_preflight_check: attestable"
_FAIL = ("[FAIL] attestation_preflight_check: this checkout would make the "
         "attestation measure itself")


# ── THE PIN ────────────────────────────────────────────────────────────────


def test_a_checkout_with_pre_existing_pytest_cache_gets_a_PASSING_preflight_through_the_tier_path(
        tmp_path, land_text):
    """The acceptance line of vibe-ic#2008, executed: `.pytest_cache` and
    `__pycache__` already sit in the checkout, and the tier's hygiene path
    still reaches a PASSING `attestation preflight`."""
    repo = _checkout_with_residue(tmp_path)
    rc, out = _drive(tmp_path, land_text, prepare=True)
    subject = _field(out, "SUBJECT")
    assert subject and Path(subject) != repo, out
    assert _field(out, "HYGIENE_SUBJECT") == subject, (
        "the lane measured something other than the prepared subject")
    assert rc == 0, out
    assert _PASS in out, out
    # The subject is HEAD's tree, and it is CLEAN of the residue.
    assert not (Path(subject) / "pkg" / "__pycache__").exists()
    assert not (Path(subject) / ".pytest_cache").exists()
    # The checkout itself was not cleaned — the residue is still there, so the
    # pass came from measuring a different tree, not from sweeping this one.
    assert (repo / "pkg" / "__pycache__").is_dir()
    assert (repo / ".pytest_cache").is_dir()
    # The REPORT line says which shape ran, in the words a log reader greps.
    assert "the hygiene lane subject: a fresh worktree of HEAD" in out, out
    # Released: the variable is cleared and the registration is gone.
    assert _field(out, "RELEASED") == ""
    assert _field(out, "WORKTREES") == "1", out
    assert not Path(subject).exists()


def test_the_lane_runs_the_SUBJECTS_copy_of_the_hygiene_set_in_the_direct_push_shape(
        tmp_path, land_text):
    """`RUNTIME_ROOT` is the checkout: the script that runs is the subject's own
    `tools/ci/repo_hygiene_gates.sh`, so `$PG` in the attestation and `$PG` in
    `gate_host_independence_check._expand` name the same tree — the shape the
    hygiene shard passes in, and the one whose absence cost the parked attempt
    114 gates at CHECKOUT_ATTESTATION_WRONG_COMMAND."""
    _checkout_with_residue(tmp_path)
    _, out = _drive(tmp_path, land_text, prepare=True)
    subject = _field(out, "SUBJECT")
    ran = Path(_field(out, "HYGIENE_SCRIPT"))
    assert ran == Path(subject) / "tools" / "ci" / "repo_hygiene_gates.sh", out


def test_a_SEPARATE_runtime_root_keeps_running_the_trusted_copy(tmp_path, land_text):
    """The verified-arm shape names its own runtime; there the subject does not
    get to supply the instrument, exactly as before this change."""
    _checkout_with_residue(tmp_path)
    rt = _runtime_elsewhere(tmp_path)
    _, out = _drive(tmp_path, land_text, prepare=True, runtime=rt)
    subject = _field(out, "SUBJECT")
    assert subject, out
    assert _field(out, "HYGIENE_SUBJECT") == subject, out
    ran = Path(_field(out, "HYGIENE_SCRIPT"))
    assert ran == rt / "tools" / "ci" / "repo_hygiene_gates.sh", out
    assert _PASS in out, out


def test_the_fresh_subject_declares_ONE_writer_and_the_shared_checkout_the_full_width(
        tmp_path, land_text):
    """`VIBEIC_CHECKOUT_CONCURRENT_LANES` is read by `gate_host_independence_check`
    to decide whether it may attribute a write it sees to the gate it is
    driving. Nothing but the hygiene lane writes into the fresh subject, so 1
    is the truthful count there; the shared fallback keeps the full width."""
    _checkout_with_residue(tmp_path)
    _, out = _drive(tmp_path, land_text, prepare=True, lane_width="4")
    assert _field(out, "HYGIENE_LANES") == "1", out
    assert _field(out, "HYGIENE_JOBS") == "1", out
    _, out2 = _drive(tmp_path, land_text, prepare=False, lane_width="4")
    assert _field(out2, "HYGIENE_LANES") == "4", out2


# ── THE REVIEW GETS ITS OWN, AND IT IS FRESH EVEN AFTER THE LANE'S RUN ─────


def test_the_review_subject_is_a_SECOND_fresh_worktree_not_the_lanes(tmp_path, land_text):
    """THE DEFECT OF THE PARKED ATTEMPT, EXECUTED. The lane's hygiene run leaves
    residue in the lane's subject (planted here, as the real set does through
    the children its gates spawn). The review's subject is a DIFFERENT worktree,
    made after that, and the real preflight PASSES there while the control —
    the same preflight on the lane's used subject — FAILS."""
    repo = _checkout_with_residue(tmp_path)
    extra = (
        # what the lane's own hygiene run leaves behind in its subject
        'mkdir -p "$GK_HYG_SUBJECT/pkg/__pycache__" "$GK_HYG_SUBJECT/.pytest_cache"\n'
        ': > "$GK_HYG_SUBJECT/pkg/__pycache__/mod.cpython-312.pyc"\n'
        'gk_review_subject_prepare\n'
        'echo "REVIEW_SUBJECT=${GK_REVIEW_SUBJECT:-}"\n'
        '( cd "$GK_REVIEW_SUBJECT" && python3 -B "%s" "$PWD" --repo "$PWD" '
        '| sed "s/^/REVIEW_PREFLIGHT: /" )\n'
        '( cd "$GK_HYG_SUBJECT" && python3 -B "%s" "$PWD" --repo "$PWD" '
        '| sed "s/^/LANE_PREFLIGHT: /" )\n'
        'git -C "$ROOT" worktree list --porcelain | grep -c "^worktree " '
        '| sed "s/^/WORKTREES_WHILE_BOTH_LIVE=/"\n'
        'gk_review_subject_release\n'
        'echo "REVIEW_RELEASED=${GK_REVIEW_SUBJECT:-}"\n'
        % (_PREFLIGHT, _PREFLIGHT))
    _, out = _drive(tmp_path, land_text, prepare=True, extra=extra)
    lane_subject = _field(out, "SUBJECT")
    review_subject = _field(out, "REVIEW_SUBJECT")
    assert review_subject, out
    assert Path(review_subject) != Path(lane_subject), out
    assert Path(review_subject) != repo, out
    assert "the review subject: a fresh worktree of HEAD" in out, out
    assert f"REVIEW_PREFLIGHT: {_PASS}" in out, out
    assert f"LANE_PREFLIGHT: {_FAIL}" in out, (
        "the control did not fire: the lane's used subject carried no residue, "
        "so a shared subject would have passed too and this proves nothing")
    assert _field(out, "WORKTREES_WHILE_BOTH_LIVE") == "3", out
    assert _field(out, "REVIEW_RELEASED") == ""
    assert not Path(review_subject).exists()
    assert _field(out, "WORKTREES") == "1", out


# ── THE CONTROL: THE PRE-FIX SHAPE MUST FAIL ON THE SAME CHECKOUT ──────────


def test_control_the_pre_fix_shape_FAILS_on_the_same_checkout(tmp_path, land_text):
    """No subject prepared == `lane_hygiene` before #2008: it measures `$ROOT`.
    The same residue, the same real preflight, and it must refuse — or the
    stimulus above was never real."""
    repo = _checkout_with_residue(tmp_path)
    rc, out = _drive(tmp_path, land_text, prepare=False)
    assert _field(out, "SUBJECT") == ""
    assert _field(out, "HYGIENE_SUBJECT") == str(repo), out
    assert Path(_field(out, "HYGIENE_SCRIPT")) == \
        repo / "tools" / "ci" / "repo_hygiene_gates.sh", out
    assert rc == 1, out
    assert _FAIL in out, out
    assert "bytecode/cache artefact(s) already sit under the declared roots" in out


# ── THE REFUSAL PATHS: THE FALLBACK IS LOUD, AND IT CANNOT PASS FALSELY ────


def test_tracked_drift_refuses_to_build_a_subject_and_says_so(tmp_path, land_text):
    """A worktree of HEAD would not be the tree under test when a tracked file
    differs from HEAD, so none is made; the lane measures the checkout and the
    preflight refuses on the residue exactly as before."""
    repo = _checkout_with_residue(tmp_path)
    (repo / "pkg" / "mod.py").write_text("X = 2\n", encoding="utf-8")
    rc, out = _drive(tmp_path, land_text, prepare=True)
    assert _field(out, "SUBJECT") == "", out
    assert "the hygiene lane subject: THIS checkout — tracked path(s) differ from HEAD" in out
    assert _field(out, "HYGIENE_SUBJECT") == str(repo)
    assert rc == 1, out
    assert _field(out, "WORKTREES") == "1", out


@pytest.mark.skipif(os.geteuid() == 0, reason="root ignores directory modes")
def test_an_unwritable_git_dir_falls_back_loudly_and_never_passes(tmp_path, land_text):
    """The verified-arm shape: the subject bind is read-only, `git worktree add`
    cannot register anything, and the lane must run the old way and SAY it did
    — never silently, and never as a pass over residue."""
    repo = _checkout_with_residue(tmp_path)
    git_dir = repo / ".git"
    mode = git_dir.stat().st_mode
    os.chmod(git_dir, mode & ~(stat.S_IWUSR | stat.S_IWGRP | stat.S_IWOTH))
    try:
        rc, out = _drive(tmp_path, land_text, prepare=True)
    finally:
        os.chmod(git_dir, mode)
    assert _field(out, "SUBJECT") == "", out
    assert "the hygiene lane subject: THIS checkout — a fresh worktree of HEAD could not be" in out, out
    assert _field(out, "HYGIENE_SUBJECT") == str(repo)
    assert rc == 1, out


def test_a_git_that_does_not_answer_is_not_read_as_a_clean_tree(tmp_path, land_text):
    """`ROOT` that is not a repository: the status capture fails, and the
    function must say `git status` did not answer rather than proceed as if the
    tree were clean."""
    root = tmp_path / "checkout"
    root.mkdir()
    (root / "tools" / "ci").mkdir(parents=True)
    (root / "tools" / "ci" / "repo_hygiene_gates.sh").write_text(
        _STUB, encoding="utf-8")
    rc, out = _drive(tmp_path, land_text, prepare=True)
    assert _field(out, "SUBJECT") == "", out
    assert "the hygiene lane subject: THIS checkout — `git status` did not answer" in out, out
    assert rc != 0, out


# ── THE WIRING: EACH SUBJECT REACHES ITS READER, AND IS RELEASED IN ORDER ──


def _top_level(land_text: str) -> list[str]:
    return [l.strip() for l in land_text.splitlines()
            if l and not l[0].isspace() and not l.startswith("#")]


def test_the_lane_subject_is_prepared_right_before_the_window_and_released_after_it(land_text):
    """Prepared from the MAIN shell, immediately before `lane_run_window` and
    after the write-guard baseline (a subject made inside a lane would be made
    four times; one made before the baseline would be a write the closing
    bracket charges); released after `lane_report_window`, its only reader
    having been joined, and BEFORE the review's subject is made."""
    top = _top_level(land_text)
    i_prep = top.index("gk_hygiene_subject_prepare")
    i_win = top.index("lane_run_window")
    assert i_prep == i_win - 1, "the lane subject is not prepared right before the window"
    base = land_text.index('run "full:write-guard-baseline"')
    assert base < land_text.index("\ngk_hygiene_subject_prepare\n")
    i_report = top.index("lane_report_window")
    i_rel = top.index("gk_hygiene_subject_release")
    i_review_prep = top.index("gk_review_subject_prepare")
    assert i_report < i_rel < i_review_prep, top[i_report:i_review_prep + 1]


def test_the_serial_rerun_gets_a_fresh_lane_subject(land_text):
    """The write guard can force the window to run again, serially. The first
    hygiene run has already been in the old subject, so the re-run releases it
    and makes another before its own `lane_run_window`."""
    block = land_text.split("if lane_window_saw_a_write; then", 1)[1]
    block = block.split("\n  fi\n", 1)[0]
    i_rel = block.index("gk_hygiene_subject_release")
    i_prep = block.index("gk_hygiene_subject_prepare")
    i_run = block.index("lane_run_window")
    assert i_rel < i_prep < i_run, block


def test_the_review_measures_its_OWN_subject_prepared_just_before_it(land_text):
    """`full:gatekeeper-review` RUNS the hygiene set; pointed at `$ROOT` it
    failed the same preflight, pointed at the lane's used subject it failed
    too. Its `--repo` is the REVIEW subject, made immediately before the
    review and released immediately after, before the closing gates. The
    fallback expansion is the old argument."""
    body = _extract("run_gatekeeper_review", land_text)
    assert '--repo "${GK_REVIEW_SUBJECT:-$ROOT}"' in body, body
    assert '--repo "$ROOT"' not in body
    assert "GK_HYG_SUBJECT" not in body, "the review must not reuse the lane's subject"
    top = _top_level(land_text)
    i_prep = top.index("gk_review_subject_prepare")
    i_run = [i for i, l in enumerate(top)
             if l.startswith('run "full:gatekeeper-review"')]
    assert len(i_run) == 1, top
    assert i_prep == i_run[0] - 1, "the review subject is not prepared right before the review"
    i_rel = top.index("gk_review_subject_release")
    i_final = [i for i, l in enumerate(top)
               if l.startswith('run "full:write-guard-final"')][0]
    assert i_run[0] < i_rel < i_final, top[i_run[0]:i_final + 1]


def test_gk_cleanup_releases_both_subjects_when_the_script_dies_first(land_text):
    body = _extract("gk_cleanup", land_text)
    assert "gk_subject_release GK_HYG_SUBJECT" in body, body
    assert "gk_subject_release GK_REVIEW_SUBJECT" in body, body
    release = _extract("gk_subject_release", land_text)
    assert 'wt="${!var:-}"' in release, (
        "the release dereferences the subject unguarded; the lanes harness "
        "runs gk_cleanup with the variables never set")
    assert 'worktree remove --force "$wt"' in release, release
    assert "*/gk_lanes.??????/subject-*) rm -rf" in release, (
        "the sweep is not guarded to a lane dir this script minted")


def test_the_readers_never_dereference_a_subject_unguarded(land_text):
    """Every read of a subject variable in an extracted function is `${...:-}`-
    guarded: the lanes harness and the review-budget harness run those
    functions under `set -u` with the variables never set, and an unset
    subject is the FALLBACK, not a crash."""
    for name, var in (("lane_hygiene", "GK_HYG_SUBJECT"),
                      ("run_gatekeeper_review", "GK_REVIEW_SUBJECT")):
        body = _extract(name, land_text)
        assert f"${{{var}:-" in body, f"{name}: no guarded read of {var}"
        for hit in re.findall(rf"\${var}\b|\$\{{{var}\}}", body):
            assert body.index(f"${{{var}:-") < body.index(hit), (
                f"{name}: {hit} is read before the guard")


def test_there_is_no_flag_that_forces_either_shape(land_text):
    """The subject is decided by what the checkout IS, never by an environment
    variable somebody exports once and forgets."""
    assert not re.search(r"GATEKEEPER_HYGIENE_SUBJECT|GATEKEEPER_REVIEW_SUBJECT"
                         r"|GK_\w*SUBJECT_MODE", land_text)


# ── THE ISSUE'S SHAPE (b), KEPT AS WELL: MINIMAL RESIDUE IN THE CHECKOUT ────


def test_every_pytest_lane_disables_the_cache_provider_and_the_tier_exports_no_bytecode(land_text):
    """Both halves of vibe-ic#2008's shape (b) hold beside shape (a): every
    pytest population the tier drives carries `-p no:cacheprovider`, and the
    full tier exports `PYTHONDONTWRITEBYTECODE=1` at top level before the
    window, so even the checkout the lanes share carries as little residue as
    the lanes' own children allow."""
    for name in _LANES:
        body = _extract(name, land_text)
        assert "-p no:cacheprovider" in body, f"{name} re-enabled pytest's cache"
    top = land_text.splitlines()
    exports = [i for i, l in enumerate(top) if l == "export PYTHONDONTWRITEBYTECODE=1"]
    assert exports, "the full tier no longer exports PYTHONDONTWRITEBYTECODE"
    window = [i for i, l in enumerate(top) if l == "lane_run_window"]
    assert window and exports[0] < window[0], (
        "the export must precede the window it is meant to cover")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
