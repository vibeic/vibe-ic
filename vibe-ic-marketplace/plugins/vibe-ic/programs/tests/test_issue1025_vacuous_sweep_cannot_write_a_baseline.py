"""A sweep that examined nothing may neither PASS nor rewrite the record.

vibe-ic#1025, the two halves that were guarded only by prose.

MEASURED on `947547716` before the fix, with the real baseline copied to a
temp file so the repo's own record was never at risk::

    before: findings_total=7 runs_swept=17 per_run=4
    $ step_internal_fail_bubble_up_check.py \
        --corpus <empty> --baseline <copy> --write-baseline
    rc=0    wrote <copy> (findings_total=0)
    after:  findings_total=0 runs_swept=0  per_run=0

`--write-baseline` sat 14 lines ABOVE the `runs_with_reports == 0` check and
returned 0 before reaching it, so a sweep with zero reach rewrote the ratchet to
zero and called it success. The issue names exactly this danger and refuses to
run the command by hand — but nothing stopped anyone else from running it, and
"MAY ONLY SHRINK" is *satisfied* by that write, which is what makes it silent.

The second half is the verdict tier: a vacuous sweep must not return the same rc
as a sweep that examined everything and found nothing. That is fixed on main and
was likewise unpinned; a test lives here so it cannot regress quietly.

NOTHING HERE TOUCHES THE REPO'S BASELINE. Every case runs against a copy in
`tmp_path`, which is also what makes the destructive case safe to assert.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

PLUGIN_ROOT = Path(__file__).resolve().parent.parent.parent
PROGRAMS = PLUGIN_ROOT / "programs"
GATE = PROGRAMS / "step_internal_fail_bubble_up_check.py"
REAL_BASELINE = PROGRAMS / "step_internal_fail_bubble_up_baseline.json"

RC_VACUOUS = 2


def _empty_corpus(tmp_path: Path) -> Path:
    """A corpus with no published run tree — the zero-reach condition."""
    corpus = tmp_path / "empty_corpus"
    (corpus / "ic").mkdir(parents=True)
    return corpus


def _baseline_copy(tmp_path: Path) -> Path:
    """The REAL baseline, copied. Real so the destroy would be visible."""
    dst = tmp_path / "baseline.json"
    shutil.copy(REAL_BASELINE, dst)
    return dst


#: vibe-ic#1241 — 120s was above the 60s inner ceiling, and a bound above it can
#: outlive the 180s harness, which kills the SESSION rather than the test.
#:
#: MEASURED before lowering rather than snapped to the ceiling: the slowest test
#: in this file is 0.17s wall and each makes one `_run` call, so the real cost of
#: this subprocess is under 0.2s. 60s is ~350x that — margin for a loaded host
#: several times over, and still low enough that this call's own timeout fires
#: before the harness ends the session, which is the whole property the ceiling
#: exists to guarantee.
_GATE_TIMEOUT_S = 60


def _run(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, str(GATE), *args],
                          capture_output=True, text=True,
                          timeout=_GATE_TIMEOUT_S)


def test_write_baseline_refuses_a_sweep_that_examined_nothing(tmp_path):
    """The destroy, asserted as refused — and the file proved unchanged.

    Both halves matter: an rc alone could be returned *after* writing.
    """
    bl = _baseline_copy(tmp_path)
    before = bl.read_bytes()
    assert json.loads(before)["findings_total"] > 0, (
        "fixture premise: the shipped baseline records a non-zero total, "
        "otherwise a destroy-to-zero would be invisible here")

    r = _run("--corpus", str(_empty_corpus(tmp_path)),
             "--baseline", str(bl), "--write-baseline")

    assert r.returncode == RC_VACUOUS, (
        f"expected rc {RC_VACUOUS} (vacuous), got {r.returncode}\n"
        f"{r.stdout}{r.stderr}")
    assert bl.read_bytes() == before, (
        "the baseline was REWRITTEN by a sweep that examined nothing — this "
        "is the #1025 destroy, byte-compared, not inferred from the rc")
    assert "REFUSED" in (r.stdout + r.stderr)


def test_a_vacuous_sweep_does_not_return_the_pass_code(tmp_path):
    """Part 2: rc must distinguish 'examined nothing' from 'found nothing'."""
    r = _run("--corpus", str(_empty_corpus(tmp_path)))
    assert r.returncode == RC_VACUOUS, (
        f"a sweep with zero reach returned rc={r.returncode}; rc 0 would be "
        f"indistinguishable from a sweep that examined the whole corpus and "
        f"found no findings\n{r.stdout}{r.stderr}")
    assert "VACUOUS_PASS" in (r.stdout + r.stderr)


def test_write_baseline_still_works_when_the_sweep_actually_reaches(tmp_path):
    """The paired half — the refusal must not become a ban.

    A guard that refuses everything passes the test above while removing the
    command. This pins that a sweep WITH reach still writes.
    """
    repo_corpus = PLUGIN_ROOT.parent.parent.parent / "benchmark-data"
    if not repo_corpus.is_dir():
        import pytest
        pytest.skip("no benchmark-data corpus here")

    bl = tmp_path / "written.json"
    r = _run("--corpus", str(repo_corpus), "--baseline", str(bl),
             "--write-baseline")
    assert r.returncode == 0, f"{r.stdout}{r.stderr}"
    assert bl.is_file(), "reachable sweep did not write a baseline"
    written = json.loads(bl.read_text())
    assert written["runs_with_reports"] > 0, (
        "wrote a baseline whose own record says it examined nothing — the "
        "refusal above is then not measuring the condition it claims to")
    assert written["findings_total"] == sum(written["per_run"].values())
