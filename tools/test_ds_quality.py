#!/usr/bin/env python3
"""
Unit tests for ds_quality_check.py — Datasheet Quality Scorer
==============================================================
Tests with mock perfect datasheet, empty file, individual criteria.
Run: python3 -m pytest tools/vibe_ic_tools/test_ds_quality.py -v
"""

import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from ds_quality_check import (
    score_datasheet,
    check_features,
    check_description,
    check_pin_config,
    check_abs_max_ratings,
    check_rec_operating,
    check_electrical_chars,
    check_timing_diagrams,
    check_block_diagram,
    check_detailed_description,
    check_application_info,
    _find_section,
    _count_table_columns,
    _has_table,
    _has_ascii_art,
    _has_min_typ_max,
)


# ============================================================================
# Helper: generate a mock "perfect" datasheet
# ============================================================================

PERFECT_DATASHEET = """\
# CD4013B — CMOS Dual D-Type Flip-Flop Datasheet

**Document Number**: DS-CD4013B-001
**Revision**: 1.0
**Date**: 2026-04-09

---

## Key Features

- Dual independent D-type flip-flops with async SET and RESET
- Positive-edge triggered clock input
- Wide supply range: 3V to 15V (CMOS 4000B series)
- Ultra-low static power: typical 4nW at VDD=5V
- High noise immunity: typical 45% VDD
- Standard DIP-14 package
- Fully static operation: no minimum clock frequency
- Built-in ESD protection: HBM >= 2000V
- Commercial temperature range: 0C to 70C

---

## Product Description

The CD4013B is a CMOS dual D-type flip-flop IC belonging to the CMOS 4000B series. Each IC
contains two completely independent D-type flip-flops, each with its own Data input (D),
Clock input (CLK), asynchronous Set (SET), asynchronous Reset (RESET), true output (Q),
and complementary output (Q_bar).

The device operates on the principle that when SET=0 and RESET=0, the flip-flop samples
the D input on the rising edge of CLK and transfers its value to Q. Q_bar is the complement
of Q. When SET=1, Q is forced to 1. When RESET=1, Q is forced to 0.

The CD4013B is fabricated using complementary MOS (CMOS) technology, providing ultra-low
static power consumption, wide supply voltage range, and high noise immunity typical
of the CMOS 4000 series.

---

## Pin Configuration (14-Pin DIP)

```
            +-----+
   Q1  1 ---|     |--- 14  VDD
  Q1b  2 ---|     |--- 13  Q2
  CLK1 3 ---| CD  |--- 12  Q2b
  RST1 4 ---| 4013|--- 11  CLK2
   D1  5 ---|     |--- 10  RST2
  SET1 6 ---|     |---  9  D2
  VSS  7 ---|     |---  8  SET2
            +-----+
```

| Pin | Name | I/O | Function |
|-----|------|-----|----------|
| 1 | Q1 | O | FF1 true output |
| 2 | Q1_bar | O | FF1 complement output |
| 3 | CLK1 | I | FF1 clock input, rising edge |
| 4 | RESET1 | I | FF1 async reset, active high |
| 5 | DATA1 | I | FF1 data input |
| 6 | SET1 | I | FF1 async set, active high |
| 7 | VSS | PWR | Ground (0V) |

---

## Absolute Maximum Ratings

| Parameter | Symbol | Min | Max | Unit |
|-----------|--------|-----|-----|------|
| Supply Voltage | VDD-VSS | -0.5 | 18 | V |
| Input Voltage | VIN | -0.5 | VDD+0.5 | V |
| Output Short Circuit Current | IOS | - | 25 | mA |
| Power Dissipation | PD | - | 500 | mW |
| Storage Temperature | Tstg | -65 | 150 | C |
| Operating Temperature | TA | 0 | 70 | C |
| ESD (HBM) | VESD | - | 2000 | V |

---

## Recommended Operating Conditions

| Parameter | Symbol | Min | Typ | Max | Unit |
|-----------|--------|-----|-----|-----|------|
| Supply Voltage | VDD | 3 | 5 | 15 | V |
| Input High | VIH | 0.7xVDD | - | VDD | V |
| Input Low | VIL | VSS | - | 0.3xVDD | V |
| Temperature | TA | 0 | 25 | 70 | C |

---

## Electrical Characteristics

### DC Characteristics (TA=25C)

| Parameter | Symbol | Condition | Min | Typ | Max | Unit |
|-----------|--------|-----------|-----|-----|-----|------|
| Output High | VOH | IOH=-1mA | 4.6 | 4.95 | - | V |
| Output Low | VOL | IOL=1mA | - | 0.05 | 0.4 | V |
| Supply Current | IDD | Static | - | 0.004 | 4 | uA |
| Input Leakage | IIN | - | - | 0.1 | 1 | uA |

### AC Characteristics (TA=25C, CL=50pF)

| Parameter | Symbol | VDD=5V | VDD=10V | Unit |
|-----------|--------|--------|---------|------|
| Propagation Delay CLK->Q (LH) | tPLH | 150/250 | 60/100 | ns |
| Propagation Delay CLK->Q (HL) | tPHL | 150/250 | 60/100 | ns |
| Rise Time | tR | 100/200 | 50/100 | ns |
| Fall Time | tF | 100/200 | 50/100 | ns |
| Setup Time D->CLK | tSU | 60 | 25 | ns |
| Hold Time CLK->D | tH | 40 | 15 | ns |
| Max Clock Frequency | fMAX | 2.5 | 6 | MHz |

---

## Timing Diagrams

```
        ____      ____      ____
CLK  __|    |____|    |____|    |____
        _______________
D    __|               |____________
                 _______________
Q    ___________|               |____
     _______________
Q_b                 |________________
```

The timing diagram shows normal clocked operation. D is sampled on the rising edge
of CLK. After propagation delay tPLH/tPHL, Q reflects the sampled D value.
Q_bar is always the complement of Q.

---

## Block Diagram

```
        +---------------------------+
        |        CD4013B            |
        |                           |
   D ---|---> D-FF ----> Q          |
        |      ^    |               |
  CLK --|------+    +--> Q_bar      |
        |      |                    |
  SET --|---> [S]                   |
        |                           |
  RST --|---> [R]                   |
        +---------------------------+
```

The block diagram shows a single flip-flop unit within the CD4013B.
The D input is captured at the CLK rising edge.
SET and RESET are asynchronous overrides.

---

## Detailed Description

The CD4013B implements two identical positive-edge-triggered D flip-flops with
asynchronous Set and Reset controls. The device uses standard CMOS technology with
P-channel and N-channel enhancement-mode transistors.

### Theory of Operation

Each flip-flop contains a master-slave latch pair. On the rising edge of CLK:
1. The master latch captures the D input value.
2. The slave latch transfers the master's value to Q and Q_bar outputs.
3. After the clock edge, the outputs remain stable regardless of D changes.

### Register Map

This is a simple combinational/sequential IC with no addressable registers.
However, the following state table describes the flip-flop behavior:

| SET | RESET | CLK | D | Q(next) | Q_bar(next) |
|-----|-------|-----|---|---------|-------------|
| 0 | 0 | Rising | 0 | 0 | 1 |
| 0 | 0 | Rising | 1 | 1 | 0 |
| 1 | 0 | X | X | 1 | 0 |
| 0 | 1 | X | X | 0 | 1 |
| 1 | 1 | X | X | 1 | 1 |

---

## Application Information

### Typical Application: Frequency Divider

Connect Q_bar to D to create a toggle flip-flop (divide-by-2).
Cascading two stages gives divide-by-4.

```
                +--------+
  CLK_IN ----->| CLK  Q |----+---> CLK_OUT (f/2)
               |        |    |
  VDD ---[10kO]-| SET    |    |
               |   Q_b |----+
  GND --------| RST  D |<---+
               +--------+
```

Component values:
- R1: 10kOhm pull-up on SET (optional, for noise immunity)
- C1: 100nF bypass capacitor VDD to VSS

This circuit divides the input frequency by 2. Each rising edge of CLK_IN
toggles the output state.
"""


