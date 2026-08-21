#!/usr/bin/env python3
"""Tests for analog_hardmacro_check.py — hardmacro deliverables gate.

NOTE ON A CORRECTED TEST (see `test_pass_complete_hardmacro` below).
`test_pass_complete_hardmacro` used to write FOUR BYTES — `b"\\x00\\x01\\x02\\x03"`
— as `ldo.gds` and assert the gate reported the hardmacro COMPLETE. That
asserted the defect: the gate's only GDS predicate was `exists() and size != 0`,
so any non-empty file was credited as a layout, and the test locked that in.
It now builds a minimal but REAL GDS stream (one BOUNDARY record) — the same
thing it always meant by "complete hardmacro" — and a sibling test asserts the
four-byte file FAILs. The assertion was not relaxed; the fixture was made
honest.
"""
from __future__ import annotations

import json
import struct
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / "analog_hardmacro_check.py"

# The deterministic-stub marker recognised by _analog_stub_marker.is_stub_text.
_STUB_MARKER = "// deterministic_stub extraction_strategy=deterministic_stub\n"


def _rec(rec_type: int, payload: bytes = b"") -> bytes:
    return struct.pack(">HH", 4 + len(payload), rec_type) + payload


def build_real_gds(width_dbu: int = 5000, height_dbu: int = 4000) -> bytes:
    """A minimal but structurally valid GDSII stream carrying ONE BOUNDARY
    record — i.e. a file that actually contains a layout."""
    out = _rec(0x0002, struct.pack(">h", 600))              # HEADER
    out += _rec(0x0102, struct.pack(">12h", *([0] * 12)))   # BGNLIB
    out += _rec(0x0206, b"TOP\x00")                          # LIBNAME
    # UNITS: 1 dbu = 1 nm
    out += _rec(0x0305, b"\x3e\x41\x89\x37\x4b\xc6\xa7\xf0"
                        b"\x39\x44\xb8\x2f\xa0\x9b\x5a\x54")
    out += _rec(0x0502, struct.pack(">12h", *([0] * 12)))   # BGNSTR
    out += _rec(0x0606, b"TOP\x00")                          # STRNAME
    out += _rec(0x0800)                                      # BOUNDARY
    out += _rec(0x0D02, struct.pack(">h", 1))                # LAYER
    out += _rec(0x0E02, struct.pack(">h", 0))                # DATATYPE
    pts = [(0, 0), (width_dbu, 0), (width_dbu, height_dbu),
           (0, height_dbu), (0, 0)]
    out += _rec(0x1003, b"".join(struct.pack(">ii", x, y) for x, y in pts))
    out += _rec(0x1100)                                      # ENDEL
    out += _rec(0x0700)                                      # ENDSTR
    out += _rec(0x0400)                                      # ENDLIB
    return out


def _run(tmp_path: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(tmp_path), "--json", str(tmp_path / "report.json")],
        capture_output=True, text=True,
    )


def _load_report(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "report.json").read_text())


def test_skip_no_analog_blocks(tmp_path):
    r = _run(tmp_path)
    assert r.returncode == 2      # #521 — VACUOUS (rc 2): the gate examined nothing.
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is True
    assert rpt["summary"]["skipped"] is True
    assert rpt["summary"]["reason"] == "no_analog_blocks"


#: What the packaged circuit contains. Nothing writes `design_content` into a
#: LEF, a Liberty, a GDS or a behavioural Verilog, so the whole answer is the
#: corner artefact's — the A4 gate of record's own subject. Every PASSING
#: fixture below now carries it, because this gate stopped signing off a macro
#: digital PnR will instantiate and integration STA will close on when nothing
#: on the tree names the circuit it models; a fixture that omitted it would be
#: asserting that silence still signs off. The FAILING fixtures are untouched:
#: each fails for its own deliverable reason and the question is asked LAST.
DESIGN_BOUND = "structure_and_geometry"


def _seed_corner(tmp_path: Path, block: str,
                 design_content=DESIGN_BOUND) -> None:
    ad = tmp_path / "phase3" / "analog" / block
    ad.mkdir(parents=True, exist_ok=True)
    doc = {"block": block, "_provenance": "real_ngspice",
           "corners": [{"name": "tt_27c_1v8", "simulator_run": True}]}
    if design_content is not None:
        doc["design_content"] = design_content
    (ad / "corner_results.json").write_text(json.dumps(doc))


