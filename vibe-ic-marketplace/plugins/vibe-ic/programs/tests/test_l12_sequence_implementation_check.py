"""Unit tests for l12_sequence_implementation_check.py."""
import json
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "l12_sequence_implementation_check.py"
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"
sys.path.insert(0, str(SCRIPT.parent))

import l12_sequence_implementation_check as chk  # noqa: E402


def _write_rtl(rtl_dir, name, body):
    (rtl_dir / name).write_text(body)


def _write_l12(path, sequences):
    path.write_text(json.dumps({"sequences": sequences}))


# ---------------------------------------------------------------------------
# PASS paths
# ---------------------------------------------------------------------------
def test_no_l12_json_passes(tmp_path):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    findings, _ = chk.audit(rtl, None)
    assert not any(f.severity == "ERROR" for f in findings)


def test_empty_sequences_passes(tmp_path):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    l12 = tmp_path / "L12.json"
    _write_l12(l12, [])
    findings, _ = chk.audit(rtl, l12)
    assert not any(f.severity == "ERROR" for f in findings)


def test_implemented_sequence_passes(tmp_path):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    _write_rtl(
        rtl, "test_mode_entry.v",
        "module test_mode_entry (input clk);\n"
        "  reg [2:0] st;\n"
        "  always @(posedge clk) begin\n"
        "    case (st) 3'd0: st <= 3'd1; default: st <= 3'd0; endcase\n"
        "    if (st == 3'd1) ;\n"
        "    if (st == 3'd2) ;\n"
        "  end\n"
        "endmodule\n"
    )
    l12 = tmp_path / "L12.json"
    _write_l12(l12, [{"id": "TEST_MODE_ENTRY",
                       "category": "host_stimulus_sequence"}])
    findings, summary = chk.audit(rtl, l12)
    assert summary["sequences_checked"] == 1
    assert not any(f.severity == "ERROR" for f in findings)


def test_info_only_category_skipped(tmp_path):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    l12 = tmp_path / "L12.json"
    _write_l12(l12, [{"id": "SOME_NOTE_ONLY",
                       "category": "documentation_only"}])
    findings, summary = chk.audit(rtl, l12)
    assert summary["sequences_skipped"] == 1
    assert not any(f.severity == "ERROR" for f in findings)


def test_rtl_module_hint_honored(tmp_path):
    """Even if the id→name mapping doesn't match, explicit rtl_module wins."""
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    _write_rtl(
        rtl, "rx_cmd.v",
        "module rx_cmd (input clk);\n"
        "  reg [3:0] st;\n"
        "  always @(posedge clk) case (st) 4'd0: st <= 4'd1; endcase\n"
        "  always @(posedge clk) if (st == 4'd1) ;\n"
        "  always @(posedge clk) if (st == 4'd2) ;\n"
        "endmodule\n"
    )
    l12 = tmp_path / "L12.json"
    _write_l12(l12, [{
        "id": "RX_9_STEP_VALIDATION",
        "category": "validation_chain",
        "rtl_module": "rx_cmd.v — FSM drives cmd_valid..."
    }])
    findings, _ = chk.audit(rtl, l12)
    assert not any(f.severity == "ERROR" for f in findings)


# ---------------------------------------------------------------------------
# FAIL paths
# ---------------------------------------------------------------------------
def test_missing_impl_module_fails(tmp_path):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    # Only an unrelated file exists.
    _write_rtl(rtl, "pad_ctrl.v", "module pad_ctrl; endmodule\n")
    l12 = tmp_path / "L12.json"
    _write_l12(l12, [{"id": "TEST_MODE_ENTRY",
                       "category": "host_stimulus_sequence"}])
    findings, _ = chk.audit(rtl, l12)
    errors = [f for f in findings if f.severity == "ERROR"]
    assert len(errors) == 1
    assert errors[0].category == "NO_IMPL_MODULE"
    assert errors[0].sequence_id == "TEST_MODE_ENTRY"


def test_stub_impl_module_fails(tmp_path):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    # File exists but has no conditional logic.
    _write_rtl(
        rtl, "cc_reset_ctrl.v",
        "module cc_reset_ctrl (input clk, output reg q);\n"
        "  always @(posedge clk) q <= 1'b0;\n"
        "endmodule\n"
    )
    l12 = tmp_path / "L12.json"
    _write_l12(l12, [{"id": "CC_RESET_700MS",
                       "category": "timed_side_effect"}])
    findings, _ = chk.audit(rtl, l12)
    errors = [f for f in findings if f.severity == "ERROR"]
    assert len(errors) == 1
    assert errors[0].category == "STUB_MODULE"


def test_missing_rtl_dir_fails(tmp_path):
    findings, _ = chk.audit(tmp_path / "ghost", None)
    assert any(f.severity == "ERROR" and f.category == "IO"
               for f in findings)


def test_invalid_json_fails(tmp_path):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    bad = tmp_path / "L12.json"
    bad.write_text("{not valid json")
    findings, _ = chk.audit(rtl, bad)
    assert any(f.category == "INVALID_JSON" for f in findings)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------
def test_cli_pass(tmp_path):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    l12 = tmp_path / "L12.json"
    _write_l12(l12, [])
    rc = chk.main(["--rtl-dir", str(rtl), "--l12-json", str(l12)])
    assert rc == 0


def test_cli_fail(tmp_path):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    l12 = tmp_path / "L12.json"
    _write_l12(l12, [{"id": "GHOST_SEQ", "category": "host_stimulus_sequence"}])
    rc = chk.main(["--rtl-dir", str(rtl), "--l12-json", str(l12)])
    assert rc == 1
