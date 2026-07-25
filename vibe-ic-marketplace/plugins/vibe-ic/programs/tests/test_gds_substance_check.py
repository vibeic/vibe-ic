"""tests/test_gds_substance_check.py — v1.0.0

NEGATIVE CONTROL for the gate. Every fabricated-artefact case below is
verified to PASS the *pre-fix* code path (`gds_size_check`, which is what
flow step 37 ran before this gate existed) and FAIL `gds_substance_check`.
A test that cannot fail against the old code is not a test, so the
`test_negative_control_*` cases assert both halves explicitly.

The fakes (all sized to clear gds_size_check's 100 KB constant):
  1. 86-byte HEADER+ENDLIB stub          — old: FAIL (TOO_SMALL)  new: FAIL
  2. 150 KB random bytes behind a HEADER — old: PASS              new: FAIL
  3. 150 KB zero-padded empty library    — old: PASS              new: FAIL
  4. 150 KB even-length junk, no ENDLIB  — old: PASS              new: FAIL
  5. 166 KB valid GDSII, 2600 squares    — old: PASS              new: FAIL
     on ONE layer                          (also passed checks A-C)

Cases 2-4 are the gate's reason to exist: `gds_size_check` reports
`pass: true, errors: 0, warnings: 0` for all three.

Case 5 is the reason check D (mask-stack floor) exists. It is the hardest
fake: structurally valid, has structures, elements and a LAYER, and carries
MORE elements than the design places instances — so checks A, B and C all
sign off. Its negative control runs the gate with `min_distinct_layers=0`,
which is literally the pre-floor code path, and asserts it passes there.
"""
from __future__ import annotations

import os
import struct
from pathlib import Path

import pytest

from programs.gds_substance_check import (
    audit_gds,
    parse_gds,
    read_def_component_count,
)
import programs.gds_size_check as gsc


# ---------------------------------------------------------------------------
# GDS builders
# ---------------------------------------------------------------------------
def _rec(rt: int, payload: bytes = b"") -> bytes:
    return struct.pack(">HH", 4 + len(payload), rt) + payload


_TS = struct.pack(">12h", 2026, 7, 25, 12, 0, 0, 2026, 7, 25, 12, 0, 0)


def _lib_prologue(libname: bytes = b"spm\x00") -> bytes:
    return (_rec(0x0002, struct.pack(">h", 600))
            + _rec(0x0102, _TS)
            + _rec(0x0206, libname)
            + _rec(0x0305, b"\x00" * 16))


def _real_gds(n_cells: int = 10, n_boundaries: int = 40) -> bytes:
    """A minimal but structurally honest GDS: cells with real geometry."""
    out = _lib_prologue()
    for i in range(n_cells):
        name = f"cell_{i}".encode()
        if len(name) % 2:
            name += b"\x00"
        out += _rec(0x0502, _TS) + _rec(0x0606, name)
        for j in range(n_boundaries):
            out += (_rec(0x0800)
                    + _rec(0x0D02, struct.pack(">h", (j % 5) + 1))
                    + _rec(0x0E02, struct.pack(">h", 0))
                    + _rec(0x1003, struct.pack(">8i", 0, 0, 100, 0,
                                               100, 100, 0, 100))
                    + _rec(0x1100))
        out += _rec(0x0700)
    return out + _rec(0x0400)


def _stub_86() -> bytes:
    """HEADER+BGNLIB+LIBNAME+UNITS+ENDLIB, zero structures, exactly 86 B."""
    for pad in range(60):
        name = b"spm" + b"_" * pad
        if len(name) % 2:
            name += b"\x00"
        blob = _lib_prologue(name) + _rec(0x0400)
        if len(blob) == 86:
            return blob
    raise AssertionError("could not build an 86-byte stub")


def _big_random(kb: int = 150) -> bytes:
    return _rec(0x0002, struct.pack(">h", 600)) + os.urandom(kb * 1024)


def _big_empty_library(kb: int = 150) -> bytes:
    body = _lib_prologue() + _rec(0x0400)
    return body + b"\x00" * (kb * 1024 - len(body))


def _big_even_junk(kb: int = 150) -> bytes:
    """Every record length even and in range, but the stream never ENDLIBs."""
    out = bytearray(_rec(0x0002, struct.pack(">h", 600)))
    i = 0
    while len(out) < kb * 1024:
        n = 4 + 2 * ((i % 40) + 1)
        out += struct.pack(">HH", n, 0x0800) + b"\xab" * (n - 4)
        i += 1
    return bytes(out)


def _categories(findings) -> set:
    return {f.category for f in findings}


# ---------------------------------------------------------------------------
# Happy path
# ---------------------------------------------------------------------------
def test_real_gds_passes() -> None:
    findings, st, _ = audit_gds(_real_gds(), None, 1.0)
    assert findings == []
    assert st.structures == 10
    assert st.elements == 400
    assert st.layers == [1, 2, 3, 4, 5]
    assert st.parsed_to_endlib and st.trailing_bytes == 0