class TestPerfectDatasheet(unittest.TestCase):
    """Test with a mock perfect datasheet — expect near 100 score."""

    def setUp(self):
        self.f = tempfile.NamedTemporaryFile(
            mode='w', suffix='.md', delete=False, encoding='utf-8'
        )
        self.f.write(PERFECT_DATASHEET)
        self.f.close()

    def tearDown(self):
        os.unlink(self.f.name)

    def test_score_high(self):
        result = score_datasheet(self.f.name)
        self.assertGreaterEqual(result['total_score'], 80,
                                f"Perfect datasheet should score >=80, got {result['total_score']}")

    def test_all_criteria_present(self):
        result = score_datasheet(self.f.name)
        for item in result['per_item']:
            self.assertGreater(item['score'], 0,
                               f"Criterion '{item['name']}' scored 0 in perfect datasheet")

    def test_json_serializable(self):
        result = score_datasheet(self.f.name)
        data = json.loads(json.dumps(result, default=str))
        self.assertIn('total_score', data)
        self.assertIn('per_item', data)
        self.assertIsInstance(data['per_item'], list)


class TestEmptyFile(unittest.TestCase):
    """Test with empty file — expect score=0."""

    def test_empty_file_score_zero(self):
        f = tempfile.NamedTemporaryFile(
            mode='w', suffix='.md', delete=False, encoding='utf-8'
        )
        f.write("")
        f.close()
        try:
            result = score_datasheet(f.name)
            self.assertEqual(result['total_score'], 0)
        finally:
            os.unlink(f.name)

    def test_file_not_found(self):
        result = score_datasheet('/nonexistent/datasheet.md')
        self.assertEqual(result['total_score'], 0)
        self.assertIn('error', result)


