#!/usr/bin/env python3
"""ORGANIC FIR_0001 [chip-AGNOSTIC] — iface_conformance_v2 fabricates a phantom
MISSING-PORT for the SystemVerilog reserved TYPE keyword `logic` scraped out of
a port table's TYPE column.

ROOT CAUSE (shipped v1.1.29): `_table_ports()` scans pipe-windows of the form
`` `name` | word `` over the WHOLE prompt with NO reserved-keyword exclusion
(unlike `_ANSI_PORT_RE` / the given-code parser, which both exclude
logic/wire/reg/...). On a `| `name` | `type` | desc |` port table the scan
straddles a cell boundary and matches `` `logic` | System `` (the TYPE cell of
one row + the first word of the DESCRIPTION cell), harvesting a phantom port
named `logic` with source=table → STRUCTURAL → block_eligible → strict rc=1 on
correct, spec-faithful RTL that declares exactly the spec's real ports.

FIX: candidate port NAMES in `_table_ports()` are filtered (whole-token,
case-SENSITIVE) through the SAME `_SV_PORT_KEYWORDS` set the header-port
parsers already use. A reserved SV type/direction keyword is never a legal port
identifier, so excluding it can only DROP a phantom — it can never mask a real
port. A real port whose identifier merely CONTAINS such a keyword as a SUBSTRING
(`logic_en`, `reg_file_addr`, `wire_sel`) is a DISTINCT whole token and is still
harvested.

§4.05 NO-LEAK: the relaxation drops candidate NAMES, so a too-wide exclusion
would wave a genuinely-missing real port through. The negatives below prove a
GENUINE missing PORT (a normal identifier in a DIRECTION table the RTL omits)
STILL hard-blocks (rc=1), and a keyword-SUBSTRING port (`reg_file_addr`)
genuinely omitted STILL hard-blocks — so the exclusion is whole-token only and
never masks a real MISSING-PORT.

The POSITIVE (`| `clk` | `logic` | ... |` table → rc=0) FAILS on shipped
v1.1.29 (phantom `logic`) and PASSES on the patched gate.

chip-AGNOSTIC: pure SV-keyword set + markdown grammar; no chip/vendor literal.
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

import pytest

# Programs dir: VIBE_PROGRAMS override wins; else this file's parent's parent
# (`<...>/programs/`) — matching the in-repo layout where the test lives under
# `programs/tests/` and `iface_conformance_v2.py` lives in `programs/`.
_OVERRIDE = os.environ.get("VIBE_PROGRAMS")
if _OVERRIDE:
    PROGRAMS = Path(_OVERRIDE).resolve()
else:
    PROGRAMS = Path(__file__).resolve().parent.parent
PROG = PROGRAMS / "iface_conformance_v2.py"

if not PROG.is_file():
    pytest.skip(
        f"iface_conformance_v2.py not found at {PROG}; set VIBE_PROGRAMS to the "
        "programs/ directory", allow_module_level=True)

sys.path.insert(0, str(PROGRAMS))
import iface_conformance_v2 as M  # noqa: E402
from _hostpaths import require_repo  # noqa: E402


# ── the FIR_0001 shape: a `| `name` | `type` | desc |` port table ────────────
# Inputs/Outputs tables carry a TYPE column whose cells are backtick-wrapped
# SystemVerilog type keywords (`logic`, `logic signed [15:0]`). The shipped
# scan straddles `` `logic` | System `` (type cell + first desc word) → phantom.
_FIR_PROMPT = """# Specification: fir_filter

## Module Interface

Module name: `fir_filter`

### Inputs
| Port           | Width / Type          | Description                       |
|----------------|-----------------------|-----------------------------------|
| `clk`          | `logic`               | System clock.                     |
| `reset`        | `logic`               | Asynchronous, active-high reset.  |
| `input_sample` | `logic signed [15:0]` | Signed 16-bit current input.      |
| `coeff0`       | `logic signed [15:0]` | Coefficient for current sample.   |

