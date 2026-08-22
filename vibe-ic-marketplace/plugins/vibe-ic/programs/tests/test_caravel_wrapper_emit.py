"""Unit tests for `caravel_wrapper_emit.py`."""
import importlib
import re
import shutil
import subprocess

import pytest

from _shipped_version import shipped_plugin_version  # noqa: E402  (#800)
mod = importlib.import_module("caravel_wrapper_emit")


def _spm_pin_map() -> mod.PinMap:
    """The spm pilot's pin-map (golden sample)."""
    return mod.PinMap(
        project_name="spm",
        core_module="spm",
        power_domains=["vccd1", "vssd1"],
        pin_assignments=[
            mod.PinAssignment("clk", "wb_clk_i", "input"),
            mod.PinAssignment("rst", "wb_rst_i", "input"),
            mod.PinAssignment("x[31:0]", "io_in[33:2]", "input"),
            mod.PinAssignment("y", "io_in[34]", "input"),
            mod.PinAssignment("p", "io_out[35]", "output"),
        ],
        unused_tie_offs={
            "io_out[37:36]": "2'b0",
            "io_out[34:0]": "35'b0",
        },
        unused_io_in_ranges=["io_in[1:0]", "io_in[37:36]"],
    )


class TestValidate:
    def test_clean_pin_map_passes(self):
        assert mod.validate_pin_map(_spm_pin_map()) == []

    def test_empty_project_name_fails(self):
        pm = _spm_pin_map()
        pm.project_name = ""
        assert mod.validate_pin_map(pm)

    def test_bad_core_module_fails(self):
        pm = _spm_pin_map()
        pm.core_module = "9bad-id"
        errors = mod.validate_pin_map(pm)
        assert any("not a valid Verilog id" in e for e in errors)

    def test_unknown_golden_port_fails(self):
        pm = _spm_pin_map()
        pm.pin_assignments.append(
            mod.PinAssignment("foo", "fake_port", "input"))
        errors = mod.validate_pin_map(pm)
        assert any("unknown golden port" in e for e in errors)

    def test_unknown_power_domain_fails(self):
        pm = _spm_pin_map()
        pm.power_domains.append("vbad1")
        errors = mod.validate_pin_map(pm)
        assert any("not a Caravel golden power net" in e for e in errors)


