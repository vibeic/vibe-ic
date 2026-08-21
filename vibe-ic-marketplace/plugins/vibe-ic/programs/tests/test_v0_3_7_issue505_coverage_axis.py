"""v0.3.7 — #505: standalone-design runner collapsed overall=FAIL on a
Phase-1 doc-extraction coverage=0% even when every RTL gate
(synth/lint/sdc) PASSed. doc-extraction-coverage and the digital-backend
deliverable are two ORTHOGONAL axes; a coverage-only phase1 failure must
not gate the RTL verdict in the standalone-design shape (--skip-phase3).

Fix shape:
  * phase1_doc_one_shot_runner classifies its end-of-main exit
    (`_v0_3_7_classify_phase1_exit`) and writes a structured
    `reports/phase1/phase1_exit_reason.json` sidecar with
    `coverage_only_failure` (FAIL whose SOLE cause is coverage, zero TODO
    stubs);
  * vibe_ic_one_shot_runner, on a phase1 FAIL in the standalone-design
    shape, reads that sidecar and demotes a coverage-only failure to a
    non-gating COVERAGE-INCOMPLETE advisory, lets phase2 run, and the
    overall verdict follows the RTL deliverable.

These tests pin the pure decision helpers on BOTH sides plus the
sidecar round-trip — the e2e (real synth/lint/sdc) needs the EDA
toolchain and is exercised by the bench harness, not unit tests.
Chip-AGNOSTIC: only counters/verdict strings participate.
"""
import json
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGRAMS))
import phase1_doc_one_shot_runner as P1D  # noqa: E402
import vibe_ic_one_shot_runner as ORCH  # noqa: E402


# ── phase1_doc side: exit classification ─────────────────────────────

def test_coverage_zero_no_todo_is_coverage_only():
    # the exact #505 scenario: curated checklist 0/1 = 0% under --strict,
    # zero TODO stubs → coverage-only FAIL.
    r = P1D._v0_3_7_classify_phase1_exit(
        cov_gate_failed=False, strict=True, pct=0.0, total_todo=0)
    assert r["verdict"] == "FAIL"
    assert r["coverage_only_failure"] is True
    assert r["coverage_pct"] == 0.0 and r["total_todo"] == 0


def test_opcode_cov_gate_failure_is_coverage_only():
    # the unconditional opcode-name coverage gate is also a doc-extraction
    # axis → coverage-only when no TODO stubs.
    r = P1D._v0_3_7_classify_phase1_exit(
        cov_gate_failed=True, strict=False, pct=100.0, total_todo=0)
    assert r["verdict"] == "FAIL" and r["coverage_only_failure"] is True


def test_todo_stubs_is_NOT_coverage_only():
    # TODO stubs are a real generated-doc incompleteness → keeps gating.
    r = P1D._v0_3_7_classify_phase1_exit(
        cov_gate_failed=False, strict=True, pct=0.0, total_todo=3)
    assert r["verdict"] == "FAIL" and r["coverage_only_failure"] is False


def test_coverage_low_but_not_strict_passes():
    # without --strict and without the opcode gate, low coverage alone is
    # not a failure at all.
    r = P1D._v0_3_7_classify_phase1_exit(
        cov_gate_failed=False, strict=False, pct=0.0, total_todo=0)
    assert r["verdict"] == "PASS" and r["coverage_only_failure"] is False


def test_full_coverage_passes():
    r = P1D._v0_3_7_classify_phase1_exit(
        cov_gate_failed=False, strict=True, pct=100.0, total_todo=0)
    assert r["verdict"] == "PASS" and r["coverage_only_failure"] is False


# ── orchestrator side: sidecar reader ────────────────────────────────

def _write_sidecar(tmp_path: Path, payload: dict) -> Path:
    d = tmp_path / "reports" / "phase1"
    d.mkdir(parents=True)
    (d / "phase1_exit_reason.json").write_text(json.dumps(payload))
    return tmp_path


def test_reader_detects_coverage_only(tmp_path):
    proj = _write_sidecar(tmp_path, {
        "verdict": "FAIL", "coverage_pct": 0.0, "total_todo": 0,
        "coverage_only_failure": True})
    flag, reason = ORCH._phase1_failure_is_coverage_only(proj)
    assert flag is True and reason["coverage_pct"] == 0.0


def test_reader_false_when_not_coverage_only(tmp_path):
    proj = _write_sidecar(tmp_path, {
        "verdict": "FAIL", "total_todo": 3, "coverage_only_failure": False})
    flag, _ = ORCH._phase1_failure_is_coverage_only(proj)
    assert flag is False


def test_reader_false_when_sidecar_absent(tmp_path):
    # prompt-mode phase1 writes no sidecar → default halting preserved.
    flag, reason = ORCH._phase1_failure_is_coverage_only(tmp_path)
    assert flag is False and reason == {}


# ── orchestrator side: aggregate treats COVERAGE-INCOMPLETE as advisory ─

def test_aggregate_coverage_incomplete_with_pass_is_pass_with_waivers():
    # phase1 demoted + phase2 PASS → overall PASS_WITH_WAIVERS (gap shown,
    # not hidden, not FAIL).
    assert ORCH._aggregate(
        ["COVERAGE-INCOMPLETE", "PASS"]) == "PASS_WITH_WAIVERS"


def test_aggregate_coverage_incomplete_with_fail_still_fails():
    # a real RTL failure downstream still fails — demotion never masks it.
    assert ORCH._aggregate(["COVERAGE-INCOMPLETE", "FAIL"]) == "FAIL"


def test_aggregate_plain_pass_unchanged():
    assert ORCH._aggregate(["PASS", "PASS"]) == "PASS"
