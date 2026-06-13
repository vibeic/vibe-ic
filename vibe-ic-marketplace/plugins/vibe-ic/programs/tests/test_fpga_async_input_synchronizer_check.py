"""Tests for fpga_async_input_synchronizer_check.py."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "fpga_async_input_synchronizer_check.py"


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
module fpga_top(input CLK_50M, input KEY_n, input RST_N, output LED);
  reg key_s1, key_s2;
  always @(posedge CLK_50M) begin
    key_s1 <= KEY_n;
    key_s2 <= key_s1;
  end
  assign LED = key_s2;
endmodule
"""

_BAD = """
module fpga_top(input CLK_50M, input KEY_n, output LED);
  reg key_s1;
  always @(posedge CLK_50M) key_s1 <= KEY_n;
  assign LED = key_s1;
endmodule
"""

_NONE = """
module fpga_top(input CLK_50M, input KEY_n, output reg LED);
  always @(posedge CLK_50M) LED <= KEY_n;
endmodule
"""


def test_2_ff_chain_passes(tmp_path):
    _rtl(tmp_path, _GOOD)
    rc, _, _ = _run([str(tmp_path / "phase2" / "stage1" / "rtl"), "--top", "fpga_top"])
    assert rc == 0


def test_1_ff_chain_fails(tmp_path):
    _rtl(tmp_path, _BAD)
    rc, out, _ = _run([str(tmp_path / "phase2" / "stage1" / "rtl"), "--top", "fpga_top"])
    assert rc == 1
    assert "missing_async_synchroniser" in out


def test_no_sync_at_all_fails(tmp_path):
    _rtl(tmp_path, _NONE)
    rc, out, _ = _run([str(tmp_path / "phase2" / "stage1" / "rtl"), "--top", "fpga_top"])
    assert rc == 1


def test_qsf_top_extraction(tmp_path):
    _rtl(tmp_path, _BAD)
    qsf = tmp_path / "top.qsf"
    qsf.write_text("""
set_global_assignment -name TOP_LEVEL_ENTITY fpga_top
set_location_assignment PIN_M9 -to KEY_n
""")
    rc, _, _ = _run([str(tmp_path / "phase2" / "stage1" / "rtl"), "--qsf", str(qsf)])
    assert rc == 1


def test_top_not_found_errors(tmp_path):
    _rtl(tmp_path, "module other; endmodule")
    rc, out, _ = _run([str(tmp_path / "phase2" / "stage1" / "rtl"), "--top", "fpga_top"])
    assert rc == 1
    assert "top_module_not_found" in out


def test_clock_input_skipped(tmp_path):
    """Clock pins shouldn't be flagged as needing synchronisers."""
    _rtl(tmp_path, """
module fpga_top(input CLK_50M, output LED);
  assign LED = CLK_50M;
endmodule
""")
    rc, out, _ = _run([str(tmp_path / "phase2" / "stage1" / "rtl"), "--top", "fpga_top"])
    assert rc == 0


def test_no_top_supplied_exits_2(tmp_path):
    _rtl(tmp_path, _GOOD)
    rc, _, _ = _run([str(tmp_path / "phase2" / "stage1" / "rtl")])
    assert rc == 2


def test_json_output(tmp_path):
    _rtl(tmp_path, _BAD)
    out = tmp_path / "rep.json"
    rc, _, _ = _run([str(tmp_path / "phase2" / "stage1" / "rtl"), "--top", "fpga_top",
                     "--json", str(out)])
    assert rc == 1
    data = json.loads(out.read_text())
    assert data["verdict"] == "FAIL"
