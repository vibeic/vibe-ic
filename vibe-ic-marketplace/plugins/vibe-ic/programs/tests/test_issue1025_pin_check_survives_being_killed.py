"""A killed pin-check must not leave the shipped source rewritten. vibe-ic#1025.

`policy_direction_pin_check --verify-pins` flips a literal IN THE REAL FILE and
restores it in a `finally`. A `finally` does not run on SIGTERM, and SIGTERM is
not hypothetical: `gatekeeper_review._run_hygiene` runs the hygiene script under
`subprocess.run(..., timeout=...)` and kills the child on TimeoutExpired. This
gate takes ~10 minutes on this corpus, so it is the one most likely to be inside
its own mutation window when that happens.

MEASURED on a clean detached origin/main worktree, before this change:

    mutation on disk after 23s:
     M programs/atpg_untestable_fault_classify.py
    sending SIGTERM ... child rc=143
    porcelain AFTER the kill: 1
    -        on_conflict="richer",
    +        on_conflict="sparser",

and separately, a run killed at 550 s left `phase3_one_shot_runner.py` with its
PDK default rewritten `sky130A` -> `nangate45`.

WHY THIS IS WORSE THAN AN ORDINARY DIRTY FILE — and why the test below is about
CONCEALMENT rather than about tidiness: the next run RE-DERIVES the argued value
from whatever the source now says. It reads the mutation as the intended value,
flips THAT, and reports a perfectly self-consistent verdict over a corrupt tree.
Two consecutive runs on the corrupted worktree agreed byte-for-byte (only pytest
wall-clock strings differed). Nothing in the output was wrong; the subject was.

So the guard has two halves, for two different deaths:
  * SIGTERM/SIGINT — handlers restore, so the ordinary kill leaves a clean tree;
  * SIGKILL — no handler can run, so a JOURNAL written outside the tree before
    the mutation lets the NEXT run repair it and SAY SO. The journal cannot
    prevent the damage. What it removes is the silence.
"""
import json
import os
import signal
import stat
import subprocess
import sys
import textwrap
import time
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent.parent
PROGRAMS = PLUGIN / "programs"

sys.path.insert(0, str(PROGRAMS))
import policy_direction_pin_check as pdpc  # noqa: E402
import _watchdog  # noqa: E402

#: Look interval / stall & backstop LOOK counts — never a runtime bound.
_LOOK_S = 0.05
_STALL_LOOKS = 600
_MAX_LOOKS = 200_000


ORIGINAL = 'x = "richer"\n'
MUTATED = 'x = "sparser"\n'


# ---------------------------------------------------------------------------
# SIGTERM — the ordinary kill, and the one `timeout` sends
# ---------------------------------------------------------------------------
def test_sigterm_inside_the_mutation_window_restores_the_file(tmp_path):
    """Drives the REAL handler in a REAL process. A test that called the
    restore function directly would prove the function works and say nothing
    about whether it is reachable from a signal, which is the whole claim."""
    target = tmp_path / "victim.py"
    target.write_text(ORIGINAL)
    journal = tmp_path / "journal.json"
    ready = tmp_path / "ready"

    driver = tmp_path / "driver.py"
    driver.write_text(textwrap.dedent(f"""
        import sys, time
        sys.path.insert(0, {str(PROGRAMS)!r})
        import policy_direction_pin_check as p
        from pathlib import Path
        t, j = Path({str(target)!r}), Path({str(journal)!r})
        p.install_signal_restore()
        p._arm(j, t, {ORIGINAL!r}, {MUTATED!r})
        t.write_text({MUTATED!r})          # the mutation is now on disk
        Path({str(ready)!r}).write_text("x")
        time.sleep(120)                    # stand in the window
    """))
    proc = subprocess.Popen([sys.executable, str(driver)])
    try:
        # NOT `for _ in range(600)`: a fixed poll budget is a wall clock wearing
        # a loop, and when it runs out the test says "driver never reached the
        # mutation window" — a statement about the driver — on the evidence that
        # this host was slow. The driver is watched by its OWN forward progress
        # (CPU + I/O over its /proc tree) instead, so a slow interpreter start is
        # waited out and a driver that wedges before arming still ends the wait.
        guard = _watchdog.loop_guard(
            "pin-check-arm", max_iter=_MAX_LOOKS, stall_iters=_STALL_LOOKS,
            progress_fn=lambda: _watchdog.host_tree_progress(proc.pid))
        for _ in guard:
            if ready.exists() or proc.poll() is not None:
                break
            time.sleep(_LOOK_S)
        assert ready.exists(), (
            "driver never reached the mutation window "
            f"({guard.reason} after {guard.iterations} looks)")
        assert target.read_text() == MUTATED, "the window was not actually open"
        proc.send_signal(signal.SIGTERM)
        # Unbounded: what is meant is "the driver exited", and the `finally`
        # below still SIGKILLs anything that did not. A 60 s bound here could
        # only ever report a busy host as the handler having failed to return.
        proc.wait()
    finally:
        if proc.poll() is None:
            proc.kill()

    assert target.read_text() == ORIGINAL, (
        "SIGTERM inside the mutation window left the file rewritten — this is "
        "the measured defect, in the shipped tree")
    assert not journal.exists(), "the journal outlived the restore"
    # The process must still die of the signal it was sent, rather than being
    # swallowed into a clean exit that a caller would read as success.
    assert proc.returncode in (-signal.SIGTERM, 128 + signal.SIGTERM), \
        proc.returncode


