#!/usr/bin/env python3
"""
Unit tests for vibe_ic_log.py -- Unified JSON Log
===================================================
Tests log entry creation, JSONL I/O, filtering, summary.
Run: python3 test_vibe_ic_log.py
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from vibe_ic_log import (
    VibeICLog,
    VALID_STATUSES,
    VALID_PHASES,
    print_entries,
    print_summary,
)


# ============================================================================
# Tests
# ============================================================================

class TestVibeICLogCreation(unittest.TestCase):
    """Test log entry creation with various fields."""

    def test_create_basic_entry(self):
        entry = VibeICLog(
            ic_name="CD4013B", phase=2, stage="synth",
            tool="yosys", status="PASS",
        )
        self.assertEqual(entry.ic_name, "CD4013B")
        self.assertEqual(entry.phase, 2)
        self.assertEqual(entry.stage, "synth")
        self.assertEqual(entry.tool, "yosys")
        self.assertEqual(entry.status, "PASS")

    def test_create_with_all_fields(self):
        entry = VibeICLog(
            ic_name="CD4013B", phase=2, stage="synth",
            tool="yosys", status="FAIL",
            metrics={"cells": 567, "area": 14157},
            errors=["syntax error at line 10"],
            duration_sec=5.2,
            timestamp="2026-04-10T02:00:00",
        )
        self.assertEqual(entry.metrics["cells"], 567)
        self.assertEqual(len(entry.errors), 1)
        self.assertEqual(entry.duration_sec, 5.2)
        self.assertEqual(entry.timestamp, "2026-04-10T02:00:00")

    def test_auto_timestamp(self):
        entry = VibeICLog(
            ic_name="CD4013B", phase=1, stage="spec",
            tool="ds_quality", status="PASS",
        )
        self.assertTrue(len(entry.timestamp) > 0)
        self.assertIn("T", entry.timestamp)

    def test_status_uppercased(self):
        entry = VibeICLog(
            ic_name="IC1", phase=1, stage="s", tool="t", status="pass",
        )
        self.assertEqual(entry.status, "PASS")

    def test_invalid_status_raises(self):
        with self.assertRaises(ValueError):
            VibeICLog(
                ic_name="IC1", phase=1, stage="s", tool="t", status="INVALID",
            )

    def test_invalid_phase_raises(self):
        with self.assertRaises(ValueError):
            VibeICLog(
                ic_name="IC1", phase=99, stage="s", tool="t", status="PASS",
            )

    def test_default_metrics_empty(self):
        entry = VibeICLog(
            ic_name="IC1", phase=1, stage="s", tool="t", status="PASS",
        )
        self.assertEqual(entry.metrics, {})
        self.assertEqual(entry.errors, [])
        self.assertEqual(entry.duration_sec, 0.0)


class TestVibeICLogSerialization(unittest.TestCase):
    """Test to_dict, to_json, from_dict, from_json round-trips."""

    def test_to_dict(self):
        entry = VibeICLog(
            ic_name="CD4013B", phase=2, stage="synth",
            tool="yosys", status="PASS", metrics={"cells": 100},
        )
        d = entry.to_dict()
        self.assertEqual(d["ic_name"], "CD4013B")
        self.assertEqual(d["phase"], 2)
        self.assertEqual(d["metrics"]["cells"], 100)

    def test_to_json_valid(self):
        entry = VibeICLog(
            ic_name="CD4013B", phase=2, stage="synth",
            tool="yosys", status="PASS",
        )
        j = entry.to_json()
        parsed = json.loads(j)
        self.assertEqual(parsed["ic_name"], "CD4013B")

    def test_from_dict_roundtrip(self):
        entry = VibeICLog(
            ic_name="CD4013B", phase=2, stage="synth",
            tool="yosys", status="FAIL",
            metrics={"cells": 567},
            errors=["err1"],
            duration_sec=3.5,
        )
        d = entry.to_dict()
        entry2 = VibeICLog.from_dict(d)
        self.assertEqual(entry2.ic_name, entry.ic_name)
        self.assertEqual(entry2.status, entry.status)
        self.assertEqual(entry2.metrics, entry.metrics)
        self.assertEqual(entry2.errors, entry.errors)

    def test_from_json_roundtrip(self):
        entry = VibeICLog(
            ic_name="IC2", phase=3, stage="fpga",
            tool="quartus", status="WARN",
        )
        j = entry.to_json()
        entry2 = VibeICLog.from_json(j)
        self.assertEqual(entry2.ic_name, "IC2")
        self.assertEqual(entry2.phase, 3)
        self.assertEqual(entry2.status, "WARN")


class TestVibeICLogFileIO(unittest.TestCase):
    """Test JSONL file append, save, load."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.log_path = os.path.join(self.tmpdir, "test.jsonl")

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_save_creates_file(self):
        entry = VibeICLog(
            ic_name="IC1", phase=1, stage="spec",
            tool="validator", status="PASS",
        )
        entry.save(self.log_path)
        self.assertTrue(os.path.exists(self.log_path))

    def test_append_and_load(self):
        e1 = VibeICLog(ic_name="IC1", phase=1, stage="s1",
                        tool="t1", status="PASS", duration_sec=1.0)
        e2 = VibeICLog(ic_name="IC1", phase=2, stage="s2",
                        tool="t2", status="FAIL", duration_sec=2.0)
        e1.append(self.log_path)
        e2.append(self.log_path)
        entries = VibeICLog.load(self.log_path)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0].stage, "s1")
        self.assertEqual(entries[1].stage, "s2")

    def test_load_nonexistent_returns_empty(self):
        entries = VibeICLog.load("/tmp/nonexistent_log_12345.jsonl")
        self.assertEqual(entries, [])

    def test_load_skips_malformed_lines(self):
        with open(self.log_path, "w") as f:
            e = VibeICLog(ic_name="IC1", phase=1, stage="s",
                          tool="t", status="PASS")
            f.write(e.to_json() + "\n")
            f.write("NOT VALID JSON\n")
            e2 = VibeICLog(ic_name="IC2", phase=2, stage="s2",
                           tool="t2", status="FAIL")
            f.write(e2.to_json() + "\n")
        entries = VibeICLog.load(self.log_path)
        self.assertEqual(len(entries), 2)


