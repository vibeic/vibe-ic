#!/usr/bin/env python3
"""vibe-ic#2221 — a GDS carries its own write time, so bytes are the wrong key.

Every assertion here is bidirectional on purpose. A canonicaliser that only
ever says "equal" is a rubber stamp, so each claim that two streams MATCH is
paired with a claim that a real difference still MOVES the digest.
"""
from __future__ import annotations

import hashlib
import struct
import subprocess
import sys
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent
PROGRAMS = HERE.parent
sys.path.insert(0, str(PROGRAMS))

import gds_canonical_digest as G                       # noqa: E402
from _gds_geometry import GdsError                      # noqa: E402


def _rec(rtype: int, dtype: int, payload: bytes = b"") -> bytes:
    return struct.pack(">HBB", 4 + len(payload), rtype, dtype) + payload


def _stream(lib_date, str_date, *, width: int = 1000,
            structures: int = 1) -> bytes:
    """A real GDSII stream with CHOSEN dates and a chosen box width."""
    out = _rec(0x00, 0x02, struct.pack(">h", 600))
    out += _rec(0x01, 0x02, struct.pack(">12h", *lib_date))
    out += _rec(0x02, 0x06, b"LIB\x00")
    out += _rec(0x03, 0x05, b"\x00" * 16)
    for _ in range(structures):
        out += _rec(0x05, 0x02, struct.pack(">12h", *str_date))
        out += _rec(0x06, 0x06, b"TOP\x00")
        out += _rec(0x08, 0x00)                                    # BOUNDARY
        out += _rec(0x0D, 0x02, struct.pack(">h", 1))              # LAYER
        out += _rec(0x0E, 0x02, struct.pack(">h", 0))              # DATATYPE
        out += _rec(0x10, 0x03, struct.pack(
            ">10i", 0, 0, width, 0, width, 500, 0, 500, 0, 0))     # XY
        out += _rec(0x11, 0x00)                                    # ENDEL
        out += _rec(0x07, 0x00)                                    # ENDSTR
    out += _rec(0x04, 0x00)
    return out


#: Two genuinely different wall-clock reads, in the shape a writer stamps.
_RUN_A = (2026, 8, 9, 13, 10, 28) * 2
_RUN_B = (2026, 9, 10, 2, 41, 7) * 2


def _write(tmp_path: Path, name: str, raw: bytes) -> Path:
    p = tmp_path / name
    p.write_bytes(raw)
    return p


def test_two_streamouts_of_one_layout_match_although_the_bytes_do_not(tmp_path):
    """The measured case: same geometry, different clock, honest verdict."""
    a = _write(tmp_path, "a.gds", _stream(_RUN_A, _RUN_A))
    b = _write(tmp_path, "b.gds", _stream(_RUN_B, _RUN_B))

    raw_a = hashlib.sha256(a.read_bytes()).hexdigest()
    raw_b = hashlib.sha256(b.read_bytes()).hexdigest()
    assert raw_a != raw_b, (
        "the fixture must reproduce the defect it exists to pin: two writes "
        "of one layout have to differ in bytes, or this file proves nothing")
    assert len(a.read_bytes()) == len(b.read_bytes())

    assert G.canonical_digest(a) == G.canonical_digest(b)


def test_a_geometry_change_still_moves_the_digest(tmp_path):
    """The negative control. A canonicaliser that cannot go DOWN is a stamp."""
    a = _write(tmp_path, "a.gds", _stream(_RUN_A, _RUN_A, width=1000))
    wider = _write(tmp_path, "wider.gds", _stream(_RUN_A, _RUN_A, width=1400))
    assert G.canonical_digest(a) != G.canonical_digest(wider)


def test_a_structure_count_change_still_moves_the_digest(tmp_path):
    """Zeroing BGNSTR must not zero the fact that a structure EXISTS."""
    one = _write(tmp_path, "one.gds", _stream(_RUN_A, _RUN_A, structures=1))
    two = _write(tmp_path, "two.gds", _stream(_RUN_A, _RUN_A, structures=2))
    assert G.canonical_digest(one) != G.canonical_digest(two)


def test_the_structure_dates_are_zeroed_and_not_only_the_library_date(tmp_path):
    """BGNSTR carries the same twelve fields, once per structure.

    The corpus file this issue was filed against carries ONE BGNLIB and one
    BGNSTR per structure, all stamped. A canonicaliser that zeroed only the
    library record would still report two runs of one layout as different, and
    would do it silently.
    """
    a = _write(tmp_path, "a.gds",
               _stream(_RUN_A, _RUN_A, structures=3))
    b = _write(tmp_path, "b.gds",
               _stream(_RUN_A, _RUN_B, structures=3))   # LIB same, STR differs
    assert (hashlib.sha256(a.read_bytes()).hexdigest()
            != hashlib.sha256(b.read_bytes()).hexdigest())
    assert G.canonical_digest(a) == G.canonical_digest(b)


