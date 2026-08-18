"""Tests for protocol_delimiter_consistency_check.py."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "protocol_delimiter_consistency_check.py"


def _run(args):
    r = subprocess.run([sys.executable, str(PROG), *args],
                       capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


_GOOD = """
module dispatcher(input clk, input rst_n, input br_high_seen,
                  output reg frame_done);
  always @(posedge clk) begin
    if (br_high_seen) begin
      frame_done <= 1'b1;  // gate on canonical BR_HIGH delimiter
    end
  end
endmodule
"""

_BAD = """
module dispatcher(input clk, input rst_n, input idle_long,
                  output reg frame_done);
  always @(posedge clk) begin
    if (idle_long) begin
      frame_done <= 1'b1;  // BUG: gate on idle_long, not BR_HIGH
    end
  end
endmodule
"""

_MIXED = """
module dispatcher(input clk, input br_high_seen, input idle_long,
                  output reg frame_done);
  always @(posedge clk) begin
    // primary trigger: br_high_seen ; fallback: idle_long timeout
    if (br_high_seen || idle_long) frame_done <= 1'b1;
  end
endmodule
"""


def _w(tmp_path: Path, body: str, name="dispatcher.v") -> Path:
    p = tmp_path / "phase2" / "stage1" / "rtl"
    p.mkdir(parents=True, exist_ok=True)
    f = p / name
    f.write_text(body)
    return f


def test_good_passes(tmp_path):
    _w(tmp_path, _GOOD)
    rc, out, _ = _run([str(tmp_path / "phase2" / "stage1" / "rtl"), "--delimiter", "BR_HIGH"])
    assert rc == 0


def test_bad_fails(tmp_path):
    _w(tmp_path, _BAD)
    rc, out, _ = _run([str(tmp_path / "phase2" / "stage1" / "rtl"), "--delimiter", "BR_HIGH"])
    assert rc == 1
    assert "proxy_without_delimiter" in out


def test_mixed_warns_but_passes(tmp_path):
    _w(tmp_path, _MIXED)
    rc, out, _ = _run([str(tmp_path / "phase2" / "stage1" / "rtl"), "--delimiter", "br_high"])
    # both delimiter and proxy present → WARN, not ERROR
    assert rc == 0
    assert "proxy_alongside_delimiter" in out


def test_l3_layer_lookup(tmp_path):
    _w(tmp_path, _BAD)
    l3 = tmp_path / "L3.json"
    l3.write_text(json.dumps({"trailing_delimiter": "BR_HIGH"}))
    rc, out, _ = _run([str(tmp_path / "phase2" / "stage1" / "rtl"), "--layer-l3", str(l3)])
    assert rc == 1


def test_no_delimiter_exits_skip(tmp_path):
    """v1.6.7: a positional dir with no delimiter source SKIPs (rc=0,
    verdict=SKIP) instead of erroring out. Avoids FAIL on non-protocol
    or unwired targets."""
    _w(tmp_path, _GOOD)
    rc, out, _ = _run([str(tmp_path / "phase2" / "stage1" / "rtl")])
    assert rc == 0
    assert '"verdict": "SKIP"' in out


def test_json_output(tmp_path):
    _w(tmp_path, _BAD)
    out = tmp_path / "rep.json"
    rc, _, _ = _run([str(tmp_path / "phase2" / "stage1" / "rtl"), "--delimiter", "BR_HIGH",
                     "--json", str(out)])
    assert rc == 1
    data = json.loads(out.read_text())
    assert data["verdict"] == "FAIL"
    assert data["errors"] >= 1
