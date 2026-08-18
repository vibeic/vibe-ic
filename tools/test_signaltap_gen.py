#!/usr/bin/env python3
"""
Unit tests for signaltap_gen.py -- SignalTap II STP Generator
==============================================================
Tests port parsing, STP XML generation, trigger/depth config.
Run: python3 test_signaltap_gen.py
"""

import os
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from signaltap_gen import (
    parse_ports_from_sv,
    parse_ports_from_string,
    generate_stp_xml,
    Port,
    BIST_SIGNALS,
)


# ============================================================================
# Mock SystemVerilog
# ============================================================================

MOCK_SV = """\
module cd4013b (
    input  logic       clk1,
    input  logic       d1,
    input  logic       s1,
    input  logic       r1,
    output logic       q1,
    output logic       q1_bar,
    input  logic [7:0] data_bus,
    output logic [3:0] addr_out
);

    // module body
    always_ff @(posedge clk1) begin
        q1 <= d1;
    end

endmodule
"""

MOCK_SV_NO_MODULE = """\
// This file has no module matching 'cd4013b'
module other_module (
    input logic a,
    output logic b
);
endmodule
"""


# ============================================================================
# Tests
# ============================================================================

class TestParsePortsFromSV(unittest.TestCase):
    """Test parsing ports from SystemVerilog files."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_parse_basic_ports(self):
        sv_path = os.path.join(self.tmpdir, "cd4013b.sv")
        with open(sv_path, "w") as f:
            f.write(MOCK_SV)
        ports = parse_ports_from_sv(sv_path, "cd4013b")
        self.assertTrue(len(ports) > 0, "Should parse ports from SV file")
        names = {p.name for p in ports}
        self.assertIn("clk1", names)
        self.assertIn("q1", names)

    def test_parse_direction(self):
        sv_path = os.path.join(self.tmpdir, "cd4013b.sv")
        with open(sv_path, "w") as f:
            f.write(MOCK_SV)
        ports = parse_ports_from_sv(sv_path, "cd4013b")
        port_map = {p.name: p for p in ports}
        self.assertEqual(port_map["clk1"].direction, "I")
        self.assertEqual(port_map["q1"].direction, "O")

    def test_parse_bus_width(self):
        sv_path = os.path.join(self.tmpdir, "cd4013b.sv")
        with open(sv_path, "w") as f:
            f.write(MOCK_SV)
        ports = parse_ports_from_sv(sv_path, "cd4013b")
        port_map = {p.name: p for p in ports}
        self.assertEqual(port_map["data_bus"].width, 8)
        self.assertEqual(port_map["addr_out"].width, 4)

    def test_parse_nonexistent_file(self):
        ports = parse_ports_from_sv("/tmp/no_file_12345.sv", "mod")
        self.assertEqual(ports, [])

    def test_parse_wrong_module_name(self):
        sv_path = os.path.join(self.tmpdir, "cd4013b.sv")
        with open(sv_path, "w") as f:
            f.write(MOCK_SV_NO_MODULE)
        ports = parse_ports_from_sv(sv_path, "cd4013b")
        # Should return empty or no matching ports
        names = {p.name for p in ports}
        self.assertNotIn("clk1", names)


class TestParsePortsFromString(unittest.TestCase):
    """Test parsing ports from manual port string."""

    def test_basic_string(self):
        ports = parse_ports_from_string("clk:I:1,data:I:8,q:O:1")
        self.assertEqual(len(ports), 3)
        self.assertEqual(ports[0].name, "clk")
        self.assertEqual(ports[1].width, 8)
        self.assertEqual(ports[2].direction, "O")

    def test_no_width(self):
        ports = parse_ports_from_string("clk:I,rst:I")
        self.assertEqual(len(ports), 2)
        self.assertEqual(ports[0].width, 1)

    def test_empty_string(self):
        ports = parse_ports_from_string("")
        self.assertEqual(len(ports), 0)


class TestGenerateStpXml(unittest.TestCase):
    """Test STP XML generation."""

    def _parse_stp(self, xml_str):
        """Parse STP XML, skipping the XML declaration."""
        return ET.fromstring(xml_str.split('\n', 1)[1] if xml_str.startswith('<?xml') else xml_str)

    def test_generates_valid_xml(self):
        ports = [
            Port(name="clk", direction="I", width=1),
            Port(name="q", direction="O", width=1),
        ]
        xml_str = generate_stp_xml("test_mod", ports)
        # Should be parseable XML
        root = self._parse_stp(xml_str)
        self.assertEqual(root.tag, "session")

    def test_contains_module_name(self):
        ports = [Port(name="a", direction="I", width=1)]
        xml_str = generate_stp_xml("my_module", ports)
        self.assertIn("my_module", xml_str)

    def test_default_trigger_signal(self):
        ports = [Port(name="a", direction="I", width=1)]
        xml_str = generate_stp_xml("mod", ports, trigger_signal="bist_fail")
        self.assertIn("bist_fail", xml_str)

    def test_custom_trigger_signal(self):
        ports = [Port(name="a", direction="I", width=1)]
        xml_str = generate_stp_xml("mod", ports, trigger_signal="my_trigger")
        self.assertIn("my_trigger", xml_str)

    def test_custom_depth(self):
        ports = [Port(name="a", direction="I", width=1)]
        xml_str = generate_stp_xml("mod", ports, depth=2048)
        self.assertIn("2048", xml_str)

    def test_custom_clock(self):
        ports = [Port(name="a", direction="I", width=1)]
        xml_str = generate_stp_xml("mod", ports, clock="CLK_100")
        self.assertIn("CLK_100", xml_str)

    def test_includes_bist_signals_by_default(self):
        ports = [Port(name="a", direction="I", width=1)]
        xml_str = generate_stp_xml("mod", ports, include_bist=True)
        self.assertIn("bist_engine", xml_str)
        self.assertIn("bist_state", xml_str)

    def test_no_bist_signals_when_disabled(self):
        ports = [Port(name="a", direction="I", width=1)]
        xml_str = generate_stp_xml("mod", ports, include_bist=False)
        self.assertNotIn("bist_engine", xml_str)

    def test_signal_names_in_xml(self):
        ports = [
            Port(name="clk", direction="I", width=1),
            Port(name="data", direction="I", width=8, msb=7, lsb=0),
        ]
        xml_str = generate_stp_xml("dut", ports)
        self.assertIn("dut_inst|clk", xml_str)
        self.assertIn("dut_inst|data[7:0]", xml_str)

    def test_trigger_position_in_xml(self):
        ports = [Port(name="a", direction="I", width=1)]
        xml_str = generate_stp_xml("mod", ports, depth=1024)
        root = self._parse_stp(xml_str)
        trigger_pos = root.find('.//trigger_position')
        self.assertIsNotNone(trigger_pos)
        # 25% pre-trigger
        self.assertEqual(trigger_pos.get('pre_trigger'), '256')


class TestRecompileInstructionBlock(unittest.TestCase):
    """The printed instruction block must survive the gate that audits it.

    vibe-ic#693. This block used to print `quartus_stp` alone, which only
    ATTACHES the .stp — the SOF is not re-mapped, re-fitted or re-assembled,
    so following it verbatim programs a board with no logic analyzer in it.
    Piping this program's real stdout into
    `programs/signaltap_recompile_sequence_check.py` returned rc=1 with
    3 x STAGE_MISSING (map, fit, asm). This test binds the two together so the
    instruction block cannot silently drift back.
    """

    GATE = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        "vibe-ic-marketplace", "plugins", "vibe-ic", "programs",
        "signaltap_recompile_sequence_check.py")

    def _emit(self, tmpdir):
        import subprocess
        sv = os.path.join(tmpdir, "dut.sv")
        with open(sv, "w") as f:
            f.write(MOCK_SV)
        out = os.path.join(tmpdir, "dut_debug.stp")
        proc = subprocess.run(
            [sys.executable,
             os.path.join(os.path.dirname(os.path.abspath(__file__)),
                          "signaltap_gen.py"),
             "--module", "cd4013b", "--sv", sv, "--output", out],
            capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        return proc.stdout

    def test_instruction_block_names_all_four_stages(self):
        with tempfile.TemporaryDirectory() as tmp:
            stdout = self._emit(tmp)
        for stage in ("quartus_stp", "quartus_map", "quartus_fit",
                      "quartus_asm"):
            self.assertIn(stage, stdout,
                          f"{stage} missing from the recompile instructions")

    def test_gate_accepts_our_own_instruction_block(self):
        import subprocess
        if not os.path.isfile(self.GATE):
            self.skipTest("plugin gate not present in this checkout")
        with tempfile.TemporaryDirectory() as tmp:
            stdout = self._emit(tmp)
            log = os.path.join(tmp, "instructions.txt")
            with open(log, "w") as f:
                f.write(stdout)
            proc = subprocess.run([sys.executable, self.GATE, log],
                                  capture_output=True, text=True)
        self.assertEqual(proc.returncode, 0,
                         f"our own instructions fail the gate:\n{proc.stderr}")


class TestBISTSignals(unittest.TestCase):
    """Test BIST signal definitions."""

    def test_bist_signals_exist(self):
        self.assertTrue(len(BIST_SIGNALS) > 0)

    def test_bist_fail_in_signals(self):
        names = {s.name for s in BIST_SIGNALS}
        self.assertIn("bist_fail", names)

    def test_bist_done_in_signals(self):
        names = {s.name for s in BIST_SIGNALS}
        self.assertIn("bist_done", names)


if __name__ == '__main__':
    unittest.main()
