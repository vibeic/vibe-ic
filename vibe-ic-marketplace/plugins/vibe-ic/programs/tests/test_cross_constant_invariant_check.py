"""Tests for cross_constant_invariant_check.py."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "cross_constant_invariant_check.py"


def _run(args):
    r = subprocess.run([sys.executable, str(PROG), *args],
                       capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def _const_map(tmp_path: Path, **kw) -> Path:
    p = tmp_path / "constants.json"
    p.write_text(json.dumps(kw))
    return p


def test_passing_invariant_exits_0(tmp_path):
    cm = _const_map(tmp_path, IBT_MAX=10000, FRAME_END=14000)
    rc, _, _ = _run(["--constants", str(cm), "--inv", "IBT_MAX < FRAME_END"])
    assert rc == 0


def test_failing_invariant_exits_1(tmp_path):
    cm = _const_map(tmp_path, IBT_MAX=22000, FRAME_END=14000)
    rc, out, _ = _run(["--constants", str(cm), "--inv", "IBT_MAX < FRAME_END"])
    assert rc == 1
    assert "invariant_violated" in out


def test_missing_constant(tmp_path):
    cm = _const_map(tmp_path, IBT_MAX=22000)
    rc, out, _ = _run(["--constants", str(cm), "--inv", "IBT_MAX < FRAME_END"])
    assert rc == 1
    assert "constant_not_found" in out


def test_rtl_param_parse(tmp_path):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "top.v").write_text("""
module top;
  parameter IBT_MAX = 22000;
  localparam FRAME_END = 14000;
  parameter [15:0] WAKE_PERIOD = 16'd5000;
endmodule
""")
    rc, out, _ = _run(["--rtl", str(rtl),
                       "--inv", "IBT_MAX < FRAME_END",
                       "--inv", "WAKE_PERIOD > 0"])
    # IBT_MAX < FRAME_END FAIL; WAKE_PERIOD > 0 PASS — but `0` not a constant.
    # So second invariant errors with constant_not_found for 0.
    assert rc == 1
    assert "invariant_violated" in out


def test_multiple_invariants_some_fail(tmp_path):
    cm = _const_map(tmp_path, A=10, B=20, C=5)
    rc, out, _ = _run(["--constants", str(cm),
                       "--inv", "A < B",
                       "--inv", "C >= B"])
    assert rc == 1
    assert out.count("invariant_violated") == 1


def test_invariants_json_file(tmp_path):
    cm = _const_map(tmp_path, IBT_MAX=22000, FRAME_END=14000)
    inv = tmp_path / "inv.json"
    inv.write_text(json.dumps([{"lhs": "IBT_MAX", "op": "<", "rhs": "FRAME_END"}]))
    rc, _, _ = _run(["--constants", str(cm), "--invariants", str(inv)])
    assert rc == 1


def test_json_output(tmp_path):
    cm = _const_map(tmp_path, A=22000, B=14000)
    out_path = tmp_path / "rep.json"
    rc, _, _ = _run(["--constants", str(cm), "--inv", "A < B",
                     "--json", str(out_path)])
    assert rc == 1
    data = json.loads(out_path.read_text())
    assert data["verdict"] == "FAIL"


def test_no_constants_or_inv_exits_2(tmp_path):
    rc, _, err = _run([])
    assert rc == 2
