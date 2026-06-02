#!/usr/bin/env python3
"""Tests for tb_timing_extremes_check.py (LL-6)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / \
    "tb_timing_extremes_check.py"


def _run(tmp_path: Path, strict: bool = False):
    cmd = [sys.executable, str(PROG), str(tmp_path),
           "--json", str(tmp_path / "rep.json")]
    if strict:
        cmd.append("--strict")
    return subprocess.run(cmd, capture_output=True, text=True)


def _make_l2(tmp_path: Path):
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L2_TIMING_WAVEFORM.json").write_text(json.dumps({
        "ibt_us": [20.0, 22.0],
        "tSRS_min_us": 20.0,
    }))


def _write_tb(tmp_path: Path, body: str):
    sim = tmp_path / "phase2" / "stage1" / "sim_full_stack"
    sim.mkdir(parents=True, exist_ok=True)
    (sim / "tb_full_stack.sv").write_text(body)


def test_tb_only_max_warns(tmp_path):
    _make_l2(tmp_path)
    _write_tb(tmp_path, """\
module tb;
  initial host_idle(22000);  // only ibt_max
endmodule
""")
    r = _run(tmp_path, strict=True)
    assert r.returncode == 1
    rep = json.loads((tmp_path / "rep.json").read_text())
    assert any(f["rule"] == "TB_TIMING_EXTREMES_NOT_COVERED"
               for f in rep["findings"])


def test_tb_only_min_warns(tmp_path):
    _make_l2(tmp_path)
    _write_tb(tmp_path, """\
module tb;
  initial host_idle(20000);  // only ibt_min
endmodule
""")
    r = _run(tmp_path, strict=True)
    assert r.returncode == 1


def test_tb_both_extremes_passes(tmp_path):
    _make_l2(tmp_path)
    _write_tb(tmp_path, """\
module tb;
  initial begin
    host_idle(20000);  // ibt_min
    host_idle(22000);  // ibt_max
  end
endmodule
""")
    r = _run(tmp_path, strict=True)
    assert r.returncode == 0


def test_no_l2_skipped(tmp_path):
    _write_tb(tmp_path, "module tb; endmodule")
    r = _run(tmp_path, strict=True)
    assert r.returncode == 0


def test_no_tb_skipped(tmp_path):
    _make_l2(tmp_path)
    r = _run(tmp_path, strict=True)
    assert r.returncode == 0  # no TB → skip


def test_huge_span_class_skipped(tmp_path):
    """BOR class (500us-999999us) span ratio = 1999. Should be skipped
    automatically — testing the 999999us extreme is impractical."""
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L2_TIMING_WAVEFORM.json").write_text(json.dumps({
        "ibt_us": [20.0, 22.0],
        "tSRS_min_us": 20.0,
        "pulse_classes": [
            {"class_name": "BIT0", "min_us": 3.6, "max_us": 9.4},
            {"class_name": "BOR", "min_us": 500.0, "max_us": 999999.0},
        ],
    }))
    _write_tb(tmp_path, """\
module tb;
  initial begin
    host_idle(20000);
    host_idle(22000);
    host_low(3600);
    host_low(9400);
  end
endmodule
""")
    r = _run(tmp_path, strict=True)
    assert r.returncode == 0
    rep = json.loads((tmp_path / "rep.json").read_text())
    assert any("BOR" in c for c in rep["summary"]["skipped_classes"])
    # ibt + BIT0 covered, BOR auto-skipped → PASS
    assert "BOR" not in rep["summary"]["l2_ranges"]


def test_waiver_skips(tmp_path):
    _make_l2(tmp_path)
    _write_tb(tmp_path, "module tb; initial host_idle(22000); endmodule")
    (tmp_path / "waivers.json").write_text(json.dumps({
        "waivers": [{
            "id": "tb_timing_extremes_override",
            "rationale": "TB at one extreme; compliance tested via FPGA only",
        }],
    }))
    r = _run(tmp_path, strict=True)
    assert r.returncode == 0
