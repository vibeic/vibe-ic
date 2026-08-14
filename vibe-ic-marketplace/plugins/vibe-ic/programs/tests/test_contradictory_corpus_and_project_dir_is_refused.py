#!/usr/bin/env python3
"""A positional beside --corpus was swallowed, so a "safe" write destroyed the record.

THE DEFECT
==========
`project_dir` is `nargs="?"` and `--corpus` selects the other mode; the two are
mutually exclusive, and supplying both was accepted with no error. Combined
with `--write-baseline` being `store_true` (it takes no path), an operator who
aims the write at a scratch file hits this, MEASURED on `a38902d16`:

    $ ...step_internal_fail_bubble_up_check.py --corpus <empty> \
          --write-baseline <scratch.json>
    rc=0
    wrote programs/step_internal_fail_bubble_up_baseline.json (findings_total=0)

`<scratch.json>` landed in `project_dir` and was dropped. The scratch file was
UNTOUCHED and the REAL record was zeroed — precisely the destruction
vibe-ic#1025 refuses to perform by hand, reached by someone who believed they
had aimed somewhere safe. I hit it myself while verifying #1025.

RELATION TO #1098, which is a different fix for a different half
================================================================
#1098 makes a ZERO-REACH write refuse, which closes the command above. It does
NOT close this one: with a NON-EMPTY corpus the same command still writes the
default baseline and still ignores the path the operator named. The refusal
here is about the CONTRADICTORY INVOCATION, not about reach, and the two
compose — with both in place the command is refused for the earlier reason.

WHY rc 2
========
"The request was not understood" is not "the design failed". Same tri-state the
rest of this program uses.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
CHECK = PLUGIN_ROOT / "programs" / "step_internal_fail_bubble_up_check.py"
REAL_BASELINE = (PLUGIN_ROOT / "programs" /
                 "step_internal_fail_bubble_up_baseline.json")
CORPUS = PLUGIN_ROOT.parents[2] / "benchmark-data"


def _run(*argv):
    p = subprocess.run([sys.executable, str(CHECK), *argv],
                       capture_output=True, text=True, timeout=55)
    return p.returncode, p.stdout + p.stderr


def _findings(path: Path):
    return json.loads(path.read_text()).get("findings_total")


# ===========================================================================
# THE RULE
# ===========================================================================
def test_a_positional_beside_corpus_is_REFUSED_not_swallowed(tmp_path):
    """THE DEFECT. Both modes given -> refuse, do not silently drop one."""
    empty = tmp_path / "empty"
    empty.mkdir()
    scratch = tmp_path / "scratch.json"
    scratch.write_text(REAL_BASELINE.read_text())
    rc, out = _run("--corpus", str(empty), "--write-baseline", str(scratch))
    assert rc == 2, f"contradictory invocation was not refused; rc={rc}\n{out}"
    assert "REFUSED" in out and "mutually exclusive" in out, out
    assert "--baseline" in out, (
        "the refusal must name the correct spelling, or the operator repeats "
        "the mistake")


def test_the_REAL_baseline_is_untouched_by_that_invocation(tmp_path):
    """The consequence, asserted separately from the exit code.

    A refusal that still wrote would satisfy the test above while doing the
    exact damage. `findings_total` is read before and after and must be equal.
    """
    before = _findings(REAL_BASELINE)
    assert before is not None
    empty = tmp_path / "empty"
    empty.mkdir()
    rc, _out = _run("--corpus", str(empty), "--write-baseline",
                    str(tmp_path / "scratch.json"))
    assert rc == 2
    assert _findings(REAL_BASELINE) == before, (
        f"the refused invocation still rewrote the shipped baseline: "
        f"{before} -> {_findings(REAL_BASELINE)}")


# ===========================================================================
# PAIRED GUARDS — refusing everything would pass the rule above
# ===========================================================================
def test_PAIRED_corpus_alone_is_NOT_refused(tmp_path):
    """Half 1. If `--corpus` alone started refusing, the ratchet would be off
    and the rule above would still pass."""
    empty = tmp_path / "empty"
    empty.mkdir()
    rc, out = _run("--corpus", str(empty))
    assert "REFUSED" not in out or "mutually exclusive" not in out, out
    # An empty corpus is the vacuity tri-state (2), never a silent PASS.
    assert rc in (0, 1, 2), rc


def test_PAIRED_a_project_dir_alone_is_NOT_refused(tmp_path):
    """Half 2. The single-project mode is the program's primary use."""
    proj = tmp_path / "proj"
    (proj / "reports").mkdir(parents=True)
    rc, out = _run(str(proj))
    assert "mutually exclusive" not in out, out


def test_PAIRED_the_correct_spelling_still_writes_the_named_file(tmp_path):
    """Half 3, and the one that keeps this a check rather than a ban on
    `--write-baseline`. `--baseline <path> --write-baseline` must still aim
    where the operator says, and must write a REAL measurement."""
    if not CORPUS.is_dir():
        pytest.skip(f"no corpus at {CORPUS}")
    scratch = tmp_path / "aimed.json"
    shutil.copy(REAL_BASELINE, scratch)
    before_real = _findings(REAL_BASELINE)
    rc, out = _run("--corpus", str(CORPUS), "--baseline", str(scratch),
                   "--write-baseline")
    assert rc == 0, out
    assert str(scratch) in out, f"did not name the file it wrote:\n{out}"
    assert _findings(REAL_BASELINE) == before_real, (
        "aiming at a scratch file still rewrote the shipped baseline")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
