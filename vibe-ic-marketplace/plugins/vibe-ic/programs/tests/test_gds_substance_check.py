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

Cases 2-4 are the gate's reason to exist: `gds_size_check` reports
`pass: true, errors: 0, warnings: 0` for all three.
"""
from __future__ import annotations

import os
import random
import struct
from pathlib import Path

import pytest

from programs.gds_substance_check import (
    MIN_DISTINCT_LAYERS,
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


#: SEEDED, not `os.urandom`. This case asserts a specific finding CATEGORY over
#: a blob that was REGENERATED EVERY RUN, so its verdict was a draw. It failed a
#: landing gate on `MALFORMED_RECORD` while five consecutive local runs were
#: green.
#:
#: HONESTLY: the failing draw was NOT reproduced. Twelve seeds all yield
#: `MALFORMED_RECORD`, so the alternative outcome is rare — this removes the
#: POSSIBILITY rather than diagnosing the byte pattern that produced it. That is
#: still the right change, because the shape is the worst kind: a case that
#: passes almost always and fails occasionally teaches the reader to re-run
#: until green, and that is how a REAL failure gets waved through.
#:
#: The bytes stay arbitrary with respect to GDSII, which is all the control
#: needs; only their reproducibility changes.
_BIG_RANDOM_SEED = 20260802


def _big_random(kb: int = 150) -> bytes:
    rnd = random.Random(_BIG_RANDOM_SEED)
    return (_rec(0x0002, struct.pack(">h", 600))
            + bytes(rnd.getrandbits(8) for _ in range(kb * 1024)))


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
@pytest.mark.parametrize("name,blob,expect_cat", [
    ("stub_86", _stub_86(), "NO_GEOMETRY"),
    ("big_random", _big_random(), "MALFORMED_RECORD"),
    ("big_empty_library", _big_empty_library(), "TRAILING_GARBAGE"),
    ("big_even_junk", _big_even_junk(), "NO_ENDLIB"),
])
def test_negative_control_new_gate_fails(name, blob, expect_cat) -> None:
    findings, _, _ = audit_gds(blob, 1826, 1.0)
    assert findings, f"{name}: new gate must FAIL but returned no findings"
    assert expect_cat in _categories(findings), (
        f"{name}: expected {expect_cat}, got {_categories(findings)}")
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


# ── #298: mask-stack floor — degenerate geometry on ONE layer is not a layout ──
# Adversarial verification of the #291 gate found 1 survivor out of 6 fakes:
# 2,600 10x10 nm boxes, ALL on one layer, 166 KB. It cleared every check by
# construction — valid structure, has structures/elements/LAYER, and 2,600
# elements beats a 1,826-instance element floor. Counting ELEMENTS is defeated
# by padding; counting distinct MASK LAYERS is not.

def _one_layer_pad(n_elements: int = 2600, layer: int = 1) -> bytes:
    """n_elements degenerate boxes, all on a SINGLE layer. No trailing bytes —
    the padding must not be what trips the gate, or the control is worthless."""
    out = _lib_prologue() + _rec(0x0502, _TS) + _rec(0x0606, b"TOP\x00")
    for _ in range(n_elements):
        out += (_rec(0x0800)
                + _rec(0x0D02, struct.pack(">h", layer))
                + _rec(0x0E02, struct.pack(">h", 0))
                + _rec(0x1003, struct.pack(">8i", 0, 0, 10, 0, 10, 10, 0, 10))
                + _rec(0x1100))
    return out + _rec(0x0700) + _rec(0x0400)


def test_298_two_sided_control_pad_passes_pre_fix_path():
    """SIDE 1 — without the floor the fake passes with ZERO findings, and it
    beats the element floor too. Asserting only that the new check catches it
    would be tautological; this pins that there was a real hole."""
    data = _one_layer_pad()
    findings, st, _ = audit_gds(data, instance_count=1826,
                                elements_per_instance=1.0,
                                min_distinct_layers=0)
    assert findings == [], f"pre-fix path should be clean, got {findings}"
    assert st.elements == 2600 > 1826          # clears the element floor
    assert len(set(st.layers)) == 1            # on a single layer


def test_298_mask_stack_floor_catches_the_pad():
    """SIDE 2 — the same bytes, with the floor, are rejected."""
    findings, _, _ = audit_gds(_one_layer_pad(), instance_count=1826,
                               elements_per_instance=1.0)
    cats = [f.category for f in findings]
    assert "MASK_STACK_TOO_THIN" in cats, cats
    assert all(f.severity == "ERROR" for f in findings
               if f.category == "MASK_STACK_TOO_THIN")


def test_298_real_layout_clears_the_floor():
    """No false FAIL: the honest builder draws 5 layers, above the floor of 4.
    Measured on 25 real chip GDS in this repo: min 17 distinct layers."""
    findings, st, _ = audit_gds(_real_gds(), instance_count=None,
                                elements_per_instance=1.0)
    assert len(set(st.layers)) >= MIN_DISTINCT_LAYERS
    assert "MASK_STACK_TOO_THIN" not in [f.category for f in findings]


def test_298_floor_is_a_structural_constant_not_per_design():
    """The threshold must not be a per-design/per-PDK tunable smuggled in as a
    default: 4 is a mask-stack fact (device + contact + interconnect + via)."""
    assert MIN_DISTINCT_LAYERS == 4


def test_298_floor_does_not_fire_on_an_empty_gds():
    """An element-less library is already NO_GEOMETRY; the layer floor must not
    pile a second, misleading finding onto it."""
    findings, _, _ = audit_gds(_stub_86(), instance_count=None,
                               elements_per_instance=1.0)
    assert "MASK_STACK_TOO_THIN" not in [f.category for f in findings]
