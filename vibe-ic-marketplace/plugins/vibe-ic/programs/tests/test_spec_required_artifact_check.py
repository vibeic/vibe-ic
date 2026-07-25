"""test_spec_required_artifact_check.py — bidirectional tests.

Covers:
  spec_required_artifact_check.py:
    - DEFECT direction: input doc declares a required artifact that is ABSENT → FAIL
    - DEFECT direction: declared artifact exists but is 0 bytes → FAIL_EMPTY
    - FIXED direction: artifact present and non-empty → PASS
    - VACUOUS case: no MUST-emit clause in doc → VACUOUS_PASS (no crash)

  arith_declaration_emit.py:
    - PASS: all derivable inputs present → 6-field declaration.json emitted
    - FAIL-CLOSED: missing RTL → non-zero exit, no file written
"""

import json
import subprocess
import sys
import tempfile
import textwrap
from pathlib import Path

import pytest

PROGRAMS_DIR = Path(__file__).parent.parent

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_rundir(tmp_path: Path) -> Path:
    rd = tmp_path / "run"
    rd.mkdir()
    return rd


def _run_gate(run_dir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROGRAMS_DIR / "spec_required_artifact_check.py"),
         str(run_dir)],
        capture_output=True, text=True,
    )


def _run_emitter(run_dir: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROGRAMS_DIR / "arith_declaration_emit.py"),
         str(run_dir)],
        capture_output=True, text=True,
    )


def _write_input_doc(run_dir: Path, content: str) -> None:
    docs = run_dir / "input" / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L7_verification_plan.md").write_text(content)


# ---------------------------------------------------------------------------
# spec_required_artifact_check — DEFECT direction (absent artifact)
# ---------------------------------------------------------------------------

class TestGateDefectAbsent:
    """Gate must FAIL when a MUST-emit artifact is absent."""

    def test_english_must_emit_absent(self, tmp_path):
        rd = _make_rundir(tmp_path)
        _write_input_doc(rd, textwrap.dedent("""\
            ## Requirements
            The Plugin MUST emit `plugin_output/report.json` before sign-off.
        """))
        # Artifact NOT created — defect condition
        r = _run_gate(rd)
        assert r.returncode == 1, f"expected FAIL, got {r.returncode}\n{r.stdout}\n{r.stderr}"
        report = json.loads((rd / "reports/phase2/gates/spec_required_artifacts.json").read_text())
        assert report["verdict"] == "FAIL"
        assert report["failed_count"] >= 1
        fail = report["results"][0]
        assert fail["status"] == "FAIL_ABSENT"

    def test_zh_tw_must_emit_absent(self, tmp_path):
        rd = _make_rundir(tmp_path)
        _write_input_doc(rd, textwrap.dedent("""\
            Plugin 在開始 RTL 設計前，**必須**於 `plugin_output/declaration.json` 聲明下列項目。
        """))
        r = _run_gate(rd)
        assert r.returncode == 1
        report = json.loads((rd / "reports/phase2/gates/spec_required_artifacts.json").read_text())
        assert report["verdict"] == "FAIL"
        statuses = [res["status"] for res in report["results"]]
        assert "FAIL_ABSENT" in statuses


# ---------------------------------------------------------------------------
# spec_required_artifact_check — DEFECT direction (empty artifact)
# ---------------------------------------------------------------------------

class TestGateDefectEmpty:
    """Gate must FAIL when the declared artifact exists but is 0 bytes."""

    def test_english_must_emit_empty_file(self, tmp_path):
        rd = _make_rundir(tmp_path)
        _write_input_doc(rd, textwrap.dedent("""\
            The Plugin MUST emit `plugin_output/summary.json` with results.
        """))
        # Create 0-byte file
        out = rd / "plugin_output"
        out.mkdir(parents=True)
        (out / "summary.json").write_text("")
        r = _run_gate(rd)
        assert r.returncode == 1
        report = json.loads((rd / "reports/phase2/gates/spec_required_artifacts.json").read_text())
        assert report["verdict"] == "FAIL"
        statuses = [res["status"] for res in report["results"]]
        assert "FAIL_EMPTY" in statuses


