#!/usr/bin/env python3
"""
Unit tests for spec_validator.py -- Cross-Consistency Checker
==============================================================
Tests matching/mismatched DS+AN, missing files, register/pin extraction.
Run: python3 test_spec_validator.py
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from spec_validator import (
    validate_consistency,
    extract_pin_names_from_table,
    extract_pin_names_from_circuit,
    extract_register_addresses,
    extract_spec_parameters,
    check_pin_consistency,
    check_register_consistency,
    check_tbd_values,
)


# ============================================================================
# Mock data
# ============================================================================

CONSISTENT_DS = """\
# CD4013B Datasheet

## Pin Configuration

| Pin | Name  | Type   | Description           |
|-----|-------|--------|-----------------------|
| 1   | Q1    | Output | Q output, flip-flop 1 |
| 2   | Q1B   | Output | Q-bar, flip-flop 1    |
| 3   | CLK1  | Input  | Clock, flip-flop 1    |
| 4   | R1    | Input  | Reset, flip-flop 1    |
| 5   | D1    | Input  | Data, flip-flop 1     |
| 6   | S1    | Input  | Set, flip-flop 1      |
| 7   | VCC   | Power  | Supply voltage         |
| 8   | GND   | Power  | Ground                 |

## Register Map

| Register   | Address | Description          |
|------------|---------|----------------------|
| CTRL       | 0x00    | Control register     |
| STATUS     | 0x01    | Status register      |
| DATA       | 0x02    | Data register        |
| CONFIG     | 0x03    | Configuration        |
"""

CONSISTENT_AN = """\
# CD4013B Application Note

## Typical Application Circuit

```
    VCC
     |
    [R1]--- D1 --- CLK1
     |
    Q1 ---- Q1B
     |
    S1      R1
     |
    GND
```

## Firmware Example

```c
#define CTRL   0x00
#define STATUS 0x01
#define DATA   0x02
#define CONFIG 0x03

void init(void) {
    write_reg(CTRL, 0x01);
    uint8_t st = read_reg(STATUS);
}
```
"""

MISMATCHED_PIN_AN = """\
# CD4013B Application Note

## Typical Application Circuit

```
    VCC
     |
    [R1]--- DATA_IN --- CLOCK
     |
    QOUT ---- QBAR
     |
    SET_PIN   RST_PIN
     |
    GND
```

## Firmware Example

Some basic usage without registers.
"""

MISMATCHED_REG_AN = """\
# CD4013B Application Note

## Typical Application Circuit

Connect VCC, GND, CLK1, D1, Q1, Q1B, S1, R1.

## Firmware Example

```c
#define CTRL   0x00
#define STATUS 0x04
#define DATA   0x02
#define NEWREG 0x10
```

Note: STATUS at 0x04 conflicts with DS (0x01).
"""

DS_WITH_TBD = """\
# IC Datasheet

## Pin Configuration

| Pin | Name | Description |
|-----|------|-------------|
| 1   | VCC  | TBD         |

## Electrical

Maximum voltage: TBD
TODO: fill in timing specs
"""

AN_CLEAN = """\
# Application Note

## Typical Application Circuit

Standard circuit with VCC, GND.

## Firmware Example

Basic setup code.
"""

SPEC_DOC = """\
# Confirmed Spec

| Parameter              | Value |
|------------------------|-------|
| supply voltage         | 5V    |
| clock frequency        | 4MHz  |

- **output drive current**: 1mA
"""


# ============================================================================
# Tests
# ============================================================================

class TestValidateConsistencyMatching(unittest.TestCase):
    """Test validate_consistency with matching DS + AN."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_consistent_docs_no_errors(self):
        ds_path = os.path.join(self.tmpdir, "ds.md")
        an_path = os.path.join(self.tmpdir, "an.md")
        with open(ds_path, "w") as f:
            f.write(CONSISTENT_DS)
        with open(an_path, "w") as f:
            f.write(CONSISTENT_AN)
        result = validate_consistency(ds_path, an_path)
        error_mismatches = [m for m in result["mismatches"]
                            if m["severity"] == "ERROR"]
        self.assertEqual(len(error_mismatches), 0,
                         f"Expected no errors, got: {error_mismatches}")
        self.assertTrue(result["consistent"])

    def test_result_has_summary(self):
        ds_path = os.path.join(self.tmpdir, "ds.md")
        an_path = os.path.join(self.tmpdir, "an.md")
        with open(ds_path, "w") as f:
            f.write(CONSISTENT_DS)
        with open(an_path, "w") as f:
            f.write(CONSISTENT_AN)
        result = validate_consistency(ds_path, an_path)
        self.assertIn("summary", result)
        self.assertIn("errors", result["summary"])
        self.assertIn("warnings", result["summary"])
        self.assertIn("info", result["summary"])

    def test_result_has_files(self):
        ds_path = os.path.join(self.tmpdir, "ds.md")
        an_path = os.path.join(self.tmpdir, "an.md")
        with open(ds_path, "w") as f:
            f.write(CONSISTENT_DS)
        with open(an_path, "w") as f:
            f.write(CONSISTENT_AN)
        result = validate_consistency(ds_path, an_path)
        self.assertIn("files", result)
        self.assertIn("datasheet", result["files"])
        self.assertIn("appnote", result["files"])


