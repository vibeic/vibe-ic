#!/usr/bin/env python3
"""
Unit tests for pnr_doctor.py — OpenROAD P&R Error Auto-Classifier
=================================================================
Tests GPL_DIVERGE, DRT_POWER_NET, FLOORPLAN_FAIL patterns,
DRC file parsing, timing slack extraction, and edge cases.
Run: python3 -m pytest tools/vibe_ic_tools/test_pnr_doctor.py -v
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pnr_doctor import analyze_pnr, PnrReport, PnrDiagnosis


class TestPnrDoctorPatterns(unittest.TestCase):
    """Test known P&R error patterns."""

    def _write_file(self, content: str, suffix='.log') -> str:
        f = tempfile.NamedTemporaryFile(mode='w', suffix=suffix, delete=False)
        f.write(content)
        f.close()
        return f.name

    # --- GPL_DIVERGE ---
    def test_gpl_diverge(self):
        tmp = self._write_file("GPL-0304 RePlAce diverged, placement failed\n")
        try:
            report = analyze_pnr(tmp)
            patterns = [d.pattern for d in report.diagnoses]
            self.assertIn('GPL_DIVERGE', patterns)
            self.assertEqual(report.status, 'FAIL')
        finally:
            os.unlink(tmp)

    # --- DRT_POWER_NET ---
    def test_drt_power_net(self):
        tmp = self._write_file(
            "DRT-0305 net VDD signal type POWER is not routable\n"
        )
        try:
            report = analyze_pnr(tmp)
            patterns = [d.pattern for d in report.diagnoses]
            self.assertIn('DRT_POWER_NET', patterns)
            self.assertEqual(report.status, 'FAIL')
        finally:
            os.unlink(tmp)

    # --- FLOORPLAN_FAIL ---
    def test_floorplan_fail(self):
        tmp = self._write_file(
            "ERROR: cannot create floorplan, site not found\n"
        )
        try:
            report = analyze_pnr(tmp)
            patterns = [d.pattern for d in report.diagnoses]
            self.assertIn('FLOORPLAN_FAIL', patterns)
            self.assertEqual(report.status, 'FAIL')
        finally:
            os.unlink(tmp)

    # --- DRC_SPACING ---
    def test_drc_spacing(self):
        tmp = self._write_file(
            "Warning: metal2 spacing violation at (100, 200)\n"
        )
        try:
            report = analyze_pnr(tmp)
            patterns = [d.pattern for d in report.diagnoses]
            self.assertIn('DRC_SPACING', patterns)
        finally:
            os.unlink(tmp)

    # --- TIMING_FAIL ---
    def test_timing_fail(self):
        tmp = self._write_file(
            "slack = -0.35 VIOLATED\n"
        )
        try:
            report = analyze_pnr(tmp)
            patterns = [d.pattern for d in report.diagnoses]
            self.assertIn('TIMING_FAIL', patterns)
        finally:
            os.unlink(tmp)

    # --- NO_CLOCK ---
    def test_no_clock(self):
        tmp = self._write_file(
            "Warning: no clock defined in design\n"
        )
        try:
            report = analyze_pnr(tmp)
            patterns = [d.pattern for d in report.diagnoses]
            self.assertIn('NO_CLOCK', patterns)
        finally:
            os.unlink(tmp)

    # --- CONGESTION ---
    def test_congestion(self):
        tmp = self._write_file(
            "Warning: routing overflow 15%\n"
        )
        try:
            report = analyze_pnr(tmp)
            patterns = [d.pattern for d in report.diagnoses]
            self.assertIn('CONGESTION', patterns)
        finally:
            os.unlink(tmp)


class TestDrcFileParsing(unittest.TestCase):
    """Test DRC report file parsing."""

    def _write_file(self, content: str, suffix='.rpt') -> str:
        f = tempfile.NamedTemporaryFile(mode='w', suffix=suffix, delete=False)
        f.write(content)
        f.close()
        return f.name

    def test_drc_empty_is_clean(self):
        """Empty DRC file means 0 violations (clean design)."""
        log = self._write_file("Design area: 5000\n", suffix='.log')
        drc = self._write_file("", suffix='.rpt')
        try:
            report = analyze_pnr(log, drc)
            self.assertEqual(report.drc_violations, 0)
        finally:
            os.unlink(log)
            os.unlink(drc)

    def test_drc_with_violations(self):
        """DRC file with violation entries."""
        log = self._write_file("Design area: 5000\n", suffix='.log')
        drc = self._write_file(
            "violation type: Metal2 spacing\n"
            "  srcs: net1 net2\n"
            "violation type: Metal3 width\n"
            "  srcs: net3\n"
            "violation type: Via1 enclosure\n"
            "  srcs: net4\n",
            suffix='.rpt'
        )
        try:
            report = analyze_pnr(log, drc)
            self.assertEqual(report.drc_violations, 3)
        finally:
            os.unlink(log)
            os.unlink(drc)

    def test_drc_file_not_found(self):
        """Missing DRC file should not crash, just skip."""
        log = self._write_file("Design area: 5000\n", suffix='.log')
        try:
            report = analyze_pnr(log, '/nonexistent/drc.rpt')
            self.assertEqual(report.drc_violations, 0)
        finally:
            os.unlink(log)


class TestTimingSlackExtraction(unittest.TestCase):
    """Test timing slack extraction from P&R logs."""

    def _write_file(self, content: str) -> str:
        f = tempfile.NamedTemporaryFile(mode='w', suffix='.log', delete=False)
        f.write(content)
        f.close()
        return f.name

    def test_positive_slack(self):
        tmp = self._write_file("Slack = 1.25\n")
        try:
            report = analyze_pnr(tmp)
            self.assertAlmostEqual(report.timing_slack, 1.25)
        finally:
            os.unlink(tmp)

    def test_negative_slack(self):
        tmp = self._write_file("slack: -0.42\n")
        try:
            report = analyze_pnr(tmp)
            self.assertAlmostEqual(report.timing_slack, -0.42)
        finally:
            os.unlink(tmp)

    def test_no_slack(self):
        """No slack line => timing_slack is None."""
        tmp = self._write_file("Design finished.\n")
        try:
            report = analyze_pnr(tmp)
            self.assertIsNone(report.timing_slack)
        finally:
            os.unlink(tmp)


class TestPnrPassCase(unittest.TestCase):
    """Test clean P&R (PASS case)."""

    def test_clean_pnr(self):
        content = (
            "OpenROAD v2.0\n"
            "Design area: 12345.67\n"
            "Utilization: 35\n"
            "Slack = 2.50\n"
            "Routing complete.\n"
        )
        f = tempfile.NamedTemporaryFile(mode='w', suffix='.log', delete=False)
        f.write(content)
        f.close()
        try:
            report = analyze_pnr(f.name)
            self.assertEqual(report.status, 'PASS')
            self.assertEqual(len(report.diagnoses), 0)
            self.assertAlmostEqual(report.area, 12345.67)
            self.assertAlmostEqual(report.utilization, 35.0)
            self.assertAlmostEqual(report.timing_slack, 2.50)
        finally:
            os.unlink(f.name)

    def test_log_not_found(self):
        report = analyze_pnr('/nonexistent/pnr.log')
        self.assertEqual(report.status, 'FAIL')
        self.assertIn('not found', report.summary)


class TestPnrJsonOutput(unittest.TestCase):
    """Test JSON serialization."""

    def test_json_serializable(self):
        content = "GPL-0304 RePlAce diverged\nDesign area: 100\n"
        f = tempfile.NamedTemporaryFile(mode='w', suffix='.log', delete=False)
        f.write(content)
        f.close()
        try:
            report = analyze_pnr(f.name)
            from dataclasses import asdict
            data = json.loads(json.dumps(asdict(report), default=str))
            self.assertIn('status', data)
            self.assertIn('diagnoses', data)
            self.assertEqual(data['status'], 'FAIL')
            self.assertEqual(data['diagnoses'][0]['pattern'], 'GPL_DIVERGE')
        finally:
            os.unlink(f.name)


if __name__ == '__main__':
    unittest.main()