class TestEmitWrapper:
    def test_has_default_nettype(self):
        w = mod.emit_wrapper(_spm_pin_map())
        assert "`default_nettype none" in w
        assert "`default_nettype wire" in w

    def test_has_module_user_project_wrapper(self):
        w = mod.emit_wrapper(_spm_pin_map())
        assert "module user_project_wrapper" in w

    def test_has_use_power_pins_block(self):
        w = mod.emit_wrapper(_spm_pin_map())
        assert "`ifdef USE_POWER_PINS" in w
        assert "`endif" in w

    def test_all_golden_ports_present(self):
        w = mod.emit_wrapper(_spm_pin_map())
        for p in mod.CARAVEL_GOLDEN_NON_POWER_PORTS:
            assert p["name"] in w

    def test_conformant_pinout_has_analog_io_and_user_clock2(self):
        # v1.2.x — the mpw_precheck Consistency PORTS check is an EXACT sorted
        # port-name-set compare vs the golden user_project_wrapper. The emitter
        # previously OMITTED analog_io[28:0] + user_clock2, hard-FAILing PORTS
        # (and the CVC power deck's user_clock2 net lookup). They must now be in
        # both the golden table AND the emitted header.
        names = {p["name"] for p in mod.CARAVEL_GOLDEN_NON_POWER_PORTS}
        assert "analog_io" in names and "user_clock2" in names
        w = mod.emit_wrapper(_spm_pin_map())
        header = w[:w.index(");")]
        assert "inout  wire [28:0] analog_io" in header
        assert "input  wire user_clock2" in header

    def test_analog_io_width_matches_golden(self):
        # golden: inout [MPRJ_IO_PADS-10:0] analog_io, MPRJ_IO_PADS=38 → [28:0]
        aio = next(p for p in mod.CARAVEL_GOLDEN_NON_POWER_PORTS
                   if p["name"] == "analog_io")
        assert aio["dir"] == "inout" and aio["width"] == "[28:0]"

    def test_reduced_wrapper_lvs_short_note_present(self):
        # HONEST: the whole-bus constant tie-offs read as LVS 'shorted ports' on
        # a reduced wrapper — the emitter must DISCLOSE that (not silently emit a
        # pattern that fails LVS with no explanation).
        w = mod.emit_wrapper(_spm_pin_map())
        assert "LVS 'shorted ports'" in w

    def test_all_power_ports_present(self):
        w = mod.emit_wrapper(_spm_pin_map())
        for pn in mod.CARAVEL_GOLDEN_POWER_PORTS:
            assert f"inout {pn}" in w

    def test_core_instantiation_present(self):
        w = mod.emit_wrapper(_spm_pin_map())
        assert "spm u_spm" in w

    def test_core_port_to_caravel_pin_mapping(self):
        w = mod.emit_wrapper(_spm_pin_map())
        # clk → wb_clk_i wired in
        assert ".clk (wb_clk_i)" in w
        # x[31:0] → io_in[33:2]
        assert ".x (io_in[33:2])" in w

    def test_output_pin_gets_wire_and_assign(self):
        w = mod.emit_wrapper(_spm_pin_map())
        # spm_p wire declared and used
        assert "wire spm_p;" in w
        assert "assign io_out[35] = spm_p;" in w

    def test_unused_tie_offs_emitted(self):
        w = mod.emit_wrapper(_spm_pin_map())
        assert "assign io_out[37:36] = 2'b0;" in w
        assert "assign io_out[34:0] = 35'b0;" in w

    def test_io_oeb_drives_input_default_and_output_zero(self):
        w = mod.emit_wrapper(_spm_pin_map())
        # io_oeb[35] = 1'b0 because p is output
        assert "assign io_oeb[35] = 1'b0;" in w
        # Other bits get 1's (input mode)
        # io_oeb[34:0] gets driven to all-1's:
        assert "assign io_oeb[34:0]" in w
        # And io_oeb[37:36]:
        assert "assign io_oeb[37:36]" in w

    def test_unused_caravel_outputs_tied_off(self):
        w = mod.emit_wrapper(_spm_pin_map())
        # wbs_ack_o, wbs_dat_o, la_data_out, user_irq tied to defaults
        assert "assign wbs_ack_o = 1'b0;" in w
        assert "assign wbs_dat_o = 32'b0;" in w
        assert "assign la_data_out = 128'b0;" in w
        assert "assign user_irq = 3'b0;" in w

    def test_emit_includes_attribution(self):
        w = mod.emit_wrapper(_spm_pin_map())
        assert "caravel_wrapper_emit.py" in w
        assert f"v{shipped_plugin_version()};" in w

    def test_pin_map_comment_lists_assignments(self):
        w = mod.emit_wrapper(_spm_pin_map())
        # Each pin assignment should appear in the comment header
        assert "spm" in w
        assert "x[31:0]" in w

    def test_output_to_io_out_marks_oeb_zero(self):
        # Two outputs: one at io_out[35], one synthetic at io_out[10]
        pm = _spm_pin_map()
        pm.pin_assignments.append(
            mod.PinAssignment("extra_out", "io_out[10]", "output"))
        w = mod.emit_wrapper(pm)
        assert "assign io_oeb[35] = 1'b0;" in w
        assert "assign io_oeb[10] = 1'b0;" in w


class TestEmitUserDefines:
    def test_emit_has_spdx(self):
        ud = mod.emit_user_defines(_spm_pin_map())
        assert "SPDX-License-Identifier" in ud

    def test_emit_lists_all_user_gpios(self):
        ud = mod.emit_user_defines(_spm_pin_map())
        # GPIO 5 through 37 should all appear
        for i in range(5, 38):
            assert f"USER_CONFIG_GPIO_{i}_INIT" in ud

    def test_io_in_range_assigns_input_mode(self):
        ud = mod.emit_user_defines(_spm_pin_map())
        # spm's x[31:0] = io_in[33:2] → GPIO 2-33 all get INPUT_NOPULL
        for i in (5, 33):
            line = f"USER_CONFIG_GPIO_{i}_INIT"
            assert line in ud
            # Check that this line carries STD_INPUT_NOPULL
            for ud_line in ud.splitlines():
                if line in ud_line:
                    assert "INPUT_NOPULL" in ud_line

    def test_io_out_single_assigns_output_mode(self):
        ud = mod.emit_user_defines(_spm_pin_map())
        # spm's p = io_out[35] → GPIO 35 = OUTPUT
        for ud_line in ud.splitlines():
            if "GPIO_35_INIT" in ud_line:
                assert "OUTPUT" in ud_line

    def test_no_placeholder_xxxx_remaining(self):
        # The whole emit must not leave any USER_CONFIG_GPIO with
        # the placeholder INVALID mode.
        ud = mod.emit_user_defines(_spm_pin_map())
        for line in ud.splitlines():
            if line.startswith("`define USER_CONFIG_GPIO_"):
                assert "GPIO_MODE_INVALID" not in line


