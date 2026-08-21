"""Tests for gds_streamout_layermap_check.py.

The check exists because a DEF->GDS streamout that runs without a layer map
silently writes every routed shape onto a GDS layer the foundry does not use
for that purpose. Measured on a commercial-PDK clean run: identical DEF and
identical deck, 4533 rules checked either way, 51 rules firing without the map
vs 1 with it. The fixtures below build minimal GDS files so the discrimination
is exercised without any PDK.
"""
from __future__ import annotations

import json
import struct
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import gds_streamout_layermap_check as mod  # noqa: E402


# ---------------------------------------------------------------------------
# Minimal GDS writer — enough structure for the record scanner
# ---------------------------------------------------------------------------
def _rec(rtype: int, dtype: int, body: bytes = b"") -> bytes:
    return struct.pack(">HBB", len(body) + 4, rtype, dtype) + body


def _i2(v: int) -> bytes:
    return struct.pack(">h", v)


def write_gds(path: Path, layers, cell: str = "TOP", texts=()) -> Path:
    """Write a GDS holding one box per (layer, datatype) in `layers`, plus a
    text label per (layer, texttype) in `texts`."""
    out = [_rec(0x00, 0x02, _i2(600)),                      # HEADER
           _rec(0x01, 0x02, _i2(0) * 12),                   # BGNLIB
           _rec(0x02, 0x06, b"TEST.DB"),                    # LIBNAME
           _rec(0x03, 0x05, b"\x00" * 16),                  # UNITS
           _rec(0x05, 0x02, _i2(0) * 12),                   # BGNSTR
           _rec(0x06, 0x06, cell.encode())]                 # STRNAME
    for lay, dt in layers:
        pts = b"".join(struct.pack(">ii", x, y) for x, y in
                       [(0, 0), (100, 0), (100, 100), (0, 100), (0, 0)])
        out += [_rec(0x08, 0x00),                           # BOUNDARY
                _rec(0x0D, 0x02, _i2(lay)),                 # LAYER
                _rec(0x0E, 0x02, _i2(dt)),                  # DATATYPE
                _rec(0x10, 0x03, pts),                      # XY
                _rec(0x11, 0x00)]                           # ENDEL
    for lay, tt in texts:
        out += [_rec(0x0C, 0x00),                           # TEXT
                _rec(0x0D, 0x02, _i2(lay)),                 # LAYER
                _rec(0x16, 0x02, _i2(tt)),                  # TEXTTYPE
                _rec(0x10, 0x03, struct.pack(">ii", 0, 0)),  # XY
                _rec(0x19, 0x06, b"PORT"),                  # STRING
                _rec(0x11, 0x00)]                           # ENDEL
    out += [_rec(0x07, 0x00), _rec(0x04, 0x00)]             # ENDSTR, ENDLIB
    path.write_bytes(b"".join(out))
    return path


@pytest.fixture()
def lib_gds(tmp_path: Path) -> Path:
    return write_gds(tmp_path / "lib.gds", [(1, 0), (3, 0), (9, 0)])


@pytest.fixture()
def layermap(tmp_path: Path) -> Path:
    p = tmp_path / "streamout.map"
    p.write_text(
        "# vendor streamout map\n"
        "MET1  drawing  9  0\n"
        "VIA1  drawing  10 0\n"
        "MET2  drawing  11 0\n"
        "MET1  pin      9  1\n")
    return p


# ---------------------------------------------------------------------------
# Layer scanning
# ---------------------------------------------------------------------------
def test_scan_gds_layers_reads_populated_pairs(tmp_path: Path):
    g = write_gds(tmp_path / "a.gds", [(9, 0), (11, 0), (11, 2)])
    assert mod.scan_gds_layers(g) == {(9, 0), (11, 0), (11, 2)}


def test_scan_gds_layers_ignores_empty_layout(tmp_path: Path):
    assert mod.scan_gds_layers(write_gds(tmp_path / "e.gds", [])) == set()


def test_scan_separates_text_from_geometry(tmp_path: Path):
    g = write_gds(tmp_path / "t.gds", [(9, 0)], texts=[(100, 2), (100, 3)])
    assert mod.scan_gds_layers(g) == {(9, 0)}
    assert mod.scan_gds_layers(g, include_text=True) == {
        (9, 0), (100, 2), (100, 3)}


def test_port_labels_are_not_orphan_geometry(tmp_path: Path, lib_gds: Path,
                                             layermap: Path):
    """Port labels are emitted on a base text layer with a per-metal
    datatype. They carry no geometry, so no DRC rule can measure them and
    they must never be reported as un-mapped shapes."""
    g = write_gds(tmp_path / "lbl.gds", [(9, 0), (11, 0)],
                  texts=[(100, 2), (100, 3)])
    findings, stats = mod.audit(g, layermap, lib_gds, None)
    assert stats.orphans == []
    assert [f for f in findings if f.severity == "ERROR"] == []


# ---------------------------------------------------------------------------
# Authority parsing
# ---------------------------------------------------------------------------
def test_layermap_targets_skip_comments_and_headers(layermap: Path):
    assert mod.parse_layermap_targets(layermap) == {
        (9, 0), (10, 0), (11, 0), (9, 1)}


