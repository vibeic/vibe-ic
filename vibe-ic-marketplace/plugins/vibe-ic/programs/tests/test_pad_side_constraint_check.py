"""Bidirectional tests for pad_side_constraint_check.py (Defect 1).

DEFECT direction: a DEF with all pins on one side vs an L-doc table
  demanding four sides => gate FAILs and names the wrong-side pins.
FIXED  direction: a DEF whose pins match the declared sides => gate PASSes.
EXTRA cases:
  - no pad-side table => vacuous-pass, no crash.
  - bus-wildcard pattern (x[size-1:0] covering x[0..N-1]).
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

PROGS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROGS))

import pad_side_constraint_check as psc  # noqa: E402

# ---------------------------------------------------------------------------
# Minimal synthetic DEF helpers
# ---------------------------------------------------------------------------

_DIEAREA = "DIEAREA ( 0 0 ) ( 93000 93000 ) ;"


def _make_def(pins: dict) -> str:
    """Build a minimal DEF text.  pins = {name: (x, y)}."""
    lines = [
        "VERSION 5.8 ;",
        "DESIGN test ;",
        _DIEAREA,
        f"PINS {len(pins)} ;",
    ]
    for name, (x, y) in pins.items():
        lines += [
            f"    - {name} + NET {name} + DIRECTION INPUT + USE SIGNAL",
            "      + PORT",
            "        + LAYER met3 ( -400 -150 ) ( 400 150 )",
            f"        + PLACED ( {x} {y} ) N ;",
        ]
    lines += ["END PINS", "END DESIGN"]
    return "\n".join(lines)


# Die bounding box: (0,0)-(93000,93000)
# Edges (nearest edge test):
#   North  edge: y = 93000  → pins with y close to 93000
#   South  edge: y = 0      → pins with y close to 0
#   East   edge: x = 93000  → pins with x close to 93000
#   West   edge: x = 0      → pins with x close to 0
#
# Placing at x=92600 means d_east = 400 ≪ d_west / d_north / d_south → EAST.
_ALL_EAST_PINS = {
    "clk":  (92600, 22100),
    "rst":  (92600, 58820),
    "p":    (92600, 60180),
    "y":    (92600, 61540),
    "x[0]": (92600, 43860),
    "x[1]": (92600, 45220),
}

_CORRECT_SIDE_PINS = {
    # North (y near 93000)
    "x[0]": (46500, 92600),
    "x[1]": (48000, 92600),
    # South (y near 0)
    "rst":  (46500, 400),
    # East (x near 93000)
    "clk":  (92600, 22100),
    # West (x near 0)
    "p":    (400, 60180),
    "y":    (400, 61540),
}

_L3_MD = """\
## Physical Pad Placement

| Pad 邊 | 包含訊號 |
|--------|---------|
| **North (N)** | `x[size-1:0]`(整個 multiplicand bus,每位元一個 pad) |
| **South (S)** | `rst` |
| **East (E)** | `clk` |
| **West (W)** | `p`、`y`(輸出與序列輸入相鄰) |
"""

_L9_MD = """\
### 9.2.2 Pad 配置

