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


# ---------------------------------------------------------------------------
# WIRING (Defect 1b): the DERIVED pin_order.cfg must actually reach OpenROAD.
#
# The gate above only DISCLOSES a wrong-side placement. The corrective half is
# step_pnr deriving a pin_order.cfg from the L-doc table and feeding it to the
# ORGANIC #650 `set_io_pin_constraint` path. That derived cfg is written to the
# canonical PnR output dir (`phase3/stage3/pnr/`), which is NOT one of the
# project-supplied locations `_v1_0_38_find_pin_order_cfg` scans
# (openlane/, pnr/, constraints/, project root) — so without the last-resort
# fallback the file is written and never read, and the corrective half is dead
# code while every test above still passes.
# ---------------------------------------------------------------------------

import re as _re  # noqa: E402

import phase3_one_shot_runner as _p3  # noqa: E402


def _emit_derived_cfg(project: Path) -> Path:
    """Run the REAL emitter step_pnr calls.

    (The first cut of this file re-implemented the derivation inline, so a
    mutation of the shipped emitter changed nothing here — the classic
    vacuous control. Everything below now exercises
    `_p3._emit_ldoc_pin_order_cfg`.)
    """
    out_dir = project / "phase3" / "stage3" / "pnr"
    out_dir.mkdir(parents=True, exist_ok=True)
    _p3._emit_ldoc_pin_order_cfg(project, out_dir)
    return out_dir / "pin_order.cfg"


def test_derived_pin_order_cfg_is_discovered(tmp_path):
    """FIXED direction: the cfg derived into phase3/stage3/pnr/ is found."""
    _write_docs(tmp_path, _L9_MD)
    assert psc._load_pad_side_table(tmp_path), "L9 table must parse"
    cfg = _emit_derived_cfg(tmp_path)
    assert cfg.is_file()
    assert _p3._v1_0_38_find_pin_order_cfg(tmp_path) == cfg


def test_derived_pin_order_cfg_reaches_openroad(tmp_path):
    """FIXED direction: the derived cfg becomes set_io_pin_constraint TCL,
    with each L-doc edge mapped to the matching OpenROAD region."""
    _write_docs(tmp_path, _L9_MD)
    _emit_derived_cfg(tmp_path)
    bare = "place_pins -hor_layers M3 -ver_layers M2"
    tcl, note = _p3._v1_0_38_pin_placement_block(tmp_path, bare)
    assert "set_io_pin_constraint" in tcl
    assert "pin_order.cfg ingested" in note
    # Each cfg entry is resolved against the design's own BTerm names and the
    # matched LITERAL names reach `-pin_names`, so the entry->region binding
    # is asserted on the emitted resolve + report pair.
    # clk genuinely belongs on East -> OpenROAD region "right".
    assert "PIN_ORDER_CONSTRAINT_APPLIED: clk -> right:" in tcl
    # rst on South -> "bottom"; p/y on West -> "left"; x bus on North -> "top".
    assert "PIN_ORDER_CONSTRAINT_APPLIED: rst -> bottom:" in tcl
    assert "PIN_ORDER_CONSTRAINT_APPLIED: p -> left:" in tcl
    assert "PIN_ORDER_CONSTRAINT_APPLIED: x\\[.*\\] -> top:" in tcl
    # DEFECT direction: the bussed North entry must NOT be handed to
    # `-pin_names` as a raw regex. That is what OpenROAD rejected with
    # `[ERROR PPL-0061] Pins {x\[.*\]} ... were not found`, after which the
    # surrounding catch demoted it to a NONFATAL note and place_pins put the
    # whole bus on the wrong edge — while every scalar entry in the same cfg
    # was honored. Measured on spm/sky130A: 32 x-bits on E instead of N.
    assert not _re.search(r"-pin_names \{x\\\[\.\*\\\]\}", tcl)
    assert "set _poc_pins [vibeic_pin_names_matching {x\\[.*\\]}]" in tcl
    # The bare auto-assign must still follow, for pins the cfg does not name.
    assert bare in tcl


