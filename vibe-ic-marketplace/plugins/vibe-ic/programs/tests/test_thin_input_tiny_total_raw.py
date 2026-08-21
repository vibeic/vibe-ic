"""Tests for v0.1.57 R7 capture: _is_thin_input_eligible must also fire on
"tiny absolute-size input" (extractor caught 100% of a brief input).

Captured from v0.1.56 CVDP run: both projects had phase1 coverage=100%
(captured everything) but sum(raw_total) was 0 and 3 respectively. The
prior predicate (any doc <100%) returned False so the 3 structural gates
(l_doc_structured_field_count_check / l9_submodule_conformance_check /
metadata_content_substance_check) failed without a waiver path, making
the final_audit FAIL even though all RTL/synth/lint gates passed.

The fix adds a TINY_INPUT_TOTAL_RAW_TOKENS predicate orthogonal to coverage.
"""
import importlib
import json
import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]


def _load():
    if "flow_compliance_check" in sys.modules:
        del sys.modules["flow_compliance_check"]
    sys.path.insert(0, str(PROGRAMS))
    return importlib.import_module("flow_compliance_check")


def _make_phase1_report(project: Path, per_doc: list):
    """Write a synthetic phase1_input_vs_generated_completeness.json."""
    reports = project / "reports" / "phase1"
    reports.mkdir(parents=True, exist_ok=True)
    (reports / "phase1_input_vs_generated_completeness.json").write_text(
        json.dumps({"per_doc": per_doc}))


def test_tiny_total_raw_zero_is_thin_eligible(tmp_path):
    """v0.1.56 CVDP fixed_arbiter case: 1 doc, raw_total=0, captured=100%."""
    mod = _load()
    proj = tmp_path / "p"
    proj.mkdir()
    _make_phase1_report(proj, [
        {"name": "design_description.md", "raw_total": 0, "captured_pct": 1.0}])
    assert mod._is_thin_input_eligible(proj) is True


def test_tiny_total_raw_three_is_thin_eligible(tmp_path):
    """v0.1.56 CVDP priority_encoder case: 1 doc, raw_total=3, captured=100%."""
    mod = _load()
    proj = tmp_path / "p"
    proj.mkdir()
    _make_phase1_report(proj, [
        {"name": "design_description.md", "raw_total": 3, "captured_pct": 1.0}])
    assert mod._is_thin_input_eligible(proj) is True


def test_tiny_total_threshold_boundary(tmp_path):
    """Exactly at the threshold: still thin-eligible (predicate is <=)."""
    mod = _load()
    proj = tmp_path / "p"
    proj.mkdir()
    _make_phase1_report(proj, [
        {"name": "d.md", "raw_total": mod.TINY_INPUT_TOTAL_RAW_TOKENS,
         "captured_pct": 1.0}])
    assert mod._is_thin_input_eligible(proj) is True


def test_rich_total_raw_not_thin_eligible_when_captured_100(tmp_path):
    """A real SoC-grade project (raw_total well above threshold + 100% capture)
    must NOT be considered thin — the structural gates apply."""
    mod = _load()
    proj = tmp_path / "p"
    proj.mkdir()
    _make_phase1_report(proj, [
        {"name": "d.md", "raw_total": 5000, "captured_pct": 1.0}])
    assert mod._is_thin_input_eligible(proj) is False


def test_rich_total_raw_with_coverage_gap_still_thin_eligible(tmp_path):
    """The original "any doc below 100% capture" predicate still fires when
    a rich project shows real extractor gaps."""
    mod = _load()
    proj = tmp_path / "p"
    proj.mkdir()
    _make_phase1_report(proj, [
        {"name": "d.md", "raw_total": 5000, "captured_pct": 0.85}])
    assert mod._is_thin_input_eligible(proj) is True


def test_reference_docs_excluded_from_total(tmp_path):
    """reference_doc entries don't count toward the thin-total predicate."""
    mod = _load()
    proj = tmp_path / "p"
    proj.mkdir()
    _make_phase1_report(proj, [
        {"name": "ref.md", "raw_total": 99999,
         "captured_pct": 1.0, "reference_doc": True},
        {"name": "d.md", "raw_total": 5, "captured_pct": 1.0}])
    # raw_total non-reference = 5 (≤ threshold) → thin-eligible
    assert mod._is_thin_input_eligible(proj) is True


# ── Waiver-gate list extension ────────────────────────────────────────────

def test_l9_submodule_conformance_in_waiver_gates():
    """v0.1.57: l9_submodule_conformance_check must be in the waiver list."""
    mod = _load()
    assert "l9_submodule_conformance_check" in mod._THIN_INPUT_WAIVER_GATES


def test_metadata_content_substance_in_waiver_gates():
    """v0.1.57: metadata_content_substance_check must be in the waiver list."""
    mod = _load()
    assert "metadata_content_substance_check" in mod._THIN_INPUT_WAIVER_GATES


def test_existing_thin_input_gates_preserved():
    """The original two gates must remain — extension is additive."""
    mod = _load()
    assert "phase1_doc_input_completeness_check" in mod._THIN_INPUT_WAIVER_GATES
    assert "l_doc_structured_field_count_check" in mod._THIN_INPUT_WAIVER_GATES


def test_tiny_input_constant_is_small():
    """The threshold must be small (<= 500) — we're catching atomic
    single-module IPs, not full SoCs."""
    mod = _load()
    assert mod.TINY_INPUT_TOTAL_RAW_TOKENS <= 500
