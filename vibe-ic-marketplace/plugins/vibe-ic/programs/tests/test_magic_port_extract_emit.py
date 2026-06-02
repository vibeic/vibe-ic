"""Unit tests for `magic_port_extract_emit.py` (Route A — canonical fix).

Pin the deterministic shape of the Magic port-labeled extraction TCL and
the shell launch preamble (the env(PDK)-before-magicrc fix). Chip-agnostic.
"""
import importlib

import pytest

mod = importlib.import_module("magic_port_extract_emit")


class TestShellPreamble:
    def test_exports_pdk_before_magic(self):
        pre = mod.build_shell_preamble("sky130A", "/foss/pdks/x", "/tmp/s.tcl")
        lines = pre.splitlines()
        # PDK + PDK_ROOT exports MUST precede the magic invocation line.
        assert lines[0].startswith("export PDK=")
        assert lines[1].startswith("export PDK_ROOT=")
        assert lines[2].startswith("magic ")

    def test_preamble_points_at_foundry_magicrc(self):
        pre = mod.build_shell_preamble("sky130A", "/foss/pdks/x", "/tmp/s.tcl")
        assert "/foss/pdks/x/sky130A/libs.tech/magic/sky130A.magicrc" in pre

    def test_preamble_uses_noconsole_dnull(self):
        pre = mod.build_shell_preamble("sky130A", "/r", "/tmp/s.tcl")
        assert "-noconsole" in pre and "-dnull" in pre

    def test_pdk_normalized_in_preamble(self):
        pre = mod.build_shell_preamble("sky130", "/r", "/tmp/s.tcl")
        assert "export PDK=sky130A" in pre

    def test_gf180_preamble(self):
        pre = mod.build_shell_preamble("gf180", "/r", "/tmp/s.tcl")
        assert "export PDK=gf180mcuC" in pre
        assert "gf180mcuC.magicrc" in pre


class TestExtractionTcl:
    def test_core_sequence_present(self):
        tcl = mod.build_extraction_tcl("top", "/g.gds", "/o.spice")
        assert "gds read /g.gds" in tcl
        assert "load top" in tcl
        assert "port makeall" in tcl
        assert "extract all" in tcl
        assert "ext2spice lvs" in tcl
        assert "ext2spice -o /o.spice" in tcl

    def test_flatten_default_on(self):
        tcl = mod.build_extraction_tcl("top", "/g.gds", "/o.spice")
        assert "flatten top" in tcl

    def test_flatten_can_be_disabled(self):
        opts = mod.MagicExtractOptions(flatten_top=False)
        tcl = mod.build_extraction_tcl("top", "/g.gds", "/o.spice", opts)
        assert "flatten top" not in tcl

    def test_port_makeall_can_be_disabled(self):
        opts = mod.MagicExtractOptions(port_makeall=False)
        tcl = mod.build_extraction_tcl("top", "/g.gds", "/o.spice", opts)
        assert "port makeall" not in tcl

    def test_relabel_emits_port_make(self):
        opts = mod.MagicExtractOptions(relabel_from=[("clk", "met3"),
                                                     ("rst_n", "met3")])
        tcl = mod.build_extraction_tcl("top", "/g.gds", "/o.spice", opts)
        assert "port clk make" in tcl
        assert "port rst_n make" in tcl

    def test_scale_off_default(self):
        tcl = mod.build_extraction_tcl("top", "/g.gds", "/o.spice")
        assert "ext2spice scale off" in tcl

    def test_done_marker(self):
        tcl = mod.build_extraction_tcl("widget", "/g.gds", "/o.spice")
        assert "MAGIC_PORT_EXTRACT_DONE widget" in tcl

    def test_chip_agnostic_arbitrary_top(self):
        tcl = mod.build_extraction_tcl("my_TOP_9", "/g.gds", "/o.spice")
        assert "load my_TOP_9" in tcl
        assert "flatten my_TOP_9" in tcl

    def test_provenance(self):
        tcl = mod.build_extraction_tcl("top", "/g.gds", "/o.spice")
        assert "magic_port_extract_emit.py" in tcl