def test_real_gds_meets_design_derived_floor() -> None:
    # 400 elements against 300 placed instances at 1.0 elem/instance.
    findings, _, floor = audit_gds(_real_gds(), 300, 1.0)
    assert findings == []
    assert floor["applied"] and floor["required_elements"] == 300


def test_floor_is_derived_not_hardcoded() -> None:
    """The floor tracks the design's own instance count, nothing else."""
    gds = _real_gds()                       # 400 elements
    assert audit_gds(gds, 300, 1.0)[0] == []
    findings, _, floor = audit_gds(gds, 5000, 1.0)
    assert "SUBSTANCE_BELOW_DESIGN_FLOOR" in _categories(findings)
    assert floor["required_elements"] == 5000


# ---------------------------------------------------------------------------
# NEGATIVE CONTROLS — must FAIL the new gate; cases 2-4 PASS the old one
# ---------------------------------------------------------------------------
# `expect_cats` is a SET, not a single category, because `_big_random` is
# built from os.urandom: which structural rule trips first depends on the
# bytes. Measured over 2000 draws — MALFORMED_RECORD 96.75%,
# TRUNCATED_RECORD 3.25% (a length field that happens to be even and in
# range but runs past EOF). Pinning the single category made this test flake
# ~1 run in 30. The guarantee the gate actually makes, and the one worth
# asserting, is that arbitrary junk trips SOME hard structural rule.
@pytest.mark.parametrize("name,blob,expect_cats", [
    ("stub_86", _stub_86(), {"NO_GEOMETRY"}),
    ("big_random", _big_random(), {"MALFORMED_RECORD", "TRUNCATED_RECORD"}),
    ("big_empty_library", _big_empty_library(), {"TRAILING_GARBAGE"}),
    ("big_even_junk", _big_even_junk(), {"NO_ENDLIB"}),
])
def test_negative_control_new_gate_fails(name, blob, expect_cats) -> None:
    findings, _, _ = audit_gds(blob, 1826, 1.0)
    assert findings, f"{name}: new gate must FAIL but returned no findings"
    assert _categories(findings) & expect_cats, (
        f"{name}: expected one of {expect_cats}, got {_categories(findings)}")
    assert all(f.severity == "ERROR" for f in findings), (
        f"{name}: every finding must be a hard ERROR, not a warning")


@pytest.mark.parametrize("name,blob", [
    ("big_random", _big_random()),
    ("big_empty_library", _big_empty_library()),
    ("big_even_junk", _big_even_junk()),
])
def test_negative_control_old_gate_passed_these(name, blob, tmp_path) -> None:
    """Pins the defect: gds_size_check signs off on all three fakes.

    If this ever starts failing, gds_size_check gained real structural
    checking and this gate's justification should be revisited.
    """
    p = tmp_path / f"{name}.gds"
    p.write_bytes(blob)
    findings, stats = gsc.audit_gds(p, min_size_kb=100.0)
    errors = [f for f in findings if f.severity == "ERROR"]
    assert errors == [], (
        f"{name}: expected the OLD gate to pass this fake, got {errors}")
    assert stats["file_size_bytes"] > 100 * 1024


def test_86_byte_stub_was_already_caught_by_size_gate(tmp_path) -> None:
    """Honest scoping: the 86-byte case was NOT the pre-existing hole."""
    p = tmp_path / "stub.gds"
    p.write_bytes(_stub_86())
    findings, _ = gsc.audit_gds(p, min_size_kb=100.0)
    assert "TOO_SMALL" in {f.category for f in findings}


# ---------------------------------------------------------------------------
# Structural edge cases
# ---------------------------------------------------------------------------
def test_truncated_record_fails() -> None:
    blob = _real_gds()[:-40]
    findings, _ = parse_gds(blob)
    assert _categories(findings) & {"TRUNCATED_RECORD", "NO_ENDLIB"}


def test_not_gdsii_first_record_fails() -> None:
    blob = _rec(0x0800) + _rec(0x0400)
    findings, _ = parse_gds(blob)
    assert "NOT_GDSII" in _categories(findings)


def test_too_short_fails() -> None:
    findings, _ = parse_gds(b"\x00\x06")
    assert "NOT_GDSII" in _categories(findings)


def test_unbalanced_structure_fails() -> None:
    blob = (_lib_prologue() + _rec(0x0502, _TS) + _rec(0x0606, b"c1\x00\x00")
            + _rec(0x0800) + _rec(0x0D02, struct.pack(">h", 1))
            + _rec(0x1100) + _rec(0x0400))          # BGNSTR without ENDSTR
    findings, _ = parse_gds(blob)
    assert "UNBALANCED_STRUCTURE" in _categories(findings)


