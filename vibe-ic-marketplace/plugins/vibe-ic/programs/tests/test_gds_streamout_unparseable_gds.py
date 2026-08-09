"""Regression: `UNREADABLE_GDS` must be reachable for a GDS that is PRESENT
but unreadable — and PASS must stay reachable for one that is fine.

Root shape (both directions matter, so both are asserted here):

  A. The record scanner is deliberately forgiving — every malformed-input path
     in it is a `break` that returns what it had. So an unreadable stream came
     back as "zero populated layers", zero populated layers have zero orphans,
     and zero orphans is this check's strongest PASS. `UNREADABLE_GDS` was
     therefore emittable only for a MISSING file: a 0-byte, truncated or
     non-GDSII artefact scored a verdict BYTE-IDENTICAL to a complete,
     correctly-mapped stream. Nothing the scanner can raise gets caught either
     — the `except (OSError, struct.error)` arm around it is unreachable for a
     parse fault, because no parse fault raises.

  B. The fix must not buy that by failing everything. A structurally complete
     stream must still PASS, a complete stream with a genuine orphan must
     still FAIL with ORPHAN_LAYER (not swallowed by an early return), and the
     null padding real streams carry after ENDLIB must not read as damage.

Chip/PDK-AGNOSTIC by construction: every fixture is a synthetic GDSII byte
string built here, and every layer number is a generic integer. No vendor, PDK,
design or SKU literal appears. Assertions are on returned findings, exit codes
and emitted JSON only.
"""
from __future__ import annotations

import importlib
import json
import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

m = importlib.import_module("gds_streamout_layermap_check")


# ---------------------------------------------------------------------------
# Synthetic GDSII bytes
# ---------------------------------------------------------------------------
def _rec(rtype: int, dtype: int, body: bytes = b"") -> bytes:
    return struct.pack(">HBB", len(body) + 4, rtype, dtype) + body


def _i2(v: int) -> bytes:
    return struct.pack(">h", v)


def _stream(layers=()) -> bytes:
    """A complete GDSII stream (HEADER .. ENDLIB) with one box per layer."""
    out = [_rec(0x00, 0x02, _i2(600)),                   # HEADER
           _rec(0x01, 0x02, _i2(0) * 12),                # BGNLIB
           _rec(0x02, 0x06, b"TEST.DB"),                 # LIBNAME
           _rec(0x03, 0x05, b"\x00" * 16),               # UNITS
           _rec(0x05, 0x02, _i2(0) * 12),                # BGNSTR
           _rec(0x06, 0x06, b"TOP")]                     # STRNAME
    for lay, dt in layers:
        pts = b"".join(struct.pack(">ii", x, y) for x, y in
                       [(0, 0), (100, 0), (100, 100), (0, 100), (0, 0)])
        out += [_rec(0x08, 0x00),                        # BOUNDARY
                _rec(0x0D, 0x02, _i2(lay)),              # LAYER
                _rec(0x0E, 0x02, _i2(dt)),               # DATATYPE
                _rec(0x10, 0x03, pts),                   # XY
                _rec(0x11, 0x00)]                        # ENDEL
    out += [_rec(0x07, 0x00), _rec(0x04, 0x00)]          # ENDSTR, ENDLIB
    return b"".join(out)


@pytest.fixture()
def authority(tmp_path: Path):
    """The three authority inputs, all well formed: a library GDS, a streamout
    map covering the routing layers, and no bridge config."""
    lib = tmp_path / "lib.gds"
    lib.write_bytes(_stream([(1, 0), (3, 0), (9, 0)]))
    mp = tmp_path / "streamout.map"
    mp.write_text("# vendor streamout map\n"
                  "MET1  drawing  9  0\n"
                  "VIA1  drawing  10 0\n"
                  "MET2  drawing  11 0\n")
    return mp, lib


# ---------------------------------------------------------------------------
# DIRECTION A — the verdict that could not be reached
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name,payload", [
    # streamout wrote nothing at all
    ("zero.gds", b""),
    # the tool wrote a diagnostic / wrapper where a stream was expected
    ("notgds.gds", b"ERROR: stream-out aborted\n" * 8),
    # the stream stops mid-library: records parse, ENDLIB never arrives
    ("cut.gds", _stream([(9, 0), (11, 0)])[:60]),
    # a record header survives but its body does not
    ("shortbody.gds", _stream([(9, 0)])[:-1]),
    # trailing bytes that cannot begin a record
    ("stray.gds", _stream([(9, 0)])[:len(_stream([(9, 0)])) - 4] + b"\x00\x01"),
])
def test_present_but_unreadable_gds_reaches_the_verdict(
        tmp_path: Path, authority, name: str, payload: bytes):
    """Each of these is PRESENT — `.is_file()` is True — so the missing-file
    arm cannot fire. Before the fix every one of them returned zero findings
    and verdict PASS."""
    mp, lib = authority
    g = tmp_path / name
    g.write_bytes(payload)
    assert g.is_file()                      # not the missing-file case

    findings, stats = m.audit(g, mp, lib, None)
    errors = [f for f in findings if f.severity == "ERROR"]
    assert [f.category for f in errors] == ["UNREADABLE_GDS"], (
        f"{name}: expected an UNREADABLE_GDS error, got {findings!r}")
    assert stats.orphans == []              # no orphan claim off unread bytes


