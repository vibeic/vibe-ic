"""Tests for memory_read_pipeline_check.py."""
from __future__ import annotations

import json
import subprocess
import sys
import textwrap
from pathlib import Path

PROGRAM = Path(__file__).parent.parent / "memory_read_pipeline_check.py"


def _run(tmp_path, src, name="mem.v"):
    p = tmp_path / name
    p.write_text(textwrap.dedent(src))
    r = subprocess.run(
        [sys.executable, str(PROGRAM), str(p), "--json"],
        capture_output=True, text=True,
    )
    return r.returncode, json.loads(r.stdout) if r.stdout else {}


def test_registered_read_without_doc_or_valid_flagged(tmp_path):
    """Bare registered-read module, no latency doc, no _valid — flagged
    as WARN.

    v1.6.125 (#47 Fix 3): registered_read_undocumented is a WARN-
    severity finding. WARN must NOT gate the flow — exit 0,
    verdict=WARN surfaced via JSON for visibility. The bug-report-
    worthy fact is still expressed (in `findings`); just the verdict
    severity is downgraded from FAIL to WARN.
    """
    src = """
    module mem(input clk, input [6:0] addr, output reg [7:0] data);
        reg [7:0] arr [0:127];
        always @(posedge clk) data <= arr[addr];
    endmodule
    """
    rc, out = _run(tmp_path, src)
    assert rc == 0
    assert out["verdict"] == "WARN"
    assert out["total_findings"] >= 1


def test_with_valid_companion_port_passes(tmp_path):
    """Registered read + `data_valid` port — passes (handshake documents lag)."""
    src = """
    module mem(input clk, input rd_en, input [6:0] addr,
               output reg [7:0] data, output reg data_valid);
        reg [7:0] arr [0:127];
        always @(posedge clk) begin
            data_valid <= rd_en;
            if (rd_en) data <= arr[addr];
        end
    endmodule
    """
    rc, out = _run(tmp_path, src)
    assert rc == 0
    assert out["verdict"] == "PASS"


def test_with_latency_doc_passes(tmp_path):
    """Registered read + explicit 'read latency = 1' doc — passes."""
    src = """
    // 1-cycle read latency — consumer must wait 1 cycle after addr.
    module mem(input clk, input [6:0] addr, output reg [7:0] data);
        reg [7:0] arr [0:127];
        always @(posedge clk) data <= arr[addr];
    endmodule
    """
    rc, out = _run(tmp_path, src)
    assert rc == 0


def test_combinational_read_passes(tmp_path):
    """`assign data = mem[addr]` — combinational, no lag."""
    src = """
    module mem(input [6:0] addr, output wire [7:0] data);
        reg [7:0] arr [0:127];
        assign data = arr[addr];
    endmodule
    """
    rc, out = _run(tmp_path, src)
    assert rc == 0


def test_mixed_semantics_flagged(tmp_path):
    """Both registered and combinational for same output — ambiguous.

    v1.6.125 (#47 Fix 3): mixed_read_semantics is WARN severity —
    surfaced via verdict=WARN, exit 0 (non-blocking).
    """
    src = """
    module mem(input clk, input [6:0] addr, output reg [7:0] data);
        reg [7:0] arr [0:127];
        always @(posedge clk) data <= arr[addr];
        assign data = arr[addr];
    endmodule
    """
    rc, out = _run(tmp_path, src)
    assert rc == 0
    assert out["verdict"] == "WARN"
    rules = [f["rule"] for f in out["findings"]]
    assert "mixed_read_semantics" in rules or "registered_read_undocumented" in rules


def test_v068_post_fix_shape(tmp_path):
    """v068 post-fix: `assign data = mem[addr]` + `data_valid <= rd_en`."""
    src = """
    // Combinational data with registered valid-strobe.
    module otp_reader(input clk, input rstn, input [6:0] addr, input rd_en,
                      output wire [7:0] data, output reg data_valid);
        reg [7:0] mem [0:127];
        assign data = mem[addr];
        always @(posedge clk or negedge rstn) begin
            if (!rstn) data_valid <= 1'b0;
            else       data_valid <= rd_en;
        end
    endmodule
    """
    rc, out = _run(tmp_path, src)
    assert rc == 0


def test_non_memory_module_not_flagged(tmp_path):
    """Module without mem[addr] pattern — not flagged."""
    src = """
    module adder(input clk, input [7:0] a, input [7:0] b, output reg [8:0] sum);
        always @(posedge clk) sum <= a + b;
    endmodule
    """
    rc, out = _run(tmp_path, src)
    assert rc == 0


def test_registered_keyword_doc_passes(tmp_path):
    """Doc matches 'registered read'."""
    src = """
    // This BRAM has registered read; output data lags addr by 1 cycle.
    module mem(input clk, input [6:0] addr, output reg [7:0] data);
        reg [7:0] arr [0:127];
        always @(posedge clk) data <= arr[addr];
    endmodule
    """
    rc, out = _run(tmp_path, src)
    assert rc == 0


def test_missing_file(tmp_path):
    r = subprocess.run(
        [sys.executable, str(PROGRAM), str(tmp_path / "nope.v")],
        capture_output=True)
    assert r.returncode == 2
