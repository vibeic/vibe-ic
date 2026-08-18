"""Tests for rtl_unit_test_coverage_check.py (v0.50.2 unit-tb coverage gate)."""
from __future__ import annotations
import json, subprocess, sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "rtl_unit_test_coverage_check.py"


def _setup(tmp: Path, rtl_files: dict, sim_files: list = None):
    rtl = tmp / "phase2" / "stage1" / "rtl"; rtl.mkdir(parents=True, exist_ok=True)
    sim = tmp / "sim_unit"; sim.mkdir(parents=True, exist_ok=True)
    for name, body in rtl_files.items():
        (rtl / name).write_text(body)
    for n in sim_files or []:
        (sim / n).write_text("// dummy tb\n")
    return tmp


def _run(proj):
    r = subprocess.run([sys.executable, str(PROG), str(proj)],
                       capture_output=True, text=True)
    try:
        return r.returncode, json.loads(r.stdout)
    except Exception:
        return r.returncode, {"_raw": r.stdout, "_err": r.stderr}


def test_module_with_fsm_needs_tb_passes_if_provided(tmp_path):
    _setup(tmp_path,
           rtl_files={
               "cmd_dispatcher.v":
                   "module cmd_dispatcher (input clk);\n"
                   "  localparam S_IDLE=0, S_RX=1;\n"
                   "  reg [3:0] st;\n"
                   "  always @* case (st)\n"
                   "    S_IDLE: ; default: ;\n"
                   "  endcase endmodule\n",
           },
           sim_files=["tb_cmd_dispatcher.v"])
    code, out = _run(tmp_path)
    assert out.get("pass") is True, out
    assert code == 0


def test_module_with_fsm_no_tb_fails(tmp_path):
    _setup(tmp_path,
           rtl_files={
               "rx_phy.v":
                   "module rx_phy (input clk);\n"
                   "  reg [7:0] low_cnt;\n"
                   "  always @(posedge clk) low_cnt <= low_cnt + 1;\n"
                   "endmodule\n",
           },
           sim_files=[])
    code, out = _run(tmp_path)
    assert out.get("pass") is False
    rules = [f["rule"] for f in out["findings"]]
    assert "missing_unit_tb" in rules


def test_module_must_tb_name_always_required(tmp_path):
    """Any file named *dispatcher.v needs a tb regardless of contents."""
    _setup(tmp_path,
           rtl_files={
               "my_dispatcher.v": "module my_dispatcher; endmodule\n",
           },
           sim_files=[])
    code, out = _run(tmp_path)
    assert out.get("pass") is False


def test_pure_combinational_skipped(tmp_path):
    """A pure-combinational helper without FSM should NOT require tb."""
    _setup(tmp_path,
           rtl_files={
               "crc8.v":
                   "module crc8(input [7:0] d, output [7:0] c);\n"
                   "  assign c = d ^ 8'h31;\n"
                   "endmodule\n",
           },
           sim_files=[])
    code, out = _run(tmp_path)
    # Should pass — crc8 doesn't match any pattern
    assert out.get("pass") is True


def test_help_works():
    r = subprocess.run([sys.executable, str(PROG), "--help"],
                       capture_output=True, text=True)
    assert r.returncode == 0