### Outputs
| Port            | Width / Type          | Description           |
|-----------------|-----------------------|-----------------------|
| `output_sample` | `logic signed [15:0]` | Output filtered sample.|
"""

# Correct, spec-faithful RTL — declares exactly the real ports, no `logic` port.
_FIR_RTL = """module fir_filter (
    input  logic clk,
    input  logic reset,
    input  logic signed [15:0] input_sample,
    input  logic signed [15:0] coeff0,
    output logic signed [15:0] output_sample
);
endmodule
"""


def _run_cli(tmp_path, rtl, prompt, rid=None, strict=True, context=None):
    rp = tmp_path / "c.sv"
    pp = tmp_path / "p.md"
    rp.write_text(rtl)
    pp.write_text(prompt)
    cmd = [sys.executable, str(PROG), "--prompt", str(pp), "--rtl", str(rp)]
    if rid is not None:
        cmd += ["--id", rid]
    if strict:
        cmd += ["--strict"]
    for i, ctx in enumerate(context or []):
        cp = tmp_path / f"ctx{i}.sv"
        cp.write_text(ctx)
        cmd += ["--context", str(cp)]
    return subprocess.run(cmd, capture_output=True, text=True)


# ── unit: `_table_ports` never harvests an SV keyword as a port name ──────────
def test_table_ports_excludes_sv_keyword_logic():
    """The phantom 'logic' (and any other reserved keyword) is NOT harvested as
    a port name from the TYPE column."""
    tp = M._table_ports(_FIR_PROMPT)
    assert "logic" not in tp, f"phantom 'logic' still harvested: {tp}"
    for kw in ("wire", "reg", "bit", "signed", "unsigned",
               "input", "output", "inout"):
        assert kw not in tp


def test_sv_port_keywords_constant_exists():
    """The canonical exclusion set is a single named frozenset reused by the
    header parser and the table extractor (no divergent re-invented list)."""
    assert "logic" in M._SV_PORT_KEYWORDS
    assert {"input", "output", "inout", "wire", "reg",
            "logic", "bit", "signed", "unsigned"} <= set(M._SV_PORT_KEYWORDS)


# ── POSITIVE: the FIR_0001 shape now passes (FAILS on shipped v1.1.29) ────────
def test_fir_type_column_table_no_phantom_logic(tmp_path):
    """A `| `clk` | `logic` | ... |` Type-column port table + RTL declaring the
    real ports → rc=0, no phantom 'logic' MISSING-PORT. This FAILS on shipped
    v1.1.29 (rc=1, phantom 'logic') and PASSES on the patched gate."""
    r = _run_cli(tmp_path, _FIR_RTL, _FIR_PROMPT, strict=True)
    assert r.returncode == 0, (
        "phantom 'logic' MISSING-PORT still blocks the FIR Type-column table\n"
        + r.stdout + r.stderr)
    assert "'logic'" not in r.stdout


def test_fir_real_artifact_path():
    """If the real FIR_0001 artifacts are present in the run tree, the exact
    failing invocation must now be conformant (skipped when absent)."""
    fir = require_repo("benchmark_external/cvdp/run_v0352_cleanroom_20260614/"
                       "converge1129/work/cvdp_copilot_FIR_0001")
    spec = fir / "spec.md"
    rtl = fir / "rtl" / "fir_filter.sv"
    if not (spec.is_file() and rtl.is_file()):
        pytest.skip("FIR_0001 artifacts not present")
    r = subprocess.run(
        [sys.executable, str(PROG), "--strict",
         "--prompt", str(spec), "--rtl", str(rtl)],
        capture_output=True, text=True)
    assert r.returncode == 0, r.stdout + r.stderr


# ── §4.05 NO-LEAK: a GENUINE missing port STILL hard-blocks ──────────────────
def test_noleak_genuine_missing_normal_port(tmp_path):
    """A normal-identifier port named in a DIRECTION table that the RTL OMITS is
    a genuine missing port → STILL rc=1 MISSING-PORT on the patched gate. The
    keyword exclusion must not wave it through."""
    prompt = (
        "## Inputs\n"
        "| Port      | Direction | Description |\n"
        "|-----------|-----------|-------------|\n"
        "| `clk`     | input     | clock       |\n"
        "| `data_in` | input     | data        |\n\n"
        "## Outputs\n"
        "| Port       | Direction | Description |\n"
        "|------------|-----------|-------------|\n"
        "| `data_out` | output    | result      |\n")
    rtl = "module foo (input logic clk, input logic data_in); endmodule\n"
    r = _run_cli(tmp_path, rtl, prompt, strict=True)
    assert r.returncode == 1, "genuine missing 'data_out' was waved through!"
    assert "MISSING-PORT" in r.stdout and "data_out" in r.stdout


def test_noleak_keyword_substring_port_harvested(tmp_path):
    """A real port whose identifier CONTAINS a reserved keyword as a SUBSTRING
    (`logic_en`, `reg_file_addr`, `wire_sel`) is a distinct whole token: it must
    STILL be harvested. When the RTL declares all of them → rc=0; when one is
    OMITTED → it STILL hard-blocks (proving the exclusion did not drop it)."""
    prompt = (
        "## Inputs\n"
        "| Port            | Direction | Type    | Description |\n"
        "|-----------------|-----------|---------|-------------|\n"
        "| `logic_en`      | input     | `logic` | enable      |\n"
        "| `reg_file_addr` | input     | `logic` | address     |\n"
        "| `wire_sel`      | input     | `logic` | select      |\n")
    # harvested whole-token, none dropped, none phantom-flagged when all present
    tp = M._table_ports(prompt)
    assert tp.get("logic_en") == "input"
    assert tp.get("reg_file_addr") == "input"
    assert tp.get("wire_sel") == "input"
    assert "logic" not in tp  # the bare Type-column keyword is still excluded
    full_rtl = ("module bar (input logic logic_en, input logic reg_file_addr, "
                "input logic wire_sel); endmodule\n")
    r_full = _run_cli(tmp_path, full_rtl, prompt, strict=True)
    assert r_full.returncode == 0, r_full.stdout + r_full.stderr
    # omit reg_file_addr → the keyword-substring port STILL hard-blocks
    missing_rtl = ("module bar (input logic logic_en, "
                   "input logic wire_sel); endmodule\n")
    r_miss = _run_cli(tmp_path, missing_rtl, prompt, strict=True)
    assert r_miss.returncode == 1, "keyword-substring port was masked!"
    assert "reg_file_addr" in r_miss.stdout



# ── Step-2.7 no-leak: a CAPITALIZED identifier (`Reg`/`Logic`/`Wire`) is a LEGAL
# distinct SV port name, NOT a reserved keyword — the case-SENSITIVE exclusion
# must keep it harvested so a genuine missing such port still hard-blocks. ──
_CAPVAR_PROMPT = """# Spec

