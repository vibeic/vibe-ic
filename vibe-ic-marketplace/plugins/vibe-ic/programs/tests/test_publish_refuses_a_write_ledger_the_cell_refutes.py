#!/usr/bin/env python3
"""A published cell may not carry a write ledger its own contents refute.

`step_write_ledger` records a SNAPSHOT of the run tree: what existed at the
instant it walked. `benchmark_evidence_publish` copies `reports/` wholesale, so
whichever snapshot happens to be lying in the run directory at publish time is
staged as though it described the tree being staged. Nothing re-checked it.

MEASURED 2026-08-13 on `benchmark-data/ic/spm/v1.9.96_gf180mcuD`: ledger
captured 2026-08-06T19:17:51Z, `phase2/stage2/dft/scan_netlist.v` written by
the same run at 2026-08-07 08:39:52 (the file's own Fault header), publish
staged the finished tree beside the mid-run record, and the commit therefore
carries a ledger stating four artefacts were never written which that same
commit carries non-empty and tracked at HEAD.

That matters because `test_matrix_d3_outputs_produced` binds a run root's
verdict to that root's ledger and the binding may only ever SUBTRACT, so a
stale record refuses a real artefact at exactly the declared path and quotes
itself as the authority.

BOTH DIRECTIONS ARE ASSERTED HERE, which is the whole point of a guard: it
REFUSES a publish whose ledger the cell refutes, and it PASSES a publish whose
ledger the cell agrees with. A check that only ever measures zero has not been
shown to work.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "benchmark_evidence_publish.py"
sys.path.insert(0, str(PROG.parent))
import benchmark_evidence_publish as B  # noqa: E402

_GDS_BYTES = b"GDSII-FAKE-STREAM-" * 64
_RESULT_PASS = "# RESULT\n\n## VERDICT\n\n**PASS_WITH_WAIVERS.** re-derived.\n"

#: The path the fixture run really writes. The RED arm points the ledger's
#: "never written" finding at THIS path; the GREEN arm points it somewhere the
#: run genuinely does not have. Same ledger schema, same publish, one bit of
#: difference — so a pass cannot come from the guard being inert.
_REAL = "phase2/stage2/synth/netlist.v"
_ABSENT = "phase2/stage2/dft/scan_netlist.v"


def _ledger(spec: str, captured: str = "2026-08-06T19:17:51Z") -> dict:
    """The emitter's shape, reduced to the half this guard reads."""
    return {
        "schema": "step_write_ledger/1",
        "project": "/somewhere/else/run",
        "captured_at": captured,
        "steps": [{
            "id": "12",
            "name": "Post-DFT optimization",
            "findings": [{
                "dimension": "D3",
                "kind": "finding",
                "rule": "declared_output_not_produced",
                "step": "12",
                "spec": spec,
                "reason": "absent",
                "detail": "no path on disk matches this spec",
            }],
        }],
    }


def _make_run(base: Path, ledger: dict | None) -> Path:
    run = base / "run"
    (run / "reports" / "audit").mkdir(parents=True)
    (run / "reports" / "audit" / "phase23_completion_audit.json").write_text(
        json.dumps({"verdict": "PASS_WITH_WAIVERS"}))
    (run / "RESULT.md").write_text(_RESULT_PASS)
    (run / "phase1" / "generated_docs").mkdir(parents=True, exist_ok=True)
    (run / "phase1" / "generated_docs" / "L1.json").write_text("{}")
    (run / "phase2" / "stage2" / "synth").mkdir(parents=True, exist_ok=True)
    (run / _REAL).write_text("module top; endmodule\n")
    (run / "phase3" / "reports").mkdir(parents=True, exist_ok=True)
    (run / "phase3" / "reports" / "drc.rpt").write_text("clean\n")
    (run / "reports" / "phase3").mkdir(parents=True, exist_ok=True)
    (run / "reports" / "phase3" / "sta.json").write_text("{}")
    (run / "provenance.jsonl").write_text('{"tool":"yosys"}\n')
    (run / "phase3" / "stage4" / "gds").mkdir(parents=True, exist_ok=True)
    (run / "phase3" / "stage4" / "gds" / "top.gds").write_bytes(_GDS_BYTES)
    if ledger is not None:
        (run / "reports" / "write_ledger.json").write_text(json.dumps(ledger))
    return run


