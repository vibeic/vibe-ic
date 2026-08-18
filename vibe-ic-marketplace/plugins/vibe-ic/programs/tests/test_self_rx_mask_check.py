"""Tests for self_rx_mask_check.py."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "self_rx_mask_check.py"


def _run(args):
    r = subprocess.run([sys.executable, str(PROG), *args],
                       capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def _rtl(tmp_path: Path, body: str, name="bus.v") -> Path:
    d = tmp_path / "phase2" / "stage1" / "rtl"
    d.mkdir(parents=True, exist_ok=True)
    f = d / name
    f.write_text(body)
    return f


_GOOD = """
module bus(input clk, input id_bus_synced, output id_bus_oe);
  wire id_bus_rx_masked = id_bus_synced | id_bus_oe;
  reg fsm_byte;
  always @(posedge clk) fsm_byte <= id_bus_rx_masked;
endmodule
"""

_BAD = """
module bus(input clk, input id_bus_synced, output id_bus_oe);
  reg fsm_byte;
  always @(posedge clk) fsm_byte <= id_bus_synced;
endmodule
"""

_GUARD_IF = """
module bus(input clk, input id_bus_synced, output id_bus_oe);
  reg fsm_byte;
  always @(posedge clk) if (!id_bus_oe) fsm_byte <= id_bus_synced;
endmodule
"""


def test_masked_passes(tmp_path):
    _rtl(tmp_path, _GOOD)
    rc, out, _ = _run([str(tmp_path / "phase2" / "stage1" / "rtl")])
    assert rc == 0


def test_unmasked_fails(tmp_path):
    _rtl(tmp_path, _BAD)
    rc, out, _ = _run([str(tmp_path / "phase2" / "stage1" / "rtl")])
    assert rc == 1
    assert "self_rx_not_masked" in out


def test_if_guard_counts_as_masked(tmp_path):
    _rtl(tmp_path, _GUARD_IF)
    rc, _, _ = _run([str(tmp_path / "phase2" / "stage1" / "rtl")])
    assert rc == 0


def test_no_oe_signals_passes(tmp_path):
    _rtl(tmp_path, "module empty(input clk, output reg led); endmodule")
    rc, out, _ = _run([str(tmp_path / "phase2" / "stage1" / "rtl")])
    assert rc == 0
    assert "no_oe_signals_found" in out


def test_pair_hint(tmp_path):
    _rtl(tmp_path, """
module bus(input clk, input sda_in_synced, output sda_drive_low);
  reg fsm_byte;
  always @(posedge clk) fsm_byte <= sda_in_synced;
endmodule
""")
    rc, out, _ = _run([str(tmp_path / "phase2" / "stage1" / "rtl"), "--pair", "sda"])
    assert rc == 1
    assert "self_rx_not_masked" in out


def test_json_output(tmp_path):
    _rtl(tmp_path, _BAD)
    out = tmp_path / "rep.json"
    rc, _, _ = _run([str(tmp_path / "phase2" / "stage1" / "rtl"), "--json", str(out)])
    assert rc == 1
    data = json.loads(out.read_text())
    assert data["verdict"] == "FAIL"
