"""Unit tests for ds_quality_check.py — datasheet (L1) quality scorer 0-100."""
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "ds_quality_check.py"
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"
sys.path.insert(0, str(SCRIPT.parent))
import ds_quality_check as ds  # noqa: E402


# A "good" datasheet hitting all 10 criteria at full marks.
GOOD_DS = """\
# Generic Sensor Datasheet

## Features
- 16-bit resolution
- I2C interface up to 400 kHz
- Low power 1.2 uA standby
- Wide supply 1.8 V to 5.5 V
- Internal temperature sensor
- Programmable interrupt

## Description
This device is a high-precision analog front end intended for portable
instrumentation. It integrates a programmable gain amplifier, a delta-sigma
converter and a digital interface in a compact package.

It supports single-shot and continuous conversion modes, and includes an
internal reference for ratiometric measurements without an external part.

## Pin Configuration
| Pin | Name | Type | Description |
|-----|------|------|-------------|
| 1   | VDD  | PWR  | Supply |
| 2   | GNDP | PWR  | Ground |
| 3   | SDAT | I/O  | Serial data |
| 4   | SCLK | IN   | Serial clock |

## Absolute Maximum Ratings
| Parameter | Min | Max | Unit |
|-----------|-----|-----|------|
| Supply voltage | -0.3 | 6.0 | V |
| Input voltage | -0.3 | 6.0 | V |
| Storage temp | -65 | 150 | C |
| Junction temp | - | 150 | C |
| ESD HBM | - | 2000 | V |

## Recommended Operating Conditions
| Parameter | Min | Typ | Max | Unit |
|-----------|-----|-----|-----|------|
| Supply | 1.8 | 3.3 | 5.5 | V |
| Temp | -40 | 25 | 85 | C |

## Electrical Characteristics
DC characteristics measured at 3.3 V.
| Param | Min | Typ | Max | Unit |
|-------|-----|-----|-----|------|
| Iq | - | 150 | 250 | uA |

AC / switching characteristics:
| Param | Min | Typ | Max | Unit |
|-------|-----|-----|-----|------|
| fSCLK | - | - | 400 | kHz |

## Timing Diagrams
```
SCLK  __|‾‾|__|‾‾|__
SDAT  ‾‾‾‾|________|‾‾
       <-tSU-><-tHD->
```

## Block Diagram
```
   +--------+      +-------+      +--------+
   |  PGA   |----->| ADC   |----->|  I2C   |
   +--------+      +-------+      +--------+
        ^              ^              |
        |              |              v
     analog in      ref              SDAT
```

## Detailed Description and Register Map
The conversion engine runs from an internal oscillator. The configuration
register selects gain, data rate and mux channel. Reading the conversion
register returns the most-recent result in two's-complement form. The device
powers up in a known reset state with all registers cleared, ensuring a
deterministic startup behaviour for the host firmware to build upon safely.

| Addr | Register | Bits | Description |
|------|----------|------|-------------|
| 0x00 | CONV     | 16   | Conversion result |
| 0x01 | CONFIG   | 16   | Configuration |

## Application Information
```
 VDD --+--[10 kohm]--+-- SDAT
       |             |
      ===0.1 uF     host
       |
      GND
```
Use a 10 kohm pull-up on SDAT and a 0.1 uF decoupling capacitor close to VDD.
"""

# A "bad" datasheet: only a title and a sparse feature list — most sections
# absent. Should score well below threshold.
BAD_DS = """\
# Sketch

## Features
- one thing

Some loose text without proper sections.
"""


def _write(tmp_path, name, content):
    p = tmp_path / name
    p.write_text(content)
    return p


def test_good_datasheet_passes():
    result = ds.score_datasheet_text(GOOD_DS, "good.md")
    assert result.verdict == "PASS", result.to_dict()
    assert result.score >= ds.THRESHOLD
    assert result.score <= ds.MAX_SCORE


def test_good_datasheet_full_marks_on_key_criteria():
    result = ds.score_datasheet_text(GOOD_DS)
    by_idx = {c.index: c for c in result.breakdown}
    # Features (>=5 bullets) and Pin config (>=3 cols) must be full marks.
    assert by_idx[1].score == 10, by_idx[1].note
    assert by_idx[3].score == 10, by_idx[3].note
    assert by_idx[5].score == 10, by_idx[5].note   # min/typ/max ROC


def test_bad_datasheet_fails():
    result = ds.score_datasheet_text(BAD_DS, "bad.md")
    assert result.verdict == "FAIL"
    assert result.score < ds.THRESHOLD


def test_empty_is_missing_not_false_fail():
    result = ds.score_datasheet_text("", "empty.md")
    assert result.verdict == "MISSING"
    assert result.score == 0


def test_missing_file_degrades_gracefully(tmp_path):
    result = ds.score_datasheet_path(tmp_path / "nope.md")
    assert result.verdict == "MISSING"


def test_project_dir_autolocate(tmp_path):
    _write(tmp_path, "04_datasheet.md", GOOD_DS)
    result = ds.score_datasheet_path(tmp_path)
    assert result.verdict == "PASS"
    assert "04_datasheet.md" in result.source


def test_deterministic():
    a = ds.score_datasheet_text(GOOD_DS).score
    b = ds.score_datasheet_text(GOOD_DS).score
    assert a == b


def test_cli_exit_codes(tmp_path, capsys):
    good = _write(tmp_path, "g.md", GOOD_DS)
    bad = _write(tmp_path, "b.md", BAD_DS)
    assert ds.main([str(good), "--json"]) == 0
    assert ds.main([str(bad), "--json"]) == 1
    assert ds.main([str(tmp_path / "missing.md")]) == 2
