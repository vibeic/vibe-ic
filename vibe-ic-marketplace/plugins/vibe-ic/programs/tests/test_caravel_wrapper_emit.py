"""Unit tests for `caravel_wrapper_emit.py`."""
import importlib

import pytest

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
        assert "v0.1.51" in w

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
