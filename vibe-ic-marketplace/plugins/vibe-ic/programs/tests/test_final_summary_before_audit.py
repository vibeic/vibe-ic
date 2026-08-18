"""Tests for v0.1.58 R8 capture: design_one_shot_runner must regenerate
`reports/final_summary.md` BEFORE invoking step_final_audit so the audit's
agent_report_sha256_attestation_check sees fresh attestations for every
artefact this phase2 run just emitted.

Captured from v0.1.57 CVDP run: the runner's final_audit reported
"agent_report_sha256_attestation_check — FAIL: 1 attestation gap(s)"
on a --skip-phase3 --skip-analog --skip-hardware path even though the
gate PASSes when invoked directly with the same project state. Root
cause: emit_final_summary ran AFTER step_final_audit at line 3564 instead
of before, so the audit read a stale attestation table.

The FPGA path at line 3545 already followed the correct pattern
(emit_final_summary → step_fpga_burn); the --skip-hardware path was
missing the parallel.
"""
import re
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
RUNNER = PROGRAMS / "design_one_shot_runner.py"


def test_emit_final_summary_precedes_step_final_audit():
    """The file must contain `emit_final_summary(...)` lexically BEFORE the
    `step_final_audit(project, phase=2, ...)` plan-append call."""
    src = RUNNER.read_text()
    # Find the line that appends step_final_audit at phase 2
    audit_pattern = re.compile(r"plan\.append\(\s*step_final_audit\(\s*project,\s*phase=2")
    m_audit = audit_pattern.search(src)
    assert m_audit is not None, "step_final_audit(phase=2) call not found"
    audit_offset = m_audit.start()

    # Find ALL emit_final_summary calls in the file
    summary_pattern = re.compile(r"_pl\.emit_final_summary\(\s*project")
    matches = list(summary_pattern.finditer(src))
    assert matches, "no _pl.emit_final_summary(project, ...) call found"

    # At least one must precede the audit append AND be reasonably close
    # (within the same function body — say within the prior 3000 chars).
    preceders = [m for m in matches
                 if 0 < (audit_offset - m.start()) < 3000]
    assert preceders, (
        "no emit_final_summary call within 3000 chars BEFORE "
        "step_final_audit(phase=2) — the audit will read a stale "
        "attestation table and FAIL with a phantom gap.")


def test_emit_final_summary_is_immediately_before_audit():
    """Stricter: the immediately-preceding line should mention final_summary
    so the ordering intent is locally obvious to future readers."""
    src = RUNNER.read_text()
    lines = src.splitlines()
    audit_line_idx = None
    for i, ln in enumerate(lines):
        if "plan.append(step_final_audit(project, phase=2" in ln:
            audit_line_idx = i
            break
    assert audit_line_idx is not None
    # Within the prior 10 lines, find an emit_final_summary mention
    window = lines[max(0, audit_line_idx - 10):audit_line_idx]
    found = any("emit_final_summary" in ln for ln in window)
    assert found, (
        "the 10 lines immediately before the phase=2 step_final_audit must "
        "include an _pl.emit_final_summary call so the intent is local. "
        "Window:\n" + "\n".join(window))


def test_fpga_burn_pattern_still_present():
    """The pre-fpga_burn emit_final_summary pattern (line ~3545, captured at
    v1.6.x) must NOT have been removed — that one is also load-bearing."""
    src = RUNNER.read_text()
    # The FPGA burn path uses emit_final_summary before step_fpga_burn
    # No need to over-specify line number; just check both appear in order.
    burn_pattern = re.compile(r"plan\.append\(\s*step_fpga_burn\(")
    m_burn = burn_pattern.search(src)
    assert m_burn is not None
    # An emit_final_summary call within 200 chars before the burn append
    head = src[max(0, m_burn.start() - 500):m_burn.start()]
    assert "_pl.emit_final_summary" in head, (
        "FPGA-burn path lost its pre-burn emit_final_summary — that pattern "
        "is also load-bearing for the SOF attestation gate.")
