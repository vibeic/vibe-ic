"""Unit tests for otp_write_lock_gate_check.py."""
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "otp_write_lock_gate_check.py"
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"
sys.path.insert(0, str(SCRIPT.parent))

import otp_write_lock_gate_check as chk  # noqa: E402


# ---------------------------------------------------------------------------
# PASS paths
# ---------------------------------------------------------------------------
def test_no_otp_writes_passes(tmp_path):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "plain.v").write_text(
        "module plain (input wire clk, output reg q);\n"
        "  always @(posedge clk) q <= 1'b0;\n"
        "endmodule\n"
    )
    findings, summary = chk.audit(rtl)
    assert summary["sites"] == 0
    assert not any(f.severity == "ERROR" for f in findings)


def test_write_guarded_by_lock_bit_passes(tmp_path):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "mac.v").write_text(
        "module mac (input wire clk, input wire id_lk, output reg otp_we);\n"
        "  always @(posedge clk) begin\n"
        "    if (!id_lk) begin\n"
        "      otp_we <= 1'b1;\n"
        "    end\n"
        "  end\n"
        "endmodule\n"
    )
    findings, summary = chk.audit(rtl)
    assert summary["sites"] == 1
    assert summary["guarded"] == 1
    assert not any(f.severity == "ERROR" for f in findings)


def test_write_guarded_by_eng_mode_passes(tmp_path):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "mac.v").write_text(
        "module mac (input wire clk, input wire eng_mode, output reg fuse_prog);\n"
        "  always @(posedge clk) begin\n"
        "    if (eng_mode) begin\n"
        "      fuse_prog <= 1'b1;\n"
        "    end\n"
        "  end\n"
        "endmodule\n"
    )
    findings, _ = chk.audit(rtl)
    assert not any(f.severity == "ERROR" for f in findings)


# ---------------------------------------------------------------------------
# FAIL paths
# ---------------------------------------------------------------------------
def test_write_without_lock_token_fails(tmp_path):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "bad.v").write_text(
        "module bad (input wire clk, input wire trigger, output reg otp_we);\n"
        "  // 50 lines of padding — far away from any lock token\n"
        + ("  // padding\n" * 50)
        + "  always @(posedge clk) begin\n"
        "    if (trigger) begin\n"
        "      otp_we <= 1'b1;\n"
        "    end\n"
        "  end\n"
        "endmodule\n"
    )
    findings, summary = chk.audit(rtl)
    assert summary["sites"] == 1
    assert summary["unguarded"] == 1
    errors = [f for f in findings if f.severity == "ERROR"]
    assert len(errors) == 1
    assert errors[0].category == "UNGATED_NV_WRITE"
    assert errors[0].signal == "otp_we"


def test_nvm_we_without_lock_fails(tmp_path):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "nvm.v").write_text(
        "module nvm (input wire clk, output reg nvm_we);\n"
        + ("  // padding\n" * 40)
        + "  always @(posedge clk) begin\n"
        "    nvm_we <= 1'b1;\n"
        "  end\n"
        "endmodule\n"
    )
    findings, _ = chk.audit(rtl)
    assert any(f.severity == "ERROR" and f.signal == "nvm_we"
               for f in findings)


def test_missing_dir_fails(tmp_path):
    findings, _ = chk.audit(tmp_path / "ghost")
    assert any(f.severity == "ERROR" and f.category == "IO"
               for f in findings)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------
def test_cli_exit_codes(tmp_path):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "ok.v").write_text(
        "module ok (input wire clk, input wire lock, output reg otp_we);\n"
        "  always @(posedge clk) begin\n"
        "    if (!lock) otp_we <= 1'b1;\n"
        "  end\n"
        "endmodule\n"
    )
    assert chk.main(["--rtl-dir", str(rtl)]) == 0


def test_cli_json_report(tmp_path):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "empty.v").write_text("module empty; endmodule\n")
    out = tmp_path / "rep.json"
    rc = chk.main(["--rtl-dir", str(rtl), "--json", str(out)])
    assert rc == 0
    import json as _json
    data = _json.loads(out.read_text())
    assert data["summary"]["pass"] is True
