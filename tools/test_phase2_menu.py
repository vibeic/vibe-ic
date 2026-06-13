#!/usr/bin/env python3
"""
Unit tests for phase2_menu.py -- Phase 2 EDA Fail-Handling Menu
=================================================================
Tests menu display, export log, handle_eda_failure API, auto-fix patterns.
Run: python3 test_phase2_menu.py
"""

import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock
import io

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from phase2_menu import (
    Phase2FailMenu,
    handle_eda_failure,
    AUTO_FIX_PATTERNS,
    _fix_unpacked_array,
    _fix_return_in_func,
)


# ============================================================================
# Mock data
# ============================================================================

MOCK_SYNTH_LOG = """\
1. Executing Verilog-2005 frontend: cd4013b.sv
2. Analyzing design hierarchy.
3. Mapping to technology library...
ERROR: Unpacked array port 'data' not supported by synthesis target.
    cd4013b.sv:15: logic [7:0] data [3:0]
4. Synthesis terminated with errors.
"""

MOCK_PNR_LOG = """\
[INFO] Reading netlist...
[INFO] Floorplanning...
[ERROR] DRC violation: metal1 spacing at (100, 200)
[WARNING] Timing slack negative: -0.5ns on path CLK->Q1
"""


# ============================================================================
# Tests
# ============================================================================

class TestPhase2FailMenuInit(unittest.TestCase):
    """Test Phase2FailMenu construction."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmpdir, "synth.log")
        with open(self.log_path, "w") as f:
            f.write(MOCK_SYNTH_LOG)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_create_menu(self):
        menu = Phase2FailMenu(
            stage="synthesis", tool="Yosys",
            log_path=self.log_path,
            project_dir=self.tmpdir,
        )
        self.assertEqual(menu.stage, "synthesis")
        self.assertEqual(menu.tool, "Yosys")

    def test_primary_error_extracted(self):
        menu = Phase2FailMenu(
            stage="synthesis", tool="Yosys",
            log_path=self.log_path,
            project_dir=self.tmpdir,
        )
        self.assertIn("ERROR", menu.primary_error)

    def test_missing_log_file(self):
        menu = Phase2FailMenu(
            stage="synthesis", tool="Yosys",
            log_path="/tmp/nonexistent_12345.log",
            project_dir=self.tmpdir,
        )
        self.assertIn("not found", menu.primary_error)


class TestMenuDisplay(unittest.TestCase):
    """Test menu header display."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmpdir, "synth.log")
        with open(self.log_path, "w") as f:
            f.write(MOCK_SYNTH_LOG)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_print_header_no_crash(self):
        menu = Phase2FailMenu(
            stage="synthesis", tool="Yosys",
            log_path=self.log_path,
            project_dir=self.tmpdir,
        )
        buf = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            menu._print_header()
        finally:
            sys.stdout = old_stdout
        output = buf.getvalue()
        self.assertIn("Phase 2", output)
        self.assertIn("Yosys", output)

    def test_view_log_no_crash(self):
        menu = Phase2FailMenu(
            stage="synthesis", tool="Yosys",
            log_path=self.log_path,
            project_dir=self.tmpdir,
        )
        buf = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            menu._view_log()
        finally:
            sys.stdout = old_stdout
        output = buf.getvalue()
        self.assertIn("ERROR", output)


