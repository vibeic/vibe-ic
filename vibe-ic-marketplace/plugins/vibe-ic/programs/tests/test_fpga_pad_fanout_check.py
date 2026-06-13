#!/usr/bin/env python3
"""Tests for fpga_pad_fanout_check.py (LL-23)."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / \
    "fpga_pad_fanout_check.py"


def _run(tmp_path: Path):
    return subprocess.run([sys.executable, str(PROG), str(tmp_path)],
                          capture_output=True, text=True)


def _write_fit_rpt(tmp_path: Path, body: str):
    out = tmp_path / "output_files"
    out.mkdir(parents=True, exist_ok=True)
    (out / "myproj.fit.rpt").write_text(body)


def _make_fitter_pin_row(pin_name: str, fanout: int,
                         oe_source: str = "tx_phy:u_tx|WideNor0 (inverted)"):
    """Synthesize a Quartus-style ';'-delimited fitter table row.
    Position 1 = name, position 7 = combinational fan-out."""
    return f"; {pin_name:18}; PIN_V10        ; ; ; output ;       ; {fanout} ; {oe_source} ;"


def test_no_fit_rpt_silent_pass(tmp_path):
    """Compile hasn't run yet → gate skipped."""
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "no Quartus fit.rpt" in r.stdout


def test_fit_rpt_no_bus_pin_passes(tmp_path):
    """fit.rpt exists but no half-duplex pin in pin table."""
    _write_fit_rpt(tmp_path, _make_fitter_pin_row("LED[0]", 1))
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "no half-duplex bus pin" in r.stdout


def test_bus_pin_fanout_1_passes(tmp_path):
    _write_fit_rpt(tmp_path, _make_fitter_pin_row("GPIO_id_bus", 1,
                                                   "GPIO_id_bus~2 (inverted)"))
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "Combinational Fan-Out ≤ 1" in r.stdout


def test_bus_pin_fanout_5_fails(tmp_path):
    """v3 benchmark_a bug: GPIO_id_bus had fan-out 5 routing through deep
    tx_phy combinational logic → connect_test FAIL."""
    _write_fit_rpt(tmp_path, _make_fitter_pin_row("GPIO_id_bus", 5))
    r = _run(tmp_path)
    assert r.returncode == 1
    assert "Combinational Fan-Out > 1" in r.stdout
    assert "GPIO_id_bus" in r.stdout


def test_lin_bus_fanout_3_fails(tmp_path):
    """Generic across protocols: lin_bus also flagged."""
    _write_fit_rpt(tmp_path, _make_fitter_pin_row("lin_bus_io", 3))
    r = _run(tmp_path)
    assert r.returncode == 1
    assert "lin_bus_io" in r.stdout


def test_waiver_skips(tmp_path):
    _write_fit_rpt(tmp_path, _make_fitter_pin_row("GPIO_id_bus", 5))
    (tmp_path / "waivers.json").write_text(json.dumps({
        "fpga_pad_fanout_alternative":
            "Custom analog buffer compensates the slow edge",
    }))
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "PASS_WITH_WAIVER" in r.stdout


# v0.119.28 regression: project-declared `pad_definitions[].fpga_alias`
# extends the half-duplex hint set ONLY for pads whose canonical name
# already matches a built-in hint. A non-bus pad alias (e.g. RSTN /
# KEY[0]) must NOT pull that pad into bus-pin scope.
def _write_l2_alias(tmp_path: Path, pad_defs):
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L2_FRS.json").write_text(json.dumps({
        "pad_definitions": pad_defs,
    }))


def test_v028_alias_on_bus_pad_extends_scope(tmp_path):
    """Positive: when L2 declares `pad_definitions[].fpga_alias` for a
    pad whose canonical name IS a half-duplex hint (e.g. `id_bus` →
    `BUS_IO_PIN`), the alias is added to the hint set and the gate
    flags fan-out on the alias name as well."""
    _write_l2_alias(tmp_path, [
        {"name": "id_bus", "fpga_alias": "BUS_IO_PIN"},
    ])
    _write_fit_rpt(tmp_path, _make_fitter_pin_row("BUS_IO_PIN", 4))
    r = _run(tmp_path)
    assert r.returncode == 1, \
        f"alias should extend scope and gate should fail: {r.stdout}"
    assert "BUS_IO_PIN" in r.stdout


def test_v028_alias_on_non_bus_pad_does_not_extend_scope(tmp_path):
    """Negative: an alias on RSTN / KEY[0] must NOT pull that pad into
    bus-pin scope (these are reset/button pins with naturally high
    fan-out — flagging them would be a false alarm)."""
    _write_l2_alias(tmp_path, [
        {"name": "RSTN",  "fpga_alias": "KEY[0]"},
        {"name": "TXLED", "fpga_alias": "LED[7]"},
    ])
    _write_fit_rpt(tmp_path, _make_fitter_pin_row("KEY[0]", 8))
    r = _run(tmp_path)
    assert r.returncode == 0, \
        f"non-bus alias must NOT elevate to bus-pin scope: {r.stdout}"
    assert "no half-duplex bus pin" in r.stdout


def test_v028_top_level_fpga_pin_aliases_dict(tmp_path):
    """Positive: top-level `fpga_pin_aliases` dict path also works,
    same canonical-name gating."""
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L2_FRS.json").write_text(json.dumps({
        "fpga_pin_aliases": {
            "id_bus": ["BUS_IO_PIN"],
            "RSTN":   ["KEY[0]"],   # MUST NOT extend scope
        },
    }))
    _write_fit_rpt(tmp_path, _make_fitter_pin_row("BUS_IO_PIN", 5))
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout
    assert "BUS_IO_PIN" in r.stdout
