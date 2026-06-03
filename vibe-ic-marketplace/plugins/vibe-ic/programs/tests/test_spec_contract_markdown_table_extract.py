"""Unit tests for the markdown-table port parser + broadened reset detection in
_specrtl_common.extract_spec_contract.

Anchored to ORGANIC-20260527-spec-conformance-extractor-coverage:
  • A datasheet that declares its interface ONLY as a markdown PIN-CONFIGURATION
    table (| Signal | Dir | Width | ...) used to extract 0 ports, so port
    conformance was silently skipped. The new md-table parser fixes that.
  • Reset semantics were keyword-only; the broadened _detect_reset adds
    active-low inference from a *_n-shaped name and a small phrase set
    (POR / edge-of-nRST / "registered to the clock"), kept conservative.

The three required shapes are covered:
  PASS  — a real datasheet pin-table parses the exact ports + reset.
  FAIL  — the parsed table drives a real port-width-mismatch end-to-end
          (previously a silent 0-port skip).
  MISSING/honesty — a generic report/regmap table (no direction column) yields
          0 ports (never invents ports), and a partial pin-table emits the INFO
          advisory note instead of a silent skip.
"""
import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _specrtl_common import (  # noqa: E402
    _detect_reset, _parse_md_table_ports, extract_spec_contract)

SCRIPT = Path(__file__).resolve().parent.parent / 'spec_conformance_check.py'
assert SCRIPT.exists()

_FIXTURES = Path(__file__).resolve().parent / 'fixtures' / 'real_benchmark'


def load_real_fixture(name: str) -> str:
    """Read a chip-AGNOSTIC real-benchmark fixture slice (path-based to avoid the
    two-conftest import ambiguity in the merged test tree)."""
    return (_FIXTURES / name).read_text()


# ---------------------------------------------------------------------------
# PASS: real datasheet pin-configuration TABLE -> exact ports + reset
# ---------------------------------------------------------------------------
def test_real_datasheet_pin_table_extracts_ports():
    src = load_real_fixture('datasheet_pin_table_interface.md')
    c = extract_spec_contract(src, confirm=False)
    assert c.source == 'md-table'
    got = {(p.name, p.direction, p.width) for p in c.ports}
    assert got == {
        ('clk', 'input', 1),
        ('rst_n', 'input', 1),
        ('data_in', 'input', 16),     # [15:0] -> 16
        ('valid_in', 'input', 1),
        ('data_out', 'output', 16),
        ('valid_out', 'output', 1),
    }, got
    # internal underscore must survive markdown-emphasis stripping
    assert any(p.name == 'rst_n' for p in c.ports)
    # reset broadened: "registered to the clock" -> synchronous;
    # active-low inferred from the rst_n name AND the explicit prose word.
    assert c.reset_mode == 'synchronous'
    assert c.reset_polarity == 'active-low'


def test_md_table_msb_lsb_and_plain_widths():
    spec = (
        "| Pin   | I/O    | [msb:lsb] |\n"
        "|-------|--------|-----------|\n"
        "| a     | input  | [7:0]     |\n"
        "| b     | input  | 4         |\n"
        "| y     | output | 1         |\n"
    )
    c = extract_spec_contract(spec, confirm=False)
    assert c.source == 'md-table'
    assert {(p.name, p.direction, p.width) for p in c.ports} == {
        ('a', 'input', 8), ('b', 'input', 4), ('y', 'output', 1)}


def test_md_table_short_dir_tokens_and_backticks():
    # `in`/`out`/`io` short tokens + backtick-quoted cells.
    spec = (
        "| Signal | Dir | Width |\n"
        "|--------|-----|-------|\n"
        "| `clk`  | in  | 1     |\n"
        "| `bus`  | io  | 8     |\n"
        "| `done` | out | 1     |\n"
    )
    c = extract_spec_contract(spec, confirm=False)
    assert {(p.name, p.direction, p.width) for p in c.ports} == {
        ('clk', 'input', 1), ('bus', 'inout', 8), ('done', 'output', 1)}


# ---------------------------------------------------------------------------
# FAIL: the parsed table drives a real conformance error end-to-end
# (previously a silent 0-port skip because the table was unparsed).
# ---------------------------------------------------------------------------
def _run(tmp_path, spec_text, sv):
    spec = tmp_path / 'spec.md'
    spec.write_text(spec_text)
    rtl = tmp_path / 'dut.sv'
    rtl.write_text(sv)
    jf = tmp_path / 'out.json'
    res = subprocess.run(
        [sys.executable, str(SCRIPT), '--spec', str(spec),
         '--json', str(jf), str(rtl)],
        capture_output=True, text=True)
    findings = json.loads(jf.read_text()) if jf.exists() else []
    return res, {f['rule'] for f in findings}


_PIN_TABLE_SPEC = (
    "# Pin Configuration\n"
    "| Signal | Direction | Width |\n"
    "|--------|-----------|-------|\n"
    "| clk    | input     | 1     |\n"
    "| d      | input     | 8     |\n"
    "| q      | output    | 8     |\n"
)


