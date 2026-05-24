#!/usr/bin/env python3
"""
Unit tests for an_validator.py -- Application Note Quality Scorer
=================================================================
Tests with mock appnote, empty file, individual section detection, JSON output.
Run: python3 test_an_validator.py
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from an_validator import (
    score_appnote,
    check_overview,
    check_typical_application,
    check_component_selection,
    check_pcb_layout,
    check_firmware_example,
    check_design_calculations,
    check_faq,
    check_competitive_comparison,
    _find_section,
    _has_table,
    _count_table_rows,
    _has_code_block,
    _has_ascii_art,
    _count_list_items,
    CRITERIA,
)


# ============================================================================
# Mock data
# ============================================================================

PERFECT_APPNOTE = """\
# CD4013B Application Note

## Overview

This application note describes how to use the CD4013B dual D-type flip-flop
in typical applications. The CD4013B is widely used in digital circuits for
frequency division, data latching, and shift register configurations.

The device operates across a wide supply voltage range (3V-15V) and features
extremely low power consumption, making it ideal for battery-powered designs.

## Typical Application Circuit

The following schematic shows a basic toggle flip-flop configuration:

```
        VDD
         |
    R1 10kOhm
         |
   +-----+-----+
   |             |
   | CD4013B    |
   | FF1        |
   |  D --- Q --+
   |  CLK       |
   |  S   Q_bar |
   |  R         |
   +-----+------+
         |
        GND
```

Connect R1 (10kOhm pull-up) to VDD. Use C1 (100nF) for decoupling.
U1 is the CD4013B IC. D1 protection diode recommended.

## External Component Selection

| Component | Value   | Type              | Purpose            |
|-----------|---------|-------------------|--------------------|
| R1        | 10kOhm | Carbon film 1/4W  | Pull-up resistor   |
| R2        | 4.7kOhm| Metal film 1/4W   | Series resistor    |
| C1        | 100nF   | MLCC X7R          | Decoupling         |
| C2        | 10uF    | Electrolytic       | Bulk bypass        |
| C3        | 47pF    | NPO/C0G           | Filter capacitor   |

## PCB Layout

When laying out the PCB for the CD4013B circuit, follow these guidelines:

```
  +--[C1]--+
  |         |
  +--[U1]--+
  |         |
  +--[GND]-+
```

- Place bypass capacitor C1 as close as possible to VDD pin
- Use ground plane for low impedance return path
- Keep trace routing short for clock signals
- Add decoupling capacitors within 5mm of power pins
- Use via stitching for ground plane continuity

## Firmware Example

The following C code demonstrates how to configure a microcontroller to
drive the CD4013B clock and data inputs via GPIO:

```c
#include <stdint.h>

#define GPIO_CLK  0x01
#define GPIO_DATA 0x02
#define GPIO_SET  0x04
#define GPIO_RST  0x08

// Register at address 0x40020000
volatile uint32_t *GPIO_PORT = (volatile uint32_t *)0x40020000;

void cd4013b_write(uint8_t data, uint8_t clk) {
    // Set data line
    if (data) *GPIO_PORT |= GPIO_DATA;
    else      *GPIO_PORT &= ~GPIO_DATA;

    // Toggle clock via SPI-like bit-bang
    *GPIO_PORT |= GPIO_CLK;   // CLK high (posedge)
    *GPIO_PORT &= ~GPIO_CLK;  // CLK low
}

void cd4013b_reset(void) {
    *GPIO_PORT |= GPIO_RST;   // Assert reset
    *GPIO_PORT &= ~GPIO_RST;  // Release
}
```

## Design Calculations

The toggle frequency is calculated as:

    f_toggle = f_clk / 2

For a 1MHz clock input:

    f_toggle = 1000000 / 2 = 500000 Hz = 500kHz

Power dissipation calculation:

    P_dynamic = C_pd * VDD^2 * f_clk
    P_dynamic = 50pF * (5V)^2 * 1MHz = 1.25mW

Maximum clock frequency at VDD=5V:

    f_max = 4MHz (from datasheet)

Current consumption with 1MHz toggle:

    I_dd = P_dynamic / VDD = 1.25mW / 5V = 250uA

## FAQ

- **Q: What happens when both SET and RESET are high?**
  Both Q and Q_bar go high (illegal state per datasheet).

- **Q: Can I use the CD4013B at 1.8V?**
  No, minimum VDD is 3V for the 4000B series.