# ---------------------------------------------------------------------------
# SIGKILL — no handler runs; the NEXT run must repair and SAY SO
# ---------------------------------------------------------------------------
def test_a_journal_left_by_a_killed_run_is_repaired_and_announced(tmp_path):
    target = tmp_path / "victim.py"
    target.write_text(MUTATED)           # as a SIGKILLed run would leave it
    journal = tmp_path / "journal.json"
    journal.write_text(json.dumps(
        {"file": str(target), "original": ORIGINAL, "mutated": MUTATED}))

    rc, lines = pdpc.recover_journal(journal)
    assert rc == 0, lines
    assert target.read_text() == ORIGINAL
    assert not journal.exists()
    assert any("REPAIRED" in ln for ln in lines), lines
    # The announcement must name the concealment, not just the file: a reader
    # who is told only "restored a file" has no reason to distrust the verdicts
    # of the runs that came before it.
    assert any("re-derived" in ln.lower() or "corrupt" in ln.lower()
               for ln in lines), lines


def test_a_file_edited_since_the_kill_is_refused_not_clobbered(tmp_path):
    """The journal's job is to undo THIS gate's write. If the file matches
    neither what the gate wrote nor what it would restore, somebody has been in
    there since and the gate cannot prove an overwrite would only undo itself."""
    target = tmp_path / "victim.py"
    target.write_text('x = "richer"  # a human edited this\n')
    journal = tmp_path / "journal.json"
    journal.write_text(json.dumps(
        {"file": str(target), "original": ORIGINAL, "mutated": MUTATED}))

    before = target.read_text()
    rc, lines = pdpc.recover_journal(journal)
    assert rc == 2, lines
    assert target.read_text() == before, "the human's edit was overwritten"
    assert journal.exists(), "the journal must survive so the state is not lost"
    assert any("Refusing to overwrite" in ln for ln in lines), lines


# ---------------------------------------------------------------------------
# the positive arms — an always-fires recovery must die on these
# ---------------------------------------------------------------------------
def test_no_journal_is_a_silent_no_op(tmp_path):
    rc, lines = pdpc.recover_journal(tmp_path / "absent.json")
    assert rc == 0 and lines == [], lines


def test_an_already_clean_file_is_not_announced_as_repaired(tmp_path):
    """A journal whose file is ALREADY the original — the run died after the
    restore but before clearing it. Nothing to repair, and announcing a repair
    that did not happen is the same class of false report."""
    target = tmp_path / "victim.py"
    target.write_text(ORIGINAL)
    journal = tmp_path / "journal.json"
    journal.write_text(json.dumps(
        {"file": str(target), "original": ORIGINAL, "mutated": MUTATED}))

    rc, lines = pdpc.recover_journal(journal)
    assert rc == 0 and lines == [], lines
    assert not journal.exists()
    assert target.read_text() == ORIGINAL


def test_a_normal_run_leaves_no_journal_behind(tmp_path):
    """`_arm` then `_disarm` is the ordinary path; a journal surviving it would
    make every subsequent run announce a repair that never happened."""
    target = tmp_path / "victim.py"
    target.write_text(ORIGINAL)
    journal = tmp_path / "journal.json"
    pdpc._arm(journal, target, ORIGINAL, MUTATED)
    assert journal.is_file()
    pdpc._disarm(journal)
    assert not journal.exists()
    assert pdpc._INFLIGHT == {}


def test_the_journal_is_private_and_does_not_duplicate_the_mutated_source(
        tmp_path):
    """Crash recovery needs the original bytes and a mutant digest, not two
    complete source files readable under the caller's ordinary umask."""
    target = tmp_path / "victim.py"
    target.write_text(ORIGINAL)
    journal = tmp_path / "journal.json"
    pdpc._arm(journal, target, ORIGINAL, MUTATED)
    try:
        mode = stat.S_IMODE(journal.stat().st_mode)
        record = json.loads(journal.read_text())
        assert mode == 0o600, oct(mode)
        assert record["original"] == ORIGINAL
        assert "mutated" not in record
        assert len(record["mutated_sha256"]) == 64
    finally:
        pdpc._disarm(journal)


def test_a_deleted_random_worktree_does_not_orphan_its_journal(
        tmp_path, monkeypatch):
    """Recovery scans the stable owner directory, not only today's root key."""
    monkeypatch.setattr(pdpc.tempfile, "tempdir", str(tmp_path))
    root = tmp_path / "random-worktree" / "programs"
    root.mkdir(parents=True)
    target = root / "victim.py"
    target.write_text(ORIGINAL)
    journal = pdpc.journal_for(root)
    pdpc._arm(journal, target, ORIGINAL, MUTATED)
    target.unlink()                       # parent already deleted the scratch

    rc, lines = pdpc.recover_all_journals()
    assert rc == 0, lines
    assert not journal.exists(), (
        "a root-keyed journal survived after its random scratch target was "
        "deleted; no later run can reconstruct that key")


# ---------------------------------------------------------------------------
# the journal must live OUTSIDE the tree it audits
# ---------------------------------------------------------------------------
def test_the_journal_is_not_written_into_the_audited_tree(tmp_path):
    """A gate that journals into the corpus it audits is what the dispatcher's
    corpus-write guard exists to catch (#1029)."""
    root = tmp_path / "programs"
    root.mkdir()
    j = pdpc.journal_for(root)
    assert root not in j.parents and j.parent != root, j


def test_two_worktrees_do_not_share_a_journal(tmp_path):
    """Otherwise one checkout repairs a path belonging to another — restoring
    bytes from a tree it never read."""
    a, b = tmp_path / "a" / "programs", tmp_path / "b" / "programs"
    a.mkdir(parents=True)
    b.mkdir(parents=True)
    assert pdpc.journal_for(a) != pdpc.journal_for(b)
