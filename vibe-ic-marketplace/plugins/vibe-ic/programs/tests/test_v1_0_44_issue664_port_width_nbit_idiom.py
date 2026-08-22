"""Regression for ORGANIC #664 — Phase-1 port-table walkers lose structured
bus WIDTH (msb/lsb/bits) when the Width column uses the `<N>-bit` / `N-bit` /
bracketed-symbolic idiom.

現象 (round-4 v1.0.42 6-IC clean-room): an external-interface port table
declares port widths with a compound width-spec cell — `1-bit` / `8-bit` /
`N-bit` (number-or-identifier + `-bit`), a bracketed `[WIDTH-1:0]` / `[31:0]`
cell sitting alone, or a bracket embedded in prose like
`N-bit([size-1:0], parameter size 預設 32)` — rather than a bare integer.

The structured 4-col grid walker (_RE_L1_L9_RST_IFACE_4COL, whose width
sub-pattern _V1_6_423_WIDTH_CELL_PERMISSIVE only accepted
`\\d{1,4}|*|IDENT(±d)|(variable)|-|empty`) matched ZERO rows for such a
table, so every multi-bit port fell through to the width-less #627 backtick
walker (`backticked_interface_v455`) and landed with width=None / msb=None /
lsb=None / bits=None in BOTH L1.pin_table and L9.top_ports — a latent
bus-mis-sizing for any consumer that trusts L9.top_ports[].width.

Fix (chip-AGNOSTIC, two structural changes in
phase1_doc_one_shot_runner.py):
  (1) _V1_6_423_WIDTH_CELL_PERMISSIVE also accepts `<N>-bit` / `N-bit` /
      `<IDENT>-bit`, a leading bracketed width `[M:L]` / `[WIDTH-1:0]`, and a
      cell that merely CONTAINS a `[...:...]` bracket inside prose — so the
      whole row is no longer dropped from the structured walker.
  (2) _parse_port_width recognises the `<N>-bit` idiom: a leading integer +
      `-bit` → (N, N-1, 0, None); a symbolic `N-bit([expr:lsb], ...)` keeps
      the bracket-search fallback that yields width_symbolic.
  The 4COL emit path now hands the RAW width cell to _add_pin (which calls
  _parse_port_width) so msb/lsb/bits / width_symbolic populate L1.pin_table
  and cascade to L9.top_ports.

NEGATIVE no-leak (load-bearing — this RELAXES a structural row-regex):
  (a) #627's positive case still holds: the leading name-cell token is the
      port; width/parameter tokens in later cells are NOT promoted as ports
      (covered by test_v1_0_25_issue627_*; re-asserted here for the same
      shape via the L1 pin_table path);
  (b) a bare `N-bit` (non-numeric, no bracket) stays width-symbolic-or-None,
      never a fabricated integer;
  (c) a genuine ID/position second column (`Bits` 7:0 register-map row) is
      NOT swept up as a port-width table by this walker;
  (d) the `-` / `*` / `(variable)` placeholders still resolve to None width.

chip-AGNOSTIC: pure structural grammar (number / identifier / `-bit` suffix /
bracket); NO chip / vendor / SKU literal — proven on BOTH an English-header
and a CJK-header table.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import phase1_doc_one_shot_runner as R  # noqa: E402

_GEN_DIR = Path("phase1") / "generated_docs"


def _run_l1(tmp_path: Path, extracted: dict) -> dict:
    """Drive gen_l1_datasheet and return the written L1_DATASHEET dict."""
    (tmp_path / _GEN_DIR).mkdir(parents=True, exist_ok=True)
    R.gen_l1_datasheet(tmp_path, extracted)
    return json.loads(
        (tmp_path / _GEN_DIR / "L1_DATASHEET.json").read_text())


def _by_name(l1: dict) -> dict:
    return {p["name"]: p for p in l1.get("pin_table", [])}


# ── (0) unit: the parser recognises the `<N>-bit` idiom ──────────────────────

@pytest.mark.parametrize("cell,expect", [
    ("8-bit", (8, 7, 0, None)),
    ("1-bit", (1, 0, 0, None)),
    ("32-bit", (32, 31, 0, None)),
    ("<8-bit>", (8, 7, 0, None)),
    ("8-bit data bus", (8, 7, 0, None)),
    ("[31:0]", (32, 31, 0, None)),
    ("[WIDTH-1:0]", (None, None, 0, "WIDTH-1:0")),
    ("N-bit(`[size-1:0]`, parameter `size` 預設 32)", (None, None, 0, "size-1:0")),
])
def test_parse_port_width_nbit_and_bracket_idioms(cell, expect):
    assert R._parse_port_width(cell) == expect


def test_parse_port_width_bare_symbolic_nbit_is_none_NOLEAK():
    """A bare `N-bit` (non-numeric, NO bracket) must NOT fabricate an
    integer width — it stays unresolved (None,None,None,None)."""
    assert R._parse_port_width("N-bit") == (None, None, None, None)


@pytest.mark.parametrize("cell", ["-", "*", "(variable)", "variable", ""])
def test_parse_port_width_placeholders_still_none_NOLEAK(cell):
    assert R._parse_port_width(cell) == (None, None, None, None)


# ── (1) the fix: English-header table → typed width in L1.pin_table ──────────

ENGLISH_TABLE = """## External Interface

