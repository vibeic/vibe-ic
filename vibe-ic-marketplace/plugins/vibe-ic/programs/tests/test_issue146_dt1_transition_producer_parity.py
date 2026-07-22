"""#146 blocker-2 — DT1 transition-coverage producer must fire from PHASE 3.

The Step-11 scan cut (`cut_netlist.v`) is only born by the time phase3 runs, so
the DT1 transition producer — like the DT2 path-delay producer — must run from
phase3_one_shot_runner once the cut exists. Without it, DT1's gate
(transition_coverage_check) hard-FAILs on a permanently-absent
transition_coverage.json (evidence: sha256 clean_run_v1422 produced
path_delay_coverage.json but NOT transition_coverage.json).

This is a STRUCTURAL parity test over the runner source (the giant phase3 runner
block is integration-tested end-to-end, not unit-callable): it pins that the DT1
producer is wired next to DT2, guarded on cut_netlist.v, invoking
transition_fault_atpg_run.py, and placed BEFORE the DT2 block (so DT3, which
needs BOTH coverage files, can fire).
"""
from __future__ import annotations

from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
_SRC = (PROG / "phase3_one_shot_runner.py").read_text()


def test_dt1_producer_invokes_transition_atpg():
    assert "transition_fault_atpg_run.py" in _SRC


def test_dt1_producer_guarded_on_cut_and_regrade():
    # Produce/RE-GRADE when the cut exists AND the report needs (re-)grading:
    # absent, or a NON-GRADED placeholder (BLOCKED / ENGINE_LIMITED / ERROR)
    # left by the phase2 pass on the GENERIC pre-map netlist. A real
    # PASS/NOT_APPLICABLE is preserved (the re-grade guard is idempotent).
    assert '_dt1_cut = project / "phase2/stage2/dft/cut_netlist.v"' in _SRC
    assert '_dt1_json = project / "reports/phase2/dft/transition_coverage.json"' \
        in _SRC
    assert "if _dt1_cut.is_file() and _dt_needs_regrade(_dt1_json):" in _SRC
    # the shared re-grade predicate must re-run only NON-graded placeholders
    assert "def _dt_needs_regrade(" in _SRC
    assert '"BLOCKED", "ENGINE_LIMITED", "ERROR"' in _SRC


def test_dt1_producer_runs_before_dt2():
    i_dt1 = _SRC.index("_dt1_json = project")
    i_dt2 = _SRC.index("_dt2_json = project")
    assert i_dt1 < i_dt2, "DT1 producer must precede DT2 so DT3 can fire"


def test_dt1_producer_is_nonfatal():
    # the producer must be best-effort (a try/except that appends a note),
    # never crash the phase3 finalize.
    seg = _SRC[_SRC.index("_dt1_json = project"):_SRC.index("_dt2_json = project")]
    assert "transition_fault_atpg non-fatal" in seg
