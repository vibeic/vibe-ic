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
# _sanitize_id — Verilog reserved-word escaping (H3 / M5)
# ---------------------------------------------------------------------------

def test_sanitize_id_escapes_reserved_words():
    # A signal literally named "reg" / "input" etc. must not stay a bare
    # keyword — otherwise the emitted Verilog is uncompilable.
    for kw in ("reg", "input", "output", "module", "wire", "begin", "end",
               "case", "wait", "logic", "always", "assign"):
        out = scaf._sanitize_id(kw)
        assert out.lower() not in scaf.VERILOG_RESERVED, (
            f"{kw!r} sanitized to bare keyword {out!r}")
        assert out == kw + "_sig"


def test_sanitize_id_reserved_case_insensitive():
    # Mixed/upper case keywords still collide and must be escaped.
    assert scaf._sanitize_id("REG").lower() not in scaf.VERILOG_RESERVED
    assert scaf._sanitize_id("Input").lower() not in scaf.VERILOG_RESERVED


def test_sanitize_id_non_reserved_unchanged():
    # A non-keyword that merely contains a keyword substring is left alone.
    assert scaf._sanitize_id("register_file") == "register_file"
    assert scaf._sanitize_id("input_data") == "input_data"


def test_top_module_name_reserved_escaped():
    out = scaf.derive_top_module_name({"ic_name": "module"}, {}, None)
    assert out.lower() not in scaf.VERILOG_RESERVED
    assert out == "module_sig"


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


def test_signals_no_dup_clk_for_busclock():
    """M2: a real clock named 'BusClock' (SPI/S12SPIV4) must be recognised by
    the auto-add guard so NO spurious second 'clk' port is appended."""
    l17 = {"channels": [
        {"name": "BusClock", "direction_master": "input", "purpose": "bus clk"},
        {"name": "MOSI", "direction_master": "output"},
    ]}
    sigs = scaf.derive_signals(l17, {})
    names = [s["name"] for s in sigs]
    # exactly one clock signal — BusClock — and no auto-added "clk"
    clock_sigs = [n for n in names if scaf._is_clock_name(n)]
    assert clock_sigs == ["BusClock"], clock_sigs
    assert "clk" not in names


def test_signals_no_dup_clk_for_pclk():
    """M2: a real clock named 'PCLK' (AHB/APB) must also be recognised — the
    old startswith('clk') guard missed it and appended a dead 'clk'."""
    l17 = {"channels": [
        {"name": "PCLK", "direction_master": "input", "purpose": "APB clk"},
        {"name": "PRESETn", "direction_master": "input", "purpose": "APB rst"},
    ]}
    sigs = scaf.derive_signals(l17, {})
    names = [s["name"] for s in sigs]
    clock_sigs = [n for n in names if scaf._is_clock_name(n)]
    assert clock_sigs == ["PCLK"], clock_sigs
    assert "clk" not in names
    # PRESETn already a reset → no spurious "rst_n" appended
    assert "rst_n" not in names


def test_detect_rst_active_high_names():
    """M3: names that merely end/start with 'n' must infer ACTIVE-HIGH."""
    for name in ("reset_in", "reset", "rst"):
        sigs = [{"name": name, "direction": "input", "width": 1, "comment": ""}]
        rst, active_low = scaf._detect_rst_port(sigs)
        assert rst == name
        assert active_low is False, f"{name} should be active-high"


def test_detect_rst_active_low_names():
    """M3: canonical active-low forms must infer ACTIVE-LOW."""
    for name in ("rst_n", "resetn", "PRESETn", "aresetn"):
        sigs = [{"name": name, "direction": "input", "width": 1, "comment": ""}]
        rst, active_low = scaf._detect_rst_port(sigs)
        assert rst == name
        assert active_low is True, f"{name} should be active-low"


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
# derive_clock_period_ns (L8)
# ---------------------------------------------------------------------------

def test_clock_period_from_explicit_clock_mhz():
    period, note = scaf.derive_clock_period_ns({"clock_mhz": 100})
    assert period == 10.0  # 100 MHz -> 10 ns
    assert "clock_mhz" in note


def test_clock_period_default_when_absent():
    period, note = scaf.derive_clock_period_ns({})
    assert period == 10.0
    assert "default" in note


def test_clock_period_from_frequency_literal_max():
    l8 = {"auto_discovered_literals": [
        {"kind": "frequency", "value": "25", "unit": "MHz"},
        {"kind": "frequency", "value": "12.5", "unit": "MHz"},
    ]}
    period, _ = scaf.derive_clock_period_ns(l8)
    assert period == 40.0  # 25 MHz (the max) -> 40 ns