def test_declared_layers_walks_nested_config():
    cfg = {"dummy_fill": {"layers": [{"gds": "11/0"}, {"gds": "13/0"}]},
           "tap_geom_layers": {"nwell": "2/0"},
           "port_label_restore": {"text_layer": "100/0",
                                  "vdd_marker": "901/0"},
           "stdcell_exclusion_marker_layer": "65/0,113/0",
           "lvs_engine": "klayout", "rail_margin_um": 0.8}
    assert mod.declared_layers(cfg) == {
        (11, 0), (13, 0), (2, 0), (100, 0), (901, 0), (65, 0), (113, 0)}


# ---------------------------------------------------------------------------
# The discrimination this check exists for
# ---------------------------------------------------------------------------
def test_unmapped_streamout_is_flagged(tmp_path: Path, lib_gds: Path):
    """No map: routed metal landed on the reader's own numbering, so those
    layers match no authority."""
    g = write_gds(tmp_path / "off.gds",
                  [(1, 0), (3, 0), (9, 0), (36, 0), (38, 0), (40, 0)])
    findings, stats = mod.audit(g, None, lib_gds, None)
    cats = {f.category for f in findings if f.severity == "ERROR"}
    assert "NO_LAYERMAP" in cats
    assert "ORPHAN_LAYER" in cats
    assert stats.orphans == ["36/0", "38/0", "40/0"]


def test_mapped_streamout_is_clean(tmp_path: Path, lib_gds: Path,
                                   layermap: Path):
    g = write_gds(tmp_path / "on.gds",
                  [(1, 0), (3, 0), (9, 0), (10, 0), (11, 0)])
    findings, stats = mod.audit(g, layermap, lib_gds, None)
    assert [f for f in findings if f.severity == "ERROR"] == []
    assert stats.orphans == []
    assert stats.layermap_applied is True


def test_partial_map_still_catches_orphans(tmp_path: Path, lib_gds: Path,
                                           layermap: Path):
    """A map that is present but does not cover every routing layer leaves
    the uncovered geometry on reader numbering — still a fault."""
    g = write_gds(tmp_path / "part.gds", [(9, 0), (11, 0), (42, 0)])
    findings, stats = mod.audit(g, layermap, lib_gds, None)
    assert stats.orphans == ["42/0"]
    assert any(f.category == "ORPHAN_LAYER" for f in findings
               if f.severity == "ERROR")


def test_config_declared_layers_are_not_orphans(tmp_path: Path, lib_gds: Path,
                                                layermap: Path):
    """Fill and marker layers the flow legitimately draws must not be
    mistaken for un-mapped geometry."""
    cfg = tmp_path / "signoff.json"
    cfg.write_text(json.dumps(
        {"dummy_fill": {"layers": [{"gds": "13/0"}]},
         "port_label_restore": {"vdd_marker": "901/0"}}))
    g = write_gds(tmp_path / "cfg.gds", [(9, 0), (11, 0), (13, 0), (901, 0)])
    findings, stats = mod.audit(g, layermap, lib_gds, cfg)
    assert stats.orphans == []
    assert [f for f in findings if f.severity == "ERROR"] == []


def test_missing_map_tolerated_when_not_signoff(tmp_path: Path, lib_gds: Path):
    g = write_gds(tmp_path / "oss.gds", [(1, 0), (9, 0)])
    findings, _ = mod.audit(g, None, lib_gds, None, require_layermap=False)
    assert [f.category for f in findings if f.severity == "ERROR"] == []


def test_verdict_is_independent_of_violation_count(tmp_path: Path,
                                                   lib_gds: Path,
                                                   layermap: Path):
    """The check must never act as a DRC filter: adding more geometry on
    correctly-mapped layers cannot change its verdict."""
    a = write_gds(tmp_path / "few.gds", [(9, 0), (11, 0)])
    b = write_gds(tmp_path / "many.gds",
                  [(9, 0), (11, 0), (11, 0), (11, 0), (9, 0)])
    fa, _ = mod.audit(a, layermap, lib_gds, None)
    fb, _ = mod.audit(b, layermap, lib_gds, None)
    assert ([f.category for f in fa if f.severity == "ERROR"]
            == [f.category for f in fb if f.severity == "ERROR"] == [])


def test_missing_gds_reports_unreadable(tmp_path: Path):
    findings, _ = mod.audit(tmp_path / "nope.gds", None, None, None)
    assert findings[0].category == "UNREADABLE_GDS"


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def test_cli_exit_codes_and_json(tmp_path: Path, lib_gds: Path,
                                 layermap: Path):
    bad = write_gds(tmp_path / "bad.gds", [(9, 0), (36, 0)])
    out = tmp_path / "r.json"
    rc = mod.main(["--gds", str(bad), "--lib-gds", str(lib_gds),
                   "--json", str(out)])
    assert rc == 1
    assert json.loads(out.read_text())["verdict"] == "FAIL"

    good = write_gds(tmp_path / "good.gds", [(9, 0), (11, 0)])
    assert mod.main(["--gds", str(good), "--layermap", str(layermap),
                     "--lib-gds", str(lib_gds)]) == 0
