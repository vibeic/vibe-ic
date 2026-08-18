"""Tests for derived_clock_sdc_required_check.py."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "derived_clock_sdc_required_check.py"


def _run(args):
    r = subprocess.run([sys.executable, str(PROG), *args],
                       capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def _rtl(tmp_path: Path, body: str, name="div.v") -> Path:
    d = tmp_path / "phase2" / "stage1" / "rtl"
    d.mkdir(parents=True, exist_ok=True)
    f = d / name
    f.write_text(body)
    return f


_RTL_DIVIDER = """
module clkdiv(input ext_clk, output reg core_clk);
  always @(posedge ext_clk) core_clk <= ~core_clk;
endmodule
"""

_RTL_NO_DIVIDER = """
module clkdiv(input ext_clk, output reg out);
  always @(posedge ext_clk) out <= 1'b1;
endmodule
"""

_GOOD_SDC = """
create_clock -name ext_clk -period 20 [get_ports ext_clk]
create_generated_clock -name core_clk -divide_by 2 -source [get_ports ext_clk] [get_pins core_clk_reg/Q]
"""

_BAD_SDC = """
create_clock -name ext_clk -period 20 [get_ports ext_clk]
"""


def test_divider_with_sdc_passes(tmp_path):
    _rtl(tmp_path, _RTL_DIVIDER)
    sdc = tmp_path / "design.sdc"
    sdc.write_text(_GOOD_SDC)
    rc, _, _ = _run([str(tmp_path / "phase2" / "stage1" / "rtl"), "--sdc", str(sdc)])
    assert rc == 0


def test_divider_without_sdc_fails(tmp_path):
    _rtl(tmp_path, _RTL_DIVIDER)
    sdc = tmp_path / "design.sdc"
    sdc.write_text(_BAD_SDC)
    rc, out, _ = _run([str(tmp_path / "phase2" / "stage1" / "rtl"), "--sdc", str(sdc)])
    assert rc == 1
    assert "derived_clock_sdc_missing" in out


def test_divider_without_any_sdc_fails(tmp_path):
    _rtl(tmp_path, _RTL_DIVIDER)
    rc, out, _ = _run([str(tmp_path / "phase2" / "stage1" / "rtl")])
    assert rc == 1


def test_no_divider_passes_even_without_sdc(tmp_path):
    _rtl(tmp_path, _RTL_NO_DIVIDER)
    rc, out, _ = _run([str(tmp_path / "phase2" / "stage1" / "rtl")])
    assert rc == 0


def test_json_output(tmp_path):
    _rtl(tmp_path, _RTL_DIVIDER)
    out = tmp_path / "rep.json"
    rc, _, _ = _run([str(tmp_path / "phase2" / "stage1" / "rtl"), "--json", str(out)])
    assert rc == 1
    data = json.loads(out.read_text())
    assert data["verdict"] == "FAIL"


def test_multiple_dividers(tmp_path):
    _rtl(tmp_path, """
module multi(input ext_clk, output reg div2_clk, output reg div4_clk);
  always @(posedge ext_clk) div2_clk <= ~div2_clk;
  always @(posedge div2_clk) div4_clk <= ~div4_clk;
endmodule
""")
    sdc = tmp_path / "design.sdc"
    sdc.write_text("create_generated_clock -name div2_clk ...")  # only one
    rc, out, _ = _run([str(tmp_path / "phase2" / "stage1" / "rtl"), "--sdc", str(sdc)])
    assert rc == 1
    assert out.count("derived_clock_sdc_missing") == 1  # only div4_clk missing
