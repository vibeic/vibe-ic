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
    assert r.returncode == 0
    rpt = _load_report(tmp_path)
    assert rpt["passed"] is True
    assert rpt["summary"]["skipped"] is True
    assert rpt["summary"]["reason"] == "no_analog_blocks"


def _seed_hardmacro(tmp_path: Path, block: str, gds_bytes: bytes,
                    stub: bool = False) -> Path:
    ad = tmp_path / "phase3" / "analog" / block
    ad.mkdir(parents=True, exist_ok=True)
    (ad / "spec.json").write_text("{}")
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
