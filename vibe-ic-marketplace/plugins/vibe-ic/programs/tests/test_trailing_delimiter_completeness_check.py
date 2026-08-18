"""Tests for trailing_delimiter_completeness_check.py."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "trailing_delimiter_completeness_check.py"


def _run(args):
    r = subprocess.run([sys.executable, str(PROG), *args],
                       capture_output=True, text=True)
    return r.returncode, r.stdout, r.stderr


_GOOD_TB = """
module tb;
  initial begin
    // CMD 0x70 register read
    send_cmd(0x70);
    drive_br_high();
    #100;
    // CMD 0x74 wake
    send_cmd(0x74);
    drive_BR_HIGH();
    #500_000;
    $finish;
  end
endmodule
"""

_BAD_TB = """
module tb;
  initial begin
    // CMD 0x70 register read
    send_cmd(0x70);
    #500_000;
    // CMD 0x74 wake
    send_cmd(0x74);
    #500_000;
    $finish;
  end
endmodule
"""


def _write_tb(tmp_path: Path, name: str, body: str) -> Path:
    f = tmp_path / "phase2" / "stage1" / "sim"
    f.mkdir(parents=True, exist_ok=True)
    p = f / name
    p.write_text(body)
    return p


def test_good_tb_passes(tmp_path):
    _write_tb(tmp_path, "tb_good.v", _GOOD_TB)
    rc, out, _ = _run([str(tmp_path / "phase2" / "stage1" / "sim"), "--delimiter", "BR_HIGH"])
    assert rc == 0, f"out={out}"


def test_bad_tb_fails(tmp_path):
    _write_tb(tmp_path, "tb_bad.v", _BAD_TB)
    rc, out, _ = _run([str(tmp_path / "phase2" / "stage1" / "sim"), "--delimiter", "BR_HIGH"])
    assert rc == 1
    assert "trailing_delimiter_missing" in out


def test_delimiter_from_l3_json(tmp_path):
    _write_tb(tmp_path, "tb_bad.v", _BAD_TB)
    l3 = tmp_path / "L3_CMD_PROTOCOL.json"
    l3.write_text(json.dumps({"trailing_delimiter": "BR_HIGH"}))
    rc, out, _ = _run([str(tmp_path / "phase2" / "stage1" / "sim"), "--layer-l3", str(l3)])
    assert rc == 1
    assert "trailing_delimiter_missing" in out


def test_delimiter_from_l9_nested(tmp_path):
    _write_tb(tmp_path, "tb_bad.v", _BAD_TB)
    l9 = tmp_path / "L9_INTEGRATION_SPEC.json"
    l9.write_text(json.dumps({"protocol": {"trailing_delimiter": "BR_HIGH"}}))
    rc, out, _ = _run([str(tmp_path / "phase2" / "stage1" / "sim"), "--layer-l9", str(l9)])
    assert rc == 1


def test_no_delimiter_resolved_skips(tmp_path):
    """v1.6.7: positional dir without any delimiter source SKIPs (rc=0,
    verdict=SKIP) instead of erroring out."""
    _write_tb(tmp_path, "tb.v", _GOOD_TB)
    rc, out, _ = _run([str(tmp_path / "phase2" / "stage1" / "sim")])
    assert rc == 0
    assert '"verdict": "SKIP"' in out


def test_json_output_path(tmp_path):
    _write_tb(tmp_path, "tb_bad.v", _BAD_TB)
    out = tmp_path / "rep.json"
    rc, _, _ = _run([str(tmp_path / "phase2" / "stage1" / "sim"), "--delimiter", "BR_HIGH",
                     "--json", str(out)])
    assert rc == 1
    data = json.loads(out.read_text())
    assert data["verdict"] == "FAIL"
    assert data["errors"] >= 2  # both packets bad


def test_no_tb_files_warns(tmp_path):
    empty = tmp_path / "empty"
    empty.mkdir(parents=True, exist_ok=True)
    rc, out, _ = _run([str(empty), "--delimiter", "BR_HIGH"])
    # No errors but a WARN — overall verdict still PASS (no ERRORs)
    assert rc == 0