class TestIoOebRangeCompute:
    def test_no_outputs_means_full_input_range(self):
        ranges = mod._compute_io_oeb_input_ranges(set())
        # One range covering entire 0-37
        assert ranges == [(0, 37)]

    def test_one_output_splits_ranges(self):
        ranges = mod._compute_io_oeb_input_ranges({35})
        # Output at 35 → input ranges [0,34] and [36,37]
        assert (0, 34) in ranges
        assert (36, 37) in ranges
        assert 35 not in [r for ra in ranges for r in (ra[0], ra[1])
                            if ra[0] == ra[1]]

    def test_multiple_outputs_split_ranges(self):
        ranges = mod._compute_io_oeb_input_ranges({10, 35})
        assert (0, 9) in ranges
        assert (11, 34) in ranges
        assert (36, 37) in ranges


class TestLoadPinMap:
    def test_load_json_format(self, tmp_path):
        import json
        p = tmp_path / "pm.json"
        p.write_text(json.dumps({
            "project_name": "test",
            "core_module": "test_core",
            "power_domains": ["vccd1", "vssd1"],
            "pin_assignments": [
                {"core_port": "clk", "caravel_pin": "wb_clk_i",
                 "port_dir": "input"}
            ],
        }))
        pm = mod.load_pin_map(p)
        assert pm.project_name == "test"
        assert pm.core_module == "test_core"
        assert len(pm.pin_assignments) == 1

    def test_load_json_reads_lvs_short_clean_fields(self, tmp_path):
        import json
        p = tmp_path / "pm.json"
        p.write_text(json.dumps({
            "project_name": "t",
            "core_module": "t",
            "power_domains": ["vccd1", "vssd1"],
            "pin_assignments": [],
            "lvs_short_clean": True,
            "tie_hi_cell": "gf180mcu_fd_sc_mcu7t5v0__tiehi",
            "tie_lo_cell": "gf180mcu_fd_sc_mcu7t5v0__tielo",
            "tie_hi_pin": "Y",
            "tie_lo_pin": "Y",
        }))
        pm = mod.load_pin_map(p)
        assert pm.lvs_short_clean is True
        assert pm.tie_hi_cell == "gf180mcu_fd_sc_mcu7t5v0__tiehi"
        assert pm.tie_lo_cell == "gf180mcu_fd_sc_mcu7t5v0__tielo"
        assert pm.tie_hi_pin == "Y" and pm.tie_lo_pin == "Y"

    def test_default_lvs_short_clean_is_false(self):
        # Backward compat: the historical default is the whole-bus constant.
        assert _spm_pin_map().lvs_short_clean is False


# ---------------------------------------------------------------------------
# v1.2.x LVS-short-clean tie-off mode
# ---------------------------------------------------------------------------
def _clean_pin_map() -> mod.PinMap:
    pm = _spm_pin_map()
    pm.lvs_short_clean = True
    return pm