def test_no_derived_cfg_keeps_bare_auto_assign(tmp_path):
    """DEFECT direction / no-op guard: a project with NO L-doc table and no
    derived cfg keeps the legacy bare place_pins, byte-for-byte."""
    _emit_derived_cfg(tmp_path)          # no docs -> must write nothing
    assert not (tmp_path / "phase3" / "stage3" / "pnr" /
                "pin_order.cfg").exists()
    bare = "place_pins -hor_layers M3 -ver_layers M2"
    tcl, note = _p3._v1_0_38_pin_placement_block(tmp_path, bare)
    assert tcl == bare
    assert note == ""
    assert "set_io_pin_constraint" not in tcl


def test_project_supplied_cfg_wins_over_derived(tmp_path):
    """Precedence: a project-supplied cfg must OUTRANK the derived one, so the
    fallback can never hijack an explicit override."""
    _write_docs(tmp_path, _L9_MD)
    _emit_derived_cfg(tmp_path)
    supplied = tmp_path / "openlane" / "pin_order.cfg"
    supplied.parent.mkdir(parents=True, exist_ok=True)
    supplied.write_text("#N\nclk\n", encoding="utf-8")
    assert _p3._v1_0_38_find_pin_order_cfg(tmp_path) == supplied


# ---------------------------------------------------------------------------
# FRONT B — the pattern rewrite false-positived on a CONFORMING design.
#
# `_pattern_to_regex` rewrote ANY bracketed index to `\[\d+\]`, including an
# explicit single-bit constraint. A pad table that splits a bus across two
# edges (routine on a real pad ring) therefore made every bit match BOTH
# edges' patterns; the later dict key overwrote expected_sides for all of
# them and the gate FAILed a design that was placed exactly as declared.
# The derived pin_order.cfg carried the same rewrite, so the CORRECTIVE half
# would have pinned the whole bus to one edge.
# ---------------------------------------------------------------------------

_SPLIT_BUS_MD = """\
### Pad ring

| Edge | Signals |
|------|---------|
| North (N) | `data[0]`, `data[1]` |
| South (S) | `data[2]`, `data[3]` |
"""

_SPLIT_RANGE_MD = """\
### Pad ring

| Edge | Signals |
|------|---------|
| North (N) | `data[7:0]` |
| South (S) | `data[15:8]` |
"""


def _split_bus_def(n_north: int, n_south: int) -> str:
    pins = {}
    for i in range(n_north):
        pins[f"data[{i}]"] = (20000 + i * 1000, 92600)          # North
    for j in range(n_south):
        pins[f"data[{n_north + j}]"] = (20000 + j * 1000, 400)  # South
    return _make_def(pins)


def test_split_bus_single_bit_table_passes_a_conforming_layout(tmp_path):
    """The skeptic's exact reproduction: data[0],data[1] North /
    data[2],data[3] South, DEF placing them EXACTLY as declared.

    MUTATION THIS CATCHES: dropping the explicit-numeric-index branch of
    `_index_regex` (i.e. restoring `\\[\\d+\\]` for every index) -> every bit
    matches both edges and this conforming design is reported FAIL.
    """
    def_path = _write_def(tmp_path, _split_bus_def(2, 2))
    _write_docs(tmp_path, _SPLIT_BUS_MD)

    result = psc.check(tmp_path, def_path)

    assert result["verdict"] == "PASS", (
        f"a design that obeys the document must not FAIL: {result['note']}\n"
        f"wrong={result['wrong_side_pins']}")


def test_split_bus_single_bit_table_still_catches_a_real_violation(tmp_path):
    """Control: swap two bits and the gate must FAIL, naming them."""
    pins = {"data[0]": (20000, 92600), "data[1]": (21000, 92600),
            "data[2]": (22000, 92600),      # declared South, placed North
            "data[3]": (23000, 400)}
    def_path = _write_def(tmp_path, _make_def(pins))
    _write_docs(tmp_path, _SPLIT_BUS_MD)

    result = psc.check(tmp_path, def_path)
    assert result["verdict"] == "FAIL"
    assert set(result["wrong_side_pins"]) == {"data[2]"}


