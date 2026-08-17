"""Three properties of a landing ROUND, each measured before it was written.

`tools/gatekeeper-land.sh` is ~31 minutes of wall clock. Five consecutive
observed rounds ended red and produced ZERO landings — about 2.5 hours of gate
time for no stamp — and three separate reasons in that log were not findings
about anybody's code:

  A. NO LOCK.  There was no `flock` anywhere in the 818-line script. Two full
     rounds were observed running in the SAME worktree 19 s apart, and one of
     them paid all 1864 s only to end on `worktree unchanged since the gates
     started`, because a concurrent process had dropped a file in.

     The wall clock is the SMALLER half. `programs/tests/
     test_issue1129_gatekeeper_prepare_landing.py::
     test_the_real_program_runs_against_this_repo_and_honours_its_boundary`
     opens with `if G.dirty_paths(repo_root): pytest.skip(...)`, so a second
     round does not fail that landing test — it DOWNGRADES it to `skipped`.
     A check that quietly stops being made is the thing this repo distrusts
     most, so serialising rounds BUYS coverage rather than spending it, and
     `test_the_concurrency_the_lock_prevents_is_the_one_that_downgrades_a_test`
     pins that claim to the code it is a claim about.

  B. A CHEAP-TIER FAIL DID NOT STOP THE FULL TIER.  Rounds 1 and 3 were
     provably unstampable within 3 SECONDS and each still paid ~1860 s. The
     stamp is written on `FAILED -eq 0` alone, so after a cheap FAIL nothing
     downstream can change the verdict — only the bill.

     Measured directly on one host, one base, one candidate commit, one planted
     cheap-tier defect, the script as the only variable: 1230 s before, 1 s
     after, and the two arms' cheap-tier gate lines diffed IDENTICAL at 14 of
     14 lines.

     THE TRAP THIS MUST NOT FALL INTO: the reason the script ran on was to
     report EVERY cheap finding in one pass instead of making the operator
     re-run an hour-long gate once per finding. Turning that into an
     abort-on-first-failure would be a REGRESSION dressed as a speed-up, and
     from the outside the two look identical. So
     `test_the_cheap_tier_still_reports_EVERY_finding_not_only_the_first`
     plants two INDEPENDENT cheap defects and demands both are named.

  C. THE RUN FINGERPRINT WAS CAPTURED AT SECOND 4 AND COMPARED ONCE, AT THE
     END.  A tree that moved early was therefore reported after the whole
     round, and the answer named a 31-minute window rather than a stage.

WHY THESE TESTS DRIVE THE REAL SCRIPT.  A test asserting the file CONTAINS
`flock` would pass on a lock that is taken and never checked; a test asserting
it contains `full tier NOT ENTERED` would pass on a branch that prints the line
and runs the tier anyway. Every behavioural test below executes
`tools/gatekeeper-land.sh` itself in a scratch repository and reads an
observable: an exit code, a marker file a stage writes when it RUNS, or the
stamp.

THE CANARY.  `plugin_full_audit` is the last stage of the full tier before the
closing gates, so the marker its stub writes is the one observable that
distinguishes "the full tier ran" from "the full tier was skipped" without
reading the script's own prose about itself.

chip-AGNOSTIC: git, bash and stub programs only. No design, PDK or vendor input.
"""
from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parents[2]
_LAND = _REPO / "tools" / "gatekeeper-land.sh"
_REAL_PROGRAMS = _REPO / "vibe-ic-marketplace/plugins/vibe-ic/programs"
_CLEAN_CHECK = _REAL_PROGRAMS / "landing_worktree_is_clean_check.py"
_ISSUE1129 = _REAL_PROGRAMS / "tests/test_issue1129_gatekeeper_prepare_landing.py"

# The tracked file the "a stage moved the tree" stubs append to. It lives under
# `vibe-ic-marketplace`, which is one of `landing_worktree_is_clean_check`'s
# SHIPPED_PATHS, so a modification to it is exactly what that gate measures.
_SUBJECT = "vibe-ic-marketplace/plugins/vibe-ic/SUBJECT.txt"

_PY = "#!/usr/bin/env python3\nimport os, sys\n"


def _git(repo: Path, *args: str) -> subprocess.CompletedProcess:
    r = subprocess.run(["git", "-C", str(repo), *args],
                       capture_output=True, text=True, timeout=30)
    assert r.returncode == 0, (args, r.stdout, r.stderr)
    return r


