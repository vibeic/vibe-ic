"""Unit tests for pulse_decoder_edge_check.py."""
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "pulse_decoder_edge_check.py"
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"
sys.path.insert(0, str(SCRIPT.parent))

import pulse_decoder_edge_check as chk  # noqa: E402


# ---------------------------------------------------------------------------
# PASS paths
# ---------------------------------------------------------------------------
def test_non_decoder_file_passes(tmp_path):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "empty.v").write_text(
        "module empty (input wire clk);\n"
        "  always @(posedge clk) begin end\n"
        "endmodule\n"
    )
    findings, summary = chk.audit(rtl)
    assert summary["checked"] == 0
    assert not any(f.severity == "ERROR" for f in findings)


def test_pulse_decoder_with_qq_edge_detector_passes(tmp_path):
    """Mimic v052 rx_phy pattern: low_cnt + 3 thresholds + id_q/id_qq edge."""
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "decoder.v").write_text(
        "module decoder (input wire clk, input wire bus);\n"
        "  reg bus_q, bus_qq;\n"
        "  reg [7:0] low_cnt;\n"
        "  always @(posedge clk) begin\n"
        "    bus_q <= bus; bus_qq <= bus_q;\n"
        "    if (bus_qq == 1'b0 && bus_q == 1'b1) begin\n"
        "      if (low_cnt >= 8'd100) ;\n"
        "      else if (low_cnt >= 8'd50) ;\n"
        "      else if (low_cnt >= 8'd10) ;\n"
        "      low_cnt <= 0;\n"
        "    end else if (bus_qq == 0) low_cnt <= low_cnt + 1;\n"
        "  end\n"
        "endmodule\n"
    )
    findings, summary = chk.audit(rtl)
    assert summary["checked"] == 1
    errors = [f for f in findings if f.severity == "ERROR"]
    assert not errors


def test_pulse_decoder_with_one_stage_edge_passes(tmp_path):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "dec.v").write_text(
        "module dec (input wire clk, input wire sig);\n"
        "  reg sig_q;\n"
        "  reg [7:0] low_cnt;\n"
        "  always @(posedge clk) begin\n"
        "    sig_q <= sig;\n"
        "    if (sig && !sig_q) begin  // rising edge\n"
        "      if (low_cnt >= 8'd50) ;\n"
        "      else if (low_cnt >= 8'd20) ;\n"
        "    end\n"
        "  end\n"
        "endmodule\n"
    )
    findings, summary = chk.audit(rtl)
    assert summary["checked"] == 1
    assert not any(f.severity == "ERROR" for f in findings)


# ---------------------------------------------------------------------------
# FAIL paths
# ---------------------------------------------------------------------------
def test_pulse_decoder_without_edge_fails(tmp_path):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "bad.v").write_text(
        "module bad (input wire clk, input wire bus);\n"
        "  reg [7:0] low_cnt;\n"
        "  always @(posedge clk) begin\n"
        "    if (bus == 0) low_cnt <= low_cnt + 1;\n"
        "    else low_cnt <= 0;\n"
        "    // Classification with NO edge gate — re-fires every LOW cycle\n"
        "    if (low_cnt >= 8'd100) ;\n"
        "    else if (low_cnt >= 8'd50) ;\n"
        "    else if (low_cnt >= 8'd10) ;\n"
        "  end\n"
        "endmodule\n"
    )
    findings, summary = chk.audit(rtl)
    assert summary["checked"] == 1
    errors = [f for f in findings if f.severity == "ERROR"]
    assert len(errors) == 1
    assert errors[0].category == "NO_EDGE_DETECTOR"


def test_missing_dir_fails(tmp_path):
    findings, _ = chk.audit(tmp_path / "no_such_dir")
    assert any(f.severity == "ERROR" and f.category == "IO"
               for f in findings)


def test_single_threshold_is_not_classifier(tmp_path):
    """disc_detect-style: only 1 threshold predicate → not a classifier."""
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "disc.v").write_text(
        "module disc (input wire clk, input wire bus);\n"
        "  reg [15:0] low_cnt;\n"
        "  always @(posedge clk) begin\n"
        "    if (bus == 0) low_cnt <= low_cnt + 1;\n"
        "    if (low_cnt >= 16'd5000) ;  // single threshold\n"
        "  end\n"
        "endmodule\n"
    )
    findings, summary = chk.audit(rtl)
    assert summary["checked"] == 0
    assert not any(f.severity == "ERROR" for f in findings)


# ---------------------------------------------------------------------------
# CLI plumbing
# ---------------------------------------------------------------------------
def test_cli_exit_codes(tmp_path):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "good.v").write_text(
        "module good (input wire clk, input wire s);\n"
        "  reg s_q, s_qq; reg [7:0] low_cnt;\n"
        "  always @(posedge clk) begin\n"
        "    s_q <= s; s_qq <= s_q;\n"
        "    if (s_qq == 1'b0 && s_q == 1'b1) begin\n"
        "      if (low_cnt >= 8'd10) ; else if (low_cnt >= 8'd5) ;\n"
        "    end\n"
        "  end\n"
        "endmodule\n"
    )
    assert chk.main(["--rtl-dir", str(rtl)]) == 0
