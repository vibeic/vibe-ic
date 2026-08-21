#!/usr/bin/env python3
"""Tests for fpga_port_qsf_consistency_check.py (LL-10)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / \
    "fpga_port_qsf_consistency_check.py"


def _run(tmp_path: Path, strict: bool = False):
    cmd = [sys.executable, str(PROG), str(tmp_path),
           "--json", str(tmp_path / "rep.json")]
    if strict:
        cmd.append("--strict")
    return subprocess.run(cmd, capture_output=True, text=True)


def _make_qsf(tmp_path: Path, signals: dict[str, str]):
    qd = tmp_path / "quartus_work"
    qd.mkdir(parents=True, exist_ok=True)
    text = "\n".join(
        f"set_location_assignment {pin} -to {sig}"
        for sig, pin in signals.items()
    )
    (qd / "proj.qsf").write_text(text + "\n")


def _make_top(tmp_path: Path, port_decls: str):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "fpga_top.sv").write_text(f"""\
module fpga_top (
{port_decls}
);
endmodule
""")


def test_matched_ports_pass(tmp_path):
    _make_qsf(tmp_path, {
        "MAX10_clk_50MHz": "PIN_P11",
        "KEY_rstn":         "PIN_B8",
        "GPIO_id_bus":      "PIN_V10",
    })
    _make_top(tmp_path, """\
  input  wire        MAX10_clk_50MHz,
  input  wire        KEY_rstn,
  inout  wire        GPIO_id_bus""")
    r = _run(tmp_path, strict=True)
    assert r.returncode == 0, f"stdout: {r.stdout}"


def test_qsf_unmatched_in_rtl_fails(tmp_path):
    _make_qsf(tmp_path, {
        "MAX10_clk_50MHz": "PIN_P11",
        "GPIO_id_bus":      "PIN_V10",
    })
    # RTL uses different name (the v0119_fresh_v2 bug)
    _make_top(tmp_path, """\
  input  wire        MAX10_CLK1_50,
  inout  wire        ARDUINO_IO_8""")
    r = _run(tmp_path, strict=True)
    assert r.returncode == 1
    rep = json.loads((tmp_path / "rep.json").read_text())
    findings = rep["findings"]
    assert any(f["rule"] == "QSF_SIGNAL_NOT_IN_RTL_TOP"
               for f in findings)
    unmatched = rep["summary"]["qsf_unmatched_in_rtl"]
    assert "GPIO_id_bus" in unmatched
    assert "MAX10_clk_50MHz" in unmatched


def test_no_qsf_skipped(tmp_path):
    _make_top(tmp_path, """  inout  wire    foo""")
    r = _run(tmp_path, strict=True)
    assert r.returncode == 0


def test_no_fpga_top_skipped(tmp_path):
    _make_qsf(tmp_path, {"x": "PIN_A1"})
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "internal.sv").write_text(
        "module internal(input a, output b); endmodule\n"
    )
    r = _run(tmp_path, strict=True)
    assert r.returncode == 0


def test_non_top_inout_module_ignored_by_fallback(tmp_path):
    """v0.119.5 hardening: a non-top module with `inout` (e.g. an
    analog pad submodule, an I/O cell wrapper) must NOT be matched by
    the fallback. Previously the fallback matched ANY module with
    `inout`, which could falsely identify an analog-pad block as the
    FPGA top in a mixed-signal project. With v0.119.5 the fallback
    requires `top` in module name OR file name, so the module below
    (`io_pad_block` in `io_pads.sv`) must be ignored — and since no
    top is found, the gate returns skipped (rc=0) instead of running
    the consistency check against the wrong module."""
    _make_qsf(tmp_path, {"GPIO_id_bus": "PIN_V10"})
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / "io_pads.sv").write_text("""\
module io_pad_block (
  input  logic        oe,
  inout  wire         pad,
  output logic        din
);
endmodule
""")
    r = _run(tmp_path, strict=True)
    # With fallback tightened, no fpga-top is found → silent skip.
    # rc=0 with `skipped_reason` referencing missing top.
    assert r.returncode == 0
    rep = json.loads((tmp_path / "rep.json").read_text())
    assert rep["summary"].get("skipped_reason"), \
        "must skip when no top-named inout-bearing module exists"
    # Specifically, must NOT have parsed io_pad_block's `pad` as a top
    # port — that would be the false-positive the hardening prevents.
    assert "pad" not in (rep["summary"].get("rtl_ports") or [])


def test_waiver_skips(tmp_path):
    _make_qsf(tmp_path, {"GPIO_id_bus": "PIN_V10"})
    _make_top(tmp_path, "  inout  wire   weird_name")
    (tmp_path / "waivers.json").write_text(json.dumps({
        "waivers": [{"id": "fpga_port_qsf_unconstrained",
                     "rationale": "Pre-prototype, pin assignment frozen later"}],
    }))
    r = _run(tmp_path, strict=True)
    assert r.returncode == 0


def test_bus_index_normalized(tmp_path):
    """LED[0]..LED[7] in QSF should all map to base name LED matching the
    RTL port declared as `output [7:0] LED`."""
    qd = tmp_path / "quartus_work"
    qd.mkdir(parents=True, exist_ok=True)
    (qd / "p.qsf").write_text("""
set_location_assignment PIN_A8 -to LED[0]
set_location_assignment PIN_A9 -to LED[1]
""")
    _make_top(tmp_path, "  output wire [7:0]  LED,\n  inout  wire  bus")
    # Add bus to QSF to satisfy fpga-top requires-inout heuristic
    with open(qd / "p.qsf", "a") as f:
        f.write("set_location_assignment PIN_V10 -to bus\n")
    r = _run(tmp_path, strict=True)
    rep = json.loads((tmp_path / "rep.json").read_text())
    assert "LED" in rep["summary"]["qsf_signals"]
    assert "LED" in rep["summary"]["rtl_ports"]
    assert "LED" not in rep["summary"]["qsf_unmatched_in_rtl"]