def test_unreadable_gds_is_a_fail_verdict_not_a_pass(tmp_path: Path,
                                                     authority):
    """End to end through the CLI: exit code and emitted JSON, not internals.
    A 0-byte stream used to exit 0 with `"verdict": "PASS"`."""
    mp, lib = authority
    g = tmp_path / "zero.gds"
    g.write_bytes(b"")
    out = tmp_path / "r.json"

    rc = m.main(["--gds", str(g), "--layermap", str(mp),
                 "--lib-gds", str(lib), "--json", str(out)])

    assert rc == 1
    payload = json.loads(out.read_text())
    assert payload["verdict"] == "FAIL"
    assert [f["category"] for f in payload["findings"]] == ["UNREADABLE_GDS"]


def test_unreadable_gds_fails_even_with_no_authority_inputs(tmp_path: Path):
    """The orphan gate self-disables when it has no authority to judge
    against (`if allowed else []`). Parseability is not an accounting
    question, so it must not inherit that escape hatch."""
    g = tmp_path / "cut.gds"
    g.write_bytes(_stream([(9, 0)])[:40])
    findings, _ = m.audit(g, None, None, None, require_layermap=False)
    assert [f.category for f in findings if f.severity == "ERROR"] == [
        "UNREADABLE_GDS"]


# ---------------------------------------------------------------------------
# DIRECTION B — the OTHER verdict is still reachable
# ---------------------------------------------------------------------------
def test_complete_stream_still_passes(tmp_path: Path, authority):
    """The point of the fix is discrimination, not loudness."""
    mp, lib = authority
    g = tmp_path / "ok.gds"
    g.write_bytes(_stream([(1, 0), (3, 0), (9, 0), (10, 0), (11, 0)]))

    findings, stats = m.audit(g, mp, lib, None)
    assert [f for f in findings if f.severity == "ERROR"] == []
    assert stats.orphans == []
    assert m.main(["--gds", str(g), "--layermap", str(mp),
                   "--lib-gds", str(lib)]) == 0


def test_null_padding_after_endlib_is_not_damage(tmp_path: Path, authority):
    """Real streams are padded out to a block boundary with nulls after
    ENDLIB. Reading that as a truncated record would fail every good GDS —
    the exact way this fix could have gone wrong."""
    mp, lib = authority
    g = tmp_path / "padded.gds"
    g.write_bytes(_stream([(9, 0), (10, 0), (11, 0)]) + b"\x00" * 2048)

    findings, _ = m.audit(g, mp, lib, None)
    assert [f for f in findings if f.severity == "ERROR"] == []
    assert m.main(["--gds", str(g), "--layermap", str(mp),
                   "--lib-gds", str(lib)]) == 0


def test_shapeless_but_complete_stream_is_not_called_unreadable(
        tmp_path: Path, authority):
    """A stream that is whole but carries no geometry is a SUBSTANCE question,
    answered by the substance gate. This check must not annex it: its verdict
    is about layer numbering, and it has no numbering complaint here."""
    mp, lib = authority
    g = tmp_path / "hollow.gds"
    g.write_bytes(_stream([]))

    findings, stats = m.audit(g, mp, lib, None)
    assert [f.category for f in findings if f.severity == "ERROR"] == []
    assert stats.gds_layers == []


def test_real_orphan_still_fails_through_the_new_gate(tmp_path: Path,
                                                      authority):
    """The precondition returns early — prove it does not short-circuit the
    accounting for a stream that IS readable."""
    mp, lib = authority
    g = tmp_path / "orphan.gds"
    g.write_bytes(_stream([(9, 0), (11, 0), (777, 4)]))

    findings, stats = m.audit(g, mp, lib, None)
    errs = [f for f in findings if f.severity == "ERROR"]
    assert [f.category for f in errs] == ["ORPHAN_LAYER"]
    assert stats.orphans == ["777/4"]
    assert m.main(["--gds", str(g), "--layermap", str(mp),
                   "--lib-gds", str(lib)]) == 1


# ---------------------------------------------------------------------------
# Authority inputs: warned about, never verdict-bearing
# ---------------------------------------------------------------------------
def test_truncated_authority_gds_warns_but_does_not_flip_a_pass(
        tmp_path: Path):
    """A short read of the LIBRARY narrows the allowed set and can manufacture
    orphans. Say so — but a fact about this check's own inputs must not
    change the verdict by itself."""
    lib = tmp_path / "lib.gds"
    lib.write_bytes(_stream([(1, 0), (3, 0), (9, 0)])[:-6])   # no ENDLIB
    mp = tmp_path / "streamout.map"
    mp.write_text("MET1 drawing 9 0\nVIA1 drawing 10 0\nMET2 drawing 11 0\n")
    g = tmp_path / "d.gds"
    g.write_bytes(_stream([(9, 0), (10, 0), (11, 0)]))

    findings, _ = m.audit(g, mp, lib, None)
    warns = [f for f in findings if f.severity == "WARNING"]
    assert "AUTHORITY_GDS_TRUNCATED" in {f.category for f in warns}
    assert [f for f in findings if f.severity == "ERROR"] == []
    assert m.main(["--gds", str(g), "--layermap", str(mp),
                   "--lib-gds", str(lib)]) == 0
