#!/usr/bin/env python3
"""Tests for response_latency_observability_check.py (LL-5)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / \
    "response_latency_observability_check.py"


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


def _write_top(tmp_path: Path, body: str, fpga: bool = True):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "fpga_top.sv").write_text(body)
    if fpga:
        # Gate now requires FPGA constraints to fire (skips ASIC-only)
        (tmp_path / "example_chip.qsf").write_text("# stub")


def test_top_without_observable_warns(tmp_path):
    _make_l2(tmp_path)
    _write_top(tmp_path, """\
module fpga_top (
  input  logic clk,
  input  logic rstn,
  output logic [7:0] LED
);
endmodule
""")
    r = _run(tmp_path, strict=True)
    assert r.returncode == 1
    rep = json.loads((tmp_path / "rep.json").read_text())
    assert any(f["rule"] == "MISSING_RESPONSE_LATENCY_OBSERVABLE"
               for f in rep["findings"])


def test_top_with_dbg_latency_passes(tmp_path):
    _make_l2(tmp_path)
    _write_top(tmp_path, """\
module fpga_top (
  input  logic clk,
  input  logic rstn,
  output logic [15:0] dbg_response_latency_cycles,
  output logic [7:0]  LED
);
endmodule
""")
    r = _run(tmp_path, strict=True)
    assert r.returncode == 0


def test_top_with_dbg_resp_cyc_passes(tmp_path):
    _make_l2(tmp_path)
    _write_top(tmp_path, """\
module my_chip_top (
  output logic [15:0] dbg_resp_cyc_cnt
);
endmodule
""")
    r = _run(tmp_path, strict=True)
    assert r.returncode == 0


def test_non_half_duplex_skipped(tmp_path):
    _write_top(tmp_path, """\
module fpga_top (output logic [7:0] LED);
endmodule
""")
    r = _run(tmp_path, strict=True)
    assert r.returncode == 0  # skipped (no L2)


def test_asic_only_project_skipped(tmp_path):
    """No .qsf/.xdc → ASIC-only project, gate doesn't apply."""
    _make_l2(tmp_path)
    _write_top(tmp_path, """\
module fpga_top (output logic [7:0] LED);
endmodule
""", fpga=False)
    r = _run(tmp_path, strict=True)
    assert r.returncode == 0
    rep = json.loads((tmp_path / "rep.json").read_text())
    assert "ASIC project" in rep["summary"]["skipped_reason"]


def test_signaltap_present_skipped(tmp_path):
    """If signaltap config present, alternative observability — skip."""
    _make_l2(tmp_path)
    _write_top(tmp_path, """\
module fpga_top (output logic [7:0] LED);
endmodule
""")
    (tmp_path / "signaltap.stp").write_text("# fake signaltap")
    r = _run(tmp_path, strict=True)
    assert r.returncode == 0
    rep = json.loads((tmp_path / "rep.json").read_text())
    assert "signaltap" in rep["summary"]["skipped_reason"]


def test_top_with_suffix_order_dbg_passes(tmp_path):
    """v0.119.1: bidirectional regex must accept latency-then-dbg order."""
    _make_l2(tmp_path)
    _write_top(tmp_path, """\
module fpga_top (
  input  logic clk,
  output logic [15:0] response_latency_dbg_o
);
endmodule
""")
    r = _run(tmp_path, strict=True)
    assert r.returncode == 0, "latency_dbg suffix order must be accepted"


def test_top_with_monitor_prefix_passes(tmp_path):
    """v0.119.1: 'monitor_' is a valid observability marker."""
    _make_l2(tmp_path)
    _write_top(tmp_path, """\
module fpga_top (
  input  logic clk,
  output logic [15:0] monitor_resp_cyc_cnt
);
endmodule
""")
    r = _run(tmp_path, strict=True)
    assert r.returncode == 0


def test_top_with_obs_suffix_passes(tmp_path):
    """v0.119.1: 'obs' marker after latency keyword."""
    _make_l2(tmp_path)
    _write_top(tmp_path, """\
module fpga_top (
  input  logic clk,
  output logic [15:0] response_cycles_obs
);
endmodule
""")
    r = _run(tmp_path, strict=True)
    assert r.returncode == 0


def test_no_false_alert_on_dbg_clk(tmp_path):
    """v0.119.1: a 'dbg_clk' port must NOT count as latency observable
    (no latency token present)."""
    _make_l2(tmp_path)
    _write_top(tmp_path, """\
module fpga_top (
  input  logic clk,
  output logic dbg_clk,
  output logic [7:0] LED
);
endmodule
""")
    r = _run(tmp_path, strict=True)
    assert r.returncode == 1, \
        "dbg_clk has no latency token — gate must still flag missing observable"


def test_no_false_alert_on_response_data(tmp_path):
    """v0.119.1: a 'response_data' port has no observability marker
    and shouldn't be misread as a latency observable."""
    _make_l2(tmp_path)
    _write_top(tmp_path, """\
module fpga_top (
  input  logic clk,
  output logic [7:0] response_data,
  output logic [7:0] LED
);
endmodule
""")
    r = _run(tmp_path, strict=True)
    assert r.returncode == 1, \
        "response_data lacks observability marker — must not satisfy gate"


def test_waiver_skips(tmp_path):
    _make_l2(tmp_path)
    _write_top(tmp_path, """\
module fpga_top (output logic [7:0] LED);
endmodule
""")
    (tmp_path / "waivers.json").write_text(json.dumps({
        "waivers": [{
            "id": "response_latency_alternative_observable",
            "rationale": "Project uses external bus analyzer for latency",
        }],
    }))
    r = _run(tmp_path, strict=True)
    assert r.returncode == 0