| 邊 | 訊號 | 備註 |
|----|------|------|
| North (N) | `x[size-1:0]` 全部位元 | 北邊 pad 之間最小間距 0.1 µm |
| South (S) | `rst` | |
| East (E)  | `clk` | |
| West (W)  | `p`、`y` | |
"""


def _write_docs(project: Path, md_text: str, filename: str = "L9_constraints.md"):
    docs = project / "input" / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / filename).write_text(md_text, encoding="utf-8")


def _write_def(project: Path, def_text: str) -> Path:
    pnr = project / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True, exist_ok=True)
    p = pnr / "test.def"
    p.write_text(def_text)
    return p


# ---------------------------------------------------------------------------
# Helper: parse markdown table directly
# ---------------------------------------------------------------------------

def test_parse_markdown_table_l9(tmp_path):
    """parse_pad_table_from_markdown resolves N/S/E/W from L9 table."""
    table = psc._parse_pad_table_from_markdown(_L9_MD)
    assert table is not None
    assert "N" in table
    assert "S" in table
    assert "E" in table
    assert "W" in table
    assert any("x" in p for p in table["N"])
    assert "rst" in table["S"]
    assert "clk" in table["E"]


def test_parse_markdown_table_l3_zh(tmp_path):
    """parse_pad_table_from_markdown resolves N/S/E/W from L3 Traditional Chinese table."""
    table = psc._parse_pad_table_from_markdown(_L3_MD)
    assert table is not None
    assert set(table.keys()) == {"N", "S", "E", "W"}


# ---------------------------------------------------------------------------
# DEFECT direction: all pins on East side vs table demanding four sides
# ---------------------------------------------------------------------------

def test_defect_all_pins_east(tmp_path):
    """DEFECT: DEF has every pin on the East edge; L9 demands N/S/E/W → FAIL."""
    def_text = _make_def(_ALL_EAST_PINS)
    def_path = _write_def(tmp_path, def_text)
    _write_docs(tmp_path, _L9_MD)

    result = psc.check(tmp_path, def_path)

    assert result["verdict"] == "FAIL", f"Expected FAIL, got {result['verdict']}: {result['note']}"
    wrong = result["wrong_side_pins"]
    # clk should be East (correct), but rst should be South (wrong), p/y West (wrong),
    # x[0]/x[1] should be North (wrong) — they are all East
    assert "rst" in wrong, "rst must be flagged (placed East, expected South)"
    assert "p" in wrong, "p must be flagged (placed East, expected West)"
    assert "y" in wrong, "y must be flagged (placed East, expected West)"
    # x[0] and x[1] should be on North
    assert "x[0]" in wrong or "x[1]" in wrong, "x bits must be flagged (placed East, expected North)"
    # The note must name specific pins
    assert "rst" in result["note"], "note must name the wrong-side pin 'rst'"
    assert result["vacuous"] is False


def test_defect_names_pinsets_not_counts(tmp_path):
    """FAIL result lists pin NAME SETS (not just counts) for each side mismatch."""
    def_text = _make_def(_ALL_EAST_PINS)
    def_path = _write_def(tmp_path, def_text)
    _write_docs(tmp_path, _L9_MD)

    result = psc.check(tmp_path, def_path)
    assert result["verdict"] == "FAIL"
    # Each entry in wrong_side_pins must have 'actual' and 'expected' keys
    for name, info in result["wrong_side_pins"].items():
        assert "actual" in info
        assert "expected" in info
        assert info["actual"] in ("N", "S", "E", "W")
        assert info["expected"] in ("N", "S", "E", "W")


# ---------------------------------------------------------------------------
# FIXED direction: pins on correct sides => PASS
# ---------------------------------------------------------------------------

def test_fixed_correct_sides(tmp_path):
    """FIXED: DEF pins match L9 declared sides → PASS."""
    def_text = _make_def(_CORRECT_SIDE_PINS)
    def_path = _write_def(tmp_path, def_text)
    _write_docs(tmp_path, _L9_MD)

    result = psc.check(tmp_path, def_path)

    assert result["verdict"] == "PASS", (
        f"Expected PASS, got {result['verdict']}: {result['note']}\n"
        f"wrong_side_pins={result['wrong_side_pins']}")
    assert result["wrong_side_pins"] == {}
    assert result["vacuous"] is False


# ---------------------------------------------------------------------------
# VACUOUS PASS: no pad-side table in L docs
# ---------------------------------------------------------------------------

def test_no_pad_table_vacuous_pass(tmp_path):
    """No L-doc pad-side table → VACUOUS_PASS, no crash."""
    docs = tmp_path / "input" / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L9_constraints.md").write_text("# L9\n\n## 9.1 SDC\nNothing here.\n")

    def_text = _make_def(_ALL_EAST_PINS)
    def_path = _write_def(tmp_path, def_text)

    result = psc.check(tmp_path, def_path)

    assert result["verdict"] == "VACUOUS_PASS", (
        f"Expected VACUOUS_PASS, got {result['verdict']}")
    assert result["vacuous"] is True
    assert result["wrong_side_pins"] == {}


def test_no_docs_dir_vacuous_pass(tmp_path):
    """Missing input/docs directory → VACUOUS_PASS, no crash."""
    def_text = _make_def(_ALL_EAST_PINS)
    def_path = _write_def(tmp_path, def_text)
    result = psc.check(tmp_path, def_path)
    assert result["verdict"] == "VACUOUS_PASS"


# ---------------------------------------------------------------------------
# Bus wildcard: x[size-1:0] covers x[0..N-1]
# ---------------------------------------------------------------------------

def test_bus_wildcard_matches_indexed_pins(tmp_path):
    """Bus pattern x[size-1:0] (or x[.*]) must match x[0], x[1], ..., x[31]."""
    # Build a DEF with x[0..7] all on North (correct) plus other pins correct
    north_y = 92600
    east_x = 92600
    south_y = 400
    west_x = 400
    pins = {}
    for i in range(8):
        pins[f"x[{i}]"] = (46000 + i * 1000, north_y)
    pins["rst"] = (46500, south_y)
    pins["clk"] = (east_x, 22100)
    pins["p"] = (west_x, 60180)
    pins["y"] = (west_x, 61540)

    def_text = _make_def(pins)
    def_path = _write_def(tmp_path, def_text)
    _write_docs(tmp_path, _L9_MD)

    result = psc.check(tmp_path, def_path)
    assert result["verdict"] == "PASS", (
        f"Bus wildcard PASS failed: {result['note']}\n"
        f"wrong={result['wrong_side_pins']}")


def test_bus_wildcard_detects_wrong_side(tmp_path):
    """Bus pattern x[size-1:0] covers x[0..7]; placing them East → FAIL."""
    east_x = 92600
    pins = {}
    for i in range(8):
        pins[f"x[{i}]"] = (east_x, 20000 + i * 2000)  # all East → wrong
    pins["rst"] = (46500, 400)   # South → correct
    pins["clk"] = (east_x, 50000)  # East → correct
    pins["p"] = (400, 60180)    # West → correct
    pins["y"] = (400, 61540)    # West → correct

    def_text = _make_def(pins)
    def_path = _write_def(tmp_path, def_text)
    _write_docs(tmp_path, _L9_MD)

    result = psc.check(tmp_path, def_path)
    assert result["verdict"] == "FAIL"
    wrong_names = set(result["wrong_side_pins"].keys())
    for i in range(8):
        assert f"x[{i}]" in wrong_names, f"x[{i}] should be flagged"


# ---------------------------------------------------------------------------
# _side_of_pin helper unit tests
# ---------------------------------------------------------------------------

def test_side_of_pin_edges():
    die = (0, 0, 93000, 93000)
    assert psc._side_of_pin(92600, 46500, die) == "E"
    assert psc._side_of_pin(400, 46500, die) == "W"
    assert psc._side_of_pin(46500, 92600, die) == "N"
    assert psc._side_of_pin(46500, 400, die) == "S"


# ---------------------------------------------------------------------------
# CLI exit codes
# ---------------------------------------------------------------------------

def test_cli_fail_exit_code(tmp_path):
    """CLI returns exit code 1 on FAIL."""
    def_text = _make_def(_ALL_EAST_PINS)
    _write_def(tmp_path, def_text)
    _write_docs(tmp_path, _L9_MD)
    rc = psc.main([str(tmp_path)])
    assert rc == 1


def test_cli_pass_exit_code(tmp_path):
    """CLI returns exit code 0 on PASS."""
    def_text = _make_def(_CORRECT_SIDE_PINS)
    _write_def(tmp_path, def_text)
    _write_docs(tmp_path, _L9_MD)
    rc = psc.main([str(tmp_path)])
    assert rc == 0


def test_cli_vacuous_pass_exit_code(tmp_path):
    """CLI returns exit code 0 on VACUOUS_PASS."""
    def_text = _make_def(_ALL_EAST_PINS)
    _write_def(tmp_path, def_text)
    # no docs
    rc = psc.main([str(tmp_path)])
    assert rc == 0