def test_split_bus_numeric_range_table_passes_a_conforming_layout(tmp_path):
    """Same defect in RANGE form: data[7:0] North / data[15:8] South."""
    def_path = _write_def(tmp_path, _split_bus_def(8, 8))
    _write_docs(tmp_path, _SPLIT_RANGE_MD)

    result = psc.check(tmp_path, def_path)
    assert result["verdict"] == "PASS", (
        f"{result['note']}\nwrong={result['wrong_side_pins']}")


def test_split_bus_numeric_range_still_catches_a_real_violation(tmp_path):
    def_path = _write_def(tmp_path, _split_bus_def(9, 7))  # data[8] on North
    _write_docs(tmp_path, _SPLIT_RANGE_MD)

    result = psc.check(tmp_path, def_path)
    assert result["verdict"] == "FAIL"
    assert "data[8]" in result["wrong_side_pins"]


def test_pattern_to_regex_index_semantics():
    """The rewrite rules, pinned."""
    assert psc._pattern_to_regex("data[0]").match("data[0]")
    assert not psc._pattern_to_regex("data[0]").match("data[1]")
    assert psc._pattern_to_regex("data[7:0]").match("data[7]")
    assert not psc._pattern_to_regex("data[7:0]").match("data[8]")
    # symbolic width is not knowable from the document -> any index
    assert psc._pattern_to_regex("x[size-1:0]").match("x[31]")
    assert psc._pattern_to_regex("x[N-1:0]").match("x[0]")
    # plain names and globs unchanged
    assert psc._pattern_to_regex("rst").match("rst")
    assert not psc._pattern_to_regex("rst").match("rst_n")
    assert psc._pattern_to_regex("dat.*").match("dat_valid")


def test_pin_order_cfg_tokens_do_not_widen_a_single_bit():
    """The CORRECTIVE half must constrain exactly what the document says.

    MUTATION THIS CATCHES: dropping the explicit-index branch of
    `pin_order_cfg_tokens` -> `data[0]` becomes `data\\[.*\\]` and OpenROAD
    pins the WHOLE bus to that edge.
    """
    assert psc.pin_order_cfg_tokens("data[0]") == [r"data\[0\]"]
    assert psc.pin_order_cfg_tokens("data[3:0]") == [
        r"data\[0\]", r"data\[1\]", r"data\[2\]", r"data\[3\]"]
    assert psc.pin_order_cfg_tokens("x[size-1:0]") == [r"x\[.*\]"]
    assert psc.pin_order_cfg_tokens("rst") == ["rst"]


def test_derived_cfg_keeps_a_split_bus_split(tmp_path):
    """End-to-end on the derived cfg: the two edges must NOT both claim the
    whole bus."""
    _write_docs(tmp_path, _SPLIT_BUS_MD)
    cfg = _emit_derived_cfg(tmp_path)
    text = cfg.read_text()
    sections = _p3._v1_0_38_parse_pin_order_cfg(text)
    by_edge = {e: p for e, p in sections}
    assert by_edge["N"] == [r"data\[0\]", r"data\[1\]"]
    assert by_edge["S"] == [r"data\[2\]", r"data\[3\]"]
    assert r"data\[.*\]" not in text


# ---------------------------------------------------------------------------
# An AMBIGUOUS table is a document defect, not a layout violation.
# ---------------------------------------------------------------------------

_AMBIGUOUS_MD = """\
### Pad ring

| Edge | Signals |
|------|---------|
| North (N) | `data[size-1:0]` |
| South (S) | `data[2]` |
"""


def test_ambiguous_table_is_reported_as_ambiguous(tmp_path):
    """Two edges claim data[2]. Letting the last dict key win manufactures a
    wrong-side verdict against a design that obeyed one of the two readings.

    MUTATION THIS CATCHES: removing the ambiguity detection -> the check
    silently picks one edge and FAILs the pins placed per the other.
    """
    def_path = _write_def(tmp_path, _split_bus_def(2, 2))
    _write_docs(tmp_path, _AMBIGUOUS_MD)

    result = psc.check(tmp_path, def_path)
    assert result["verdict"] == "ERROR", result
    assert "AMBIGUOUS" in result["note"]
    assert "data[2]" in result["note"]
    assert result["wrong_side_pins"] == {}