class TestVibeICLogFiltering(unittest.TestCase):
    """Test filtering loaded entries (simulating show --phase/--status)."""

    def setUp(self):
        self.entries = [
            VibeICLog(ic_name="IC1", phase=1, stage="spec",
                      tool="t1", status="PASS"),
            VibeICLog(ic_name="IC1", phase=2, stage="synth",
                      tool="t2", status="FAIL"),
            VibeICLog(ic_name="IC1", phase=2, stage="pnr",
                      tool="t3", status="PASS"),
            VibeICLog(ic_name="IC2", phase=3, stage="fpga",
                      tool="t4", status="WARN"),
        ]

    def test_filter_by_phase(self):
        phase2 = [e for e in self.entries if e.phase == 2]
        self.assertEqual(len(phase2), 2)

    def test_filter_by_status(self):
        fails = [e for e in self.entries if e.status == "FAIL"]
        self.assertEqual(len(fails), 1)

    def test_filter_by_ic_name(self):
        ic2 = [e for e in self.entries if e.ic_name == "IC2"]
        self.assertEqual(len(ic2), 1)

    def test_combined_filter(self):
        phase2_pass = [e for e in self.entries
                       if e.phase == 2 and e.status == "PASS"]
        self.assertEqual(len(phase2_pass), 1)


class TestVibeICLogSummary(unittest.TestCase):
    """Test summary statistics via print_summary (no crash)."""

    def test_summary_no_crash(self):
        entries = [
            VibeICLog(ic_name="IC1", phase=1, stage="s",
                      tool="t", status="PASS", duration_sec=1.0),
            VibeICLog(ic_name="IC1", phase=2, stage="s2",
                      tool="t2", status="FAIL", duration_sec=2.0),
        ]
        # Should not raise
        import io
        buf = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            print_summary(entries)
        finally:
            sys.stdout = old_stdout

    def test_summary_empty(self):
        import io
        buf = io.StringIO()
        old_stdout = sys.stdout
        sys.stdout = buf
        try:
            print_summary([])
        finally:
            sys.stdout = old_stdout


if __name__ == '__main__':
    unittest.main()