| signal | width | direction | description |
|--------|-------|-----------|-------------|
| data | 8-bit | input | data bus |
| addr | [WIDTH-1:0] | input | address bus |
| q | [31:0] | output | result bus |
| en | 1 | input | enable |
"""


def test_english_header_nbit_and_bracket_widths_land_typed(tmp_path: Path):
    l1 = _run_l1(tmp_path, {"L3_external_interface.md": ENGLISH_TABLE})
    pins = _by_name(l1)
    for nm in ("data", "addr", "q", "en"):
        assert nm in pins, f"port {nm!r} dropped from L1.pin_table: {list(pins)}"
    # `8-bit` resolves to a concrete 8-bit bus
    assert pins["data"]["width"] == 8
    assert pins["data"]["msb"] == 7 and pins["data"]["lsb"] == 0
    # `[31:0]` resolves to 32
    assert pins["q"]["width"] == 32
    assert pins["q"]["msb"] == 31 and pins["q"]["lsb"] == 0
    # `[WIDTH-1:0]` parametric → width_symbolic preserved (no int fabricated)
    assert pins["addr"].get("width_symbolic") == "WIDTH-1:0"
    assert pins["addr"].get("width") in (None, "[WIDTH-1:0]")
    # bare numeric still works
    assert pins["en"]["width"] == 1


# ── (2) CJK-header table (chip-AGNOSTIC across header language) ───────────────

CJK_TABLE = """## 外部介面

| 訊號名 | 寬度 | 方向 | 描述 |
|--------|------|------|------|
| `clk` | 1-bit | input | 時脈 |
| `rst` | 1-bit | input | 重置 |
| `x` | N-bit(`[size-1:0]`, parameter `size` 預設 32) | input | 被乘數 |
| `y` | N-bit(`[size-1:0]`, parameter `size` 預設 32) | input | 乘數 |
| `p` | [63:0] | output | 乘積 |
"""


def test_cjk_header_symbolic_and_bracket_widths(tmp_path: Path):
    l1 = _run_l1(tmp_path, {"L3_external_interface.md": CJK_TABLE})
    pins = _by_name(l1)
    for nm in ("clk", "rst", "x", "y", "p"):
        assert nm in pins, f"port {nm!r} dropped: {list(pins)}"
    # single-bit control
    assert pins["clk"]["width"] == 1
    # parametric datapath bus → symbolic preserved
    assert pins["x"].get("width_symbolic") == "size-1:0"
    assert pins["y"].get("width_symbolic") == "size-1:0"
    # concrete output bus
    assert pins["p"]["width"] == 64
    assert pins["p"]["msb"] == 63 and pins["p"]["lsb"] == 0
    # NEGATIVE no-leak (#627): the width-cell `size` parameter token is NEVER
    # promoted as a separate port.
    assert "size" not in pins, f"width-cell parameter promoted as a port: {list(pins)}"


# ── (3) NEGATIVE no-leak: register-map ID column is not a port-width table ───

def test_register_map_bits_column_not_swept_as_ports_NOLEAK(tmp_path: Path):
    """A register-map table whose 2nd column is a position/ID field
    (`Bits` = 7:0) and whose 3rd column is an access mode (`rw`, not a
    direction word) must NOT be harvested as a port-width interface table."""
    doc = """## Register Map

| Field | Bits | Access |
|-------|------|--------|
| `cfg` | 7:0 | rw |
| `mode` | 15:8 | rw |
"""
    l1 = _run_l1(tmp_path, {"REGS.md": doc})
    pins = _by_name(l1)
    # `cfg`/`mode` are register fields, not top-level ports — they have no
    # input/output/inout direction cell so the 4COL walker must not emit them.
    assert "cfg" not in pins and "mode" not in pins, (
        f"register-map fields leaked as ports: {list(pins)}")


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-q"]))