class TestValidateConsistencyMismatch(unittest.TestCase):
    """Test validate_consistency with mismatched documents."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_mismatched_pin_names_reports_errors(self):
        ds_path = os.path.join(self.tmpdir, "ds.md")
        an_path = os.path.join(self.tmpdir, "an.md")
        with open(ds_path, "w") as f:
            f.write(CONSISTENT_DS)
        with open(an_path, "w") as f:
            f.write(MISMATCHED_PIN_AN)
        result = validate_consistency(ds_path, an_path)
        # Should have pin-related mismatches
        pin_issues = [m for m in result["mismatches"]
                      if m["check"] == "pin_names"]
        self.assertTrue(len(pin_issues) > 0,
                        "Should detect pin name mismatches")

    def test_mismatched_register_addresses(self):
        ds_path = os.path.join(self.tmpdir, "ds.md")
        an_path = os.path.join(self.tmpdir, "an.md")
        with open(ds_path, "w") as f:
            f.write(CONSISTENT_DS)
        with open(an_path, "w") as f:
            f.write(MISMATCHED_REG_AN)
        result = validate_consistency(ds_path, an_path)
        reg_issues = [m for m in result["mismatches"]
                      if m["check"] == "register_addresses"
                      and m["type"] in ("address_mismatch", "an_only")]
        self.assertTrue(len(reg_issues) > 0,
                        "Should detect register address mismatches")


class TestMissingFiles(unittest.TestCase):
    """Test graceful handling of missing files."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_missing_ds_file(self):
        an_path = os.path.join(self.tmpdir, "an.md")
        with open(an_path, "w") as f:
            f.write(CONSISTENT_AN)
        result = validate_consistency("/tmp/no_ds_12345.md", an_path)
        self.assertFalse(result["consistent"])
        self.assertTrue(any(m["type"] == "file_not_found"
                            for m in result["mismatches"]))

    def test_missing_an_file(self):
        ds_path = os.path.join(self.tmpdir, "ds.md")
        with open(ds_path, "w") as f:
            f.write(CONSISTENT_DS)
        result = validate_consistency(ds_path, "/tmp/no_an_12345.md")
        self.assertFalse(result["consistent"])

    def test_both_files_missing(self):
        result = validate_consistency("/tmp/no1.md", "/tmp/no2.md")
        self.assertFalse(result["consistent"])
        self.assertEqual(result["summary"]["total_checks"], 0)

    def test_missing_optional_spec_file(self):
        ds_path = os.path.join(self.tmpdir, "ds.md")
        an_path = os.path.join(self.tmpdir, "an.md")
        with open(ds_path, "w") as f:
            f.write(CONSISTENT_DS)
        with open(an_path, "w") as f:
            f.write(CONSISTENT_AN)
        result = validate_consistency(ds_path, an_path,
                                      spec_path="/tmp/no_spec_12345.md")
        # Missing spec is an error
        self.assertFalse(result["consistent"])


class TestExtractPinNames(unittest.TestCase):
    """Test pin name extraction functions."""

    def test_extract_from_table(self):
        pins = extract_pin_names_from_table(CONSISTENT_DS)
        # Should find at least some standard pins
        self.assertTrue(len(pins) > 0, "Should extract pin names from table")

    def test_extract_from_circuit(self):
        pins = extract_pin_names_from_circuit(CONSISTENT_AN)
        self.assertTrue(len(pins) > 0, "Should extract pin names from circuit")

    def test_empty_text_returns_empty(self):
        pins = extract_pin_names_from_table("")
        # May find something from full-text fallback, but should not crash
        self.assertIsInstance(pins, set)


class TestExtractRegisterAddresses(unittest.TestCase):
    """Test register address extraction."""

    def test_extract_from_ds_table(self):
        regs = extract_register_addresses(CONSISTENT_DS, "datasheet")
        self.assertIn("CTRL", regs)
        self.assertEqual(regs["CTRL"], "0X00")

    def test_extract_from_an_defines(self):
        regs = extract_register_addresses(CONSISTENT_AN, "appnote")
        self.assertIn("CTRL", regs)

    def test_empty_text(self):
        regs = extract_register_addresses("", "datasheet")
        self.assertEqual(len(regs), 0)


class TestCheckTBDValues(unittest.TestCase):
    """Test TBD/TODO/FIXME detection."""

    def test_detects_tbd_in_ds(self):
        mismatches = check_tbd_values(DS_WITH_TBD, AN_CLEAN)
        tbd_issues = [m for m in mismatches if m["type"] == "unresolved_placeholder"]
        self.assertTrue(len(tbd_issues) > 0)

    def test_clean_docs_no_tbd(self):
        mismatches = check_tbd_values(AN_CLEAN, AN_CLEAN)
        tbd_issues = [m for m in mismatches if m["type"] == "unresolved_placeholder"]
        self.assertEqual(len(tbd_issues), 0)


class TestExtractSpecParameters(unittest.TestCase):
    """Test spec parameter extraction."""

    def test_extract_from_spec_doc(self):
        params = extract_spec_parameters(SPEC_DOC)
        self.assertTrue(len(params) > 0)

    def test_empty_spec(self):
        params = extract_spec_parameters("")
        self.assertEqual(len(params), 0)


class TestJSONSerializable(unittest.TestCase):
    """Test that results are JSON-serializable."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_result_serializable(self):
        ds_path = os.path.join(self.tmpdir, "ds.md")
        an_path = os.path.join(self.tmpdir, "an.md")
        with open(ds_path, "w") as f:
            f.write(CONSISTENT_DS)
        with open(an_path, "w") as f:
            f.write(CONSISTENT_AN)
        result = validate_consistency(ds_path, an_path)
        serialized = json.dumps(result, ensure_ascii=False)
        parsed = json.loads(serialized)
        self.assertEqual(parsed["consistent"], result["consistent"])


if __name__ == '__main__':
    unittest.main()
