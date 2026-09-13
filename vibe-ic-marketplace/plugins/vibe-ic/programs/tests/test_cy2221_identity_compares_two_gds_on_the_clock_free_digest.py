"""test_cy2221_identity_compares_two_gds_on_the_clock_free_digest.py — #2221, both directions.

THE DEFECT, MEASURED BEFORE IT WAS REPAIRED (2026-09-10, 8HD-6, image
`ghcr.io/vibeic/vibeic-eda:0.3.41`, corpus `8c4b608`): one layout
(`ic/spm/v1.10.18_sky130A/.../spm.gds`) was read ONCE into KLayout and streamed
out TWICE, two seconds apart.

    sizes            1616344 vs 1616344    identical
    raw md5          bf1b51eb…  vs  0cae1964…
    differing bytes  98 of 1616344
      inside a BGNLIB/BGNSTR date payload    98
      outside                                 0

49 date records (1 BGNLIB + 48 BGNSTR). So byte-equality over a GDS reports
"the stream-out is not reproducible" on every design, forever, and says nothing
about the geometry.

WHAT IS PINNED HERE, and what deliberately is NOT. The raw hash stays exact
everywhere it attests a single artefact -- that is asserted below, because a
"fix" that quietly canonicalised the attestation would have destroyed the one
property those gates exist for. Only the COMPARISON of two runs moves.
"""
from __future__ import annotations

import hashlib
import struct
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import gds_canonical_digest as G                                # noqa: E402
from _gds_geometry import GdsError, _RT                         # noqa: E402

#: The two record types that carry dates, resolved from the SHIPPED
#: table rather than re-typed here: a second copy of 0x01/0x05 would let
#: this file keep passing after the module stopped looking at them.
_BGNLIB = next(k for k, v in _RT.items() if v == "BGNLIB")
_BGNSTR = next(k for k, v in _RT.items() if v == "BGNSTR")
from _ppa import identity as ident                              # noqa: E402
from _ppa import provenance as prov                             # noqa: E402


def _rec(rtype: int, dtype: int, payload: bytes) -> bytes:
    return struct.pack(">HBB", len(payload) + 4, rtype, dtype) + payload


def _dates(*fields: int) -> bytes:
    assert len(fields) == 12
    return struct.pack(">12h", *fields)


def _stream(second: int, cell: bytes = b"TOP\x00", xy: int = 7) -> bytes:
    """A minimal well-formed GDS whose only clock-fed fields carry `second`.

    Two calls differing ONLY in `second` are exactly the shape KLayout produced
    above: same geometry, different date payloads.
    """
    return b"".join([
        _rec(0x00, 0x02, struct.pack(">h", 600)),                  # HEADER
        _rec(_BGNLIB, 0x02, _dates(2026, 9, 10, 1, 2, second,
                                    2026, 9, 10, 1, 2, second)),
        _rec(0x02, 0x06, b"lib.db\x00"),                           # LIBNAME
        _rec(0x03, 0x05, struct.pack(">dd", 0.001, 1e-9)),         # UNITS
        _rec(_BGNSTR, 0x02, _dates(2026, 9, 10, 1, 2, second,
                                    2026, 9, 10, 1, 2, second)),
        _rec(0x06, 0x06, cell),                                    # STRNAME
        _rec(0x08, 0x00, b""),                                     # BOUNDARY
        _rec(0x0D, 0x02, struct.pack(">h", 1)),                    # LAYER
        _rec(0x0E, 0x02, struct.pack(">h", 0)),                    # DATATYPE
        _rec(0x10, 0x03, struct.pack(">10i", 0, 0, xy, 0, xy, xy,
                                     0, xy, 0, 0)),                # XY
        _rec(0x11, 0x00, b""),                                     # ENDEL
        _rec(0x07, 0x00, b""),                                     # ENDSTR
        _rec(0x04, 0x00, b""),                                     # ENDLIB
    ])


# ── the defect ───────────────────────────────────────────────────────────────

def test_two_streamouts_of_one_layout_are_not_byte_equal():
    """The premise. If this ever goes green the rest of the file is pointless."""
    a, b = _stream(28), _stream(31)
    assert a != b, "the fixture no longer models a clock-carrying stream"
    assert len(a) == len(b), "only the clock may move between these two"
    assert hashlib.sha256(a).hexdigest() != hashlib.sha256(b).hexdigest()


def _spans(data: bytes):
    """[start,end) of every BGNLIB/BGNSTR date payload, walked here so the
    property below is measured against the FILE and not against the module's
    own idea of where it looked."""
    out, off = [], 0
    while off + 4 <= len(data):
        length, rt, _dt = struct.unpack_from(">HBB", data, off)
        if length < 4:
            break
        if rt in (_BGNLIB, _BGNSTR) and length - 4 == G.DATE_FIELD_BYTES:
            out.append((off + 4, off + length))
        off += length
    return out


def test_every_differing_byte_is_inside_a_date_payload():
    """The measured 98-of-98, as a property rather than a remembered number."""
    a, b = _stream(28), _stream(31)
    spans = _spans(a)
    assert spans, "no date payload was located at all"
    differing = [i for i in range(len(a)) if a[i] != b[i]]
    assert differing, "the two streams did not differ"
    outside = [i for i in differing
               if not any(s <= i < e for s, e in spans)]
    assert outside == [], (
        f"{len(outside)} differing byte(s) lie outside every date payload, so "
        f"zeroing dates is NOT sufficient here: {outside[:16]}")


