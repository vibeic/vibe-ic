"""Tests for payload_bit_position_check.py."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "payload_bit_position_check.py"


def _run(args):
    r = subprocess.run([sys.executable, str(PROG), *args],
                       capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def _bitmap(tmp_path: Path, body) -> Path:
    p = tmp_path / "bitmap.json"
    p.write_text(json.dumps(body))
    return p


def _rtl(tmp_path: Path, body: str, name="dispatcher.v") -> Path:
    d = tmp_path / "phase2" / "stage1" / "rtl"
    d.mkdir(parents=True, exist_ok=True)
    f = d / name
    f.write_text(body)
    return f


_GOOD_RTL = """
module dispatcher;
  wire [7:0] byte1;
  wire rd5k = byte1[3];
  wire out1 = byte1[7];
endmodule
"""

_BAD_RTL = """
module dispatcher;
  wire [7:0] byte1;
  wire rd5k = byte1[6];   // BUG: spec says bit 3
  wire out1 = byte1[7];
endmodule
"""

_BITMAP = {"byte1": {"bit3": "RD5K", "bit7": "OUT1"}}


def test_correct_indexing_passes(tmp_path):
    _rtl(tmp_path, _GOOD_RTL)
    bm = _bitmap(tmp_path, _BITMAP)
    rc, out, _ = _run([str(tmp_path / "phase2" / "stage1" / "rtl"), "--bitmap", str(bm)])
    assert rc == 0


def test_wrong_index_fails(tmp_path):
    _rtl(tmp_path, _BAD_RTL)
    bm = _bitmap(tmp_path, _BITMAP)
    rc, out, _ = _run([str(tmp_path / "phase2" / "stage1" / "rtl"), "--bitmap", str(bm)])
    assert rc == 1
    assert "bit_position_mismatch" in out


def test_signal_not_found_warns_by_default(tmp_path):
    _rtl(tmp_path, "module dispatcher; wire [7:0] byte1; endmodule")
    bm = _bitmap(tmp_path, _BITMAP)
    rc, out, _ = _run([str(tmp_path / "phase2" / "stage1" / "rtl"), "--bitmap", str(bm)])
    assert rc == 0
    assert "spec_signal_not_found" in out


def test_signal_not_found_strict_fails(tmp_path):
    _rtl(tmp_path, "module dispatcher; wire [7:0] byte1; endmodule")
    bm = _bitmap(tmp_path, _BITMAP)
    rc, out, _ = _run([str(tmp_path / "phase2" / "stage1" / "rtl"), "--bitmap", str(bm), "--strict-name"])
    assert rc == 1


def test_module_filter(tmp_path):
    rtl = """
module other;
  wire [7:0] byte1; wire bad = byte1[5];  // wrong bit but in OTHER module
endmodule
module dispatcher;
  wire [7:0] byte1; wire rd5k = byte1[3]; wire out1 = byte1[7];
endmodule
"""
    _rtl(tmp_path, rtl)
    bm = _bitmap(tmp_path, _BITMAP)
    rc, out, _ = _run([str(tmp_path / "phase2" / "stage1" / "rtl"), "--bitmap", str(bm),
                       "--module", "dispatcher"])
    assert rc == 0


def test_json_output(tmp_path):
    _rtl(tmp_path, _BAD_RTL)
    bm = _bitmap(tmp_path, _BITMAP)
    out = tmp_path / "rep.json"
    rc, _, _ = _run([str(tmp_path / "phase2" / "stage1" / "rtl"), "--bitmap", str(bm),
                     "--json", str(out)])
    assert rc == 1
    data = json.loads(out.read_text())
    assert data["verdict"] == "FAIL"


def test_layer_l3_lookup(tmp_path):
    _rtl(tmp_path, _BAD_RTL)
    l3 = tmp_path / "L3.json"
    l3.write_text(json.dumps({"bit_layouts": _BITMAP}))
    rc, out, _ = _run([str(tmp_path / "phase2" / "stage1" / "rtl"), "--layer-l3", str(l3)])
    assert rc == 1


def test_no_bitmap_exits_2(tmp_path):
    _rtl(tmp_path, _GOOD_RTL)
    rc, _, _ = _run([str(tmp_path / "phase2" / "stage1" / "rtl")])
    assert rc == 2
