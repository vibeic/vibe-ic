#!/usr/bin/env python3
"""Tests for single_bus_driver_check.py (LL-16)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / \
    "single_bus_driver_check.py"


def _run(tmp_path: Path):
    return subprocess.run([sys.executable, str(PROG), str(tmp_path)],
                          capture_output=True, text=True)


def _make_half_duplex(tmp_path: Path):
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L2_FRS.json").write_text(json.dumps({
        "tSRS_min_us": 20.0, "ibt_us": [20.0, 22.0],
    }))


def _write_rtl(tmp_path: Path, body: str, name: str = "wrapper.sv"):
    rtl = tmp_path / "phase2" / "stage1" / "rtl"
    rtl.mkdir(parents=True, exist_ok=True)
    (rtl / name).write_text(body)


def test_non_half_duplex_silent_pass(tmp_path):
    _write_rtl(tmp_path, "module m; endmodule")
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "not half-duplex" in r.stdout


def test_single_driver_passes(tmp_path):
    _make_half_duplex(tmp_path)
    _write_rtl(tmp_path, """\
module wrapper;
  logic tx_oe;
  logic id_bus_oe;
  assign id_bus_oe = tx_oe;
endmodule
""")
    r = _run(tmp_path)
    assert r.returncode == 0


def test_or_two_drivers_fails(tmp_path):
    """Classic fresh-agent bug: wake FSM ORed in parallel with tx_phy."""
    _make_half_duplex(tmp_path)
    _write_rtl(tmp_path, """\
module wrapper;
  logic tx_oe, wake_drv;
  logic id_bus_oe;
  assign id_bus_oe = tx_oe | wake_drv;
endmodule
""")
    r = _run(tmp_path)
    assert r.returncode == 1
    assert "tx_oe" in r.stdout and "wake_drv" in r.stdout


def test_ternary_counts_as_single_driver(tmp_path):
    """A ternary mux selects ONE source at a time — not multi-driver."""
    _make_half_duplex(tmp_path)
    _write_rtl(tmp_path, """\
module wrapper;
  logic sel, src_a, src_b;
  logic id_bus_oe;
  assign id_bus_oe = sel ? src_a : src_b;
endmodule
""")
    r = _run(tmp_path)
    assert r.returncode == 0


def test_or_with_constant_zero_passes(tmp_path):
    """`tx_oe | 1'b0` is a single real driver."""
    _make_half_duplex(tmp_path)
    _write_rtl(tmp_path, """\
module wrapper;
  logic tx_oe;
  logic id_bus_oe;
  assign id_bus_oe = tx_oe | 1'b0;
endmodule
""")
    r = _run(tmp_path)
    assert r.returncode == 0


def test_waiver_skips(tmp_path):
    _make_half_duplex(tmp_path)
    _write_rtl(tmp_path, """\
module wrapper;
  logic tx_oe, wake_drv;
  logic id_bus_oe;
  assign id_bus_oe = tx_oe | wake_drv;
endmodule
""")
    (tmp_path / "waivers.json").write_text(json.dumps({
        "single_bus_driver_alternative":
            "Multi-master arbitration scheme intentional",
    }))
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "PASS_WITH_WAIVER" in r.stdout


# ====================================================================
# Wave 10 (v0.119.42) — open-drain OR-of-enables PASSes when consumed
# by a single tristate. False-positive surfaced in the v0.119.41
# fresh-agent benchmark where the legitimate
#   assign id_bus_oe = wake_drv | tx_drv_low;
#   assign id_bus    = id_bus_oe ? 1'b0 : 1'bz;
# was flagged as a multi-driver FAIL even though `id_bus` has exactly
# one driver (the tristate). All numbers / names below are bus-name
# agnostic — the gate must work for any half-duplex bus net.
# ====================================================================

def test_wave10_or_enables_with_single_tristate_passes(tmp_path):
    """Standard half-duplex open-drain pattern: OR of LOW pull-down
    enables consumed by a single tristate `assign bus = oe ? 0 : Z`.
    `id_bus` has one driver; OR of enables is a control input."""
    _make_half_duplex(tmp_path)
    _write_rtl(tmp_path, """\
module wrapper;
  logic wake_drv, tx_drv_low;
  logic id_bus_oe;
  wire id_bus;
  assign id_bus_oe = wake_drv | tx_drv_low;
  assign id_bus    = id_bus_oe ? 1'b0 : 1'bz;
endmodule
""")
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "single physical driver" in r.stdout, r.stdout


def test_wave10_three_way_or_with_single_tristate_passes(tmp_path):
    """Three FSM enables OR-ed into one tristate — still one physical
    driver."""
    _make_half_duplex(tmp_path)
    _write_rtl(tmp_path, """\
module wrapper;
  logic drv_wake, drv_br, drv_byte;
  logic id_bus_oe;
  wire id_bus;
  assign id_bus_oe = drv_wake | drv_br | drv_byte;
  assign id_bus    = id_bus_oe ? 1'b0 : 1'bz;
endmodule
""")
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr


def test_wave10_two_assign_to_bus_fails(tmp_path):
    """Two `assign <bus> = ...;` statements driving the same bus net
    is the genuine multi-driver violation."""
    _make_half_duplex(tmp_path)
    _write_rtl(tmp_path, """\
module wrapper;
  logic a_low, b_low;
  wire id_bus;
  assign id_bus = a_low ? 1'b0 : 1'bz;
  assign id_bus = b_low ? 1'b0 : 1'bz;
endmodule
""")
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "driven by 2" in r.stdout and "assign" in r.stdout, r.stdout


def test_wave10_two_always_blocks_fail(tmp_path):
    """Two always_ff blocks both writing to the same bus net is a
    multi-driver violation."""
    _make_half_duplex(tmp_path)
    _write_rtl(tmp_path, """\
module wrapper(input clk);
  reg id_bus;
  always_ff @(posedge clk) begin
    id_bus <= 1'b0;
  end
  always_ff @(posedge clk) begin
    id_bus <= 1'b1;
  end
endmodule
""")
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "multiple always blocks" in r.stdout, r.stdout


def test_wave10_chip_agnostic_bus_name(tmp_path):
    """The OR-of-enables PASS path must work for any bus net name
    matching the heuristic (kline, lin_bus, owire, …) — NOT just
    `id_bus`."""
    _make_half_duplex(tmp_path)
    _write_rtl(tmp_path, """\
module wrapper;
  logic wake_drv, tx_drv;
  logic kline_oe;
  wire  kline;
  assign kline_oe = wake_drv | tx_drv;
  assign kline    = kline_oe ? 1'b0 : 1'bz;
endmodule
""")
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr


def test_wave10_or_without_tristate_still_fails(tmp_path):
    """Sanity: OR-of-enables WITHOUT a tristate consumer is still the
    original anti-pattern (the OR fans out unsafely). Must FAIL."""
    _make_half_duplex(tmp_path)
    _write_rtl(tmp_path, """\
module wrapper;
  logic tx_oe, wake_drv;
  logic id_bus_oe;
  assign id_bus_oe = tx_oe | wake_drv;
  // NO tristate consumer — id_bus_oe is just floating.
endmodule
""")
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