def test_clock_period_ignores_subhz_baud_literals():
    # 44.1 kHz is a payload rate, not a core clock — should be ignored,
    # falling back to the default period.
    l8 = {"auto_discovered_literals": [
        {"kind": "frequency", "value": "44.1", "unit": "kHz"},
    ]}
    period, note = scaf.derive_clock_period_ns(l8)
    assert period == 10.0
    assert "default" in note


def test_clock_period_clamped_for_ghz():
    period, _ = scaf.derive_clock_period_ns({"clock_mhz": 5000})  # 5 GHz
    assert period >= 1.0


# ---------------------------------------------------------------------------
# cocotb emitters
# ---------------------------------------------------------------------------

def test_emit_cocotb_test_basic_structure():
    sigs = [
        {"name": "clk", "direction": "input", "width": 1, "comment": ""},
        {"name": "rst_n", "direction": "input", "width": 1, "comment": ""},
        {"name": "q", "direction": "output", "width": 1, "comment": ""},
    ]
    py = scaf.emit_cocotb_test("dut", sigs, {"clock_mhz": 100}, ["cat A"])
    assert "import cocotb" in py
    assert "@cocotb.test()" in py
    assert "Clock(dut.clk" in py
    assert "dut.rst_n.value = 0" in py  # active-low asserted then released
    assert "dut.rst_n.value = 1" in py
    assert "TODO" in py
    assert "cat A" in py  # compliance category surfaced as comment


def test_emit_cocotb_test_active_high_reset():
    sigs = [
        {"name": "clk", "direction": "input", "width": 1, "comment": ""},
        {"name": "reset", "direction": "input", "width": 1, "comment": ""},
    ]
    py = scaf.emit_cocotb_test("dut", sigs, {}, [])
    # active-high reset: assert 1, release 0
    assert "dut.reset.value = 1" in py
    assert "dut.reset.value = 0" in py


def test_emit_cocotb_test_is_valid_python(tmp_path: Path):
    import py_compile
    sigs = [
        {"name": "clk", "direction": "input", "width": 1, "comment": ""},
        {"name": "rst_n", "direction": "input", "width": 1, "comment": ""},
    ]
    py = scaf.emit_cocotb_test("dut", sigs, {}, ["cat A", "cat B"])
    f = tmp_path / "dut_cocotb_test.py"
    f.write_text(py)
    py_compile.compile(str(f), doraise=True)


def test_emit_cocotb_makefile_fields():
    mk = scaf.emit_cocotb_makefile("spi_master")
    assert "TOPLEVEL_LANG ?= verilog" in mk
    assert "VERILOG_SOURCES = $(PWD)/spi_master_top.v" in mk
    assert "TOPLEVEL = spi_master" in mk
    assert "MODULE   = spi_master_cocotb_test" in mk
    assert "SIM ?= icarus" in mk


# ---------------------------------------------------------------------------
# SoC integration wrapper
# ---------------------------------------------------------------------------

def test_emit_soc_wrap_apb_bus_present():
    sigs = [
        {"name": "clk", "direction": "input", "width": 1, "comment": ""},
        {"name": "rst_n", "direction": "input", "width": 1, "comment": ""},
        {"name": "sclk", "direction": "output", "width": 1, "comment": ""},
    ]
    v = scaf.emit_soc_wrap_v("dut", sigs, [])
    for p in ("PCLK", "PRESETn", "PADDR", "PSEL", "PENABLE", "PWRITE",
              "PWDATA", "PRDATA", "PREADY"):
        assert p in v, f"missing APB signal {p}"
    assert "module dut_soc_wrap" in v
    assert "endmodule" in v
    # native port re-exposed
    assert "sclk" in v


def test_emit_soc_wrap_with_regs_decode_stub():
    sigs = [
        {"name": "clk", "direction": "input", "width": 1, "comment": ""},
        {"name": "rst_n", "direction": "input", "width": 1, "comment": ""},
    ]
    regs = [
        {"name": "CTRL", "offset": "0x00", "width": 8, "access": "rw",
         "fields": []},
        {"name": "STATUS", "offset": "0x04", "width": 8, "access": "ro",
         "fields": []},
    ]
    v = scaf.emit_soc_wrap_v("dut", sigs, regs)
    assert "register-file decode stub" in v
    assert "CTRL" in v
    assert "STATUS" in v
    # no read-only ID register path when regs exist
    assert "WRAP_ID" not in v