def _seed_hardmacro(tmp_path: Path, block: str, gds_bytes: bytes,
                    stub: bool = False, design_content=DESIGN_BOUND) -> Path:
    ad = tmp_path / "phase3" / "analog" / block
    ad.mkdir(parents=True, exist_ok=True)
    (ad / "spec.json").write_text("{}")
    _seed_corner(tmp_path, block, design_content)
    hm = tmp_path / "phase3" / "analog" / "hardmacro" / block
    hm.mkdir(parents=True, exist_ok=True)
    if gds_bytes is not None:
        (hm / f"{block}.gds").write_bytes(gds_bytes)
    marker = _STUB_MARKER if stub else ""
    (hm / f"{block}.lef").write_text(
        marker + f"MACRO {block}\n  PIN vout\n  END vout\nEND {block}\n")
    (hm / f"{block}.lib").write_text(
        marker + f'library ({block}_lib) {{\n  cell ({block}) {{}}\n}}\n')
    (hm / f"{block}.v").write_text(
        marker + f"module {block}(input vin, output vout);\nendmodule\n")
    return hm


def test_pass_complete_hardmacro(tmp_path):
    """A hardmacro whose .gds is a REAL layout passes. (Corrected fixture: this
    test used to hand the gate four bytes of non-GDS and assert COMPLETE.)"""
    _seed_hardmacro(tmp_path, "ldo", build_real_gds())
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is True
    assert rpt["summary"]["complete"] == 1
    assert rpt["summary"]["design_bound_blocks"] == ["ldo"]


# ── the step's DECLARED gate answers the same question as its siblings ─────
# `flow/phase1_phase2_phase3.yaml` declares THIS program for A8;
# `analog_liberty_nonzero_delay_check`, which reads the record and grades the
# `.lib` INSIDE the package this gate signs off, appears nowhere in that YAML.
# Measured, before these three: over one complete package on three trees
# differing only in the recorded `design_content`, this gate and
# `analog_a8_hardmacro_gen_check` both answered PASS / PASS / PASS while the
# Liberty gate answered PASS / PASS_STRUCTURE_ONLY / FAIL. The cross-gate
# agreement lives in `test_two_gates_over_one_artefact_cannot_disagree`; these
# are this gate's own three answers.

def test_a_package_that_names_no_circuit_does_not_sign_off(tmp_path):
    """Every deliverable is present and real — including a GDS with genuine
    geometry — so the only thing this can fail on is the certification."""
    _seed_hardmacro(tmp_path, "ldo", build_real_gds(), design_content=None)
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout
    rpt = _load_report(tmp_path)
    assert "HARDMACRO_SUBJECT_UNDECLARED" in {f["rule"]
                                              for f in rpt["findings"]}
    assert rpt["summary"]["undisclosed_blocks"] == ["ldo"]


def test_a_disclosed_library_default_signs_off_in_its_own_tier(tmp_path):
    """Only silence costs. A package whose corner artefact records a library
    default still signs off — in the structure-only tier, never as a
    design-bound pass — because failing an honest ceiling teaches the next run
    to stop being honest."""
    _seed_hardmacro(tmp_path, "ldo", build_real_gds(),
                    design_content="structure_only")
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    rpt = _load_report(tmp_path)
    assert rpt["summary"]["verdict_tier"] == "PASS_STRUCTURE_ONLY"
    assert rpt["summary"]["structure_only_blocks"] == ["ldo"]
    assert rpt["summary"]["design_bound_blocks"] == []
    assert any(l.lstrip().startswith("STRUCTURE_ONLY:")
               for l in (r.stdout + r.stderr).splitlines()), r.stdout + r.stderr


def test_an_incomplete_package_is_still_incomplete(tmp_path):
    """ORDERING CONTROL. A package with no behavioural view is diagnosed as
    that, even on a tree that also says nothing about its subject."""
    hm = _seed_hardmacro(tmp_path, "ldo", build_real_gds(),
                         design_content=None)
    (hm / "ldo.v").unlink()
    r = _run(tmp_path)
    assert r.returncode == 1
    rules = {f["rule"] for f in _load_report(tmp_path)["findings"]}
    assert "HARDMACRO_INCOMPLETE" in rules, rules
    assert "HARDMACRO_SUBJECT_UNDECLARED" not in rules, rules


def test_fail_gds_without_geometry(tmp_path):
    """THE discriminator. Four bytes of non-GDS at hardmacro/<b>/<b>.gds, with
    a perfectly valid LEF/LIB/V, must NOT be signed off as a hardmacro."""
    _seed_hardmacro(tmp_path, "ldo", b"\x00\x01\x02\x03")
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is False
    rules = {f["rule"] for f in rpt["findings"]}
    assert "HARDMACRO_GDS_NO_GEOMETRY" in rules, rpt["findings"]


