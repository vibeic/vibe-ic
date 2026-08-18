"""Tests for gds_topcell_name_check.py — GDSII top-cell-name equality.

Covers the three mandated cases:
  * PASS — the named top cell IS defined and is the hierarchy root.
  * real FAIL — the named top cell is absent from the GDS.
  * missing-data honesty — missing / empty file FAILs honestly (no vacuous PASS).
Plus the sub-cell WARNING and a real-corpus PASS when available.
"""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import gds_topcell_name_check as g  # noqa: E402
from _hostpaths import corpus_path  # noqa: E402


# --------------------------------------------------------------------------
# Minimal GDSII record builder (big-endian: len[2] type[1] dtype[1] body)
# --------------------------------------------------------------------------
def _rec(rtype: int, dtype: int, body: bytes = b"") -> bytes:
    if len(body) % 2:  # GDSII pads strings/records to even length
        body += b"\x00"
    rlen = 4 + len(body)
    return struct.pack(">H", rlen) + bytes([rtype, dtype]) + body


def _strname(name: str) -> bytes:
    return _rec(0x06, 0x06, name.encode("ascii"))


def _sname(name: str) -> bytes:
    return _rec(0x12, 0x06, name.encode("ascii"))


def _header() -> bytes:
    return _rec(0x00, 0x02, struct.pack(">H", 600))  # HEADER, version 600


def _make_gds(defined, refs=()) -> bytes:
    out = _header()
    for d in defined:
        out += _strname(d)
    for r in refs:
        out += _sname(r)
    return out


def _write(tmp_path: Path, data: bytes, name="design.gds") -> Path:
    p = tmp_path / name
    p.write_bytes(data)
    return p


# --------------------------------------------------------------------------
# PASS — named top cell defined and is the hierarchy root.
# --------------------------------------------------------------------------
def test_pass_named_topcell_is_root(tmp_path):
    # chip_top references two leaf cells; chip_top itself is never referenced.
    gds = _make_gds(defined=["chip_top", "leaf_a", "leaf_b"],
                    refs=["leaf_a", "leaf_b"])
    p = _write(tmp_path, gds)
    rc = g.main(["--gds-file", str(p), "--top-name", "chip_top",
                 "--json", str(tmp_path / "r.json")])
    assert rc == 0
    rep = json.loads((tmp_path / "r.json").read_text())
    assert rep["summary"]["pass"] is True
    assert rep["summary"]["named_cell_defined"] is True
    assert rep["summary"]["top_cell_candidates"] == ["chip_top"]
    cats = {f["category"] for f in rep["findings"]}
    assert "TOPCELL_MATCH" in cats


# --------------------------------------------------------------------------
# real FAIL — named top cell absent from the GDS.
# --------------------------------------------------------------------------
def test_fail_named_topcell_absent(tmp_path):
    gds = _make_gds(defined=["some_other_top", "leaf"], refs=["leaf"])
    p = _write(tmp_path, gds)
    rc = g.main(["--gds-file", str(p), "--top-name", "chip_top",
                 "--json", str(tmp_path / "r.json")])
    assert rc == 1
    rep = json.loads((tmp_path / "r.json").read_text())
    assert rep["summary"]["pass"] is False
    assert rep["summary"]["named_cell_defined"] is False
    cats = {f["category"] for f in rep["findings"]}
    assert "TOPCELL_NAME_MISMATCH" in cats


# --------------------------------------------------------------------------
# WARNING — named cell exists but is a referenced sub-cell, not the root.
# --------------------------------------------------------------------------
def test_warn_named_is_subcell(tmp_path):
    gds = _make_gds(defined=["chip_top", "core"], refs=["core"])
    p = _write(tmp_path, gds)
    # Ask for "core" which IS defined but is referenced by chip_top.
    rc = g.main(["--gds-file", str(p), "--top-name", "core",
                 "--json", str(tmp_path / "r.json")])
    assert rc == 0  # present => PASS, but flagged
    rep = json.loads((tmp_path / "r.json").read_text())
    assert rep["summary"]["pass"] is True
    assert rep["summary"]["named_cell_referenced"] is True
    cats = {f["category"] for f in rep["findings"]}
    assert "TOPNAME_IS_SUBCELL" in cats
    assert "chip_top" in rep["summary"]["top_cell_candidates"]


# --------------------------------------------------------------------------
# missing-data honesty — missing file & empty file both FAIL (never vacuous).
# --------------------------------------------------------------------------
def test_missing_file_fails_honestly(tmp_path):
    rc = g.main(["--gds-file", str(tmp_path / "nope.gds"),
                 "--top-name", "chip_top",
                 "--json", str(tmp_path / "r.json")])
    assert rc == 1
    rep = json.loads((tmp_path / "r.json").read_text())
    assert rep["summary"]["pass"] is False
    assert {f["category"] for f in rep["findings"]} == {"MISSING_GDS"}


def test_empty_file_fails_honestly(tmp_path):
    p = _write(tmp_path, b"")
    rc = g.main(["--gds-file", str(p), "--top-name", "chip_top"])
    assert rc == 1


def test_no_structures_fails(tmp_path):
    # Valid header but zero STRNAME definitions.
    p = _write(tmp_path, _header())
    findings, stats = g.check_topcell(p, "chip_top")
    assert stats["structure_count"] == 0
    assert any(f.category == "NO_STRUCTURES" for f in findings)
    assert g.build_report(findings, stats, str(p))["summary"]["pass"] is False


def test_garbage_input_no_crash(tmp_path):
    p = _write(tmp_path, b"\xff\xff\x99\x99not a gds at all \x00\x01")
    rc = g.main(["--gds-file", str(p), "--top-name", "chip_top"])
    # Garbage => no structures parsed => honest FAIL, never a crash.
    assert rc == 1


# --------------------------------------------------------------------------
# Real-corpus PASS (skipped if the fixture GDS is not on this machine).
# --------------------------------------------------------------------------
_REAL_GDS = corpus_path("spm_benchmark_v0211/phase3/stage4/gds/chip_top.gds")


@pytest.mark.skipif(not _REAL_GDS.is_file(),
                    reason="real corpus GDS not present; set $VIBEIC_CORPUS_ROOT to the external benchmark corpus")
def test_real_corpus_chip_top_passes(tmp_path):
    rc = g.main(["--gds-file", str(_REAL_GDS), "--top-name", "chip_top",
                 "--json", str(tmp_path / "r.json")])
    assert rc == 0
    rep = json.loads((tmp_path / "r.json").read_text())
    assert rep["summary"]["top_cell_candidates"] == ["chip_top"]


@pytest.mark.skipif(not _REAL_GDS.is_file(),
                    reason="real corpus GDS not present; set $VIBEIC_CORPUS_ROOT to the external benchmark corpus")
def test_real_corpus_wrong_name_fails(tmp_path):
    rc = g.main(["--gds-file", str(_REAL_GDS), "--top-name", "not_the_top"])
    assert rc == 1