# ── the repair ───────────────────────────────────────────────────────────────

def test_the_canonical_digest_makes_two_streamouts_of_one_layout_equal(tmp_path):
    a, b = tmp_path / "run1.gds", tmp_path / "run2.gds"
    a.write_bytes(_stream(28))
    b.write_bytes(_stream(31))
    assert a.read_bytes() != b.read_bytes(), "the fixture stopped differing"
    assert G.canonical_digest(a) == G.canonical_digest(b), (
        "two stream-outs of one layout still compare different")


def test_the_canonical_digest_still_separates_two_DIFFERENT_layouts(tmp_path):
    """THE LOAD-BEARING NEGATIVE. A canonicaliser that zeroed too much would
    pass the test above and report every layout in the repo as the same one."""
    def w(name, data):
        p = tmp_path / name
        p.write_bytes(data)
        return p
    base = G.canonical_digest(w("base.gds", _stream(28)))
    assert base != G.canonical_digest(w("geom.gds", _stream(28, xy=9)))
    assert base != G.canonical_digest(w("cell.gds", _stream(28, cell=b"OTHER\x00")))


def test_canonicalisation_changes_ONLY_date_payload_bytes(tmp_path):
    raw = _stream(28)
    p = tmp_path / "x.gds"
    p.write_bytes(raw)
    canonical = G.canonical_bytes(p)
    assert len(canonical) == len(raw), "canonicalisation resized the stream"
    spans = _spans(raw)
    moved = [i for i in range(len(raw)) if raw[i] != canonical[i]]
    assert moved, "nothing was zeroed, so the dates were not found"
    assert all(any(s <= i < e for s, e in spans) for i in moved), (
        "canonicalisation touched a byte outside a date payload")
    for start, end in spans:
        assert canonical[start:end] == b"\x00" * (end - start)


# ── the honesty rule: NOT_MEASURED, never a zero and never a raw fallback ────

@pytest.mark.parametrize("body,why", [
    (b"", "empty"),
    (b"\x00\x02", "shorter than a header"),
    (b"\x00\x02\x00\x02", "a record that cannot hold its own header"),
    (_stream(28) + b"\x01\x02", "a trailing fragment"),
    (_stream(28)[:-3], "a truncated final record"),
    (b"this is a DRC report, not a layout at all", "not a stream"),
])
def test_a_file_that_is_not_a_gds_stream_is_NOT_MEASURED(tmp_path, body, why):
    path = tmp_path / "thing.gds"
    path.write_bytes(body)
    with pytest.raises((GdsError, ValueError)):
        G.canonical_digest(path)


# ── the seam: two runs compare correctly through the identity comparator ─────

def _run_tree(root: Path, second: int, xy: int = 7) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "chip_top.gds").write_bytes(_stream(second, xy=xy))
    return root


def _identity(root: Path):
    rows = prov.artefact_refs(root, [{"role": "gds", "path": "chip_top.gds"}])
    return ident.identity("implementation", artefacts=rows), rows


def test_the_raw_attestation_hash_is_still_exact(tmp_path):
    """NOT relaxed: the single-artefact record still names the shipped bytes."""
    root = _run_tree(tmp_path / "run", 28)
    _record, rows = _identity(root)
    raw = "sha256:" + hashlib.sha256((root / "chip_top.gds").read_bytes()).hexdigest()
    assert rows[0]["sha256"] == raw, (
        "the attestation hash was canonicalised — that destroys the one "
        "property provenance_check and benchmark_evidence_publish exist for")


def test_two_runs_of_one_layout_compare_SAME(tmp_path):
    left, _ = _identity(_run_tree(tmp_path / "a", 28))
    right, _ = _identity(_run_tree(tmp_path / "b", 31))
    verdict = ident.compare(left, right)
    assert verdict["verdict"] == "SAME", verdict


def test_two_runs_of_DIFFERENT_layouts_still_compare_DIFFERENT(tmp_path):
    left, _ = _identity(_run_tree(tmp_path / "a", 28, xy=7))
    right, _ = _identity(_run_tree(tmp_path / "b", 28, xy=9))
    verdict = ident.compare(left, right)
    assert verdict["verdict"] == "DIFFERENT", verdict


def test_a_gds_that_cannot_be_canonicalised_is_UNDETERMINED_not_DIFFERENT(
        tmp_path):
    """The whole point of the honesty rule, at the seam that consumes it."""
    good = _run_tree(tmp_path / "a", 28)
    bad = tmp_path / "b"
    bad.mkdir()
    (bad / "chip_top.gds").write_bytes(b"truncated nonsense")
    left, _ = _identity(good)
    right, rows = _identity(bad)
    # The ATTESTATION is untouched: the row still records exactly which bytes
    # are on disk. It is the IDENTITY that refuses, which is the whole point --
    # a file we cannot canonicalise is one we cannot compare, and saying so is
    # not the same as saying the two layouts differ.
    assert rows[0]["status"] == prov.MEASURED, rows[0]
    assert rows[0]["sha256"].startswith("sha256:"), rows[0]
    assert rows[0]["identity_status"] == prov.NOT_MEASURED, rows[0]
    assert rows[0]["identity_reason"], "NOT_MEASURED with no reason"
    assert "identity_sha256" not in rows[0], (
        "a canonical digest was recorded for a file that could not be "
        "canonicalised")
    verdict = ident.compare(left, right)
    assert verdict["verdict"] == "UNDETERMINED", verdict
    assert "NOT_MEASURED" in verdict["reason"], verdict