- **Q: What is the maximum clock frequency?**
  4MHz at VDD=5V, higher at VDD=10V or 15V.

- **Q: Do I need external pull-up resistors?**
  Only if driving open-drain outputs into the CD4013B.

- **Q: How do I cascade two flip-flops for a divide-by-4?**
  Connect Q1 to CLK2, and feed Q_bar1 back to D1.

- **Q: What ESD protection level does the CD4013B have?**
  HBM >= 2000V on all pins (CMOS 4000B standard).

## Competitive Comparison

| Feature         | CD4013B | SN7474  | MC14013B | CD4027B |
|----------------|---------|---------|----------|---------|
| Supply (V)      | 3-15    | 4.75-5.25| 3-18    | 3-15    |
| Static Power    | 4nW     | 10mW   | 4nW      | 4nW     |
| Max Clock (MHz) | 4       | 25     | 4.2      | 3.5     |
| Package         | DIP-14  | DIP-14 | DIP-14   | DIP-16  |
| ESD (HBM)       | 2kV     | 1kV    | 2kV      | 2kV     |
"""

EMPTY_APPNOTE = ""

OVERVIEW_ONLY = """\
## Overview

This application note provides a comprehensive guide to using the CD4013B.
It covers typical applications, component selection, PCB layout, and more.
The CD4013B is a versatile CMOS dual D-type flip-flop used in many designs.
"""


# ============================================================================
# Tests
# ============================================================================

class TestScoreAppnoteFullDocument(unittest.TestCase):
    """Test score_appnote with complete and empty documents."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_perfect_appnote_high_score(self):
        path = os.path.join(self.tmpdir, "perfect.md")
        with open(path, "w") as f:
            f.write(PERFECT_APPNOTE)
        result = score_appnote(path)
        self.assertGreaterEqual(result["total_score"], 56,
                                "Perfect appnote should score >= 56/80")

    def test_empty_file_score_zero(self):
        path = os.path.join(self.tmpdir, "empty.md")
        with open(path, "w") as f:
            f.write("")
        result = score_appnote(path)
        self.assertEqual(result["total_score"], 0,
                         "Empty file should score 0")

    def test_missing_file_returns_error(self):
        result = score_appnote("/tmp/nonexistent_appnote_12345.md")
        self.assertEqual(result["total_score"], 0)
        self.assertIn("error", result)

    def test_json_output_structure(self):
        path = os.path.join(self.tmpdir, "test.md")
        with open(path, "w") as f:
            f.write(PERFECT_APPNOTE)
        result = score_appnote(path)
        self.assertIn("file", result)
        self.assertIn("total_score", result)
        self.assertIn("max_score", result)
        self.assertIn("per_item", result)
        self.assertEqual(result["max_score"], 80)

    def test_per_item_count_matches_criteria(self):
        path = os.path.join(self.tmpdir, "test.md")
        with open(path, "w") as f:
            f.write(PERFECT_APPNOTE)
        result = score_appnote(path)
        self.assertEqual(len(result["per_item"]), len(CRITERIA))

    def test_per_item_fields(self):
        path = os.path.join(self.tmpdir, "test.md")
        with open(path, "w") as f:
            f.write(PERFECT_APPNOTE)
        result = score_appnote(path)
        for item in result["per_item"]:
            self.assertIn("name", item)
            self.assertIn("score", item)
            self.assertIn("max", item)
            self.assertIn("reason", item)
            self.assertEqual(item["max"], 10)

    def test_result_json_serializable(self):
        path = os.path.join(self.tmpdir, "test.md")
        with open(path, "w") as f:
            f.write(PERFECT_APPNOTE)
        result = score_appnote(path)
        # Should not raise
        serialized = json.dumps(result, ensure_ascii=False)
        parsed = json.loads(serialized)
        self.assertEqual(parsed["total_score"], result["total_score"])


class TestCheckOverview(unittest.TestCase):
    """Test the check_overview criterion."""

    def test_good_overview(self):
        score, reason = check_overview(PERFECT_APPNOTE)
        self.assertGreaterEqual(score, 7)

    def test_no_overview(self):
        score, reason = check_overview("# Some Other Title\n\nNo overview here.\n")
        self.assertLessEqual(score, 5)

    def test_brief_overview(self):
        text = "## Overview\n\nBrief note about the IC. Not much here.\n"
        score, reason = check_overview(text)
        self.assertGreater(score, 0)
        self.assertLessEqual(score, 7)

    def test_empty_text(self):
        score, reason = check_overview("")
        self.assertEqual(score, 0)