def test_canonical_bytes_zero_every_date_span_and_change_nothing_else(tmp_path):
    """Byte-level: what moved is exactly the date spans, and only those."""
    raw = _stream(_RUN_A, _RUN_A, structures=2)
    p = _write(tmp_path, "a.gds", raw)
    canon = G.canonical_bytes(p)
    assert len(canon) == len(raw)
    moved = [i for i in range(len(raw)) if raw[i] != canon[i]]
    assert moved, "nothing was canonicalised — the fixture carries no dates"
    spans, off = [], 0
    while off + 4 <= len(raw):
        length, rt = struct.unpack_from(">HH", raw, off)
        if rt >> 8 in (0x01, 0x05) and (rt & 0xFF) == 0x02:
            spans.append((off + 4, off + 4 + G.DATE_FIELD_BYTES))
        off += length
    assert all(any(s <= i < e for s, e in spans) for i in moved)
    assert all(canon[s:e] == G.ZEROED_DATES for s, e in spans)


def test_a_file_that_is_not_a_gds_is_refused_not_digested(tmp_path):
    """Fail-closed: never hand back a digest of something unparsed."""
    junk = _write(tmp_path, "junk.gds", b"this is not a stream" * 4)
    with pytest.raises(GdsError):
        G.canonical_digest(junk)


def test_a_well_formed_record_that_is_not_HEADER_is_refused(tmp_path):
    """The junk above dies on its length. This reaches the HEADER clause.

    Two different refusals, and they are tested separately because a file whose
    first record happens to declare a VALID length would sail past the length
    check and reach this one; asserting only the junk case would leave the
    HEADER clause unexercised and free to be deleted.
    """
    not_header = _rec(0x02, 0x06, b"LIB\x00") + _rec(0x04, 0x00)
    p = _write(tmp_path, "nh.gds", not_header)
    with pytest.raises(GdsError, match="not HEADER"):
        G.canonical_digest(p)


def test_a_truncated_stream_is_refused(tmp_path):
    """Cut the tail off a real stream. The walk ends quietly; we must not.

    `_gds_geometry._iter_records` stops when fewer than four bytes remain, so
    before this was pinned a stream cut mid-record produced a digest that read
    exactly like a digest of the whole file.
    """
    raw = _stream(_RUN_A, _RUN_A)
    cut = _write(tmp_path, "cut.gds", raw[:len(raw) - 6])
    with pytest.raises(GdsError, match="ENDLIB"):
        G.canonical_digest(cut)


def test_zero_padding_after_endlib_is_tolerated(tmp_path):
    """Block padding is not content. Measured absent on the corpus, but legal.

    Three published GDS carry ZERO trailing bytes (spm sky130A, mdio chip_top,
    spm gf180mcuD), so this tolerance is not covering for anything the corpus
    actually does -- it is here so a writer that pads to a block boundary is
    not refused, while a non-zero tail still is.
    """
    raw = _stream(_RUN_A, _RUN_A)
    plain = _write(tmp_path, "plain.gds", raw)
    padded = _write(tmp_path, "padded.gds", raw + b"\x00" * 2048)
    assert G.canonical_digest(plain) == G.canonical_digest(padded)


def test_a_non_zero_tail_after_endlib_is_refused(tmp_path):
    raw = _stream(_RUN_A, _RUN_A)
    junked = _write(tmp_path, "tail.gds", raw + b"\x01" * 16)
    with pytest.raises(GdsError, match="follow ENDLIB"):
        G.canonical_digest(junked)


def test_a_date_record_of_the_wrong_width_is_refused(tmp_path):
    """A fixed-span zeroing on a non-conforming record would corrupt it."""
    out = _rec(0x00, 0x02, struct.pack(">h", 600))
    out += _rec(0x01, 0x02, struct.pack(">6h", *([0] * 6)))   # half-width
    out += _rec(0x04, 0x00)
    odd = _write(tmp_path, "odd.gds", out)
    with pytest.raises(GdsError, match="payload byte"):
        G.canonical_digest(odd)


def _cli(*args):
    return subprocess.run(
        [sys.executable, str(PROGRAMS / "gds_canonical_digest.py"), *args],
        capture_output=True, text=True)


def test_cli_compare_accepts_two_runs_of_one_layout(tmp_path):
    a = _write(tmp_path, "a.gds", _stream(_RUN_A, _RUN_A))
    b = _write(tmp_path, "b.gds", _stream(_RUN_B, _RUN_B))
    got = _cli("--compare", str(a), str(b))
    assert got.returncode == 0, got.stdout + got.stderr


def test_cli_compare_still_rejects_two_different_layouts(tmp_path):
    a = _write(tmp_path, "a.gds", _stream(_RUN_A, _RUN_A, width=1000))
    b = _write(tmp_path, "b.gds", _stream(_RUN_A, _RUN_A, width=1400))
    got = _cli("--compare", str(a), str(b))
    assert got.returncode == 1
    assert "DIFFER" in got.stdout


def test_cli_says_NOT_MEASURED_rather_than_printing_a_digest_of_junk(tmp_path):
    junk = _write(tmp_path, "junk.gds", b"nope")
    got = _cli(str(junk))
    assert got.returncode == 2
    assert "NOT_MEASURED" in got.stdout
