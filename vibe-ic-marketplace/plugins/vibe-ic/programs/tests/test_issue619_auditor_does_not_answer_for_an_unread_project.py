"""#619 — the zero-denominator auditor answered PASS for a project it never read.

`gate_zero_denominator_refuses_check` audits the PROGRAM REGISTRY: it builds one
fresh empty project per gate and probes all 498. It also accepted a `project`
positional, ignored it, and answered PASS — byte-identical output for a path
that exists, a path that is empty, and a path that is not there:

    $ … gate_zero_denominator_refuses_check.py <a path that is not there>
    PASS — 498 gate(s) probed against an empty project; 22 stated a zero …
    rc=0

That is the exact shape the file exists to detect. Its own subject is "a zero
denominator that exits 0 is a silent pass", and it was reporting success over a
population it had never established, so a run pointed at a typo'd path read PASS.

Both registry-wide meta-checks caught it the moment it joined the registry it
audits — five tests across `test_issue511_empty_project_pass_disclosure` and
`test_issue564_honest_zero_census`, `PASS_ON_A_PROJECT_THAT_IS_NOT_THERE`. Main
was red on them.

THE FIX IS NOT "READ THE PROJECT". A registry-wide auditor legitimately does not
need one. What it must not do is accept an argument, ignore it, and answer PASS:
a path it will not read is a path it cannot vouch for, so an absent one is
NOT_CHECKED (rc 2, the disclosed-skip convention).

The output now also says what was audited. "probed against an empty project"
reads, to anyone who passed a project path, as a statement about THEIR project.
"""
from __future__ import annotations

import importlib
import pathlib
import subprocess
import sys

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
_GATE = _PROGRAMS / "gate_zero_denominator_refuses_check.py"

G = importlib.import_module("gate_zero_denominator_refuses_check")

#: MEASURED: one full 498-gate drive takes 3s on this host (the per-gate probes
#: run in a thread pool with their own 120s budget each). 60 is the harness
#: ceiling for an inner subprocess bound and leaves 20x headroom; the earlier
#: 600 both exceeded the ceiling and would have hidden a hang for ten minutes.
_BUDGET = 60


def _run(*args, timeout=_BUDGET):
    r = subprocess.run([sys.executable, str(_GATE), *args],
                       capture_output=True, text=True, timeout=timeout)
    return r.returncode, r.stdout + r.stderr


# ── the reported defect ─────────────────────────────────────────────────────
def test_a_project_that_is_not_there_is_not_a_pass(tmp_path):
    """THE ISSUE'S OWN REPRODUCTION."""
    missing = tmp_path / "no_such_project_xyz"
    rc, out = _run(str(missing), timeout=_BUDGET)
    assert rc == G.RC_CANNOT_PROBE, (rc, out[-400:])
    assert "does not exist" in out
    assert str(missing) in out, "the refusal must name the path it refused"


def test_the_refusal_says_why_rather_than_only_that(tmp_path):
    """A reader who passed a path needs to learn that this check never reads
    one — otherwise the obvious next move is to fix the path."""
    rc, out = _run(str(tmp_path / "nope"), timeout=_BUDGET)
    assert rc == G.RC_CANNOT_PROBE
    assert "PROGRAM REGISTRY" in out
    assert "never reads the project argument" in out


def test_the_refusal_is_cheap(tmp_path):
    """It must decline BEFORE driving 498 gates: an auditor that spends a
    minute to say "I cannot answer" gets run less, and this one guards the
    landing path."""
    import time
    t0 = time.time()
    _run(str(tmp_path / "nope"), timeout=_BUDGET)
    assert time.time() - t0 < 20, "the registry was driven before the refusal"


# ── the accept cases, which are what keep the check switched on ─────────────
def test_an_existing_empty_directory_still_runs_the_audit(tmp_path):
    """THE ACCEPT CASE. The project is not this check's population, so an empty
    one is no reason to decline — only an ABSENT one is."""
    rc, out = _run(str(tmp_path))
    assert rc == G.RC_OK, out[-500:]
    assert "gate(s) probed" in out


def test_the_standing_no_argument_invocation_is_unchanged():
    """`repo_hygiene_gates.sh` passes no project at all, so the default `.`
    must keep running the real audit — a fix that switched off the standing
    invocation would be the same defect from the other end."""
    rc, out = _run()
    assert rc == G.RC_OK, out[-500:]
    assert "498" in out or "gate(s) probed" in out


def test_the_output_no_longer_reads_as_a_statement_about_that_project(tmp_path):
    """The wording half. `probed against an empty project` is true of this
    check's own fixtures and false of anything the caller named."""
    _rc, out = _run(str(tmp_path))
    assert "is not read" in out
    assert "OWN fresh empty project" in out
    assert "probed against an empty project" not in out, (
        "the ambiguous sentence is back")


# ── it must stay inside the registry it audits ──────────────────────────────
def test_it_is_still_in_the_population_it_audits():
    """It is named `*_check.py` on purpose: a registry-wide auditor that dodges
    the registry convention by naming is how this defect would have gone
    unnoticed in the first place."""
    assert _GATE.name.endswith("_check.py")


def test_it_still_excludes_itself_from_its_own_probe(tmp_path):
    """LOAD-BEARING and found the expensive way: `project_check_programs` is
    `glob("*_check.py")`, so probing itself spawned the whole population again
    — a 35-minute hang and 75 orphaned processes."""
    import shutil
    shutil.copy(_GATE, tmp_path / _GATE.name)
    (tmp_path / "other_check.py").write_text(
        "print('PASS: 3 file(s) scanned')\n", encoding="utf-8")
    _v, _f, stats = G.audit(tmp_path, timeout=20, workers=2)
    assert stats["gates_probed"] == 1, stats