def _publish(run: Path, dest_root: Path):
    return subprocess.run(
        [sys.executable, str(PROG),
         "--run-dir", str(run), "--ic", "widgetmul", "--pdk", "openpdkx",
         "--plugin-version", "9.9.9", "--dest-root", str(dest_root)],
        capture_output=True, text=True)


# --------------------------------------------------------------------------
# the predicate, both directions
# --------------------------------------------------------------------------

def test_the_guard_finds_the_claim_the_cell_refutes(tmp_path):
    """RED arm. The ledger says `_REAL` was never written; the cell carries it."""
    cell = tmp_path / "cell"
    (cell / "phase2" / "stage2" / "synth").mkdir(parents=True)
    (cell / _REAL).write_text("module top; endmodule\n")
    (cell / "reports").mkdir(parents=True)
    (cell / "reports" / "write_ledger.json").write_text(
        json.dumps(_ledger(_REAL)))

    problems = B.stale_write_ledger(cell)
    assert len(problems) == 1, problems
    assert _REAL in problems[0]
    assert "NOT WRITTEN" in problems[0]


def test_the_guard_is_silent_when_the_record_is_true(tmp_path):
    """GREEN arm — and it must be a REAL green, not an inert one.

    Identical cell, identical ledger schema, identical publish; the ONLY
    difference is that the spec the ledger calls absent really is absent. If
    this and the test above ever agree, the guard has stopped measuring.
    """
    cell = tmp_path / "cell"
    (cell / "phase2" / "stage2" / "synth").mkdir(parents=True)
    (cell / _REAL).write_text("module top; endmodule\n")
    (cell / "reports").mkdir(parents=True)
    (cell / "reports" / "write_ledger.json").write_text(
        json.dumps(_ledger(_ABSENT)))

    assert B.stale_write_ledger(cell) == []


def test_a_zero_byte_artefact_does_not_refute_the_record(tmp_path):
    """`absent` and `written 0 bytes` are different findings.

    A 0-byte file is equally consistent with "the tool never wrote anything",
    so it is not the evidence that proves the ledger wrong, and promoting it
    here would make the guard refuse publishes over nothing.
    """
    cell = tmp_path / "cell"
    (cell / "phase2" / "stage2" / "synth").mkdir(parents=True)
    (cell / _REAL).write_text("")
    (cell / "reports").mkdir(parents=True)
    (cell / "reports" / "write_ledger.json").write_text(
        json.dumps(_ledger(_REAL)))

    assert B.stale_write_ledger(cell) == []


def test_a_cell_with_no_ledger_is_not_a_finding(tmp_path):
    """Publishing no ledger is allowed; it is what a run that never ran the
    emitter does. Only a ledger that LIES is refused."""
    cell = tmp_path / "cell"
    cell.mkdir()
    assert B.stale_write_ledger(cell) == []


# --------------------------------------------------------------------------
# the seam: publish itself
# --------------------------------------------------------------------------

def test_publish_refuses_a_run_whose_ledger_its_own_tree_refutes(tmp_path):
    run = _make_run(tmp_path, _ledger(_REAL))
    r = _publish(run, tmp_path / "dest")
    assert r.returncode == 1, (r.returncode, r.stdout, r.stderr)
    assert "REFUSED" in r.stderr
    assert "write ledger" in r.stderr
    assert _REAL in r.stderr
    # The refusal must name the repair, and it must not be "re-emit over the
    # cell" -- a cell's mtimes are a copy's, so that record's time-derived half
    # is withheld and the D5/D7 totals fall to zero.
    assert "FINISHED run" in r.stderr


def test_publish_accepts_a_run_whose_ledger_is_true_of_it(tmp_path):
    run = _make_run(tmp_path, _ledger(_ABSENT))
    r = _publish(run, tmp_path / "dest")
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
    cell = tmp_path / "dest" / "ic" / "widgetmul" / "v9.9.9_openpdkx"
    assert (cell / "reports" / "write_ledger.json").is_file(), \
        "a TRUE ledger must still be published; the guard filters lies, not records"


def test_publish_still_works_with_no_ledger_at_all(tmp_path):
    run = _make_run(tmp_path, None)
    r = _publish(run, tmp_path / "dest")
    assert r.returncode == 0, (r.returncode, r.stdout, r.stderr)