| Signal | Direction | Type |
|--------|-----------|------|
| `Reg`  | output    | logic |
| `clk`  | input     | logic |
"""
_CAPVAR_RTL = "module top (\n    input clk\n);\nendmodule\n"


def test_noleak_capitalized_keyword_port_still_blocks(tmp_path):
    """`Reg` (capital) is a legal port identifier, NOT the reserved `reg`; a
    direction-ful missing `Reg` must STILL hard-block (rc=1) — the keyword
    exclusion is case-SENSITIVE so it never masks a capitalized real port."""
    r = _run_cli(tmp_path, _CAPVAR_RTL, _CAPVAR_PROMPT, rid="cvdp_copilot_reg_0001")
    assert r.returncode == 1, (
        "a capitalized legal identifier `Reg` declared output and omitted by the "
        f"RTL must remain block-eligible\n{r.stdout}{r.stderr}")
    assert "Reg" in r.stdout


def test_capitalized_keyword_variants_harvested_unit():
    assert "Reg" in M._table_ports("| `Reg` | output | r |\n")
    assert "Logic" in M._table_ports("| `Logic` | input | l |\n")
    assert "Wire" in M._table_ports("| `Wire` | input | w |\n")
    # lowercase reserved keyword still excluded
    assert "logic" not in M._table_ports("| `clk` | `logic` | desc |\n")

if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))