class TestConstBitHelpers:
    def test_parse_const_bits_all_zero(self):
        assert mod._parse_const_bits("32'b0", 32) == [0] * 32

    def test_parse_const_bits_all_ones_hex(self):
        # 35'h7ffffffff = 35 ones
        assert mod._parse_const_bits("35'h7ffffffff", 35) == [1] * 35

    def test_parse_const_bits_mixed(self):
        # 2'h3 -> both bits 1 ; 3'h5 -> LSB-first 1,0,1
        assert mod._parse_const_bits("2'h3", 2) == [1, 1]
        assert mod._parse_const_bits("3'h5", 3) == [1, 0, 1]

    def test_parse_const_bits_rejects_non_constant(self):
        assert mod._parse_const_bits("some_wire", 4) is None

    def test_expand_full_bus_uses_golden_width(self):
        widths = mod._golden_port_bit_widths()
        specs = mod._expand_const_tie("wbs_dat_o", "32'b0", widths)
        assert len(specs) == 32
        assert all(name == "wbs_dat_o" and val == 0 for name, _, val in specs)
        assert {idx for _, idx, _ in specs} == set(range(32))

    def test_expand_scalar_bus_has_no_index(self):
        widths = mod._golden_port_bit_widths()
        specs = mod._expand_const_tie("wbs_ack_o", "1'b0", widths)
        assert specs == [("wbs_ack_o", None, 0)]

    def test_expand_range_maps_lsb_to_low_index(self):
        widths = mod._golden_port_bit_widths()
        # 2'b10 -> bit0(lo=36)=0, bit1(37)=1
        specs = mod._expand_const_tie("io_out[37:36]", "2'b10", widths)
        val_by_idx = {idx: val for _, idx, val in specs}
        assert val_by_idx == {36: 0, 37: 1}


class TestLvsShortCleanEmit:
    def test_default_mode_keeps_whole_bus_constant(self):
        # Opt-in only: default emit unchanged (backward compat).
        w = mod.emit_wrapper(_spm_pin_map())
        assert "assign wbs_dat_o = 32'b0;" in w
        assert "sky130_fd_sc_hd__conb_1" not in w

    def test_clean_mode_replaces_whole_bus_constant(self):
        w = mod.emit_wrapper(_clean_pin_map())
        # No whole-bus constant tie-offs remain
        assert "assign wbs_dat_o = 32'b0;" not in w
        assert "assign la_data_out = 128'b0;" not in w
        assert "assign io_out[34:0] = 35'b0;" not in w
        # Distinct tie cells now present
        assert "sky130_fd_sc_hd__conb_1 _tiecell_wbs_dat_o_0" in w

    def test_clean_mode_note_present(self):
        w = mod.emit_wrapper(_clean_pin_map())
        assert "LVS-short-clean tie-offs" in w

    def test_clean_mode_distinct_net_per_output_bit(self):
        # THE core LVS property: no two output ports share one net.
        w = mod.emit_wrapper(_clean_pin_map())
        assigns = re.findall(r"assign\s+(\S+)\s*=\s*(_tie_\S+?);", w)
        src_wires = [src for _, src in assigns]
        assert len(src_wires) > 0
        # Every tie-off assign draws from a UNIQUE wire → distinct net.
        assert len(src_wires) == len(set(src_wires))

    def test_clean_mode_one_cell_drives_one_wire(self):
        w = mod.emit_wrapper(_clean_pin_map())
        conns = re.findall(
            r"__conb_1\s+(\S+)\s+\(\.\w+\((_tie_\S+?)\)\);", w)
        inst_names = [inst for inst, _ in conns]
        driven = [wire for _, wire in conns]
        assert len(inst_names) == len(set(inst_names))  # distinct instances
        assert len(driven) == len(set(driven))           # distinct nets
        # Cell-driven net set == assign source-wire set (no dangling / gaps).
        assigns = re.findall(r"assign\s+\S+\s*=\s*(_tie_\S+?);", w)
        assert set(driven) == set(assigns)

    def test_clean_mode_io_oeb_polarity(self):
        # io_oeb bit for an output pin = LO (0 = output-enable); others = HI (1).
        w = mod.emit_wrapper(_clean_pin_map())
        pin_by_bit = dict(
            (int(b), p) for b, p in re.findall(
                r"__conb_1\s+_tiecell_io_oeb_(\d+)\s+\(\.(\w+)\(", w))
        assert pin_by_bit[35] == "LO"   # p is at io_out[35]
        assert pin_by_bit[10] == "HI"   # input/Z default

    def test_clean_mode_count_matches_unused_output_bits(self):
        # spm: 37 unused io_out bits + 38 io_oeb + 1+32+128+3 defaults = 239.
        w = mod.emit_wrapper(_clean_pin_map())
        cells = re.findall(r"__conb_1\s+_tiecell_", w)
        assert len(cells) == 37 + 38 + (1 + 32 + 128 + 3)

    def test_clean_mode_honors_custom_pdk_tie_cell(self):
        pm = _clean_pin_map()
        pm.tie_hi_cell = "gf180mcu_fd_sc_mcu7t5v0__tiehi"
        pm.tie_lo_cell = "gf180mcu_fd_sc_mcu7t5v0__tielo"
        pm.tie_hi_pin = "Y"
        pm.tie_lo_pin = "Y"
        w = mod.emit_wrapper(pm)
        assert "gf180mcu_fd_sc_mcu7t5v0__tielo _tiecell_wbs_dat_o_0 (.Y(" in w
        assert "gf180mcu_fd_sc_mcu7t5v0__tiehi _tiecell_io_oeb_10 (.Y(" in w
        assert "sky130_fd_sc_hd__conb_1" not in w

    def test_clean_mode_no_io_out_bit_double_driven(self):
        # Real output io_out[35] driven by core; tie cells cover the rest —
        # no io_out bit is driven twice.
        w = mod.emit_wrapper(_clean_pin_map())
        tie_bits = set(int(i) for i in re.findall(
            r"assign io_out\[(\d+)\] = _tie_io_out_\d+;", w))
        assert 35 not in tie_bits           # 35 is the real core output
        assert tie_bits == set(range(0, 38)) - {35}


