"""Unit tests for spec_validator.py — DS<->AN cross-consistency checker."""
import sys
from pathlib import Path

SCRIPT = Path(__file__).parent.parent / "spec_validator.py"
assert SCRIPT.exists(), f"Script not found: {SCRIPT}"
sys.path.insert(0, str(SCRIPT.parent))
import spec_validator as sv  # noqa: E402


# Consistent pair: every AN pin + register is present in the DS, no TBD.
GOOD_DS = """\
# Datasheet

## Pin Configuration
| Pin | Name | Type |
|-----|------|------|
| 1   | VDDA | PWR  |
| 2   | SDAT | I/O  |
| 3   | SCLK | IN   |
| 4   | ALRT | OUT  |

## Register Map
| Addr | Register |
|------|----------|
| 0x00 | CONV     |
| 0x01 | CONFIG   |
| 0x02 | THRESH   |
"""

GOOD_AN = """\
# Application Note

## Typical Application Circuit
```
 VDDA --[10 kohm]-- SDAT --- host
 SCLK --- host
 ALRT --- host_irq
```

## Firmware Example
```c
i2c_write(0x01, 0x8483);  // CONFIG
v = i2c_read(0x00);       // CONV
i2c_write(0x02, 0x7fff);  // THRESH
```
"""

# Bad AN: references pin 'XPIN' not in DS, register 0x09 not in DS, and a TBD.
BAD_AN = """\
# Application Note

## Typical Application Circuit
```
 VDDA --[10 kohm]-- SDAT --- host
 XPIN --- something
```

## Firmware Example
```c
i2c_write(0x09, 0x0001);  // unknown register
```

## Notes
Threshold value is TBD.
"""


def test_consistent_pair_passes():
    r = sv.validate(GOOD_DS, GOOD_AN)
    assert r.verdict == "PASS", r.to_dict()
    assert r.error_count == 0


def test_pin_mismatch_flagged():
    r = sv.validate(GOOD_DS, BAD_AN)
    rules = {f.rule for f in r.findings if f.severity == "ERROR"}
    assert "pin-mismatch" in rules
    assert r.verdict == "FAIL"


def test_register_mismatch_flagged():
    r = sv.validate(GOOD_DS, BAD_AN)
    msgs = [f.message for f in r.findings
            if f.severity == "ERROR" and f.rule == "register-mismatch"]
    assert any("0x09" in m for m in msgs), msgs


def test_unresolved_tbd_flagged():
    r = sv.validate(GOOD_DS, BAD_AN)
    rules = {f.rule for f in r.findings if f.severity == "ERROR"}
    assert "unresolved-tbd" in rules


def test_no_tbd_in_clean_docs():
    r = sv.validate(GOOD_DS, GOOD_AN)
    assert r.stats.get("unresolved_tbd_total", 0) == 0


def test_missing_section_skips_not_fails():
    # AN with no firmware/circuit sections -> cross checks SKIP, no ERROR.
    sparse_an = "# AN\n\n## Overview\nJust prose, no circuit or firmware.\n"
    r = sv.validate(GOOD_DS, sparse_an)
    assert r.verdict == "PASS"
    assert any(f.rule == "section-missing" for f in r.findings)


def test_no_documents_is_missing():
    r = sv.validate(None, None)
    assert r.verdict == "MISSING"


def test_sparse_pins_no_false_alert():
    # DS pin table exists but AN circuit yields no parsable pins -> SKIP.
    an_no_pins = ("# AN\n\n## Typical Application Circuit\n"
                  "Use a pull-up resistor and a decoupling capacitor.\n")
    r = sv.validate(GOOD_DS, an_no_pins)
    # No pin-mismatch ERROR should be raised from unparsable prose.
    assert not any(f.rule == "pin-mismatch" for f in r.findings)


def test_deterministic():
    a = sv.validate(GOOD_DS, BAD_AN).error_count
    b = sv.validate(GOOD_DS, BAD_AN).error_count
    assert a == b


def test_cli_exit_codes(tmp_path):
    ds = tmp_path / "ds.md"
    an_good = tmp_path / "an_good.md"
    an_bad = tmp_path / "an_bad.md"
    ds.write_text(GOOD_DS)
    an_good.write_text(GOOD_AN)
    an_bad.write_text(BAD_AN)
    assert sv.main(["--ds", str(ds), "--an", str(an_good), "--json"]) == 0
    assert sv.main(["--ds", str(ds), "--an", str(an_bad), "--json"]) == 1
