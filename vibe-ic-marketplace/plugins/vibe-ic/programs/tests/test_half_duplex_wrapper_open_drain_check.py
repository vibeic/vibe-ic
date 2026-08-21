#!/usr/bin/env python3
"""Tests for half_duplex_wrapper_open_drain_check.py (LL-17)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / \
    "half_duplex_wrapper_open_drain_check.py"


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


def test_open_drain_split_via_data_passes(tmp_path):
    """`oe ? tx : 1'bz` — synth recognises open-drain pattern."""
    _make_half_duplex(tmp_path)
    _write_rtl(tmp_path, """\
module wrapper;
  logic id_bus_oe, id_bus_tx;
  wire GPIO_id_bus;
  assign GPIO_id_bus = id_bus_oe ? id_bus_tx : 1'bz;
endmodule
""")
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout


def test_open_drain_split_via_condition_passes(tmp_path):
    """`(oe && !tx) ? 1'b0 : 1'bz` — also open-drain."""
    _make_half_duplex(tmp_path)
    _write_rtl(tmp_path, """\
module wrapper;
  logic id_bus_oe, id_bus_tx;
  wire GPIO_id_bus;
  assign GPIO_id_bus = (id_bus_oe && !id_bus_tx) ? 1'b0 : 1'bz;
endmodule
""")
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout


def test_tristate_pattern_fails(tmp_path):
    """`oe ? 1'b0 : 1'bz` — synth infers tristate, NOT open-drain."""
    _make_half_duplex(tmp_path)
    _write_rtl(tmp_path, """\
module wrapper;
  logic id_bus_oe;
  wire GPIO_id_bus;
  assign GPIO_id_bus = id_bus_oe ? 1'b0 : 1'bz;
endmodule
""")
    r = _run(tmp_path)
    assert r.returncode == 1
    assert "tristate pattern" in r.stdout or "single-oe-hardcoded-zero" in r.stdout


def test_push_pull_no_tristate_silently_skipped(tmp_path):
    """An assign without 1'bz isn't a tristate output — gate ignores."""
    _make_half_duplex(tmp_path)
    _write_rtl(tmp_path, """\
module wrapper;
  logic id_bus_oe;
  wire GPIO_id_bus;
  assign GPIO_id_bus = id_bus_oe;  // not tristate-shaped
endmodule
""")
    r = _run(tmp_path)
    assert r.returncode == 0


def test_waiver_skips(tmp_path):
    _make_half_duplex(tmp_path)
    _write_rtl(tmp_path, """\
module wrapper;
  logic id_bus_oe;
  wire GPIO_id_bus;
  assign GPIO_id_bus = id_bus_oe ? 1'b0 : 1'bz;
endmodule
""")
    (tmp_path / "waivers.json").write_text(json.dumps({
        "wrapper_open_drain_alternative":
            "Lab board uses dedicated push-pull driver — wake-only pin",
    }))
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "PASS_WITH_WAIVER" in r.stdout