def _write(path: Path, text: str, *, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    if executable:
        path.chmod(0o755)


@pytest.fixture()
def land_repo(tmp_path):
    """A scratch repo carrying the REAL script and stand-ins for its stages.

    Every stage the full tier invokes gets a stub that exits 0 and prints the
    tokens the script greps for, so a round with nothing planted is GREEN and
    ends in a stamp. That green round is what makes the negative tests mean
    something: each one plants exactly one defect and the difference is the
    defect rather than the fixture.

    `landing_worktree_is_clean_check.py` is COPIED, not stubbed — the
    fingerprint semantics are the subject of half these tests, and a stand-in
    for them would be a test of the stand-in.
    """
    assert _LAND.is_file(), f"{_LAND} not found — resolve the repo root"
    assert _CLEAN_CHECK.is_file(), f"{_CLEAN_CHECK} not found"

    r = tmp_path / "land"
    plugin = r / "vibe-ic-marketplace/plugins/vibe-ic"
    prog = plugin / "programs"
    prog.mkdir(parents=True)
    (plugin / ".claude-plugin").mkdir(parents=True)

    _write(r / "tools/gatekeeper-land.sh", _LAND.read_text(encoding="utf-8"))
    _write(r / ".gitignore", "__pycache__/\n.pytest_cache/\n*.pyc\n")
    _write(plugin / ".claude-plugin/plugin.json", '{"version": "1.2.3"}\n')
    _write(r / _SUBJECT, "the tree under test\n")
    (prog / "landing_worktree_is_clean_check.py").write_bytes(
        _CLEAN_CHECK.read_bytes())

    # The marker every stage-stub touches, so a test can ask "did this stage
    # RUN" instead of parsing the script's own narration.
    ran = r / "ran"
    ran.mkdir()

    def stub(name: str, body: str) -> None:
        _write(prog / name, _PY + f'open({str(ran)!r} + "/{name}", "w").close()\n'
                                  + body)

    # ---- cheap tier -------------------------------------------------------
    stub("marketplace_version_sync_check.py",
         'import time\n'
         'time.sleep(float(os.environ.get("GK_STUB_SLEEP", "0")))\n'
         'sys.exit(int(os.environ.get("GK_STUB_VERSION_SYNC_RC", "0")))\n')
    stub("gitignore_scratch_guard.py", "sys.exit(0)\n")
    # ---- full tier --------------------------------------------------------
    # Three stages take a write-guard snapshot/compare pair. Only the OUTERMOST
    # one — the pair bracketing the whole full tier, `WG_BASE` — sits after the
    # last fingerprint checkpoint, and that is the only place a planted move can
    # test the END-of-round gate. `gk_writeguard` is that pair's mktemp
    # template; the test that uses this asserts the move actually happened, so a
    # renamed template fails loudly instead of quietly proving nothing.
    stub("suite_write_guard.py",
         'if "--snapshot" in sys.argv:\n'
         '    open(sys.argv[sys.argv.index("--snapshot") + 1], "w").write("s")\n'
         'if "--compare" in sys.argv and os.environ.get("GK_STUB_MOVE_AT") == "compare":\n'
         '    if "gk_writeguard" in sys.argv[sys.argv.index("--compare") + 1]:\n'
         '        open(os.environ["GK_STUB_SUBJECT"], "a").write("moved late\\n")\n'
         f'        open({str(ran)!r} + "/moved", "w").close()\n'
         'sys.exit(0)\n')
    stub("scratch_root_guard.py", "sys.exit(0)\n")
    stub("ci_targeted_test_select.py", 'print("programs/tests/test_stub.py")\n')
    stub("pytest_per_file_junit.py",
         'print("suite_write_guard: clean")\n'
         'print("=== pytest junit summary")\n'
         'print("AGGREGATE_COMPLETE")\n'
         'if os.environ.get("GK_STUB_MOVE_AT") == "targeted":\n'
         '    open(os.environ["GK_STUB_SUBJECT"], "a").write("moved by the targeted arm\\n")\n'
         'sys.exit(0)\n')
    stub("landing_unselectable_pytest_corpus.py",
         'print("tools/test_gk_stub.py") if "--audit" not in sys.argv else None\n'
         'sys.exit(0)\n')
    # THE CANARY. Last stage of the full tier before the closing gates.
    stub("plugin_full_audit.py",
         'sys.exit(int(os.environ.get("GK_STUB_AUDIT_RC", "0")))\n')
    _write(r / "tools/ci/repo_hygiene_gates.sh", "#!/usr/bin/env bash\nexit 0\n",
           executable=True)
    # `run_repo_tools_pytest` DISCOVERS `tools/**/test_*.py` and calls an empty
    # corpus a failure, correctly. One trivial file keeps that stage honest.
    _write(r / "tools/test_gk_stub.py", "def test_ok():\n    assert True\n")

    _git(r, "init", "-q")
    _git(r, "config", "user.email", "t@t")
    _git(r, "config", "user.name", "t")
    _git(r, "add", "-A")
    _git(r, "commit", "-q", "-m", "base")
    return r


# 55 s, under the 60 s inner-bound ceiling the 180 s harness implies
# (`ci_harness_timeout_ceiling_check`, which reads `--timeout=180` out of
# gatekeeper-land.sh itself). Measured: a green scratch round is ~2 s and the
# background round below is ~8 s, so these bounds are insurance, not budgets.
def _run(repo: Path, *args: str, env: dict | None = None, timeout: int = 55):
    e = dict(os.environ)
    e["GK_STUB_SUBJECT"] = str(repo / _SUBJECT)
    e.update(env or {})
    return subprocess.run(["bash", "tools/gatekeeper-land.sh", *args],
                          cwd=str(repo), capture_output=True, text=True,
                          timeout=timeout, env=e)


def _blob(p) -> str:
    return p.stdout + p.stderr


def _ran(repo: Path, name: str) -> bool:
    return (repo / "ran" / name).exists()


def _stamp(repo: Path) -> Path:
    return repo / ".git" / "gatekeeper-stamp"


# ===========================================================================
# THE FIXTURE ITSELF — an empty result is not a zero
# ===========================================================================
def test_a_round_with_nothing_planted_is_green_and_stamps(land_repo):
    """The control. Every negative test below is a one-variable difference from
    THIS round, so if this one is not green they are all measuring the fixture
    rather than the change."""
    out = _run(land_repo)
    blob = _blob(out)
    assert out.returncode == 0, blob
    assert "=== ALL GATES PASS" in blob, blob
    assert _ran(land_repo, "plugin_full_audit.py"), (
        "the full tier did not reach its last stage on a GREEN round — the "
        f"canary this whole file reads is not wired.\n{blob}")
    assert _stamp(land_repo).is_file(), blob


# ===========================================================================
# A. ONE ROUND AT A TIME, PER WORKTREE
# ===========================================================================
def test_a_second_round_in_the_same_worktree_is_refused_and_names_the_holder(
        land_repo):
    """Two rounds ran in one worktree 19 s apart. The second must not start.

    ONE background round carries three assertions, because each one costs a
    real 6-second window and this file runs inside the landing gate it is about.
    The third — the stamp — is here rather than in its own test for that reason:
    a refusal that measured NOTHING must not invalidate the round that IS
    measuring. Every other refusal path in this script drops the stamp
    deliberately, so "always drop it" is the easy wrong rule to generalise.
    """
    holder = land_repo / ".git" / "gatekeeper-land.holder"
    _stamp(land_repo).write_text("deadbeef\n")
    env = dict(os.environ)
    env["GK_STUB_SUBJECT"] = str(land_repo / _SUBJECT)
    env["GK_STUB_SLEEP"] = "6"
    first = subprocess.Popen(["bash", "tools/gatekeeper-land.sh"],
                             cwd=str(land_repo), stdout=subprocess.PIPE,
                             stderr=subprocess.STDOUT, text=True, env=env)
    try:
        deadline = time.time() + 30
        while not holder.is_file() and time.time() < deadline:
            time.sleep(0.05)
        assert holder.is_file(), (
            "the round that WON the lock wrote no holder note, so a refusal "
            "could not name it — an unattributable refusal is the failure mode "
            "this replaces")
        note = holder.read_text()
        second = _run(land_repo, timeout=55)
        blob = _blob(second)
        stamp_after = (_stamp(land_repo).read_text()
                       if _stamp(land_repo).exists() else "<removed>")
    finally:
        first.wait(timeout=55)

    assert second.returncode == 3, (
        f"a concurrent round must refuse, got rc={second.returncode}\n{blob}")
    assert "REFUSED" in blob and "already holds this worktree" in blob, blob
    pid = re.search(r"pid (\d+)", note)
    assert pid, f"the holder note does not carry a pid: {note!r}"
    assert pid.group(1) in blob, (
        "the refusal did not NAME the holder, so an operator cannot tell a "
        f"live round from a stale lock.\nholder note: {note!r}\n{blob}")
    # It refused BEFORE measuring anything: no gate line, no tier header.
    assert "PASS" not in blob and "cheap tier" not in blob, (
        f"the refused round ran gates anyway\n{blob}")
    assert stamp_after == "deadbeef\n", (
        "the refused round removed a stamp it never measured, so one round can "
        "sabotage another's verdict")


def test_the_lock_is_released_when_the_round_ends(land_repo):
    """A lock nobody releases turns one bad round into a permanently blocked
    worktree, which is a worse failure than the one it fixes."""
    first = _run(land_repo)
    assert first.returncode == 0, _blob(first)
    second = _run(land_repo)
    blob = _blob(second)
    assert "REFUSED" not in blob, (
        f"the lock outlived the round that took it\n{blob}")
    assert second.returncode == 0, blob
    assert not (land_repo / ".git" / "gatekeeper-land.holder").exists(), (
        "the holder note outlived its round; the next loser would print a "
        "dead pid as if it were live")


def test_the_concurrency_the_lock_prevents_is_the_one_that_downgrades_a_test():
    """THE COVERAGE CLAIM, pinned to the code it is a claim about.

    The lock is justified as a coverage GAIN, not only a saving: a concurrent
    round dirties the tree, and the real-tree landing test does not fail on a
    dirty tree — it SKIPS. If that guard is ever rewritten the justification
    has to be re-derived, so this reads the real file rather than trusting the
    comment in `gatekeeper-land.sh`."""
    src = _ISSUE1129.read_text(encoding="utf-8")
    m = re.search(r"if G\.dirty_paths\(repo_root\):\s*\n\s*pytest\.skip\(", src)
    assert m, (
        "the landing test no longer downgrades itself to `skipped` on a dirty "
        "tree. That is the silent coverage loss the round lock was justified "
        f"by; re-derive the justification in {_LAND}.")


# ===========================================================================
# B. A CHEAP-TIER REFUSAL DOES NOT BUY THE FULL TIER
# ===========================================================================
def test_a_cheap_tier_failure_refuses_before_the_full_tier(land_repo):
    """The planted defect is the REAL one this gate exists for: a tracked file
    under a shipped path modified in the worktree (the v1.9.12 shape). It is
    caught by a CHEAP gate, so the ~31-minute tier must not start."""
    (land_repo / _SUBJECT).write_text("edited after the commit\n")
    out = _run(land_repo)
    blob = _blob(out)

    assert "FAIL  worktree carries no uncommitted change" in blob, (
        f"the planted defect was not caught at all — this test proves nothing "
        f"about where the round stopped.\n{blob}")
    assert not _ran(land_repo, "plugin_full_audit.py"), (
        "the cheap tier had already refused this landing and the full tier ran "
        f"anyway — that is the ~1860 s that five measured rounds paid.\n{blob}")
    assert not _ran(land_repo, "scratch_root_guard.py"), (
        f"the targeted-test arm started after a cheap refusal\n{blob}")
    assert "full tier NOT ENTERED" in blob, blob
    assert out.returncode == 1, blob
    assert not _stamp(land_repo).exists(), (
        "a refused round left a stamp behind, which is the direction of this "
        "bug that fails OPEN")


def test_the_cheap_tier_still_reports_EVERY_finding_not_only_the_first(
        land_repo):
    """THE REGRESSION THIS CHANGE COULD HAVE BEEN.

    Two INDEPENDENT cheap defects, planted so that the FIRST cheap gate and a
    LATER one both fail. An abort-on-first-failure passes every other test in
    this file and fails this one: it would report the version-sync finding and
    send the operator away to fix it, then spend another round telling them
    about the dirty worktree.
    """
    (land_repo / _SUBJECT).write_text("edited after the commit\n")
    out = _run(land_repo, env={"GK_STUB_VERSION_SYNC_RC": "1"})
    blob = _blob(out)

    assert "FAIL  marketplace <-> plugin version sync" in blob, blob
    assert "FAIL  worktree carries no uncommitted change" in blob, (
        "only the FIRST cheap finding was reported. The cheap tier must run to "
        "completion so one pass produces the whole list; this turned a complete "
        f"finding list into a first-failure abort.\n{blob}")
    # ...and the non-blocking probe that trails the cheap tier still ran, so
    # "runs to completion" is not satisfied by stopping one gate later.
    assert _ran(land_repo, "gitignore_scratch_guard.py"), (
        f"the cheap tier stopped before its last item\n{blob}")
    assert not _ran(land_repo, "plugin_full_audit.py"), blob
    assert out.returncode == 1, blob


def test_a_green_cheap_tier_still_pays_for_the_full_tier(land_repo):
    """THE COVERAGE SIDE OF THE SAME LINE. The saving must come from rounds
    that were already refused, never from rounds that were not."""
    out = _run(land_repo)
    blob = _blob(out)
    assert out.returncode == 0, blob
    for stage in ("scratch_root_guard.py", "pytest_per_file_junit.py",
                  "suite_write_guard.py", "plugin_full_audit.py"):
        assert _ran(land_repo, stage), (
            f"{stage} did not run on a round whose cheap tier was GREEN — the "
            f"early exit is firing on rounds it must not touch.\n{blob}")


def test_the_full_tier_still_catches_what_only_it_can_see(land_repo):
    """PLANTED DEFECT, full tier. `plugin_full_audit` is invisible to every
    cheap gate, so a round whose cheap tier is green must still be refused by
    it — otherwise the early exit removed a check instead of a cost."""
    out = _run(land_repo, env={"GK_STUB_AUDIT_RC": "1"})
    blob = _blob(out)
    assert _ran(land_repo, "plugin_full_audit.py"), blob
    assert "FAIL  plugin full audit" in blob, blob
    assert out.returncode == 1, blob
    assert not _stamp(land_repo).exists(), blob


# ===========================================================================
# C. THE FINGERPRINT, RE-ASSERTED BETWEEN STAGES
# ===========================================================================
def test_a_tree_that_moves_during_the_targeted_arm_stops_the_round_there(
        land_repo):
    """PLANTED DEFECT, and the one round 4 paid 1864 s for.

    The stub for the targeted-test arm — 82-84% of a real round — appends to a
    tracked file under a shipped path. The end-of-round gate would catch that
    too; the point is WHERE. Every stage after the move is measuring a tree
    that is not the one this round would stamp, so none of them may run."""
    out = _run(land_repo, env={"GK_STUB_MOVE_AT": "targeted"})
    blob = _blob(out)

    assert "FAIL  worktree unchanged after the targeted tests" in blob, (
        "the tree moved under the gates and the round carried on to the end "
        f"before noticing\n{blob}")
    assert not _ran(land_repo, "plugin_full_audit.py"), (
        "the hygiene tier ran on a tree that had already moved — those are "
        f"minutes spent measuring something that will not be stamped\n{blob}")
    assert "the full tier wrote nothing into the tree" not in blob, (
        f"the closing gates ran after the round was already lost\n{blob}")
    assert out.returncode == 1, blob
    assert not _stamp(land_repo).exists(), blob


def test_the_end_of_round_gate_is_untouched_and_still_bites(land_repo):
    """NO CHECK WAS REMOVED. A move made AFTER the last checkpoint — inside the
    write-guard comparison, the final stage — is past every new checkpoint, and
    the original end-of-round gate must still refuse it."""
    out = _run(land_repo, env={"GK_STUB_MOVE_AT": "compare"})
    blob = _blob(out)
    assert _ran(land_repo, "plugin_full_audit.py"), (
        f"the round did not get as far as the stage that plants this\n{blob}")
    # AN EMPTY RESULT IS NOT A ZERO: prove the probe fired before reading the
    # verdict it is supposed to have produced.
    assert _ran(land_repo, "moved"), (
        "the planted move never happened, so this test would have passed on a "
        f"script with no end-of-round gate at all\n{blob}")
    assert "FAIL  worktree unchanged since the gates started" in blob, (
        "the tree moved in the last stage and the original end-of-round gate "
        f"did not catch it — a checkpoint replaced it instead of preceding it\n"
        f"{blob}")
    assert out.returncode == 1, blob
    assert not _stamp(land_repo).exists(), blob


def test_every_checkpoint_compares_against_the_fingerprint_the_cheap_tier_took(
        land_repo):
    """A checkpoint that took a FRESH fingerprint would compare the tree with
    itself and pass forever — a check-shaped no-op. All of them, and the
    end-of-round gate, must read the one file `--emit-fingerprint` wrote."""
    src = _LAND.read_text(encoding="utf-8")
    emit = re.findall(r"--emit-fingerprint\s+\"(\$\w+)\"", src)
    expect = re.findall(r"--expect-fingerprint\s+\"(\$\w+)\"", src)
    assert len(emit) == 1, f"the fingerprint is recorded more than once: {emit}"
    assert len(expect) >= 2, (
        f"the fingerprint is still compared only at the end: {expect}")
    assert set(expect) == set(emit), (
        f"a comparison reads a different fingerprint than the one recorded: "
        f"emit={emit} expect={expect}")
