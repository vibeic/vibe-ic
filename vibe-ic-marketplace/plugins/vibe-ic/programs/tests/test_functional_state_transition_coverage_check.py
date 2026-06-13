"""Tests for functional_state_transition_coverage_check.py."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent
        / "functional_state_transition_coverage_check.py")


def _run(args):
    r = subprocess.run([sys.executable, str(PROG), *args],
                       capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


def _tb(tmp_path: Path, body: str, name="tb_top.v") -> Path:
    d = tmp_path / "phase2" / "stage1" / "sim"
    d.mkdir(parents=True, exist_ok=True)
    f = d / name
    f.write_text(body)
    return f


def test_full_coverage_passes(tmp_path):
    _tb(tmp_path, """
module tb;
  initial begin
    send_cmd(8'h74);
    #10;
    if (awake_q !== 1'b1) $fatal;
  end
endmodule
""")
    rc, _, _ = _run([str(tmp_path / "phase2" / "stage1" / "sim"),
                     "--cov", "0x74:awake_q == 1'b1"])
    assert rc == 0


def test_opcode_not_exercised_fails(tmp_path):
    _tb(tmp_path, """
module tb;
  initial begin
    send_cmd(8'h70);
  end
endmodule
""")
    rc, out, _ = _run([str(tmp_path / "phase2" / "stage1" / "sim"),
                       "--cov", "0x74:awake_q == 1'b1"])
    assert rc == 1
    assert "opcode_not_exercised" in out


def test_opcode_exercised_but_no_assertion(tmp_path):
    _tb(tmp_path, """
module tb;
  initial begin
    send_cmd(8'h74);
  end
endmodule
""")
    rc, out, _ = _run([str(tmp_path / "phase2" / "stage1" / "sim"),
                       "--cov", "0x74:awake_q == 1'b1"])
    assert rc == 1
    assert "assertion_missing" in out


def test_coverage_json(tmp_path):
    _tb(tmp_path, """
module tb;
  initial begin
    send_cmd(8'h74);
    if (awake_q !== 1'b1) $fatal;
  end
endmodule
""")
    cov = tmp_path / "cov.json"
    cov.write_text(json.dumps([{"opcode": "0x74",
                                 "must_assert_set": ["awake_q == 1'b1"]}]))
    rc, _, _ = _run([str(tmp_path / "phase2" / "stage1" / "sim"), "--coverage", str(cov)])
    assert rc == 0


def test_multiple_opcodes_partial(tmp_path):
    _tb(tmp_path, """
module tb;
  initial begin
    send_cmd(8'h70);
    if (reg_q != 8'h00) $fatal;
    send_cmd(8'h74);
    // missing awake_q assertion
  end
endmodule
""")
    rc, out, _ = _run([str(tmp_path / "phase2" / "stage1" / "sim"),
                       "--cov", "0x70:reg_q != 8'h00",
                       "--cov", "0x74:awake_q == 1'b1"])
    assert rc == 1
    assert "assertion_missing" in out


def test_json_output(tmp_path):
    _tb(tmp_path, "module tb; initial send_cmd(8'h70); endmodule")
    out = tmp_path / "rep.json"
    rc, _, _ = _run([str(tmp_path / "phase2" / "stage1" / "sim"),
                     "--cov", "0x74:awake_q == 1'b1",
                     "--json", str(out)])
    assert rc == 1
    data = json.loads(out.read_text())
    assert data["verdict"] == "FAIL"


def test_no_coverage_exits_2(tmp_path):
    _tb(tmp_path, "module tb; endmodule")
    rc, _, _ = _run([str(tmp_path / "phase2" / "stage1" / "sim")])
    assert rc == 2