class TestGdsWriteTcl:
    def test_core_sequence_and_order(self):
        tcl = mod.build_gds_write_tcl("top", "/lay/top.mag", "/out/top.gds")
        # Required commands present.
        assert "load /lay/top.mag" in tcl
        assert "select top cell" in tcl
        assert "gds write /out/top.gds" in tcl
        # Order: load -> select top cell -> gds write.
        i_load = tcl.index("load /lay/top.mag")
        i_sel = tcl.index("select top cell")
        i_gds = tcl.index("gds write /out/top.gds")
        assert i_load < i_sel < i_gds

    def test_done_marker(self):
        tcl = mod.build_gds_write_tcl("widget", "/w.mag", "/w.gds")
        assert "MAGIC_GDS_WRITE_DONE widget -> /w.gds" in tcl

    def test_provenance(self):
        tcl = mod.build_gds_write_tcl("top", "/t.mag", "/t.gds")
        assert "magic_port_extract_emit.py" in tcl

    def test_chip_agnostic_arbitrary_top(self):
        tcl = mod.build_gds_write_tcl("my_TOP_9", "/m.mag", "/m.gds")
        assert "MAGIC_GDS_WRITE_DONE my_TOP_9" in tcl

    @pytest.mark.parametrize("top,mag,gds", [
        ("", "/m.mag", "/g.gds"),
        ("   ", "/m.mag", "/g.gds"),
        ("top", "", "/g.gds"),
        ("top", "   ", "/g.gds"),
        ("top", "/m.mag", ""),
        ("top", "/m.mag", "   "),
        (None, "/m.mag", "/g.gds"),
        ("top", None, "/g.gds"),
        ("top", "/m.mag", None),
    ])
    def test_empty_or_bad_args_raise(self, top, mag, gds):
        with pytest.raises(ValueError):
            mod.build_gds_write_tcl(top, mag, gds)


class TestLefWriteTcl:
    def test_core_sequence_and_order(self):
        tcl = mod.build_lef_write_tcl("top", "/lay/top.mag", "/out/top.lef")
        assert "load /lay/top.mag" in tcl
        assert "select top cell" in tcl
        assert "lef write /out/top.lef" in tcl
        i_load = tcl.index("load /lay/top.mag")
        i_sel = tcl.index("select top cell")
        i_lef = tcl.index("lef write /out/top.lef")
        assert i_load < i_sel < i_lef

    def test_pin_layers_emitted_before_write_in_order(self):
        tcl = mod.build_lef_write_tcl(
            "top", "/t.mag", "/t.lef", pin_layers=["met3", "met4"])
        assert "lef setlayer met3" in tcl
        assert "lef setlayer met4" in tcl
        # Both setlayer lines precede the lef write, in the given order.
        i_m3 = tcl.index("lef setlayer met3")
        i_m4 = tcl.index("lef setlayer met4")
        i_w = tcl.index("lef write /t.lef")
        assert i_m3 < i_m4 < i_w

    def test_no_pin_layers_emits_no_setlayer(self):
        tcl = mod.build_lef_write_tcl("top", "/t.mag", "/t.lef")
        assert "lef setlayer" not in tcl
        # None and empty list are both "rely on default layer set".
        tcl2 = mod.build_lef_write_tcl("top", "/t.mag", "/t.lef", pin_layers=[])
        assert "lef setlayer" not in tcl2

    def test_done_marker(self):
        tcl = mod.build_lef_write_tcl("widget", "/w.mag", "/w.lef")
        assert "MAGIC_LEF_WRITE_DONE widget -> /w.lef" in tcl

    def test_provenance(self):
        tcl = mod.build_lef_write_tcl("top", "/t.mag", "/t.lef")
        assert "magic_port_extract_emit.py" in tcl

    @pytest.mark.parametrize("top,mag,lef", [
        ("", "/m.mag", "/o.lef"),
        ("top", "", "/o.lef"),
        ("top", "/m.mag", ""),
        ("top", "/m.mag", "   "),
        (None, "/m.mag", "/o.lef"),
        ("top", None, "/o.lef"),
        ("top", "/m.mag", None),
    ])
    def test_empty_or_bad_args_raise(self, top, mag, lef):
        with pytest.raises(ValueError):
            mod.build_lef_write_tcl(top, mag, lef)

    @pytest.mark.parametrize("bad_layers", [
        ["met3", ""],
        ["met3", "   "],
        [None],
        ["", "met4"],
    ])
    def test_blank_pin_layer_entry_raises(self, bad_layers):
        with pytest.raises(ValueError):
            mod.build_lef_write_tcl("top", "/t.mag", "/t.lef",
                                    pin_layers=bad_layers)


class TestNoHdlcHardcoding:
    def test_no_hdlc_literal_in_code(self):
        import inspect
        src = inspect.getsource(mod)
        code = src.split('"""', 2)[-1] if src.count('"""') >= 2 else src
        assert "hdlc_core" not in code.replace("RESULT_e2e_pilot.md", "")