class TestCheckFeatures(unittest.TestCase):
    """Test criterion 1: Features section."""

    def test_features_with_many_items(self):
        text = "## Key Features\n" + "\n".join(f"- Feature item {i}" for i in range(10))
        score, reason = check_features(text)
        self.assertEqual(score, 10)

    def test_features_with_few_items(self):
        text = "## Features\n- Item 1\n- Item 2\n"
        score, reason = check_features(text)
        self.assertGreater(score, 0)
        self.assertLess(score, 10)

    def test_no_features_section(self):
        text = "## Overview\nSome text\n"
        score, reason = check_features(text)
        self.assertEqual(score, 0)


class TestCheckDescription(unittest.TestCase):
    """Test criterion 2: Description paragraphs."""

    def test_good_description(self):
        text = (
            "## Description\n\n"
            "This is a full paragraph describing the IC. It has multiple sentences "
            "and is quite detailed about the functionality.\n\n"
            "This is a second paragraph providing additional technical details "
            "about the architecture and operation.\n\n"
            "And a third paragraph with application notes.\n"
        )
        score, reason = check_description(text)
        self.assertEqual(score, 10)

    def test_no_description(self):
        text = "## Pin Table\n| Pin | Name |\n"
        score, reason = check_description(text)
        self.assertEqual(score, 0)


class TestCheckPinConfig(unittest.TestCase):
    """Test criterion 3: Pin configuration."""

    def test_pin_table_with_columns(self):
        text = (
            "## Pin Configuration\n"
            "| Pin | Name | I/O | Function |\n"
            "|-----|------|-----|----------|\n"
            "| 1 | Q1 | O | Output |\n"
            "| 2 | D1 | I | Data input |\n"
        )
        score, reason = check_pin_config(text)
        self.assertGreaterEqual(score, 8)

    def test_no_pin_config(self):
        text = "## Overview\nGeneral text only.\n"
        score, reason = check_pin_config(text)
        self.assertEqual(score, 0)


class TestCheckAbsMaxRatings(unittest.TestCase):
    """Test criterion 4: Absolute Maximum Ratings."""

    def test_abs_max_with_table(self):
        text = (
            "## Absolute Maximum Ratings\n"
            "| Parameter | Symbol | Min | Max | Unit |\n"
            "|-----------|--------|-----|-----|------|\n"
            "| Supply | VDD | -0.5 | 18 | V |\n"
            "| Input | VIN | -0.5 | VDD+0.5 | V |\n"
            "| Current | IOS | - | 25 | mA |\n"
            "| Power | PD | - | 500 | mW |\n"
            "| Temp | Tstg | -65 | 150 | C |\n"
        )
        score, reason = check_abs_max_ratings(text)
        self.assertEqual(score, 10)

    def test_no_abs_max(self):
        text = "## Features\n- Dual flip-flop\n"
        score, reason = check_abs_max_ratings(text)
        self.assertEqual(score, 0)


class TestCheckRecOperating(unittest.TestCase):
    """Test criterion 5: Recommended Operating Conditions."""

    def test_rec_operating_with_min_typ_max(self):
        text = (
            "## Recommended Operating Conditions\n"
            "| Parameter | Symbol | Min | Typ | Max | Unit |\n"
            "|-----------|--------|-----|-----|-----|------|\n"
            "| VDD | VDD | 3 | 5 | 15 | V |\n"
        )
        score, reason = check_rec_operating(text)
        self.assertEqual(score, 10)

    def test_no_rec_operating(self):
        text = "## Electrical Specs\nSome data\n"
        score, reason = check_rec_operating(text)
        self.assertEqual(score, 0)


