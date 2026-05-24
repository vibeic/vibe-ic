"""Tests for mask_application_check.py."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "mask_application_check.py"


def _run(args):
    r = subprocess.run([sys.executable, str(PROG), *args],
                       capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def _rtl(tmp_path: Path, body: str, name="store.v") -> Path:
    d = tmp_path / "phase2" / "stage1" / "rtl"
    d.mkdir(parents=True, exist_ok=True)
    f = d / name
    f.write_text(body)
    return f


_GOOD_HEX = """
module store(input clk, input [7:0] payload_byte1, output reg [7:0] reg_q);
  always @(posedge clk) reg_q <= payload_byte1 & 8'hE8;
endmodule
"""

_GOOD_HEX_PREFIX = """
module store(input clk, input [7:0] payload_byte1, output reg [7:0] reg_q);
  always @(posedge clk) reg_q <= payload_byte1 & 0xE8;
endmodule
"""

_BAD_RAW = """
module store(input clk, input [7:0] payload_byte1, output reg [7:0] reg_q);
  always @(posedge clk) reg_q <= payload_byte1;
endmodule
"""

_BAD_WRONG_MASK = """
module store(input clk, input [7:0] payload_byte1, output reg [7:0] reg_q);
  always @(posedge clk) reg_q <= payload_byte1 & 8'hFF;
endmodule
"""


def test_correct_mask_passes(tmp_path):
    _rtl(tmp_path, _GOOD_HEX)
    rc, out, _ = _run([str(tmp_path / "phase2" / "stage1" / "rtl"),
                       "--mask", "payload_byte1 AND 0xE8"])
    assert rc == 0


def test_raw_value_fails(tmp_path):
    _rtl(tmp_path, _BAD_RAW)
    rc, out, _ = _run([str(tmp_path / "phase2" / "stage1" / "rtl"),
                       "--mask", "payload_byte1 AND 0xE8"])
    assert rc == 1
    assert "mask_not_applied" in out


def test_wrong_mask_value_fails(tmp_path):
    _rtl(tmp_path, _BAD_WRONG_MASK)
    rc, out, _ = _run([str(tmp_path / "phase2" / "stage1" / "rtl"),
                       "--mask", "payload_byte1 AND 0xE8"])
    assert rc == 1


def test_masks_json_file(tmp_path):
    _rtl(tmp_path, _BAD_RAW)
    masks = tmp_path / "masks.json"
    masks.write_text(json.dumps([
        {"signal": "payload_byte1", "and_mask": "0xE8"}
    ]))
    rc, _, _ = _run([str(tmp_path / "phase2" / "stage1" / "rtl"), "--masks", str(masks)])
    assert rc == 1


def test_signal_not_referenced_passes(tmp_path):
    """If the signal is not used anywhere, no mask violation possible."""
    _rtl(tmp_path, "module empty; endmodule")
    rc, _, _ = _run([str(tmp_path / "phase2" / "stage1" / "rtl"),
                     "--mask", "payload_byte1 AND 0xE8"])
    assert rc == 0


def test_multiple_signals(tmp_path):
    _rtl(tmp_path, """
module multi(input clk, input [7:0] a, input [7:0] b,
             output reg [7:0] qa, output reg [7:0] qb);
  always @(posedge clk) begin
    qa <= a & 8'hF0;
    qb <= b;       // missing mask
  end
endmodule
""")
    rc, out, _ = _run([str(tmp_path / "phase2" / "stage1" / "rtl"),
                       "--mask", "a AND 0xF0",
                       "--mask", "b AND 0x0F"])
    assert rc == 1
    assert out.count("mask_not_applied") == 1


def test_json_output(tmp_path):
    _rtl(tmp_path, _BAD_RAW)
    out = tmp_path / "rep.json"
    rc, _, _ = _run([str(tmp_path / "phase2" / "stage1" / "rtl"),
                     "--mask", "payload_byte1 AND 0xE8",
                     "--json", str(out)])
    assert rc == 1
    data = json.loads(out.read_text())
    assert data["verdict"] == "FAIL"


def test_no_masks_exits_2(tmp_path):
    _rtl(tmp_path, _GOOD_HEX)
    rc, _, _ = _run([str(tmp_path / "phase2" / "stage1" / "rtl")])
    assert rc == 2
