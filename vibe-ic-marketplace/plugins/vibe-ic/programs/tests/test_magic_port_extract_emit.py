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


class TestNoHdlcHardcoding:
    def test_no_hdlc_literal_in_code(self):
        import inspect
        src = inspect.getsource(mod)
        code = src.split('"""', 2)[-1] if src.count('"""') >= 2 else src
        assert "hdlc_core" not in code.replace("RESULT_e2e_pilot.md", "")
