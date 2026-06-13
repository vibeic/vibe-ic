"""Tests for periodic_signal_required_check.py."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "periodic_signal_required_check.py"


def _run(args):
    r = subprocess.run([sys.executable, str(PROG), *args],
                       capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def _rtl(tmp_path: Path, body: str, name="top.v") -> Path:
    d = tmp_path / "phase2" / "stage1" / "rtl"
    d.mkdir(parents=True, exist_ok=True)
    f = d / name
    f.write_text(body)
    return f


_GOOD = """
module top(input clk, output reg wake_out);
  parameter WAKE_PERIOD = 50000;
  reg [15:0] cnt;
  always @(posedge clk) begin
    if (cnt == WAKE_PERIOD) begin
      cnt <= 0; wake_out <= ~wake_out;
    end else cnt <= cnt + 1;
  end
endmodule
"""

_NO_GENERATOR = """
module top(input clk, output reg wake_out);
  parameter WAKE_PERIOD = 50000;
endmodule
"""

_NO_PORT = """
module top(input clk);
  parameter WAKE_PERIOD = 50000;
endmodule
"""


def test_good_passes(tmp_path):
    _rtl(tmp_path, _GOOD)
    rc, _, _ = _run([str(tmp_path / "phase2" / "stage1" / "rtl"),
                     "--required", "wake=WAKE_PERIOD,wake_out"])
    assert rc == 0


def test_no_generator_fails(tmp_path):
    _rtl(tmp_path, _NO_GENERATOR)
    rc, out, _ = _run([str(tmp_path / "phase2" / "stage1" / "rtl"),
                       "--required", "wake=WAKE_PERIOD,wake_out"])
    assert rc == 1
    assert "generator_missing" in out


def test_no_port_fails(tmp_path):
    _rtl(tmp_path, _NO_PORT)
    rc, out, _ = _run([str(tmp_path / "phase2" / "stage1" / "rtl"),
                       "--required", "wake=WAKE_PERIOD,wake_out"])
    assert rc == 1
    assert "output_port_missing" in out


def test_no_const_fails(tmp_path):
    _rtl(tmp_path, "module top(output reg wake_out); endmodule")
    rc, out, _ = _run([str(tmp_path / "phase2" / "stage1" / "rtl"),
                       "--required", "wake=WAKE_PERIOD,wake_out"])
    assert rc == 1
    assert "period_const_missing" in out


def test_manifest_json(tmp_path):
    _rtl(tmp_path, _NO_GENERATOR)
    m = tmp_path / "m.json"
    m.write_text(json.dumps([{"name": "wake",
                               "period_const": "WAKE_PERIOD",
                               "output_port": "wake_out"}]))
    rc, _, _ = _run([str(tmp_path / "phase2" / "stage1" / "rtl"), "--periodic", str(m)])
    assert rc == 1


def test_json_output(tmp_path):
    _rtl(tmp_path, _NO_GENERATOR)
    out = tmp_path / "rep.json"
    rc, _, _ = _run([str(tmp_path / "phase2" / "stage1" / "rtl"),
                     "--required", "wake=WAKE_PERIOD,wake_out",
                     "--json", str(out)])
    assert rc == 1
    data = json.loads(out.read_text())
    assert data["verdict"] == "FAIL"


def test_no_required_exits_2(tmp_path):
    _rtl(tmp_path, _GOOD)
    rc, _, _ = _run([str(tmp_path / "phase2" / "stage1" / "rtl")])
    assert rc == 2