class TestCheckTypicalApplication(unittest.TestCase):
    """Test the check_typical_application criterion."""

    def test_with_schematic_and_components(self):
        score, reason = check_typical_application(PERFECT_APPNOTE)
        self.assertGreaterEqual(score, 6)

    def test_no_application_section(self):
        score, reason = check_typical_application("# Title\n\nSome text.\n")
        self.assertEqual(score, 0)

    def test_reference_without_section(self):
        text = "Some text mentioning typical application circuit for this IC.\n"
        score, reason = check_typical_application(text)
        self.assertGreater(score, 0)


class TestCheckComponentSelection(unittest.TestCase):
    """Test the check_component_selection criterion."""

    def test_with_table_and_values(self):
        score, reason = check_component_selection(PERFECT_APPNOTE)
        self.assertGreaterEqual(score, 7)

    def test_no_component_section(self):
        score, reason = check_component_selection("# Title\n\nNo components.\n")
        self.assertEqual(score, 0)


class TestCheckPCBLayout(unittest.TestCase):
    """Test the check_pcb_layout criterion."""

    def test_with_guidelines_and_diagram(self):
        score, reason = check_pcb_layout(PERFECT_APPNOTE)
        self.assertGreaterEqual(score, 4)

    def test_no_pcb_section(self):
        score, reason = check_pcb_layout("# Title\n\nNothing about PCB.\n")
        self.assertEqual(score, 0)


class TestCheckFirmwareExample(unittest.TestCase):
    """Test the check_firmware_example criterion."""

    def test_with_code_and_registers(self):
        score, reason = check_firmware_example(PERFECT_APPNOTE)
        self.assertGreaterEqual(score, 8)

    def test_no_firmware_section(self):
        score, reason = check_firmware_example("# Title\n\nNo code.\n")
        self.assertEqual(score, 0)


class TestCheckDesignCalculations(unittest.TestCase):
    """Test the check_design_calculations criterion."""

    def test_with_formulas(self):
        score, reason = check_design_calculations(PERFECT_APPNOTE)
        self.assertGreaterEqual(score, 5)

    def test_no_calc_section(self):
        score, reason = check_design_calculations("# Title\n\nNo calculations.\n")
        self.assertEqual(score, 0)


class TestCheckFAQ(unittest.TestCase):
    """Test the check_faq criterion."""

    def test_faq_with_5_plus_items(self):
        score, reason = check_faq(PERFECT_APPNOTE)
        self.assertGreaterEqual(score, 6)

    def test_no_faq(self):
        score, reason = check_faq("# Title\n\nNo FAQ.\n")
        self.assertEqual(score, 0)


class TestCheckCompetitiveComparison(unittest.TestCase):
    """Test the check_competitive_comparison criterion."""

    def test_with_table(self):
        score, reason = check_competitive_comparison(PERFECT_APPNOTE)
        self.assertGreaterEqual(score, 7)

    def test_no_comparison(self):
        score, reason = check_competitive_comparison("# Title\n\nNothing.\n")
        self.assertEqual(score, 0)


class TestHelpers(unittest.TestCase):
    """Test helper functions."""

    def test_find_section_existing(self):
        result = _find_section(PERFECT_APPNOTE, [r'overview'])
        self.assertTrue(len(result) > 0)

    def test_find_section_missing(self):
        result = _find_section("# Title\n\nSome text.\n", [r'nonexistent'])
        self.assertEqual(result, "")

    def test_has_table_true(self):
        text = "| A | B |\n|---|---|\n| 1 | 2 |\n"
        self.assertTrue(_has_table(text))

    def test_has_table_false(self):
        self.assertFalse(_has_table("No table here."))

    def test_count_table_rows(self):
        text = "| H1 | H2 |\n|---|---|\n| R1 | R2 |\n| R3 | R4 |\n"
        self.assertEqual(_count_table_rows(text), 2)

    def test_has_code_block(self):
        self.assertTrue(_has_code_block("```c\nint x;\n```"))
        self.assertFalse(_has_code_block("No code."))

    def test_has_ascii_art_box_drawing(self):
        self.assertTrue(_has_ascii_art("Some text\n┌──────┐\n│ test │\n└──────┘\n"))

    def test_count_list_items(self):
        text = "- Item 1\n- Item 2\n- Item 3\n"
        self.assertEqual(_count_list_items(text), 3)


if __name__ == '__main__':
    unittest.main()