# ---------------------------------------------------------------------------
# spec_required_artifact_check — FIXED direction
# ---------------------------------------------------------------------------

class TestGateFixed:
    """Gate must PASS when declared artifact is present and non-empty."""

    def test_english_artifact_present(self, tmp_path):
        rd = _make_rundir(tmp_path)
        _write_input_doc(rd, textwrap.dedent("""\
            The Plugin MUST emit `plugin_output/declaration.json` before sign-off.
        """))
        out = rd / "plugin_output"
        out.mkdir(parents=True)
        (out / "declaration.json").write_text('{"bit_order": "LSB_first"}')
        r = _run_gate(rd)
        assert r.returncode == 0, f"expected PASS\n{r.stdout}\n{r.stderr}"
        report = json.loads((rd / "reports/phase2/gates/spec_required_artifacts.json").read_text())
        assert report["verdict"] == "PASS"
        assert report["failed_count"] == 0

    def test_zh_tw_artifact_present(self, tmp_path):
        rd = _make_rundir(tmp_path)
        _write_input_doc(rd, textwrap.dedent("""\
            **必須**於 `plugin_output/declaration.json` 聲明下列項目
        """))
        out = rd / "plugin_output"
        out.mkdir(parents=True)
        (out / "declaration.json").write_text('{"bit_order": "LSB_first"}')
        r = _run_gate(rd)
        assert r.returncode == 0
        report = json.loads((rd / "reports/phase2/gates/spec_required_artifacts.json").read_text())
        assert report["verdict"] == "PASS"


# ---------------------------------------------------------------------------
# spec_required_artifact_check — VACUOUS case
# ---------------------------------------------------------------------------

class TestGateVacuous:
    """No MUST-emit clause → VACUOUS_PASS with explicit note."""

    def test_no_must_emit_clauses(self, tmp_path):
        rd = _make_rundir(tmp_path)
        _write_input_doc(rd, textwrap.dedent("""\
            # Verification Plan
            This document describes timing requirements.
            All outputs are optional and may be omitted.
        """))
        r = _run_gate(rd)
        assert r.returncode == 0, f"vacuous should exit 0\n{r.stdout}\n{r.stderr}"
        report = json.loads((rd / "reports/phase2/gates/spec_required_artifacts.json").read_text())
        assert report["verdict"] == "VACUOUS_PASS"
        assert "no MUST" in report["note"].lower() or "vacuous" in report["note"].lower() or "nothing" in report["note"].lower()

    def test_no_input_docs_dir(self, tmp_path):
        """No input/docs directory at all — should VACUOUS_PASS, not crash."""
        rd = _make_rundir(tmp_path)
        r = _run_gate(rd)
        assert r.returncode == 0
        report = json.loads((rd / "reports/phase2/gates/spec_required_artifacts.json").read_text())
        assert report["verdict"] == "VACUOUS_PASS"


# ---------------------------------------------------------------------------
# arith_declaration_emit — PASS direction (all inputs present)
# ---------------------------------------------------------------------------

_MINIMAL_RTL = textwrap.dedent("""\
    `default_nettype none
    //============================================================================
    // spm — serial-parallel multiplier
    // y : serial multiplier, LSB-first
    // p : serial product, LSB-first
    // Reset    : synchronous, active-high
    // Algorithm: textbook carry-save shift-add serial-parallel multiplier.
    //============================================================================
    module spm #(parameter size = 16) (
        input wire clk, input wire rst, input wire [size-1:0] x,
        input wire y, output wire p
    );
        reg yr; reg pr;
        always @(posedge clk) begin
            if (rst) begin yr <= 0; pr <= 0; end
            else begin yr <= y; pr <= yr & x[0]; end
        end
        assign p = pr;
    endmodule
    `default_nettype wire
""")

_MINIMAL_L2 = json.dumps({
    "schema_version": 2,
    "doc_class": "frs",
    "frs_sections": [{"content": 'Plugin 須聲明 "signed_2c" 或 "unsigned"；預設 signed_2c'}],
})

