"""Tests for programs/benchmark_triage_absorption_audit.py — the machine-
checkable CONVERGENCE BAR of the program-first + AI-backup doctrine
(open-benchmark-methodology § 4.2; user directive 2026-06-18).

The audit's load-bearing assertion: every benchmark fail whose verdict implies
AI-solvability (RECOVERABLE_AUTHORING / AUTHORING / LESSON_GATE_GAP /
SCORING_HARNESS_GAP / EXTRACTION_GAP / COVERAGE_GAP / CONVENTION_INFERENCE /
REAL_RTL_BUG, or any record whose independent_blind_passes==true) MUST carry an
`absorption_ref` (a program-rule patch id OR a gated-AI-step + test reference).
A fail is absorption-exempt ONLY if verdict ∈ {TRUE_FLOOR, DATASET_DEFECT} AND
it carries `floor_evidence` (blind-fails for TRUE_FLOOR; golden-fails-own-TB for
DATASET_DEFECT). A 'RECOVERABLE_AUTHORING' label is NOT a free pass; a bare
'TRUE_FLOOR' label cannot dodge a hard solve.

ACCEPTANCE shapes (from the doctrine spec):
  * un-absorbed RECOVERABLE_AUTHORING            → FAIL
  * same + absorption_ref                        → PASS
  * TRUE_FLOOR + floor_evidence (blind-fails)    → PASS  (exempt)
  * TRUE_FLOOR WITHOUT floor_evidence            → FAIL  (cannot dodge by label)
  * DATASET_DEFECT + golden-fails-own-TB ev.     → PASS
  * SCORING_HARNESS_GAP without absorption_ref   → FAIL
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
_PROG = _PROGRAMS / "benchmark_triage_absorption_audit.py"

if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))
import benchmark_triage_absorption_audit as M  # noqa: E402


def _audit(records):
    """Helper: run the in-process audit and return the report dict."""
    return M.audit_records(records)


def _run_cli(tmp_path, records, name="triage.json"):
    """Helper: write the records to disk and invoke the CLI; return (rc, report)."""
    p = tmp_path / name
    p.write_text(json.dumps(records))
    out = tmp_path / "report.json"
    cp = subprocess.run(
        [sys.executable, str(_PROG), str(p), "--json", str(out)],
        capture_output=True, text=True)
    report = json.loads(out.read_text())
    return cp.returncode, report


# ── the six acceptance shapes ──────────────────────────────────────────────
def test_unabsorbed_recoverable_authoring_fails(tmp_path):
    """An un-absorbed RECOVERABLE_AUTHORING fail → FAIL (rc=1). A
    'RECOVERABLE_AUTHORING' label is NOT a free pass to skip absorption."""
    recs = [{"id": "p1", "bench": "rtllm", "verdict": "RECOVERABLE_AUTHORING",
             "independent_blind_passes": True}]
    rc, rep = _run_cli(tmp_path, recs)
    assert rc == 1
    assert rep["verdict"] == "FAIL"
    assert rep["n_violations"] == 1
    assert rep["violations"][0]["id"] == "p1"


def test_recoverable_authoring_with_absorption_ref_passes(tmp_path):
    """The SAME RECOVERABLE_AUTHORING fail, once it carries an absorption_ref
    (program-rule patch id), → PASS (rc=0)."""
    recs = [{"id": "p1", "bench": "rtllm", "verdict": "RECOVERABLE_AUTHORING",
             "independent_blind_passes": True,
             "absorption_ref": "rtl_hygiene_lint.py:remainder-width-rule + "
                               "test_rtl_hygiene_lint::test_remainder_width"}]
    rc, rep = _run_cli(tmp_path, recs)
    assert rc == 0
    assert rep["verdict"] == "PASS"
    assert rep["n_violations"] == 0
    assert rep["n_absorbed"] == 1
    assert "p1" in rep["absorbed"]


def test_true_floor_with_evidence_blind_fails_passes(tmp_path):
    """A TRUE_FLOOR with floor_evidence AND independent_blind_passes==false
    (the AI tried and could NOT solve it blind) → PASS (exempt, rc=0)."""
    recs = [{"id": "ring_counter", "bench": "rtllm", "verdict": "TRUE_FLOOR",
             "independent_blind_passes": False,
             "floor_evidence": "TB uses VCS-only '{...} array-aggregate init at "
                               "testbench.v:42 — iverilog rejects; blind solve "
                               "also could not satisfy the hidden TB"}]
    rc, rep = _run_cli(tmp_path, recs)
    assert rc == 0
    assert rep["verdict"] == "PASS"
    assert rep["n_exempt"] == 1
    assert "ring_counter" in rep["exempt"]


def test_true_floor_without_evidence_fails(tmp_path):
    """A TRUE_FLOOR WITHOUT floor_evidence → FAIL (rc=1): you cannot dodge a hard
    solve by merely labelling something FLOOR."""
    recs = [{"id": "p2", "bench": "rtllm", "verdict": "TRUE_FLOOR",
             "independent_blind_passes": False}]
    rc, rep = _run_cli(tmp_path, recs)
    assert rc == 1
    assert rep["verdict"] == "FAIL"
    assert rep["violations"][0]["rule"] == "floor_without_evidence"


def test_dataset_defect_with_golden_fails_own_tb_passes(tmp_path):
    """A DATASET_DEFECT carrying golden-fails-own-TB evidence → PASS (rc=0)."""
    recs = [{"id": "Prob062", "bench": "verilogeval_v2", "verdict": "DATASET_DEFECT",
             "floor_evidence": "the unmodified golden RefModule fails its OWN "
                               "Prob062_test.sv at assertion line 88 (golden-"
                               "fails-own-TB)"}]
    rc, rep = _run_cli(tmp_path, recs)
    assert rc == 0
    assert rep["verdict"] == "PASS"
    assert rep["n_exempt"] == 1


def test_scoring_harness_gap_without_absorption_ref_fails(tmp_path):
    """A SCORING_HARNESS_GAP (AI-solvable harness work) without an absorption_ref
    → FAIL (rc=1)."""
    recs = [{"id": "cvdp_jsonl", "bench": "cvdp-open", "verdict": "SCORING_HARNESS_GAP"}]
    rc, rep = _run_cli(tmp_path, recs)
    assert rc == 1
    assert rep["verdict"] == "FAIL"
    assert rep["violations"][0]["rule"] == "unabsorbed_ai_solvable"


# ── reinforcing edge cases (the label-laundering guards) ─────────────────────
def test_true_floor_but_blind_passed_fails(tmp_path):
    """TRUE_FLOOR but independent_blind_passes==true is a contradiction — the AI
    solved it blind, so it is NOT a floor and MUST be absorbed → FAIL."""
    recs = [{"id": "p3", "verdict": "TRUE_FLOOR",
             "independent_blind_passes": True,
             "floor_evidence": "claimed floor"}]
    rc, rep = _run_cli(tmp_path, recs)
    assert rc == 1
    assert rep["violations"][0]["rule"] == "true_floor_blind_passed"


def test_blind_pass_with_non_solvable_label_still_needs_absorption():
    """A record whose verdict is not in the AI-solvable set but whose
    independent_blind_passes==true is STILL AI-solvable (the AI demonstrably
    solved it) — without an absorption_ref → violation."""
    rep = _audit([{"id": "x", "verdict": "DATASET_DEFECT",
                   "independent_blind_passes": True,
                   "floor_evidence": "claims defect"}])
    # blind passed → treated as solvable → contradiction with DATASET_DEFECT
    assert rep["verdict"] == "FAIL"
    assert rep["n_violations"] == 1


def test_mixed_set_all_converged_passes():
    """A realistic mixed residual set where every fail is converged → PASS."""
    rep = _audit([
        {"id": "a", "verdict": "RECOVERABLE_AUTHORING",
         "independent_blind_passes": True, "absorption_ref": "prog.py:r1 + test"},
        {"id": "b", "verdict": "TRUE_FLOOR", "independent_blind_passes": False,
         "floor_evidence": "blind also failed; spec under-discloses internal name"},
        {"id": "c", "verdict": "DATASET_DEFECT",
         "floor_evidence": "golden fails own TB"},
        {"id": "d", "verdict": "COVERAGE_GAP",
         "absorption_ref": "spec_coverage_check.py enum-boundary rule + test"},
    ])
    assert rep["verdict"] == "PASS"
    assert rep["n_absorbed"] == 2
    assert rep["n_exempt"] == 2


def test_unknown_verdict_fails():
    """An unrecognised verdict cannot be silently accepted → violation."""
    rep = _audit([{"id": "q", "verdict": "PROBABLY_FINE"}])
    assert rep["verdict"] == "FAIL"
    assert rep["violations"][0]["rule"] == "unknown_verdict"


def test_io_error_exit_2(tmp_path):
    """A missing input file → exit 2."""
    cp = subprocess.run(
        [sys.executable, str(_PROG), str(tmp_path / "nope.json")],
        capture_output=True, text=True)
    assert cp.returncode == 2


def test_help_runs():
    """--help works and documents the verdict vocabulary."""
    cp = subprocess.run([sys.executable, str(_PROG), "--help"],
                        capture_output=True, text=True)
    assert cp.returncode == 0
    assert "absorption_ref" in cp.stdout
    assert "TRUE_FLOOR" in cp.stdout


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
