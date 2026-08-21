#!/usr/bin/env python3
"""Minimal REAL GDSII stream bytes, for tests that need a tape-out artefact.

Why this exists
---------------
The tape-out checklist's GDS slot (`signoff_audit._check_tapeout`) credits only
the flow's DECLARED stream-out artefact (`phase3/stage4/gds/*.gds`) and only
when that file carries actual GDSII substance — a non-empty file whose first
record is a HEADER. Fixtures that used to write `"GDS"` or `"binary gds data"`
into an arbitrary `.gds` were asserting on a shape the gate no longer accepts,
and rightly so: that is precisely the "a file nothing verified" defect the slot
was tightened to refuse.

So a test that needs the GDS slot CREDITED must hand the gate a real stream.
This module emits the smallest structurally honest one: HEADER, BGNLIB,
LIBNAME, UNITS, one empty structure, ENDLIB. It is bytes, not text, and it is
chip-AGNOSTIC (no design, PDK or vendor name anywhere).

It is deliberately NOT a substitute for a laid-out GDS: `gds_substance_check`
demands geometry proportional to the placed-instance count, and this stream has
none. Tests of THAT gate build their own richer streams.
"""
from __future__ import annotations

import struct
from pathlib import Path

#: `phase3/stage4/gds/*.gds` — what the flow yaml declares as Step 37's
#: stream-out artefact, and the only location the tape-out GDS slot credits.
DECLARED_GDS_DIR = "phase3/stage4/gds"


def _record(rtype: int, dtype: int, payload: bytes = b"") -> bytes:
    """One GDSII record: big-endian u16 total length, u8 type, u8 data-type."""
    return struct.pack(">HBB", 4 + len(payload), rtype, dtype) + payload


def minimal_gdsii_bytes(structures: int = 1) -> bytes:
    """The smallest byte string that IS a GDSII stream (HEADER .. ENDLIB)."""
    out = _record(0x00, 0x02, struct.pack(">h", 600))               # HEADER
    out += _record(0x01, 0x02, struct.pack(">12h", *([0] * 12)))    # BGNLIB
    out += _record(0x02, 0x06, b"LIB\x00")                          # LIBNAME
    out += _record(0x03, 0x05, b"\x00" * 16)                        # UNITS
    for _ in range(structures):
        out += _record(0x05, 0x02, struct.pack(">12h", *([0] * 12)))  # BGNSTR
        out += _record(0x06, 0x06, b"TOP\x00")                        # STRNAME
        out += _record(0x07, 0x00)                                    # ENDSTR
    out += _record(0x04, 0x00)                                        # ENDLIB
    return out


def write_gdsii(path: Path, structures: int = 1) -> Path:
    """Write a minimal real GDSII stream at `path` (parents created)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(minimal_gdsii_bytes(structures))
    return path


def write_declared_streamout(project: Path, name: str = "chip_top.gds") -> Path:
    """Write a creditable Step-37 stream-out into `project`.

    The one call a fixture needs when its subject is NOT the GDS slot and it
    simply requires that slot satisfied.
    """
    return write_gdsii(project / DECLARED_GDS_DIR / name)