class TestLvsShortCleanSynth:
    """Prove the emitted LVS-clean wrapper is real Verilog: parses/elaborates
    (iverilog) and its distinct tie cells survive synthesis (yosys)."""

    _CORE_STUB = (
        "`default_nettype none\n"
        "module spm(input clk, input rst, input [31:0] x, input y,"
        " output p);\n"
        "  assign p = ^x ^ y ^ clk ^ rst;\n"
        "endmodule\n"
        "`default_nettype wire\n"
    )
    _CONB_BEHAV = (
        "`default_nettype none\n"
        "module sky130_fd_sc_hd__conb_1(output HI, output LO);\n"
        "  assign HI = 1'b1;\n"
        "  assign LO = 1'b0;\n"
        "endmodule\n"
        "`default_nettype wire\n"
    )
    _CONB_BBOX = (
        "`default_nettype none\n"
        "(* blackbox *)\n"
        "module sky130_fd_sc_hd__conb_1(output HI, output LO);\n"
        "endmodule\n"
        "`default_nettype wire\n"
    )

    def _write(self, tmp_path):
        w = tmp_path / "user_project_wrapper.v"
        w.write_text(mod.emit_wrapper(_clean_pin_map()))
        (tmp_path / "spm.v").write_text(self._CORE_STUB)
        return w

    def test_iverilog_elaborates(self, tmp_path):
        if not shutil.which("iverilog"):
            pytest.skip("iverilog not installed")
        w = self._write(tmp_path)
        conb = tmp_path / "conb.v"
        conb.write_text(self._CONB_BEHAV)
        r = subprocess.run(
            ["iverilog", "-g2012", "-t", "null", str(w),
             str(tmp_path / "spm.v"), str(conb)],
            capture_output=True, text=True)
        assert r.returncode == 0, r.stderr

    def test_yosys_keeps_distinct_tie_cells(self, tmp_path):
        if not shutil.which("yosys"):
            pytest.skip("yosys not installed")
        w = self._write(tmp_path)
        conb = tmp_path / "conb_bb.v"
        conb.write_text(self._CONB_BBOX)
        cnt = tmp_path / "cnt.txt"
        script = (
            f"read_verilog -sv {conb}; "
            f"read_verilog -sv {tmp_path / 'spm.v'}; "
            f"read_verilog -sv {w}; "
            "hierarchy -top user_project_wrapper; proc; flatten; "
            "opt -purge; check; "
            f"tee -o {cnt} select -count t:sky130_fd_sc_hd__conb_1"
        )
        r = subprocess.run(["yosys", "-q", "-p", script],
                           capture_output=True, text=True)
        assert r.returncode == 0, r.stderr
        # Every distinct tie cell drives a distinct used output bit, so all
        # survive opt -purge (a whole-bus constant would collapse to 1 net).
        assert "239 objects." in cnt.read_text()
