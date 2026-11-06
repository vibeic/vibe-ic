#!/usr/bin/env python3
"""The census step's timeout path must keep the promise its own docstring makes.

THE PROMISE, quoted from `gatekeeper_prepare_landing`'s module docstring:
a census step that cannot complete "leaves the landing exactly where it stood
before this step existed ... the only thing it can do is fail to save an hour".

THE DEFECT IT DID NOT KEEP IT UNDER (vibe-ic#1382, refuting PR #1659)
====================================================================
`subprocess.run(..., timeout=N)` kills the child with SIGKILL. A child's
``finally:`` therefore never runs, so the generator's own
``--written-json`` declaration is never written and `_read_written` returns
``[]``. Meanwhile `--fix` has already rewritten anchored figures: the tree IS
dirty. The boundary check downstream then sees a dirty path that nothing
declared and REFUSES, and `gatekeeper-land.sh` exits 1 on a refusal.

So on a loaded host — the exact condition the bound exists for — a best-effort
convenience turned into a landing that could not start. The old comment said
"anything written before it fired is still declared"; nothing was.

WHY THE FIRST TEST BELOW IS THE ONE THAT MATTERS
================================================
It asserts the OS behaviour directly rather than trusting the reading. If a
future Python made `subprocess.run` terminate gracefully, this test would fail
and the fix could be simplified — which is the honest way for a workaround to
expire.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_PROGRAMS = _HERE.parent
sys.path.insert(0, str(_PROGRAMS))

import _progress_run as PR  # noqa: E402




# ══════════════════════════════════════════════════════════════════════
# The premise, asserted rather than assumed
# ══════════════════════════════════════════════════════════════════════

def test_a_stopped_child_never_runs_its_finally(tmp_path):
    """This is WHY the declaration comes back empty. Assert it, do not argue it.

    THE STOP IS THE SUPERVISOR'S NOW (vibe-ic#2051, R4) and it is still a
    SIGKILL, so the premise is unchanged — but it is asserted against the call
    the census actually makes, not against a `subprocess.run` the census no
    longer contains. If a future supervisor stopped a child gracefully, this
    test fails and the workaround in the stall branch can be simplified: that
    is the honest way for a workaround to expire.
    """
    child = tmp_path / "child.py"
    decl = tmp_path / "written.json"
    child.write_text(
        "import sys, time, pathlib\n"
        "try:\n"
        "    time.sleep(30)\n"
        "finally:\n"
        "    pathlib.Path(sys.argv[1]).write_text('[\"a\"]')\n",
        encoding="utf-8")
    with pytest.raises(PR.Stalled):
        PR.run([sys.executable, str(child), str(decl)],
               stall_looks=4, poll_s=0.25)
    assert not decl.exists(), (
        "the supervisor stopped SIGKILLing a stalled child — the workaround in "
        "_default_census_writer's stall branch can now be simplified")




# ══════════════════════════════════════════════════════════════════════
# The behaviour, in both directions, against a real git tree
# ══════════════════════════════════════════════════════════════════════