def test_elements_without_layer_fails() -> None:
    blob = (_lib_prologue() + _rec(0x0502, _TS) + _rec(0x0606, b"c1\x00\x00")
            + _rec(0x0800) + _rec(0x1100) + _rec(0x0700) + _rec(0x0400))
    findings, _, _ = audit_gds(blob, None, 1.0)
    assert "NO_LAYERS" in _categories(findings)


# ---------------------------------------------------------------------------
# DEF instance count
# ---------------------------------------------------------------------------
def test_read_def_component_count(tmp_path: Path) -> None:
    d = tmp_path / "routed.def"
    d.write_text("VERSION 5.8 ;\nDESIGN spm ;\nCOMPONENTS 1826 ;\n"
                 "- inst1 CELL ;\nEND COMPONENTS\n")
    assert read_def_component_count(d) == 1826


def test_read_def_component_count_missing(tmp_path: Path) -> None:
    d = tmp_path / "routed.def"
    d.write_text("VERSION 5.8 ;\nDESIGN spm ;\n")
    assert read_def_component_count(d) is None
    assert read_def_component_count(tmp_path / "nope.def") is None


def test_no_def_skips_floor_but_keeps_structure_checks() -> None:
    findings, _, floor = audit_gds(_stub_86(), None, 1.0)
    assert floor["applied"] is False
    assert "NO_GEOMETRY" in _categories(findings)


# ---------------------------------------------------------------------------
# NEGATIVE CONTROL — the element-inflation fake (mask-stack floor, check D)
#
# Fake 5 defeats every earlier check by construction: it is a structurally
# valid GDSII, so the record walk is clean; it has a structure, elements and
# a LAYER, so the substance checks are clean; and it carries MORE elements
# than the design places instances, so the design-derived floor is clean.
# It is 166 KB, so gds_size_check signs off too. The only thing it does not
# have is a mask stack — every square is on layer 8.
# ---------------------------------------------------------------------------
def _inflated_single_layer(n_boundaries: int = 2600) -> bytes:
    """Valid GDSII padded to clear the element floor with one-layer filler."""
    out = _lib_prologue() + _rec(0x0502, _TS) + _rec(0x0606, b"spm\x00")
    for _ in range(n_boundaries):
        out += (_rec(0x0800)
                + _rec(0x0D02, struct.pack(">h", 8))
                + _rec(0x0E02, struct.pack(">h", 0))
                + _rec(0x1003, struct.pack(">10i", 0, 0, 10, 0,
                                           10, 10, 0, 10, 0, 0))
                + _rec(0x1100))
    return out + _rec(0x0700) + _rec(0x0400)


def test_negative_control_inflated_fake_passes_everything_else() -> None:
    """Pins the defect the mask-stack floor closes.

    `min_distinct_layers=0` disables check D, which is exactly the gate's
    behaviour before this floor existed. The fake must sign off cleanly
    there — otherwise the test below proves nothing.
    """
    blob = _inflated_single_layer()
    findings, st, floor = audit_gds(blob, 1826, 1.0, min_distinct_layers=0)
    assert findings == [], (
        f"pre-floor gate must PASS this fake, got {_categories(findings)}")
    assert st.parsed_to_endlib and st.trailing_bytes == 0
    assert floor["applied"] and st.elements >= floor["required_elements"]
    assert st.layers == [8]


def test_negative_control_inflated_fake_also_passed_the_size_gate(
        tmp_path: Path) -> None:
    blob = _inflated_single_layer()
    p = tmp_path / "inflated.gds"
    p.write_bytes(blob)
    findings, stats = gsc.audit_gds(p, min_size_kb=100.0)
    assert [f for f in findings if f.severity == "ERROR"] == []
    assert stats["file_size_bytes"] > 100 * 1024


def test_inflated_fake_fails_mask_stack_floor() -> None:
    findings, _, floor = audit_gds(_inflated_single_layer(), 1826, 1.0)
    assert "TOO_FEW_MASK_LAYERS" in _categories(findings)
    assert all(f.severity == "ERROR" for f in findings)
    assert floor["actual_distinct_layers"] == 1
    assert floor["min_distinct_layers"] == 4


def test_mask_stack_floor_does_not_fire_on_real_layouts() -> None:
    """_real_gds() draws 5 layers; the floor must stay silent."""
    findings, st, _ = audit_gds(_real_gds(), 300, 1.0)
    assert findings == []
    assert len(st.layers) >= 4


def test_no_layers_takes_precedence_over_too_few() -> None:
    """A geometry-without-LAYER file reports NO_LAYERS, not TOO_FEW."""
    blob = (_lib_prologue() + _rec(0x0502, _TS) + _rec(0x0606, b"c1\x00\x00")
            + _rec(0x0800) + _rec(0x1100) + _rec(0x0700) + _rec(0x0400))
    cats = _categories(audit_gds(blob, None, 1.0)[0])
    assert "NO_LAYERS" in cats and "TOO_FEW_MASK_LAYERS" not in cats
