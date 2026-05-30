"""Tests for phase2_scaffold_gen.py — v0.1.88 Phase 2 scaffolding generator.

Doctrine: the scaffold generator must be GENERAL across all 39+ protocols.
Tests pin (a) Verilog-identifier sanitization, (b) signal-derivation
priority (L17 > L9), (c) FSM state enumeration, (d) register decode, and
(e) end-to-end emit + iverilog compile-ability on representative protocols.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

# Make programs/ importable
PROGRAMS_DIR = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS_DIR))

import phase2_scaffold_gen as scaf  # noqa: E402


# ---------------------------------------------------------------------------
# _sanitize_id
# ---------------------------------------------------------------------------

def test_sanitize_id_basic():
    assert scaf._sanitize_id("MOSI") == "MOSI"
    assert scaf._sanitize_id("SCK") == "SCK"


def test_sanitize_id_strips_spaces():
    assert scaf._sanitize_id("13.56 MHz RF carrier") == "sig_13_56_MHz_RF_carrier"


def test_sanitize_id_leading_digit_prefixed():
    # Verilog identifiers can't start with a digit
    out = scaf._sanitize_id("1Wire DQ")
    assert out[0].isalpha() or out[0] == "_"
    assert out.startswith("sig_") or out.startswith("_")


def test_sanitize_id_special_chars():
    assert scaf._sanitize_id("D+ / D-") == "D_D"
    assert scaf._sanitize_id("PAD[7:0]") == "PAD_7_0"


def test_sanitize_id_empty_fallback():
    assert scaf._sanitize_id("") == "unnamed"
    assert scaf._sanitize_id("   ") == "unnamed"


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

def test_unwrap_fields_passthrough_top_level():
    d = {"channels": [{"name": "A"}]}
    out = scaf._unwrap_fields(d)
    assert "channels" in out


def test_unwrap_fields_merges_nested():
    d = {"fields": {"key": "value"}, "other": "x"}
    out = scaf._unwrap_fields(d)
    assert out["key"] == "value"
    assert out["other"] == "x"


def test_list_or_empty():
    assert scaf._list_or_empty([1, 2, 3]) == [1, 2, 3]
    assert scaf._list_or_empty(None) == []
    assert scaf._list_or_empty("foo") == []


# ---------------------------------------------------------------------------
# derive_top_module_name
# ---------------------------------------------------------------------------

def test_top_module_from_l9():
    out = scaf.derive_top_module_name({}, {"top_module": "spi_master"}, None)
    assert out == "spi_master"


def test_top_module_strips_parens():
    out = scaf.derive_top_module_name(
        {"ic_name": "AMBA AHB + APB (ARM IHI 0033C + IHI 0024C)"}, {}, None)
    assert "(" not in out
    assert out == "AMBA_AHB_APB"


def test_top_module_fallback_dut():
    assert scaf.derive_top_module_name({}, {}, None) == "dut"


# ---------------------------------------------------------------------------
# derive_signals
# ---------------------------------------------------------------------------

def test_signals_from_l17_channels():
    l17 = {"channels": [
        {"name": "MOSI", "direction_master": "output", "purpose": "data out"},
        {"name": "MISO", "direction_master": "input", "purpose": "data in"},
    ]}
    sigs = scaf.derive_signals(l17, {})
    names = [s["name"] for s in sigs]
    assert "MOSI" in names
    assert "MISO" in names
    # clk + rst_n auto-added
    assert any("clk" in n.lower() or "clock" in n.lower() for n in names)
    assert any("rst" in n.lower() for n in names)


def test_signals_dedup():
    l17 = {"channels": [
        {"name": "DQ", "direction_master": "inout"},
        {"name": "DQ", "direction_master": "inout"},
    ]}
    sigs = scaf.derive_signals(l17, {})
    assert sum(1 for s in sigs if s["name"] == "DQ") == 1


def test_signals_direction_normalize():
    l17 = {"channels": [
        {"name": "A", "direction_master": "output (when enabled)"},
        {"name": "B", "direction_master": "input"},
        {"name": "C", "direction_master": "bidirectional"},
    ]}
    sigs = scaf.derive_signals(l17, {})
    dirs = {s["name"]: s["direction"] for s in sigs}
    assert dirs["A"] == "output"
    assert dirs["B"] == "input"
    assert dirs["C"] == "inout"


def test_signals_clk_rst_auto_added_when_missing():
    l17 = {"channels": [{"name": "DQ", "direction_master": "inout"}]}
    sigs = scaf.derive_signals(l17, {})
    names = [s["name"] for s in sigs]
    assert "clk" in names or any("clk" in n.lower() for n in names)
    assert "rst_n" in names or any("rst" in n.lower() for n in names)


# ---------------------------------------------------------------------------
# derive_fsm_states
# ---------------------------------------------------------------------------

def test_fsm_states_dedup():
    l6 = {"fsm_hints": [
        {"name": "IDLE"},
        {"name": "TX"},
        {"name": "IDLE"},  # dup
    ]}
    out = scaf.derive_fsm_states(l6)
    assert out == ["IDLE", "TX"]


def test_fsm_states_master_slave():
    l6 = {
        "fsm_hints_master": [{"name": "M_IDLE"}, {"name": "M_TX"}],
        "fsm_hints_slave":  [{"name": "S_IDLE"}, {"name": "S_RX"}],
    }
    out = scaf.derive_fsm_states(l6)
    assert "M_IDLE" in out
    assert "S_IDLE" in out


def test_fsm_states_capped_at_32():
    l6 = {"fsm_states": [{"name": f"S{i}"} for i in range(50)]}
    out = scaf.derive_fsm_states(l6)
    assert len(out) <= 32


# ---------------------------------------------------------------------------
# derive_registers
# ---------------------------------------------------------------------------

def test_registers_basic_extraction():
    l4 = {"registers": [
        {"name": "CTRL", "offset": "0x00", "width": 8, "access": "rw"},
        {"name": "STATUS", "offset": "0x04", "width": 8, "access": "ro"},
    ]}
    out = scaf.derive_registers(l4, {})
    assert len(out) == 2
    assert out[0]["name"] == "CTRL"
    assert out[1]["access"] == "ro"


def test_registers_width_parse():
    l4 = {"registers": [{"name": "X", "width": "32-bit"}]}
    out = scaf.derive_registers(l4, {})
    assert out[0]["width"] == 32


def test_registers_default_width():
    l4 = {"registers": [{"name": "X"}]}
    out = scaf.derive_registers(l4, {})
    assert out[0]["width"] == 8


# ---------------------------------------------------------------------------
# Verilog emission shape
# ---------------------------------------------------------------------------

def test_emit_top_v_has_module_and_endmodule():
    sigs = [{"name": "clk", "direction": "input", "width": 1, "comment": ""}]
    v = scaf.emit_top_v("dut", sigs, "Test IC")
    assert "module dut" in v
    assert "endmodule" in v
    assert "input" in v


def test_emit_top_v_handles_widths():
    sigs = [{"name": "data", "direction": "input", "width": 8, "comment": ""}]
    v = scaf.emit_top_v("dut", sigs, "Test")
    assert "[7:0]" in v


def test_emit_fsm_v_empty_states():
    v = scaf.emit_fsm_v("dut", [])
    assert "intentionally empty" in v


def test_emit_fsm_v_with_states():
    v = scaf.emit_fsm_v("dut", ["IDLE", "ACTIVE"])
    assert "S_IDLE" in v
    assert "S_ACTIVE" in v
    assert "endmodule" in v


def test_emit_regs_v_empty():
    v = scaf.emit_regs_v("dut", [])
    assert "no addressable register file" in v


def test_emit_tb_v_has_dumpvars():
    sigs = [
        {"name": "clk", "direction": "input", "width": 1, "comment": ""},
        {"name": "rst_n", "direction": "input", "width": 1, "comment": ""},
        {"name": "q", "direction": "output", "width": 1, "comment": ""},
    ]
    v = scaf.emit_tb_v("dut", sigs)
    assert "$dumpfile" in v
    assert "$dumpvars" in v
    assert "u_dut" in v


# ---------------------------------------------------------------------------
# End-to-end emit_scaffold on a synthesized project (no benchmark dependency)
# ---------------------------------------------------------------------------

def _make_synth_project(tmp: Path) -> Path:
    gd = tmp / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L1_DATASHEET.json").write_text(json.dumps({"ic_name": "TestProto"}))
    (gd / "L9_INTEGRATION_SPEC.json").write_text(json.dumps({"top_module": "test_proto"}))
    (gd / "L17_CHANNEL_SIGNAL_CATALOG.json").write_text(json.dumps({
        "channels": [
            {"name": "data_in", "direction_master": "input",
             "purpose": "input signal"},
            {"name": "data_out", "direction_master": "output",
             "purpose": "output signal"},
        ],
    }))
    (gd / "L6_CONTROL_LOGIC.json").write_text(json.dumps({
        "fsm_states": [{"name": "IDLE"}, {"name": "BUSY"}],
    }))
    (gd / "L4_REGMAP.json").write_text(json.dumps({
        "registers": [
            {"name": "CTRL", "offset": "0x00", "width": 8, "access": "rw"},
        ],
    }))
    return tmp


def test_emit_scaffold_e2e(tmp_path: Path):
    proj = _make_synth_project(tmp_path)
    report = scaf.emit_scaffold(proj)
    assert report["status"] == "ok"
    assert report["top_module"] == "test_proto"
    assert report["signals_count"] >= 4  # data_in, data_out + clk + rst_n
    out_dir = proj / "phase2" / "stage1" / "scaffold"
    assert (out_dir / "test_proto_top.v").is_file()
    assert (out_dir / "test_proto_tb.v").is_file()
    assert (out_dir / "test_proto_fsm.v").is_file()
    assert (out_dir / "test_proto_regs.v").is_file()
    assert (out_dir / "compliance_vectors.txt").is_file()


def test_emit_scaffold_skip_tb(tmp_path: Path):
    proj = _make_synth_project(tmp_path)
    report = scaf.emit_scaffold(proj, skip_tb=True)
    assert report["status"] == "ok"
    out_dir = proj / "phase2" / "stage1" / "scaffold"
    assert not (out_dir / "test_proto_tb.v").is_file()


def test_emit_scaffold_missing_phase1(tmp_path: Path):
    # phase1/generated_docs doesn't exist
    report = scaf.emit_scaffold(tmp_path)
    assert report["status"] == "skipped"


@pytest.mark.skipif(subprocess.run(["which", "iverilog"],
                                   capture_output=True).returncode != 0,
                    reason="iverilog not installed")
def test_emit_scaffold_iverilog_compiles(tmp_path: Path):
    """The synthesized project's scaffold must iverilog-compile."""
    proj = _make_synth_project(tmp_path)
    report = scaf.emit_scaffold(proj)
    assert report["status"] == "ok"
    out_dir = proj / "phase2" / "stage1" / "scaffold"
    top_v = out_dir / f"{report['top_module']}_top.v"
    tb_v = out_dir / f"{report['top_module']}_tb.v"
    assert top_v.is_file()
    assert tb_v.is_file()
    out_obj = tmp_path / "iv.out"
    r = subprocess.run(
        ["iverilog", "-g2012", "-o", str(out_obj), str(top_v), str(tb_v)],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, f"iverilog stderr: {r.stderr}"
    assert out_obj.is_file()
