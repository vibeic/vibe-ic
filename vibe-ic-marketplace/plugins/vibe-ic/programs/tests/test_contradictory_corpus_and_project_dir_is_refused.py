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
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

PLUGIN_ROOT = Path(__file__).resolve().parents[2]
CHECK = PLUGIN_ROOT / "programs" / "step_internal_fail_bubble_up_check.py"
REAL_BASELINE = (PLUGIN_ROOT / "programs" /
                 "step_internal_fail_bubble_up_baseline.json")


def _reachable_corpus(root: Path) -> Path:
    """A corpus of ONE published run tree, with one unacknowledged FAIL in it.

    The corpus was never this file's subject; it was the convenient way to get a
    NON-EMPTY population. `--write-baseline` refuses a sweep that reached
    nothing (vibe-ic#1098), so half 3 below — "the correct spelling still aims
    where the operator said" — needs a sweep that reaches something, and that is
    the whole requirement.

    It used to borrow the published corpus for that, which made a test about
    ARGUMENT HANDLING depend on which cells happened to be published. When the
    result cells moved to `vibeic/benchmark-data` the borrowed population went
    to zero and the write was refused, so the test failed while the behaviour it
    checks was intact. Built here instead: the population is one tree, always
    reachable, and the number the write records is one this test chose — so the
    docstring's "must write a REAL measurement" is now asserted rather than
    hoped for.

    Shape only, no design/PDK/vendor literal: `<corpus>/ic/<d>/<v>/reports/…`,
    with a `verdict: FAIL` report that no waiver and no orchestrator roll-up
    names, which is exactly one finding for the sweep to count.
    """
    run = root / "ic" / "design" / "v1_pdk"
    (run / "reports" / "phase3").mkdir(parents=True)
    (run / "reports" / "phase3" / "ir_drop.json").write_text(
        json.dumps({"verdict": "FAIL"}))
    return root


def _run(*argv):
    p = _pr.run([sys.executable, str(CHECK), *argv],
                       capture_output=True, text=True)
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
    where the operator says, and must write a REAL measurement.

    Driven over `_reachable_corpus`, for the reason given there."""
    corpus = _reachable_corpus(tmp_path / "corpus")
    scratch = tmp_path / "aimed.json"
    shutil.copy(REAL_BASELINE, scratch)
    before_real = _findings(REAL_BASELINE)
    # The scratch file is a COPY of the shipped register, and this fixture's
    # one-run corpus is smaller than the population that register describes, so
    # the aimed write LOWERS the denominator and needs the reason vibe-ic#1704
    # requires. That is the rule under test one file over; here it is fixture
    # setup, so the reason simply says what this write is.
    rc, out = _run("--corpus", str(corpus), "--baseline", str(scratch),
                   "--write-baseline", "--shrink-reason",
                   "aiming a copy of the shipped register at a single-run "
                   "synthetic corpus built by this test; the drop is the "
                   "fixture's own population, not anything measured about the "
                   "published one.")
    assert rc == 0, out
    assert str(scratch) in out, f"did not name the file it wrote:\n{out}"
    assert _findings(REAL_BASELINE) == before_real, (
        "aiming at a scratch file still rewrote the shipped baseline")
    # ...and what landed in the named file is the sweep's own measurement, not
    # a zero. `rc == 0` alone would be satisfied by a write of nothing, which is
    # the destruction #1025 refuses; the number is asserted because the fixture
    # is what fixes it.
    wrote = json.loads(scratch.read_text())
    assert wrote["runs_with_reports"] == 1, wrote
    assert wrote["findings_total"] == 1, (
        f"the aimed write did not record the sweep's own measurement: {wrote}")


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-q"]))