def test_emit_soc_wrap_no_regs_id_register():
    sigs = [
        {"name": "clk", "direction": "input", "width": 1, "comment": ""},
        {"name": "rst_n", "direction": "input", "width": 1, "comment": ""},
    ]
    v = scaf.emit_soc_wrap_v("dut", sigs, [])
    assert "WRAP_ID" in v
    assert "read-only ID register" in v


def test_emit_soc_wrap_instantiates_block():
    sigs = [
        {"name": "clk", "direction": "input", "width": 1, "comment": ""},
        {"name": "rst_n", "direction": "input", "width": 1, "comment": ""},
        {"name": "din", "direction": "input", "width": 8, "comment": ""},
    ]
    v = scaf.emit_soc_wrap_v("mychip", sigs, [])
    assert "mychip u_mychip" in v
    assert ".clk(PCLK)" in v
    assert ".rst_n(PRESETn)" in v
    assert ".din(din)" in v


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


def _make_keyword_project(tmp: Path) -> Path:
    """Fixture whose L1 ic_name and an L17 channel are Verilog keywords.

    Exercises the H3/M5 reserved-word escaping end to end.
    """
    gd = tmp / "phase1" / "generated_docs"
    gd.mkdir(parents=True, exist_ok=True)
    (gd / "L1_DATASHEET.json").write_text(json.dumps({"ic_name": "module"}))
    (gd / "L17_CHANNEL_SIGNAL_CATALOG.json").write_text(json.dumps({
        "channels": [
            {"name": "reg", "direction_master": "input",
             "purpose": "a channel literally named reg"},
            {"name": "wire", "direction_master": "output",
             "purpose": "a channel literally named wire"},
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
    assert (out_dir / "test_proto_soc_wrap.v").is_file()
    assert (out_dir / "test_proto_cocotb_test.py").is_file()
    assert (out_dir / "Makefile").is_file()
    assert (out_dir / "compliance_vectors.txt").is_file()
    # New report keys
    assert report["clock_period_ns"] == 10.0
    assert report["has_register_file"] is True


def test_emit_scaffold_skip_cocotb_and_soc(tmp_path: Path):
    proj = _make_synth_project(tmp_path)
    scaf.emit_scaffold(proj, skip_cocotb=True, skip_soc=True)
    out_dir = proj / "phase2" / "stage1" / "scaffold"
    assert not (out_dir / "test_proto_cocotb_test.py").is_file()
    assert not (out_dir / "Makefile").is_file()
    assert not (out_dir / "test_proto_soc_wrap.v").is_file()


def test_keyword_sanitize_not_bare_keyword():
    # (a) _sanitize_id("reg") is not a bare keyword.
    assert scaf._sanitize_id("reg").lower() not in scaf.VERILOG_RESERVED


@pytest.mark.skipif(subprocess.run(["which", "iverilog"],
                                   capture_output=True).returncode != 0,
                    reason="iverilog not installed")
def test_keyword_project_iverilog_compiles(tmp_path: Path):
    # (b) emitted top.v + soc_wrap.v + tb.v still iverilog-compile when the
    # ic_name and channels are Verilog keywords.
    proj = _make_keyword_project(tmp_path)
    report = scaf.emit_scaffold(proj)
    assert report["status"] == "ok"
    top = report["top_module"]
    assert top.lower() not in scaf.VERILOG_RESERVED
    out_dir = proj / "phase2" / "stage1" / "scaffold"
    srcs = [
        str(out_dir / f"{top}_top.v"),
        str(out_dir / f"{top}_soc_wrap.v"),
        str(out_dir / f"{top}_tb.v"),
    ]
    out_obj = tmp_path / "kw.out"
    r = subprocess.run(
        ["iverilog", "-g2012", "-o", str(out_obj), *srcs],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, f"iverilog stderr: {r.stderr}"
    assert out_obj.is_file()


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
    soc_v = out_dir / f"{report['top_module']}_soc_wrap.v"
    assert top_v.is_file()
    assert tb_v.is_file()
    assert soc_v.is_file()
    out_obj = tmp_path / "iv.out"
    r = subprocess.run(
        ["iverilog", "-g2012", "-o", str(out_obj),
         str(top_v), str(soc_v), str(tb_v)],
        capture_output=True, text=True,
    )
    assert r.returncode == 0, f"iverilog stderr: {r.stderr}"
    assert out_obj.is_file()