# ---------------------------------------------------------------------------
# DEF auto-discovery: the comment said "deepest stage", the code was
# alphabetical.
# ---------------------------------------------------------------------------

def test_def_discovery_prefers_the_routed_pnr_def(tmp_path):
    """MUTATION THIS CATCHES: `sorted(rglob("*.def"))[-1]`, whose comment
    claimed "deepest stage" but is alphabetical — it picks
    `phase3/stage4/scratch.def` over `phase3/stage3/pnr/routed.def`."""
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    routed = pnr / "routed.def"
    routed.write_text(_make_def(_CORRECT_SIDE_PINS))
    stray = tmp_path / "phase3" / "stage4" / "scratch.def"
    stray.parent.mkdir(parents=True)
    stray.write_text(_make_def(_ALL_EAST_PINS))

    assert psc._discover_def(tmp_path) == routed
    _write_docs(tmp_path, _L9_MD)
    assert psc.check(tmp_path)["verdict"] == "PASS", (
        "the check must grade the ROUTED DEF, not an alphabetically-later "
        "scratch file from an earlier stage")


def test_def_discovery_falls_back_to_newest(tmp_path):
    """No canonical routed.def: newest DEF in the canonical PnR dir wins."""
    import os
    import time
    pnr = tmp_path / "phase3" / "stage3" / "pnr"
    pnr.mkdir(parents=True)
    old = pnr / "zzz_old.def"
    old.write_text(_make_def(_ALL_EAST_PINS))
    new = pnr / "aaa_new.def"
    new.write_text(_make_def(_CORRECT_SIDE_PINS))
    now = time.time()
    os.utime(old, (now - 500, now - 500))
    os.utime(new, (now, now))
    assert psc._discover_def(tmp_path) == new


# ---------------------------------------------------------------------------
# The derived cfg must not go stale.
# ---------------------------------------------------------------------------

def test_derived_cfg_is_regenerated_when_the_table_changes(tmp_path):
    """MUTATION THIS CATCHES: the write-once `if not cfg.exists()` guard,
    which pins every later run to the FIRST run's L-doc table."""
    _write_docs(tmp_path, _SPLIT_BUS_MD)
    cfg = _emit_derived_cfg(tmp_path)
    assert r"data\[0\]" in cfg.read_text()

    _write_docs(tmp_path, _SPLIT_RANGE_MD)          # the document changed
    cfg = _emit_derived_cfg(tmp_path)
    text = cfg.read_text()
    assert r"data\[8\]" in text, "the cfg is stale — it still holds the old table"
    assert r"data\[15\]" in text


def test_derived_cfg_is_removed_when_the_table_is_withdrawn(tmp_path):
    _write_docs(tmp_path, _SPLIT_BUS_MD)
    cfg = _emit_derived_cfg(tmp_path)
    assert cfg.is_file()

    (tmp_path / "input" / "docs" / "L9_constraints.md").write_text("# L9\n")
    _emit_derived_cfg(tmp_path)
    assert not cfg.exists(), (
        "a derived constraint must not outlive the document it derives from")


def test_a_human_cfg_in_the_pnr_dir_is_never_overwritten_or_deleted(tmp_path):
    """The regenerate/remove logic is keyed on our own marker, so a file a
    human dropped in the PnR dir is left alone in both directions."""
    out_dir = tmp_path / "phase3" / "stage3" / "pnr"
    out_dir.mkdir(parents=True)
    human = out_dir / "pin_order.cfg"
    human.write_text("#N\nclk\n", encoding="utf-8")

    _write_docs(tmp_path, _SPLIT_BUS_MD)
    _p3._emit_ldoc_pin_order_cfg(tmp_path, out_dir)
    assert human.read_text() == "#N\nclk\n"

    (tmp_path / "input" / "docs" / "L9_constraints.md").write_text("# L9\n")
    _p3._emit_ldoc_pin_order_cfg(tmp_path, out_dir)
    assert human.is_file() and human.read_text() == "#N\nclk\n"