def test_fail_padded_garbage_gds(tmp_path):
    """The measured shape: 500 bytes of deterministic noise defeats every
    size floor in the analog gate family; only the geometry walk sees it."""
    state, buf = 12345, bytearray()
    for _ in range(500):
        state = (1103515245 * state + 12345) & 0x7FFFFFFF
        buf.append((state >> 16) & 0xFF)
    _seed_hardmacro(tmp_path, "ldo", bytes(buf))
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout
    rpt = _load_report(tmp_path)
    rules = {f["rule"] for f in rpt["findings"]}
    assert "HARDMACRO_GDS_NO_GEOMETRY" in rules, rpt["findings"]


def test_fail_structurally_valid_but_empty_gds_library(tmp_path):
    """HEADER..ENDLIB with no BOUNDARY/PATH/SREF/AREF/BOX: parses as GDS,
    contains no layout. Must FAIL."""
    empty = (_rec(0x0002, struct.pack(">h", 600))
             + _rec(0x0102, struct.pack(">12h", *([0] * 12)))
             + _rec(0x0206, b"TOP\x00")
             + _rec(0x0502, struct.pack(">12h", *([0] * 12)))
             + _rec(0x0606, b"TOP\x00")
             + _rec(0x0700) + _rec(0x0400))
    _seed_hardmacro(tmp_path, "ldo", empty)
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout
    rules = {f["rule"] for f in _load_report(tmp_path)["findings"]}
    assert "HARDMACRO_GDS_NO_GEOMETRY" in rules


def test_guard_deterministic_stub_still_passes_without_any_gds(tmp_path):
    """Direction-1 guard: the PASS_WITH_STUB tier must survive. The A7 stub
    deliberately ships no .gds; the new geometry predicate sits AFTER the stub
    short-circuit and must never see it."""
    _seed_hardmacro(tmp_path, "ldo", None, stub=True)
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is True
    assert rpt["summary"]["verdict_tier"] == "PASS_WITH_STUB"
    assert any(f["rule"] == "HARDMACRO_STUB_ACCEPTED"
               for f in rpt["findings"]), rpt["findings"]


def test_guard_empty_gds_file_is_still_reported_as_missing(tmp_path):
    """Direction-1 guard: a zero-byte .gds keeps its original MISSING framing
    rather than being re-classified by the new predicate."""
    _seed_hardmacro(tmp_path, "ldo", b"")
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = _load_report(tmp_path)
    incomplete = [f for f in rpt["findings"]
                  if f["rule"] == "HARDMACRO_INCOMPLETE"]
    assert incomplete and "ldo.gds" in incomplete[0]["message"]
    assert not any(f["rule"] == "HARDMACRO_GDS_NO_GEOMETRY"
                   for f in rpt["findings"])


def test_fail_missing_files(tmp_path):
    (tmp_path / "phase3" / "analog" / "ldo").mkdir(parents=True)
    (tmp_path / "phase3" / "analog" / "ldo" / "spec.json").write_text("{}")
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is False
    errors = [f for f in rpt["findings"] if f["severity"] == "ERROR"]
    assert any("HARDMACRO_INCOMPLETE" in f["rule"] for f in errors)


def test_fail_lef_no_macro(tmp_path):
    bl = tmp_path / "phase3" / "analog" / "analog_block_list.json"
    bl.parent.mkdir(parents=True)
    bl.write_text(json.dumps(["osc"]))
    hm = tmp_path / "phase3" / "analog" / "hardmacro" / "osc"
    hm.mkdir(parents=True)
    (hm / "osc.gds").write_bytes(b"\x00\x01")
    (hm / "osc.lef").write_text("VERSION 5.7;\nEND LIBRARY\n")
    (hm / "osc.lib").write_text('library (osc_lib) {\n  cell (osc) {}\n}\n')
    (hm / "osc.v").write_text("module osc(input en, output clk);\nendmodule\n")
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is False
    errors = [f for f in rpt["findings"] if f["severity"] == "ERROR"]
    assert any("HARDMACRO_LEF_NO_MACRO" in f["rule"] for f in errors)


def test_exit2_bad_dir(tmp_path):
    r = subprocess.run(
        [sys.executable, str(PROG), str(tmp_path / "nonexistent")],
        capture_output=True, text=True,
    )
    assert r.returncode == 2


# ── .v / .lib content predicates: a DECLARATION, not a substring ──────────
# These two were `"module" not in text` and `"cell" not in text.lower()`.
# Measured: a Verilog file whose only occurrence of the word sat inside a `//`
# comment was signed off HARDMACRO_COMPLETE, and a Liberty file containing
# only the word "cancelled" satisfied the cell predicate.

