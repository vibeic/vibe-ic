"""Unit tests for an_validator.py — application-note (AN) scorer 0-80."""
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "an_validator.py"
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"
sys.path.insert(0, str(SCRIPT.parent))
import an_validator as an  # noqa: E402


GOOD_AN = """\
# Generic Sensor Application Note

## Overview
This application note describes how to design a complete sensing subsystem
around the device, including supply decoupling, the host interface, and the
firmware driver. It targets battery-powered instrumentation where low standby
current and ratiometric accuracy are both required at the same time.

The guidance below has been validated on a two-layer reference board and is
intended to be copied directly into a production design with minimal change,
so that a first-pass layout meets EMI and accuracy targets out of the box.

## Typical Application Circuit
```
 VDD --+--[10 kohm]--+-- SDAT --- host
       |             |
      ===0.1 uF      |
       |            host
      GND
```
The pull-up resistor and 0.1 uF decoupling capacitor are required.

## External Component Selection
| Ref | Value | Purpose |
|-----|-------|---------|
| R1  | 10 kohm | SDAT pull-up |
| C1  | 0.1 uF  | Supply decoupling |
| C2  | 1 uF    | Bulk reservoir |

## PCB Layout
- Keep the decoupling capacitor within 2 mm of the supply pin.
- Use a solid ground plane under the device.
- Route the analog input away from the digital clock.
```
[ device ]==C1== GND plane
```

## Firmware Example
```c
i2c_write(0x01, 0x8483);   // configure
uint16_t v = i2c_read(0x00); // read conversion
```
The firmware writes the CONFIG register then reads the CONV register.

## Design Calculations
The full-scale voltage is computed as:
VFS = VREF / GAIN
The LSB size is:
LSB = VFS / 32768
The pull-up value satisfies:
Rpull = (VDD - VOL) / IOL = 3.3 / 0.003 = 1100 ohm

## FAQ
- Q: What supply range is supported? The device runs from 1.8 V to 5.5 V.
- Q: Can I use a slower I2C clock? Yes, down to DC.
- Q: Is an external reference needed? No, an internal reference is provided.
- Q: How do I lower power? Use single-shot mode and power down between reads.
- Q: What is the conversion time? About 1 ms at the default data rate.

## Competitive Comparison
| Feature | This part | Competitor A | Competitor B |
|---------|-----------|--------------|--------------|
| Resolution | 16-bit | 12-bit | 16-bit |
| Iq | 150 uA | 300 uA | 200 uA |
| Interface | I2C | SPI | I2C |
"""

BAD_AN = """\
# Notes

## Overview
short.

Some text but nothing structured.
"""


def _write(tmp_path, name, content):
    p = tmp_path / name
    p.write_text(content)
    return p


def test_good_appnote_passes():
    result = an.score_appnote_text(GOOD_AN, "good.md")
    assert result.verdict == "PASS", result.to_dict()
    assert result.score >= an.THRESHOLD
    assert result.score <= an.MAX_SCORE


def test_good_appnote_full_marks_on_key_criteria():
    result = an.score_appnote_text(GOOD_AN)
    by_idx = {c.index: c for c in result.breakdown}
    assert by_idx[7].score == 10, by_idx[7].note   # FAQ >=5 Q&A
    assert by_idx[8].score == 10, by_idx[8].note   # comparison >=3 products


def test_bad_appnote_fails():
    result = an.score_appnote_text(BAD_AN, "bad.md")
    assert result.verdict == "FAIL"
    assert result.score < an.THRESHOLD


def test_empty_is_missing():
    result = an.score_appnote_text("", "empty.md")
    assert result.verdict == "MISSING"
    assert result.score == 0


def test_project_dir_autolocate(tmp_path):
    _write(tmp_path, "05_appnote.md", GOOD_AN)
    result = an.score_appnote_path(tmp_path)
    assert result.verdict == "PASS"
    assert "05_appnote.md" in result.source


def test_deterministic():
    a = an.score_appnote_text(GOOD_AN).score
    b = an.score_appnote_text(GOOD_AN).score
    assert a == b


def test_cli_exit_codes(tmp_path):
    good = _write(tmp_path, "g.md", GOOD_AN)
    bad = _write(tmp_path, "b.md", BAD_AN)
    assert an.main([str(good), "--json"]) == 0
    assert an.main([str(bad), "--json"]) == 1
    assert an.main([str(tmp_path / "missing.md")]) == 2
