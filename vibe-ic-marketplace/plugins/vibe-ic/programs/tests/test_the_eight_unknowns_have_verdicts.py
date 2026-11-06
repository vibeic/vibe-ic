"""The four causes that left eight files with NO verdict, each pinned both ways.

MEASURED TWICE BY THE OWNER before any of this was written: a 3191-file census
left 8 files with no result, and re-running those 8 alone under LOW LOAD (5 and
7 at a time) reproduced all 8 identically. Load was never the cause; four
distinct driver-side causes were.

    rc=5, no complete junit           test_arith_declaration_emit_equals_separator
                                      test_atpg_exit_code_not_signal
    unfinished live descendants       test_full_suite_run_check
                                      test_issue1283_probe_timeout_is_not_absence
    progress protocol: empty/over-    test_gds_substance_check
      sized event
    STALLED after 300 s               test_flow_matrix_coverage
                                      test_issue1129_gatekeeper_prepare_landing
                                      test_flow_matrix_census_freshness

"UNKNOWN" IS THE STATE THIS FILE EXISTS TO REMOVE, and the way to remove it is
never to widen a bound until the complaint stops. Every arm below therefore has
the direction that must STILL refuse next to the direction that must now
answer; the fourth class has ONLY the refusing direction, because nothing about
the stall detector was changed and the proof of that is that it still fires.
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))

import _watchdog                                               # noqa: E402

_TESTS = Path(__file__).resolve().parent


def _tree(tmp_path: Path, files: dict) -> Path:
    d = tmp_path / "corpus"
    d.mkdir(exist_ok=True)
    for name, body in files.items():
        (d / name).write_text(body, encoding="utf-8")
    (d / "selection.txt").write_text(
        "".join(f"{n}\n" for n in files), encoding="utf-8")
    return d


# ===========================================================================
# CAUSE 1 — rc=5 was nulled with the abnormal exits
# ===========================================================================
_NO_TESTS = (
    '"""A CLI parameterised by a path, named test_*.py. Collects nothing."""\n'
    "def main():\n"
    "    return 0\n"
)
_BROKEN_IMPORT = "import a_module_that_is_not_installed_anywhere\n"


# ===========================================================================
# CAUSE 2 — the supervisor reached the head of the tree and no further
# ===========================================================================
def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    try:
        state = Path(f"/proc/{pid}/stat").read_text()
    except OSError:
        return True
    return state.rsplit(")", 1)[-1].split()[0] != "Z"


def _wait_gone(pid: int, looks: int = 100) -> bool:
    for _ in range(looks):
        if not _alive(pid):
            return True
        time.sleep(0.1)
    return not _alive(pid)


def _grandchild_of(script: Path, pidf: Path):
    """A script whose GRANDCHILD is the thing that must die, and which names it.

    `$!` AND NOT `$$`. `$$` is the SHELL's own pid — the direct child, which
    every kill reaches, including the pre-fix one. Recording it made both arms
    below assert something trivially true: measured, the negative control
    "failed" because the pid it watched was the shell it had just killed, while
    the real orphan (`sleep 600`, reparented to init) was a DIFFERENT pid that
    nothing was looking at. The backgrounded `sleep` is the process the whole
    class is about, so it is the process whose pid is written down.
    """
    script.write_text(
        f"#!/bin/sh\nsleep 600 &\necho $! > {pidf}\nwait\n",
        encoding="utf-8")
    script.chmod(0o755)


def _read_pid(pidf: Path, proc) -> int:
    for _ in range(300):
        if pidf.is_file():
            txt = pidf.read_text().strip()
            if txt.isdigit():
                return int(txt)
        if proc is not None and proc.poll() is not None and pidf.is_file():
            break
        time.sleep(0.05)
    raise AssertionError("the fixture never recorded its grandchild pid")


def test_the_supervisor_deadline_reaches_what_the_script_launched(tmp_path):
    """THE FIX. `run_supervised` puts the child in its own session and
    `_default_kill` signals that GROUP, so `sh -> sleep 600` dies whole.

    Before this, the deadline killed `sh` and left `sleep 600` reparented to
    init. Under the per-file landing driver that leftover is a live descendant
    of the pytest session and the file's WHOLE result was UNKNOWN — measured on
    `test_full_suite_run_check.py`, every one of whose 23 tests passes.
    """
    script = tmp_path / "hangs.sh"
    pidf = tmp_path / "gc.pid"
    _grandchild_of(script, pidf)

    started = time.monotonic()
    res = _watchdog.run_supervised(
        ["bash", str(script)], stall_grace_s=3, hard_ceiling_s=3, poll_s=1)
    elapsed = time.monotonic() - started
    assert res.rc != 0, "the deadline did not fire at all"
    assert elapsed < 120, f"the deadline did not fire: {elapsed:.1f}s"

    gc = int(pidf.read_text().strip())
    assert _wait_gone(gc), (
        f"grandchild {gc} outlived the supervised deadline — the driver will "
        "call the enclosing file's result UNKNOWN however green its tests are")


#: The dispatch sites vibe-ic#2051's R4 converted that live in `programs/`.
#: MEMBERSHIP, checked as a SUBSET of what the tree yields, so a new site is
#: free to appear and a dropped one is named. `tools/d9_corpus_baseline.py::
#: run_cell::_pr.run` is the fourth converted site and is deliberately NOT
#: here: `tools/` is outside the shipped plugin package and outside the
#: population this test derives. Stated rather than silently absent.


# ===========================================================================
# CAUSE 3 — a node id the subject chose was longer than the channel
# ===========================================================================


# ===========================================================================
# CAUSE 4 — a grace shorter than a budget the subject itself declares
# ===========================================================================
_LONG = "VIBEIC_SILENCE_BUDGET_S = 1800\n\ndef test_ok():\n    assert True\n"
_OVER = ("VIBEIC_SILENCE_BUDGET_S = 99999\n\n"
         "def test_ok():\n    assert True\n")
_COMPUTED = ("import os\n"
             "VIBEIC_SILENCE_BUDGET_S = int(os.environ.get('X', '900'))\n\n"
             "def test_ok():\n    assert True\n")


# ===========================================================================
# CAUSE 4b — nothing about the stall detector changed, and it still fires
# ===========================================================================
_WEDGED = (
    "import threading\n"
    "def test_wedged():\n"
    "    threading.Event().wait()\n"
)


_WEDGED_DECLARING = (
    "VIBEIC_SILENCE_BUDGET_S = 30\n"
    "import threading\n"
    "def test_wedged():\n"
    "    threading.Event().wait()\n"
)


def test_a_declaring_file_that_wedges_is_STILL_killed_at_its_own_number(
        tmp_path):
    """THE CONTROL ON THE NEW MECHANISM ITSELF — the one that decides whether
    it is a supervision policy or an off switch.

    A declaration WIDENS a grace; it does not remove one. This file asks for 30
    s and then wedges forever. It must be killed, it must be NORECORD, and the
    refusal must quote 30 — not the base 20 it was driven with, which would mean
    the declaration was never honoured, and not silence, which would mean it was
    honoured as an exemption.

    30 s is the smallest number that is BOTH larger than the base grace this
    helper drives with (20 s) and therefore actually exercises the widening.
    """
    corpus = _tree(tmp_path, {"test_wedged_declaring.py": _WEDGED_DECLARING})
    started = time.monotonic()
    elapsed = time.monotonic() - started
    # It waited for the DECLARED number rather than the base one. Load can only
    # make this larger, so the lower bound is the safe direction to assert.
    assert elapsed >= 25, (
        f"the run ended after {elapsed:.1f}s, before the 30 s it declared — "
        "the base grace fired and the declaration did nothing")