class TestExportDiagnosticLog(unittest.TestCase):
    """Test option [7] export diagnostic log."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmpdir, "synth.log")
        with open(self.log_path, "w") as f:
            f.write(MOCK_SYNTH_LOG)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_export_creates_file(self):
        menu = Phase2FailMenu(
            stage="synthesis", tool="Yosys",
            log_path=self.log_path,
            project_dir=self.tmpdir,
        )
        buf = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            menu._export_log()
        finally:
            sys.stdout = old_stdout
        files = os.listdir(self.tmpdir)
        log_files = [f for f in files if f.startswith("phase2_diagnostic_")]
        self.assertTrue(len(log_files) > 0)

    def test_export_contains_info(self):
        menu = Phase2FailMenu(
            stage="synthesis", tool="Yosys",
            log_path=self.log_path,
            project_dir=self.tmpdir,
        )
        buf = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            menu._export_log()
        finally:
            sys.stdout = old_stdout
        files = os.listdir(self.tmpdir)
        log_files = [f for f in files if f.startswith("phase2_diagnostic_")]
        if log_files:
            path = os.path.join(self.tmpdir, log_files[0])
            with open(path) as f:
                content = f.read()
            self.assertIn("synthesis", content)
            self.assertIn("Yosys", content)


class TestHandleEdaFailure(unittest.TestCase):
    """Test handle_eda_failure API."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmpdir, "synth.log")
        with open(self.log_path, "w") as f:
            f.write(MOCK_SYNTH_LOG)

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_auto_mode_no_fix_returns_abort(self):
        buf = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            result = handle_eda_failure(
                stage="synthesis", tool="Yosys",
                log_path=self.log_path,
                project_dir=self.tmpdir,
                auto_mode=True,
            )
        finally:
            sys.stdout = old_stdout
        self.assertEqual(result, "abort")

    @patch('builtins.input', side_effect=["0"])
    def test_interactive_abort(self, mock_input):
        buf = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            result = handle_eda_failure(
                stage="synthesis", tool="Yosys",
                log_path=self.log_path,
                project_dir=self.tmpdir,
                auto_mode=False,
            )
        finally:
            sys.stdout = old_stdout
        self.assertEqual(result, "abort")


class TestAutoFixPatterns(unittest.TestCase):
    """Test auto-fix pattern definitions and detection."""

    def test_unpacked_array_pattern_exists(self):
        self.assertIn("UNPACKED_ARRAY", AUTO_FIX_PATTERNS)

    def test_multi_driver_pattern_exists(self):
        self.assertIn("MULTI_DRIVER", AUTO_FIX_PATTERNS)

    def test_return_in_func_pattern_exists(self):
        self.assertIn("RETURN_IN_FUNC", AUTO_FIX_PATTERNS)

    def test_latch_inference_pattern_exists(self):
        self.assertIn("LATCH_INFERENCE", AUTO_FIX_PATTERNS)

    def test_manual_flag_on_multi_driver(self):
        self.assertTrue(AUTO_FIX_PATTERNS["MULTI_DRIVER"].get("manual", False))

    def test_auto_fixable_unpacked_array(self):
        self.assertFalse(AUTO_FIX_PATTERNS["UNPACKED_ARRAY"].get("manual", False))


class TestFixUnpackedArray(unittest.TestCase):
    """Test _fix_unpacked_array implementation."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_fix_basic_unpacked(self):
        sv_path = os.path.join(self.tmpdir, "test.sv")
        with open(sv_path, "w") as f:
            f.write("module test(\n"
                    "    input logic [7:0] data [3:0]\n"
                    ");\nendmodule\n")
        result = _fix_unpacked_array(sv_path, 2)
        self.assertTrue(result["success"])

    def test_fix_no_pattern_found(self):
        sv_path = os.path.join(self.tmpdir, "test.sv")
        with open(sv_path, "w") as f:
            f.write("module test(\n    input logic clk\n);\nendmodule\n")
        result = _fix_unpacked_array(sv_path, 1)
        self.assertFalse(result["success"])

    def test_fix_missing_file(self):
        result = _fix_unpacked_array("/tmp/no_file_12345.sv", 1)
        self.assertFalse(result["success"])


class TestFixReturnInFunc(unittest.TestCase):
    """Test _fix_return_in_func implementation."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_fix_return_statement(self):
        sv_path = os.path.join(self.tmpdir, "test.sv")
        with open(sv_path, "w") as f:
            f.write("function automatic logic [7:0] my_func(input logic a);\n"
                    "    return a;\n"
                    "endfunction\n")
        result = _fix_return_in_func(sv_path, 2)
        self.assertTrue(result["success"])
        with open(sv_path) as f:
            content = f.read()
        self.assertIn("my_func = a;", content)

    def test_fix_missing_file(self):
        result = _fix_return_in_func("/tmp/no_file_12345.sv", 1)
        self.assertFalse(result["success"])


if __name__ == '__main__':
    unittest.main()
