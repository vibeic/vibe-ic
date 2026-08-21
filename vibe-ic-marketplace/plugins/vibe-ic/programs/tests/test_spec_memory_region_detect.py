#!/usr/bin/env python3
"""Tests for spec_memory_region_detect — the memory-map completeness detector."""
import importlib.util
import sys
from pathlib import Path

_PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))
_spec = importlib.util.spec_from_file_location(
    "spec_memory_region_detect", _PROGRAMS / "spec_memory_region_detect.py")
_M = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_M)
detect = _M.detect_memory_region


# The real cvdp_copilot_apb_dsp_unit_0001 prose shape (the extraction-gap case):
# a bus that decodes to CSRs AND a 1 KB SRAM, only 0x00-0x05 reserved for regs.
APB_DSP = """\
Design an `apb_dsp_unit` module that serves as an APB interface for configuring
internal registers.

### APB Signals
- `paddr` (input, 10 bits): Address bus for accessing internal CSR registers and Memory.
- `pselx` (input): APB select signal, indicating CSR and Memory selection.

## SRAM Interface:
- `sram_valid`: At positive edge of this signal, data in `r_write_data` is latched.

4. **Memory Interface**
   - A 1 KB SRAM module serves as the memory.

**Note:** Addresses from 0x00 to 0x05 are reserved for configuration registers.
"""


def test_apb_dsp_detects_memory_region_strong():
    r = detect(APB_DSP)
    assert r["has_memory_region"] is True
    assert r["confidence"] == "strong"
    # at least one strong signal fired
    tags = " ".join(r["evidence"])
    assert ("section-header" in tags or "serves-as-memory" in tags
            or "registers-and-memory" in tags)
    req = (r["requirement"] or "").lower()
    assert "memory" in req and "datapath" in req


def test_apb_dsp_extracts_reserved_range_and_size_hints():
    r = detect(APB_DSP)
    assert r["reserved_csr_hint"] == "0x00 to 0x05"
    assert r["mem_size_hint"] and "1" in r["mem_size_hint"] and "KB" in r["mem_size_hint"]


def test_memory_address_pointer_prose_does_not_fire():
    # "holds the memory address of an operand" is a POINTER, not a memory block —
    # must NOT be flagged (no CSR+memory bus decode, no SRAM, no memory section).
    pointer = """\
Design a small block with two registers.
1. **r_operand_1** - Address: 0x0 - Holds the memory address of the first operand.
2. **r_operand_2** - Address: 0x1 - Holds the memory address of the second operand.
The computed result is made available through a designated register.
"""
    r = detect(pointer)
    assert r["has_memory_region"] is False
    assert r["confidence"] == "none"
    assert r["requirement"] is None


def test_plain_counter_prompt_does_not_fire():
    r = detect("Design an 8-bit up counter with synchronous reset and enable.")
    assert r["has_memory_region"] is False


def test_two_medium_signals_fire():
    # a dual-port SRAM keyword + a "reserved for registers" phrase = 2 medium → fire
    txt = ("The peripheral exposes a dual-port RAM. Offsets reserved for control "
           "registers occupy 0x0 to 0x3; the remaining space is data storage.")
    r = detect(txt)
    assert r["has_memory_region"] is True
    assert r["confidence"] in ("medium", "strong")


if __name__ == "__main__":
    import pytest
    raise SystemExit(pytest.main([__file__, "-q"]))