def _seed_with(tmp_path: Path, block: str, verilog: str, liberty: str) -> None:
    ad = tmp_path / "phase3" / "analog" / block
    ad.mkdir(parents=True, exist_ok=True)
    (ad / "spec.json").write_text("{}")
    _seed_corner(tmp_path, block)
    hm = tmp_path / "phase3" / "analog" / "hardmacro" / block
    hm.mkdir(parents=True, exist_ok=True)
    (hm / f"{block}.gds").write_bytes(build_real_gds())
    (hm / f"{block}.lef").write_text(
        f"MACRO {block}\n  PIN vout\n  END vout\nEND {block}\n")
    (hm / f"{block}.lib").write_text(liberty)
    (hm / f"{block}.v").write_text(verilog)


_GOOD_LIB = 'library (ldo_lib) {\n  cell (ldo) {}\n}\n'
_GOOD_V = "module ldo(input vin, output vout);\nendmodule\n"


def test_fail_verilog_module_only_inside_a_comment(tmp_path):
    """THE discriminator. A behavioural view of the hardmacro: the .v is what
    digital PnR instantiates, so a file that declares nothing is not a
    deliverable — no matter which words its comments contain."""
    _seed_with(
        tmp_path, "ldo",
        verilog=("// this is a submodule placeholder comment mentioning "
                 "module keyword\n"
                 "/* another module reference, also a comment */\n"
                 "wire vdd;\nwire vss;\nassign vdd = 1'b1;\n"),
        liberty=_GOOD_LIB)
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is False
    rules = {f["rule"] for f in rpt["findings"]}
    assert "HARDMACRO_V_NO_MODULE" in rules, rpt["findings"]
    assert "HARDMACRO_COMPLETE" not in rules, rpt["findings"]


def test_fail_liberty_cell_substring_inside_another_word(tmp_path):
    """THE discriminator for the Liberty half: 'cancelled' contains 'cell'."""
    _seed_with(
        tmp_path, "ldo",
        verilog=_GOOD_V,
        liberty="/* the release was cancelled, excellent, no timing here */\n")
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout
    rules = {f["rule"] for f in _load_report(tmp_path)["findings"]}
    assert "HARDMACRO_LIB_NO_CELL" in rules


@pytest.mark.parametrize("verilog", [
    "module ldo(input vin, output vout);\nendmodule\n",
    "`timescale 1ns/1ps\nmodule ldo (vin, vout);\ninput vin;\nendmodule\n",
    "// wrapper\n(* keep *) module ldo #(parameter W=1) (input a);\n"
    "endmodule\n",
    "/* header */\n\nmodule\tldo(input a);\nendmodule\n",
])
def test_guard_real_verilog_module_declarations_still_pass(tmp_path, verilog):
    """Direction-1 guard: every ordinary spelling of a module header — with a
    timescale directive, an attribute, a parameter list, a tab — must keep
    passing."""
    _seed_with(tmp_path, "ldo", verilog=verilog, liberty=_GOOD_LIB)
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout


def test_fail_liberty_with_only_a_test_cell_group(tmp_path):
    """`test_cell` also contains the substring 'cell' but is not the timing
    cell digital PnR links against. The predicate must require the `cell`
    keyword itself, not a word that ends in it."""
    _seed_with(
        tmp_path, "ldo",
        verilog=_GOOD_V,
        liberty='library (ldo_lib) {\n  test_cell (ldo_tc) {}\n}\n')
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout
    rules = {f["rule"] for f in _load_report(tmp_path)["findings"]}
    assert "HARDMACRO_LIB_NO_CELL" in rules


@pytest.mark.parametrize("liberty", [
    'library (ldo_lib) {\n  cell (ldo) {}\n}\n',
    'library(ldo_lib){\ncell(ldo){\narea : 100.0;\n}\n}\n',
    'library (ldo_lib) {\n  /* comment */\n  cell ("ldo") {\n  }\n}\n',
    'library (ldo_lib) {\n  CELL (ldo) {}\n}\n',
    'library (ldo_lib) {\n  cell ("1v8_ldo") {}\n}\n',
    'library (ldo_lib) {\n  test_cell (tc) {}\n  cell (ldo) {}\n}\n',
])
def test_guard_real_liberty_cell_groups_still_pass(tmp_path, liberty):
    """Direction-1 guard: the Liberty group header with/without spaces, quoted,
    or upper-cased must keep passing."""
    _seed_with(tmp_path, "ldo", verilog=_GOOD_V, liberty=liberty)
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout


def test_guard_stub_hardmacro_still_bypasses_content_predicates(tmp_path):
    """Direction-1 guard: the deterministic-stub short-circuit sits ahead of
    both predicates, so PASS_WITH_STUB is unaffected by tightening them."""
    _seed_hardmacro(tmp_path, "ldo", None, stub=True)
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout
    assert _load_report(tmp_path)["summary"]["verdict_tier"] == "PASS_WITH_STUB"