def test_md_table_drives_width_mismatch_fail(tmp_path):
    # RTL drops d to 4 bits — the table-extracted contract must catch it.
    rtl = (
        "module m(input clk, input [3:0] d, output reg [7:0] q);\n"
        "  always @(posedge clk) q <= d;\n"
        "endmodule\n"
    )
    res, rules = _run(tmp_path, _PIN_TABLE_SPEC, rtl)
    assert res.returncode == 1
    assert 'port-width-mismatch' in rules


def test_md_table_matching_rtl_passes(tmp_path):
    rtl = (
        "module m(input clk, input [7:0] d, output reg [7:0] q);\n"
        "  always @(posedge clk) q <= d;\n"
        "endmodule\n"
    )
    res, rules = _run(tmp_path, _PIN_TABLE_SPEC, rtl)
    assert res.returncode == 0
    assert 'port-width-mismatch' not in rules
    assert 'port-missing' not in rules and 'port-extra' not in rules


# ---------------------------------------------------------------------------
# MISSING-DATA / honesty: do not invent ports; surface a partial-parse note.
# ---------------------------------------------------------------------------
def test_generic_report_table_yields_no_ports():
    # A report table that happens to have a "Protocol"/"Name" column but NO
    # direction column with direction-valued cells must extract 0 ports —
    # never fabricate ports from a non-interface table.
    report = (
        "| Protocol | Authored RTL | synth cells |\n"
        "|----------|--------------|-------------|\n"
        "| spi      | yes          | 1200        |\n"
        "| i2c      | yes          | 900         |\n"
    )
    c = extract_spec_contract(report, confirm=False)
    assert c.ports == []
    assert c.source == 'none'
    ports, notes = _parse_md_table_ports(report)
    assert ports == [] and notes == []


def test_regmap_table_with_name_col_but_no_direction_yields_no_ports():
    # A register-map table (Address|Name|Access|Description) has a Name column
    # but the "Access" column holds RW/RO, not input/output -> 0 ports.
    regmap = (
        "| Address | Name        | Access | Description     |\n"
        "|---------|-------------|--------|-----------------|\n"
        "| 0x300   | CTL_STATUS  | RW     | status register |\n"
        "| 0x304   | CTL_INT_EN  | RW     | interrupt enable|\n"
    )
    ports, notes = _parse_md_table_ports(regmap)
    assert ports == [], [(p.name, p.direction) for p in ports]


def test_partial_pin_table_emits_info_note():
    # One row's name cell is prose ("status word") -> unparseable; the table is
    # still detected, so the extractor surfaces an advisory note rather than
    # silently dropping it.
    partial = (
        "| Signal      | Dir    | Width |\n"
        "|-------------|--------|-------|\n"
        "| clk         | input  | 1     |\n"
        "| data        | input  | 8     |\n"
        "| status word | output | 8     |\n"
        "| q           | output | 8     |\n"
    )
    c = extract_spec_contract(partial, confirm=False)
    assert c.source == 'md-table'
    assert {p.name for p in c.ports} == {'clk', 'data', 'q'}   # 'status word' dropped
    assert c.notes, "a partial pin-table must surface an advisory note"
    assert 'table' in c.notes[0].lower()


# ---------------------------------------------------------------------------
# Reset broadening: phrase set + active-low name inference (conservative).
# ---------------------------------------------------------------------------
def test_reset_active_low_inferred_from_name():
    # No explicit "active-low" word; the rst_n name implies active-low.
    m, p, sig = _detect_reset("rst_n is a synchronous reset.")
    assert m == 'synchronous'
    assert p == 'active-low'
    assert sig == 'rst_n'


def test_reset_por_phrase_is_asynchronous():
    m, p, sig = _detect_reset(
        "The POR holds the core in reset until the supply is stable.")
    assert m == 'asynchronous'


def test_reset_edge_of_nrst_phrase():
    m, p, sig = _detect_reset("The flop clears on the rising edge of nRST.")
    assert m == 'asynchronous'
    assert p == 'active-low'   # nrst name -> active-low


def test_reset_registered_to_clock_is_synchronous():
    m, p, sig = _detect_reset(
        "The reset is registered to the clock and is active-low.")
    assert m == 'synchronous'
    assert p == 'active-low'


def test_reset_explicit_word_not_overridden_by_name():
    # An explicit "active-high" word must win even if the name is *_n-shaped
    # (conservative: name inference only fills a gap, never overrides prose).
    m, p, sig = _detect_reset("rst_n is an active-high asynchronous reset.")
    assert m == 'asynchronous'
    assert p == 'active-high'


def test_reset_plain_mention_stays_unclassified():
    # A bare "there is a reset" gives no confident mode/polarity (no fabrication).
    m, p, sig = _detect_reset("There is a reset.")
    assert m is None
    assert p is None