class TestCheckElectricalChars(unittest.TestCase):
    """Test criterion 6: Electrical Characteristics DC+AC."""

    def test_dc_and_ac(self):
        text = (
            "## Electrical Characteristics\n\n"
            "### DC Characteristics\n"
            "| Parameter | Min | Max | Unit |\n"
            "|-----------|-----|-----|------|\n"
            "| VOH | 4.6 | - | V |\n"
            "| Supply current IDD | - | 4 | uA |\n\n"
            "### AC Characteristics\n"
            "Propagation delay tPLH = 150ns\n"
            "Rise time tR = 100ns, switching frequency fMAX = 2.5MHz\n"
        )
        score, reason = check_electrical_chars(text)
        self.assertGreaterEqual(score, 7)

    def test_no_electrical(self):
        text = "## Abstract\nA simple IC.\n"
        score, reason = check_electrical_chars(text)
        self.assertEqual(score, 0)


class TestCheckTimingDiagrams(unittest.TestCase):
    """Test criterion 7: Timing diagrams."""

    def test_timing_with_ascii_art(self):
        text = (
            "## Timing Diagrams\n\n"
            "```\n"
            "        ____      ____\n"
            "CLK  __|    |____|    |____\n"
            "        _______________\n"
            "D    __|               |____\n"
            "```\n"
            "The timing diagram shows normal clocked operation of the flip-flop.\n"
        )
        score, reason = check_timing_diagrams(text)
        self.assertGreaterEqual(score, 8)

    def test_no_timing(self):
        text = "## Pinout\n| Pin | Name |\n"
        score, reason = check_timing_diagrams(text)
        self.assertEqual(score, 0)


class TestCheckBlockDiagram(unittest.TestCase):
    """Test criterion 8: Block diagram."""

    def test_block_diagram_with_art(self):
        text = (
            "## Block Diagram\n\n"
            "```\n"
            "  +-------+\n"
            "  | DFF   |\n"
            "  | D-->Q |\n"
            "  +-------+\n"
            "```\n"
            "The block diagram shows the internal structure of the flip-flop unit.\n"
        )
        score, reason = check_block_diagram(text)
        self.assertGreaterEqual(score, 8)


class TestCheckDetailedDescription(unittest.TestCase):
    """Test criterion 9: Detailed description."""

    def test_detailed_with_register_map(self):
        text = (
            "## Detailed Description\n\n"
            "The device uses CMOS technology. Each flip-flop contains a master-slave "
            "latch pair that captures data on the clock edge. The internal architecture "
            "is optimized for low power consumption.\n\n"
            "### Register Map\n"
            "| Address | Register | Description |\n"
            "|---------|----------|-------------|\n"
            "| 0x00 | CTRL | Control register |\n"
            "| 0x01 | STATUS | Status register |\n"
            "This register map provides addressable registers at 0x00 and 0x01.\n"
        )
        score, reason = check_detailed_description(text)
        self.assertGreaterEqual(score, 8)


class TestCheckApplicationInfo(unittest.TestCase):
    """Test criterion 10: Application information."""

    def test_application_with_circuit(self):
        text = (
            "## Application Information\n\n"
            "### Typical Application: Frequency Divider\n"
            "Connect Q_bar to D to create a toggle flip-flop.\n"
            "```\n"
            "  CLK --> | DFF | --> Q_out\n"
            "          |     |    |\n"
            "          | D   |<---+\n"
            "```\n"
            "Component values: R1 = 10kOhm, C1 = 100nF bypass on VDD.\n"
            "This circuit divides the input frequency by 2.\n"
        )
        score, reason = check_application_info(text)
        self.assertGreaterEqual(score, 7)

    def test_no_application(self):
        text = "## Summary\nEnd of document.\n"
        score, reason = check_application_info(text)
        self.assertEqual(score, 0)


class TestHelperFunctions(unittest.TestCase):
    """Test internal helper functions."""

    def test_find_section(self):
        text = "## Features\n- A\n- B\n## Next\nEnd\n"
        section = _find_section(text, [r'feature'])
        self.assertIn('- A', section)
        self.assertNotIn('End', section)

    def test_count_table_columns(self):
        text = "| A | B | C | D |\n|---|---|---|---|\n| 1 | 2 | 3 | 4 |\n"
        self.assertEqual(_count_table_columns(text), 4)

    def test_has_table(self):
        text = "| A | B |\n|---|---|\n| 1 | 2 |\n"
        self.assertTrue(_has_table(text))
        self.assertFalse(_has_table("Just plain text"))

    def test_has_ascii_art(self):
        art = "```\n+---+\n| A |\n+---+\n```\n"
        self.assertTrue(_has_ascii_art(art))
        self.assertFalse(_has_ascii_art("Just text"))

    def test_has_min_typ_max(self):
        self.assertTrue(_has_min_typ_max("| Min | Typ | Max |"))
        self.assertFalse(_has_min_typ_max("| Value | Unit |"))


if __name__ == '__main__':
    unittest.main()
