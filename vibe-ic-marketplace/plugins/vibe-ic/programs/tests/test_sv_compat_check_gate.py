#!/usr/bin/env python3
"""Tests for sv_compat_check.py"""
from __future__ import annotations
import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / \
    "sv_compat_check.py"


def _run(args, **kw):
    return subprocess.run(
        [sys.executable, str(PROG)] + args,
        capture_output=True, text=True, **kw,
    )


def test_help():
    r = _run(["--help"])
    assert r.returncode == 0


def test_pure_verilog(tmp_path):
    (tmp_path / "top.v").write_text("module top; wire a; endmodule\n")
    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    r = _run(["--rtl-dir", str(tmp_path), "--out-dir", str(out)])
    assert r.returncode == 0


# ====================================================================
# Wave 9 (v0.119.41) — Yosys-unfriendly unpacked-array port detection.
# ====================================================================

def test_packed_array_port_passes(tmp_path):
    """Packed array port `[7:0][3:0] foo` is fine for Yosys 0.64.
    The `logic` keyword still triggers needs_sv (return 1) but the
    port-level FAIL_UNPACKED_PORTS message must NOT appear."""
    (tmp_path / "core.sv").write_text("""\
module core(
  input  logic clk,
  output logic [7:0][3:0] foo
);
  assign foo = '0;
endmodule
""")
    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    r = _run(["--rtl-dir", str(tmp_path), "--out-dir", str(out)])
    assert "FAIL_UNPACKED_PORTS" not in r.stdout, r.stdout
    rep = json.loads((out / "sv_compat_report.json").read_text())
    assert rep["unpacked_array_port_count"] == 0, rep


def test_unpacked_array_port_fails(tmp_path):
    """Unpacked array port `output logic [7:0] foo [0:3]` triggers
    Yosys 0.64 — must FAIL with the dedicated message."""
    (tmp_path / "core.sv").write_text("""\
module core(
  input  logic clk,
  output logic [7:0] foo [0:3]
);
endmodule
""")
    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    r = _run(["--rtl-dir", str(tmp_path), "--out-dir", str(out)])
    assert r.returncode == 1, r.stdout + r.stderr
    assert "FAIL_UNPACKED_PORTS" in r.stdout, r.stdout
    rep = json.loads((out / "sv_compat_report.json").read_text())
    assert rep["unpacked_array_port_count"] >= 1, rep


def test_unpacked_internal_array_passes_port_check(tmp_path):
    """Internal (non-port) unpacked array is fine; only port-list
    matches should fail. The `logic` keyword still triggers needs_sv,
    but FAIL_UNPACKED_PORTS must NOT fire."""
    (tmp_path / "core.sv").write_text("""\
module core(
  input  logic clk,
  output logic [7:0] dout
);
  logic [7:0] mem [0:15];     // internal — OK
  assign dout = mem[0];
endmodule
""")
    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    r = _run(["--rtl-dir", str(tmp_path), "--out-dir", str(out)])
    assert "FAIL_UNPACKED_PORTS" not in r.stdout, r.stdout
    rep = json.loads((out / "sv_compat_report.json").read_text())
    assert rep["unpacked_array_port_count"] == 0, rep


def test_unpacked_port_waiver_silences(tmp_path):
    """`yosys_unpacked_port_acceptable` waiver (≥40 chars rationale)
    must silence the FAIL — useful when the project switches to a
    Yosys >= 0.39 build that accepts unpacked ports."""
    (tmp_path / "core.sv").write_text("""\
module core(
  output logic [7:0] foo [0:3]
);
endmodule
""")
    (tmp_path / "waivers.json").write_text(json.dumps({
        "waivers": [{
            "id": "yosys_unpacked_port_acceptable",
            "rationale": (
                "Project uses Yosys 0.41 from oss-cad-suite which "
                "natively elaborates SV unpacked-array ports."
            ),
        }],
    }))
    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    r = _run(["--rtl-dir", str(tmp_path), "--out-dir", str(out)])
    assert "WAIVED_UNPACKED_PORTS" in r.stdout, r.stdout
    # waiver suppresses unpacked-port FAIL but `logic` keyword still
    # triggers needs_sv exit 1
    rep = json.loads((out / "sv_compat_report.json").read_text())
    assert rep["unpacked_array_port_count"] >= 1, rep


def test_unpacked_port_short_waiver_rejected(tmp_path):
    """Rationale <40 chars must NOT silence the FAIL."""
    (tmp_path / "core.sv").write_text("""\
module core(
  output logic [7:0] foo [0:3]
);
endmodule
""")
    (tmp_path / "waivers.json").write_text(json.dumps({
        "waivers": [{
            "id": "yosys_unpacked_port_acceptable",
            "rationale": "skip",
        }],
    }))
    out = tmp_path / "out"
    out.mkdir(parents=True, exist_ok=True)
    r = _run(["--rtl-dir", str(tmp_path), "--out-dir", str(out)])
    assert r.returncode == 1, r.stdout + r.stderr
    assert "FAIL_UNPACKED_PORTS" in r.stdout, r.stdout
