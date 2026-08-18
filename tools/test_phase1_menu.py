#!/usr/bin/env python3
"""
Unit tests for phase1_menu.py -- Phase 1 Fail-Handling Menu
=============================================================
Tests menu display, export log, check_and_prompt API.
Run: python3 test_phase1_menu.py
"""

import os
import sys
import tempfile
import unittest
from unittest.mock import patch, MagicMock
import io

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from phase1_menu import (
    Phase1FailMenu,
    Phase1Status,
    QualityResult,
    CrossCheckResult,
    ScoreBreakdown,
    check_and_prompt,
    _make_default_breakdown,
    DEFAULT_DS_CATEGORIES,
    DEFAULT_AN_CATEGORIES,
)


# ============================================================================
# Helpers
# ============================================================================

def _make_failing_status(tmpdir="/tmp"):
    ds = QualityResult(
        check_name="ds_quality_check",
        score=52, max_score=100, threshold=70, passed=False,
        errors=["Missing timing diagrams"],
        warnings=["Electrical chars incomplete"],
    )
    an = QualityResult(
        check_name="an_validator",
        score=40, max_score=80, threshold=56, passed=False,
    )
    xc = CrossCheckResult(
        mismatch_count=2,
        mismatches=[
            {"field": "VCC_range", "ds_value": "3-15V",
             "an_value": "3-18V", "severity": "ERROR",
             "suggestion": "Align to DS value"},
            {"field": "CLK_freq", "ds_value": "4MHz",
             "an_value": "8MHz", "severity": "ERROR"},
        ],
        checked_fields=20,
    )
    return Phase1Status(
        ic_name="CD4013B",
        project_dir=tmpdir,
        ds_result=ds,
        an_result=an,
        xcheck_result=xc,
    )


def _make_passing_status():
    ds = QualityResult(
        check_name="ds_quality_check",
        score=85, max_score=100, threshold=70, passed=True,
    )
    an = QualityResult(
        check_name="an_validator",
        score=65, max_score=80, threshold=56, passed=True,
    )
    xc = CrossCheckResult(mismatch_count=0, mismatches=[], checked_fields=20)
    return Phase1Status(
        ic_name="CD4013B",
        project_dir="/tmp",
        ds_result=ds,
        an_result=an,
        xcheck_result=xc,
    )


# ============================================================================
# Tests
# ============================================================================

class TestPhase1StatusInit(unittest.TestCase):
    """Test Phase1Status construction and overall_pass logic."""

    def test_failing_status_not_pass(self):
        status = _make_failing_status()
        self.assertFalse(status.overall_pass)

    def test_passing_status_pass(self):
        status = _make_passing_status()
        self.assertTrue(status.overall_pass)

    def test_timestamp_auto_set(self):
        status = _make_failing_status()
        self.assertTrue(len(status.timestamp) > 0)


class TestMenuDisplay(unittest.TestCase):
    """Test menu header display."""

    def test_print_header_no_crash(self):
        status = _make_failing_status()
        menu = Phase1FailMenu(status)
        buf = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            menu._print_header()
        finally:
            sys.stdout = old_stdout
        output = buf.getvalue()
        self.assertIn("Phase 1", output)
        self.assertIn("CD4013B", output)
        self.assertIn("FAIL", output)

    def test_view_breakdown_no_crash(self):
        status = _make_failing_status()
        menu = Phase1FailMenu(status)
        buf = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            menu._view_breakdown()
        finally:
            sys.stdout = old_stdout

    def test_view_mismatches_no_crash(self):
        status = _make_failing_status()
        menu = Phase1FailMenu(status)
        buf = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            menu._view_mismatches()
        finally:
            sys.stdout = old_stdout
        output = buf.getvalue()
        self.assertIn("VCC_range", output)


class TestExportDiagnosticLog(unittest.TestCase):
    """Test option [7] export diagnostic log."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_export_creates_file(self):
        status = _make_failing_status(self.tmpdir)
        menu = Phase1FailMenu(status)
        buf = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            menu._export_log()
        finally:
            sys.stdout = old_stdout
        # Check a log file was created
        files = os.listdir(self.tmpdir)
        log_files = [f for f in files if f.startswith("phase1_diagnostic_")]
        self.assertTrue(len(log_files) > 0, "Should create diagnostic log file")

    def test_export_file_contains_data(self):
        status = _make_failing_status(self.tmpdir)
        menu = Phase1FailMenu(status)
        buf = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            menu._export_log()
        finally:
            sys.stdout = old_stdout
        files = os.listdir(self.tmpdir)
        log_files = [f for f in files if f.startswith("phase1_diagnostic_")]
        if log_files:
            path = os.path.join(self.tmpdir, log_files[0])
            with open(path) as f:
                content = f.read()
            self.assertIn("CD4013B", content)
            self.assertIn("FAIL", content)


class TestCheckAndPromptPassing(unittest.TestCase):
    """Test check_and_prompt with passing scores."""

    def test_passing_returns_pass(self):
        buf = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            result = check_and_prompt(
                ic_name="CD4013B", project_dir="/tmp",
                ds_score=85, ds_max=100, ds_threshold=70,
                an_score=65, an_max=80, an_threshold=56,
                xcheck_mismatches=0,
            )
        finally:
            sys.stdout = old_stdout
        self.assertEqual(result, "pass")

    def test_auto_mode_fail_returns_abort(self):
        buf = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            result = check_and_prompt(
                ic_name="CD4013B", project_dir="/tmp",
                ds_score=30, ds_max=100, ds_threshold=70,
                an_score=20, an_max=80, an_threshold=56,
                xcheck_mismatches=3,
                auto_mode=True,
            )
        finally:
            sys.stdout = old_stdout
        self.assertEqual(result, "abort")


class TestCheckAndPromptFailing(unittest.TestCase):
    """Test check_and_prompt with failing scores (menu interaction)."""

    @patch('builtins.input', side_effect=["0"])
    def test_abort_option(self, mock_input):
        buf = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            result = check_and_prompt(
                ic_name="CD4013B", project_dir="/tmp",
                ds_score=30, ds_max=100, ds_threshold=70,
                an_score=20, an_max=80, an_threshold=56,
                xcheck_mismatches=1,
            )
        finally:
            sys.stdout = old_stdout
        self.assertEqual(result, "abort")


class TestDefaultBreakdown(unittest.TestCase):
    """Test _make_default_breakdown helper."""

    def test_proportional_breakdown(self):
        breakdown = _make_default_breakdown(50, 100, DEFAULT_DS_CATEGORIES)
        self.assertEqual(len(breakdown), len(DEFAULT_DS_CATEGORIES))
        total = sum(b.score for b in breakdown)
        # Proportional: 50/100 * sum of max_scores
        self.assertGreater(total, 0)

    def test_zero_score_breakdown(self):
        breakdown = _make_default_breakdown(0, 100, DEFAULT_DS_CATEGORIES)
        for b in breakdown:
            self.assertEqual(b.score, 0.0)


if __name__ == '__main__':
    unittest.main()