_VERIFY_REPORT = textwrap.dedent("""\
    # Report
    | Latency | **2 cycle** |
    CALIBRATED_LATENCY: 2  BIT_ORDER: LSB_first  SIZE: 16
""")


def _make_full_emitter_rundir(tmp_path: Path) -> Path:
    rd = tmp_path / "run"
    rtl_dir = rd / "phase2" / "stage1" / "rtl"
    rtl_dir.mkdir(parents=True)
    (rtl_dir / "myip.v").write_text(_MINIMAL_RTL)

    l_dir = rd / "phase1" / "generated_docs"
    l_dir.mkdir(parents=True)
    (l_dir / "L2_FRS.json").write_text(_MINIMAL_L2)

    scale_dir = rd / "_verify_scale"
    scale_dir.mkdir()
    (scale_dir / "REPORT.md").write_text(_VERIFY_REPORT)

    return rd


class TestEmitterPass:
    """Emitter emits a complete 6-field file when all inputs present."""

    def test_emits_complete_declaration(self, tmp_path):
        rd = _make_full_emitter_rundir(tmp_path)
        r = _run_emitter(rd)
        assert r.returncode == 0, f"expected PASS\n{r.stdout}\n{r.stderr}"
        out = rd / "plugin_output" / "declaration.json"
        assert out.exists(), "declaration.json not written"
        assert out.stat().st_size > 0
        d = json.loads(out.read_text())
        required_fields = {
            "bit_order", "reset_polarity", "latency_cycles",
            "integer_encoding", "multiplier_algorithm", "size_param",
        }
        missing = required_fields - d.keys()
        assert not missing, f"missing fields: {missing}"
        # Spot-check values
        assert d["bit_order"] in ("LSB_first", "MSB_first")
        assert isinstance(d["latency_cycles"], int) and d["latency_cycles"] >= 0
        assert d["size_param"] == 16
        assert d["reset_polarity"] == "active_high"
        assert d["integer_encoding"] == "signed_2c"


# ---------------------------------------------------------------------------
# arith_declaration_emit — FAIL-CLOSED (missing RTL)
# ---------------------------------------------------------------------------

class TestEmitterFailClosed:
    """Emitter exits non-zero and writes NO file when inputs are missing."""

    def test_missing_rtl_no_file_written(self, tmp_path):
        rd = tmp_path / "run"
        rd.mkdir()
        # No RTL dir at all
        r = _run_emitter(rd)
        assert r.returncode != 0, "expected non-zero exit on missing RTL"
        out = rd / "plugin_output" / "declaration.json"
        assert not out.exists(), "should NOT write declaration.json on failure"

    def test_missing_l2_no_file_written(self, tmp_path):
        rd = tmp_path / "run"
        rtl_dir = rd / "phase2" / "stage1" / "rtl"
        rtl_dir.mkdir(parents=True)
        (rtl_dir / "myip.v").write_text(_MINIMAL_RTL)
        scale_dir = rd / "_verify_scale"
        scale_dir.mkdir()
        (scale_dir / "REPORT.md").write_text(_VERIFY_REPORT)
        # L2_FRS.json deliberately absent → integer_encoding unknown
        r = _run_emitter(rd)
        assert r.returncode != 0
        out = rd / "plugin_output" / "declaration.json"
        assert not out.exists()

    def test_missing_calibration_no_file_written(self, tmp_path):
        rd = tmp_path / "run"
        rtl_dir = rd / "phase2" / "stage1" / "rtl"
        rtl_dir.mkdir(parents=True)
        (rtl_dir / "myip.v").write_text(_MINIMAL_RTL)
        l_dir = rd / "phase1" / "generated_docs"
        l_dir.mkdir(parents=True)
        (l_dir / "L2_FRS.json").write_text(_MINIMAL_L2)
        # No _verify_scale/REPORT.md and no _verify_gls or oracle manifest
        r = _run_emitter(rd)
        assert r.returncode != 0
        out = rd / "plugin_output" / "declaration.json"
        assert not out.exists()
