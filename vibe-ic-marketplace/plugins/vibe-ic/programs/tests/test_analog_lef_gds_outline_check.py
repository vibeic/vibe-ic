"""tests/test_analog_lef_gds_outline_check.py — A8 LEF-vs-GDS outline gate.

Covers the EXTRACT-NEW rule lifted from analog-output-verify SKILL.md:
"LEF matches GDS outline" / "Cross-check LEF outline w×h vs A5 extents".

PASS  — LEF SIZE agrees with the GDS bounding box within tol.
FAIL  — LEF SIZE disagrees with GDS bbox (real defect: abstract lies
        about the macro footprint); also the missing-half / no-SIZE /
        garbage-GDS honesty cases.
EDGE  — no block list → VACUOUS_PASS; block not packaged → no FAIL;
        custom tolerance band; GDS-real round-trip.
"""
from __future__ import annotations

import json
import struct
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / "analog_lef_gds_outline_check.py"

sys.path.insert(0, str(PROG.parent))
import analog_lef_gds_outline_check as mod  # noqa: E402


# ───────────────────────── GDS stream builder ──────────────────────

def _rec(rec_type: int, payload: bytes = b"") -> bytes:
    length = 4 + len(payload)
    return struct.pack(">HH", length, rec_type) + payload


def build_gds(width_um: float, height_um: float,
              dbu_per_um: float = 1000.0,
              with_header: bool = True,
              with_geometry: bool = True,
              origin_um: tuple = (0.0, 0.0)) -> bytes:
    """Build a minimal but VALID binary GDSII stream whose single
    boundary polygon spans exactly width_um × height_um, with its
    lower-left corner at `origin_um`.

    UNITS record carries [user_per_dbu, meters_per_dbu]; we set
    meters_per_dbu = 1e-6 / dbu_per_um so 1 dbu = (1/dbu_per_um) um.

    `origin_um` defaults to (0, 0) — i.e. a pair that is REGISTERED with a
    LEF whose `ORIGIN` is 0 0. It used to be a hardcoded (10, 20) dbu, which
    was harmless while the gate only compared width and height and would
    now be an off-by-0.02um registration defect in every fixture.
    """
    out = b""
    if with_header:
        out += _rec(0x0002, struct.pack(">h", 600))           # HEADER
    out += _rec(0x0102, struct.pack(">12h", *([0] * 12)))     # BGNLIB
    out += _rec(0x0206, b"TOP\x00")                            # LIBNAME
    meters_per_dbu = 1e-6 / dbu_per_um
    user_per_dbu = 1.0 / dbu_per_um
    out += _rec(0x0305,
                mod.encode_gds_real8(user_per_dbu)
                + mod.encode_gds_real8(meters_per_dbu))        # UNITS
    out += _rec(0x0502, struct.pack(">12h", *([0] * 12)))     # BGNSTR
    out += _rec(0x0606, b"TOP\x00")                            # STRNAME
    if with_geometry:
        out += _rec(0x0800)                                    # BOUNDARY
        out += _rec(0x0D02, struct.pack(">h", 1))              # LAYER
        out += _rec(0x0E02, struct.pack(">h", 0))              # DATATYPE
        w = int(round(width_um * dbu_per_um))
        h = int(round(height_um * dbu_per_um))
        ox = int(round(origin_um[0] * dbu_per_um))
        oy = int(round(origin_um[1] * dbu_per_um))
        pts = [(ox, oy), (ox + w, oy), (ox + w, oy + h), (ox, oy + h), (ox, oy)]
        xy = b"".join(struct.pack(">ii", x, y) for x, y in pts)
        out += _rec(0x1003, xy)                                # XY
        out += _rec(0x1100)                                    # ENDEL
    out += _rec(0x0700)                                        # ENDSTR
    out += _rec(0x0400)                                        # ENDLIB
    return out


def _block_list(project: Path, blocks: list) -> None:
    p = project / "phase3" / "analog"
    p.mkdir(parents=True, exist_ok=True)
    (p / "analog_block_list.json").write_text(json.dumps({"blocks": blocks}))


def _lef(project: Path, block: str, w: float, h: float,
         size_line: bool = True, origin: tuple = (0.0, 0.0),
         foreign: tuple = None) -> None:
    h_dir = project / "phase3" / "analog" / "hardmacro" / block
    h_dir.mkdir(parents=True, exist_ok=True)
    size = f"  SIZE {w} BY {h} ;\n" if size_line else ""
    orig = f"  ORIGIN {origin[0]} {origin[1]} ;\n" if origin is not None else ""
    fgn = (f"  FOREIGN {block} {foreign[0]} {foreign[1]} ;\n"
           if foreign is not None else "")
    (h_dir / f"{block}.lef").write_text(
        "VERSION 5.8 ;\n"
        f"MACRO {block}\n  CLASS BLOCK ;\n{orig}{fgn}{size}"
        "  PIN VDD DIRECTION INOUT ; END VDD\n"
        f"END {block}\n")


def _gds(project: Path, block: str, raw: bytes) -> None:
    h_dir = project / "phase3" / "analog" / "hardmacro" / block
    h_dir.mkdir(parents=True, exist_ok=True)
    (h_dir / f"{block}.gds").write_bytes(raw)


def _run(project: Path, *extra):
    out = project / "rep.json"
    rc = subprocess.run(
        [sys.executable, str(PROG), str(project), "--json", str(out), *extra],
        capture_output=True, text=True)
    rep = json.loads(out.read_text()) if out.exists() else {}
    return rc.returncode, rep, rc.stderr


# ─────────────────────────────── PASS ──────────────────────────────

def test_pass_lef_matches_gds(tmp_path):
    _block_list(tmp_path, ["ldo"])
    _lef(tmp_path, "ldo", 80.0, 60.0)
    _gds(tmp_path, "ldo", build_gds(80.0, 60.0))
    rc, rep, _ = _run(tmp_path)
    assert rc == 0
    assert rep["verdict"] == "PASS"
    assert rep["blocks_pass"] == 1
    b = rep["blocks"][0]
    assert b["gds_bbox_um"] == [80.0, 60.0]
    assert b["lef_size_um"] == [80.0, 60.0]


def test_pass_within_tolerance(tmp_path):
    # LEF says 100x100, GDS is 100.5x99.5 → ~0.5% < 2% default tol.
    _block_list(tmp_path, ["pll"])
    _lef(tmp_path, "pll", 100.0, 100.0)
    _gds(tmp_path, "pll", build_gds(100.5, 99.5))
    rc, rep, _ = _run(tmp_path)
    assert rc == 0
    assert rep["verdict"] == "PASS"


# ─────────────────────────────── FAIL ──────────────────────────────

def test_fail_outline_mismatch(tmp_path):
    # The real defect: LEF abstract claims 100x100 but the GDS spans
    # 250x80 — macro would overlap neighbours in PnR.
    _block_list(tmp_path, ["ldo"])
    _lef(tmp_path, "ldo", 100.0, 100.0)
    _gds(tmp_path, "ldo", build_gds(250.0, 80.0))
    rc, rep, err = _run(tmp_path)
    assert rc == 1
    assert rep["verdict"] == "FAIL"
    f = rep["blocks"][0]["findings"][0]
    assert f["rule"] == "A8_LEF_GDS_OUTLINE_MISMATCH"
    assert rep["blocks"][0]["width_delta_pct"] > 2.0


def test_fail_lef_without_gds(tmp_path):
    _block_list(tmp_path, ["bg"])
    _lef(tmp_path, "bg", 40.0, 40.0)  # no GDS at all
    rc, rep, _ = _run(tmp_path)
    assert rc == 1
    assert rep["blocks"][0]["findings"][0]["rule"] == "A8_GDS_MISSING_FOR_LEF"


def test_fail_gds_without_lef(tmp_path):
    _block_list(tmp_path, ["bg"])
    _gds(tmp_path, "bg", build_gds(40.0, 40.0))  # no LEF
    rc, rep, _ = _run(tmp_path)
    assert rc == 1
    assert rep["blocks"][0]["findings"][0]["rule"] == "A8_LEF_MISSING_FOR_GDS"


def test_fail_lef_no_size_line(tmp_path):
    _block_list(tmp_path, ["bg"])
    _lef(tmp_path, "bg", 40.0, 40.0, size_line=False)
    _gds(tmp_path, "bg", build_gds(40.0, 40.0))
    rc, rep, _ = _run(tmp_path)
    assert rc == 1
    assert rep["blocks"][0]["findings"][0]["rule"] == "A8_LEF_NO_SIZE"


def test_fail_garbage_gds(tmp_path):
    # Garbage bytes must FAIL honestly, never vacuous-PASS.
    _block_list(tmp_path, ["bg"])
    _lef(tmp_path, "bg", 40.0, 40.0)
    _gds(tmp_path, "bg", b"this is not a gds file at all, just text \x00\x01")
    rc, rep, _ = _run(tmp_path)
    assert rc == 1
    assert rep["blocks"][0]["findings"][0]["rule"] == "A8_GDS_NO_GEOMETRY"


def test_fail_gds_no_geometry(tmp_path):
    # Valid header but no boundary → stub GDS → honest FAIL.
    _block_list(tmp_path, ["bg"])
    _lef(tmp_path, "bg", 40.0, 40.0)
    _gds(tmp_path, "bg", build_gds(40.0, 40.0, with_geometry=False))
    rc, rep, _ = _run(tmp_path)
    assert rc == 1
    assert rep["blocks"][0]["findings"][0]["rule"] == "A8_GDS_NO_GEOMETRY"


# ─────────────────────────────── EDGE ──────────────────────────────

def test_edge_no_block_list_vacuous_pass(tmp_path):
    rc, rep, _ = _run(tmp_path)
    assert rc == 0
    assert rep["verdict"] == "VACUOUS_PASS"


def test_edge_empty_block_list_vacuous_pass(tmp_path):
    _block_list(tmp_path, [])
    rc, rep, _ = _run(tmp_path)
    assert rc == 0
    assert rep["verdict"] == "VACUOUS_PASS"


def test_edge_not_packaged_block_no_fail(tmp_path):
    # Declared block with NO lef and NO gds → not packaged yet; that
    # is A8-presence's job, not ours → must not FAIL.
    _block_list(tmp_path, ["future_block"])
    rc, rep, _ = _run(tmp_path)
    assert rc == 0
    assert rep["verdict"] == "PASS"
    assert rep["blocks_not_packaged"] == 1
    assert rep["blocks"][0]["status"] == "NOT_PACKAGED"


def test_edge_custom_tolerance_flips_verdict(tmp_path):
    # 5% mismatch: FAIL at default 2% tol, PASS at 10% tol.
    _block_list(tmp_path, ["amp"])
    _lef(tmp_path, "amp", 100.0, 100.0)
    _gds(tmp_path, "amp", build_gds(105.0, 100.0))
    rc_strict, rep_strict, _ = _run(tmp_path)
    assert rc_strict == 1 and rep_strict["verdict"] == "FAIL"
    rc_loose, rep_loose, _ = _run(tmp_path, "--tol-pct", "10")
    assert rc_loose == 0 and rep_loose["verdict"] == "PASS"


def test_edge_block_filter(tmp_path):
    _block_list(tmp_path, ["good", "bad"])
    _lef(tmp_path, "good", 50.0, 50.0)
    _gds(tmp_path, "good", build_gds(50.0, 50.0))
    _lef(tmp_path, "bad", 50.0, 50.0)
    _gds(tmp_path, "bad", build_gds(200.0, 50.0))
    # filter to the good block only → PASS even though bad exists.
    rc, rep, _ = _run(tmp_path, "--block", "good")
    assert rc == 0 and rep["verdict"] == "PASS"
    assert rep["blocks_checked"] == 1


def test_edge_gds_real_roundtrip():
    for v in (1e-6, 1e-9, 0.001, 1.0, 0.5, 12.5):
        enc = mod.encode_gds_real8(v)
        dec = mod._gds_real8(enc)
        assert abs(dec - v) / v < 1e-6, (v, dec)


def test_edge_micron_unit_scaling(tmp_path):
    # GDS with 1 dbu = 1 nm (dbu_per_um=1000) is the common case;
    # ensure the um conversion is right by using a different scale.
    _block_list(tmp_path, ["x"])
    _lef(tmp_path, "x", 12.0, 8.0)
    _gds(tmp_path, "x", build_gds(12.0, 8.0, dbu_per_um=2000.0))
    rc, rep, _ = _run(tmp_path)
    assert rc == 0
    assert rep["blocks"][0]["gds_bbox_um"] == [12.0, 8.0]


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-q"]))


def test_an_absent_project_is_not_reported_as_a_digital_one(tmp_path):
    """The verdict was right and the REASON was a fabricated conclusion.

    Found by sweeping every project-dir gate against a path that does not
    exist. This one returned:

        VACUOUS_PASS: no analog_block_list.json — digital-only project

    VACUOUS_PASS is correct — nothing was checked and it says so. But the
    reason is what lands in the sign-off report, and "digital-only project" is
    a claim about a design nobody opened. A reader records it as an examined
    fact; the truth was a path that is not there.

    Absence of the manifest supports exactly one statement, so the reason may
    not assert anything beyond it.
    """
    import analog_lef_gds_outline_check as M
    rc, rep = M.build_report(tmp_path / "no-such-project", None, 10.0)
    assert rc == 0
    assert rep["verdict"] == "VACUOUS_PASS"
    assert "digital-only project" not in rep["reason"], \
        "the gate is again concluding 'digital-only' from a project it never opened"
    assert "nothing was examined" in rep["reason"]


# ───────────────────── REGISTRATION (LEF frame vs GDS origin) ──────
#
# The defect these cover, MEASURED on IHP SG13G2 2026-08-01: a hardmacro
# whose LEF SIZE is EXACT and whose GDS is 30.32 um out of frame. Magic's
# `lef write` normalises the abstract to the cell bounding box; `gds write`
# keeps the layout's own coordinates. Every test below FAILS against the
# pre-registration gate (it had no offset to compare and reported PASS).

_OFF = (-0.620, -30.320)   # the measured GDS bbox lower-left


def test_fail_registration_offset_with_exact_size(tmp_path):
    """SIZE exact, frame wrong — the case the width/height gate could not see."""
    _block_list(tmp_path, ["ds"])
    _lef(tmp_path, "ds", 556.810, 158.400)          # ORIGIN 0 0
    _gds(tmp_path, "ds", build_gds(556.810, 158.400, origin_um=_OFF))
    rc, rep, err = _run(tmp_path)
    assert rc == 1
    assert rep["verdict"] == "FAIL"
    b = rep["blocks"][0]
    # The outline halves agree EXACTLY — that is the whole point.
    assert b["width_delta_pct"] == 0.0
    assert b["height_delta_pct"] == 0.0
    rules = [f["rule"] for f in b["findings"]]
    assert "A8_LEF_GDS_REGISTRATION_MISMATCH" in rules
    assert "A8_LEF_GDS_OUTLINE_MISMATCH" not in rules
    assert b["registration_offset_um"] == [-0.62, -30.32]
    assert b["gds_bbox_ll_um"] == [-0.62, -30.32]
    assert b["lef_frame_ll_um"] == [0.0, 0.0]
    assert "A8_LEF_GDS_REGISTRATION_MISMATCH" in err


def test_pass_when_foreign_declares_the_offset(tmp_path):
    """A declared offset is not a defect — FOREIGN is how LEF says it."""
    _block_list(tmp_path, ["ds"])
    _lef(tmp_path, "ds", 556.810, 158.400, foreign=_OFF)
    _gds(tmp_path, "ds", build_gds(556.810, 158.400, origin_um=_OFF))
    rc, rep, _ = _run(tmp_path)
    assert rc == 0
    assert rep["verdict"] == "PASS"
    b = rep["blocks"][0]
    assert b["lef_frame_source"] == "FOREIGN"
    assert b["registration_offset_um"] == [0.0, 0.0]


def test_pass_when_origin_declares_the_offset(tmp_path):
    """ORIGIN x y puts the macro origin inside the box, so the box starts
    at (-x, -y). Declaring it that way is equally valid."""
    _block_list(tmp_path, ["ds"])
    _lef(tmp_path, "ds", 556.810, 158.400, origin=(0.620, 30.320))
    _gds(tmp_path, "ds", build_gds(556.810, 158.400, origin_um=_OFF))
    rc, rep, _ = _run(tmp_path)
    assert rc == 0
    assert rep["verdict"] == "PASS"
    assert rep["blocks"][0]["lef_frame_source"] == "ORIGIN"


def test_fail_when_foreign_has_the_wrong_sign(tmp_path):
    """A declaration that does not match the measurement explains nothing.
    Guards the direction a lenient sign rule would open."""
    _block_list(tmp_path, ["ds"])
    _lef(tmp_path, "ds", 556.810, 158.400, foreign=(0.620, 30.320))
    _gds(tmp_path, "ds", build_gds(556.810, 158.400, origin_um=_OFF))
    rc, rep, _ = _run(tmp_path)
    assert rc == 1
    assert [f["rule"] for f in rep["blocks"][0]["findings"]] == [
        "A8_LEF_GDS_REGISTRATION_MISMATCH"]


def test_foreign_without_a_point_declares_nothing(tmp_path):
    """`FOREIGN <cell> ;` carries no offset — it must fall through to
    ORIGIN and NOT be read as consent to any displacement."""
    _block_list(tmp_path, ["ds"])
    h_dir = tmp_path / "phase3" / "analog" / "hardmacro" / "ds"
    h_dir.mkdir(parents=True, exist_ok=True)
    (h_dir / "ds.lef").write_text(
        "VERSION 5.8 ;\nMACRO ds\n  CLASS BLOCK ;\n  FOREIGN ds ;\n"
        "  ORIGIN 0 0 ;\n  SIZE 556.81 BY 158.4 ;\n"
        "  PIN VDD DIRECTION INOUT ; END VDD\nEND ds\n")
    _gds(tmp_path, "ds", build_gds(556.810, 158.400, origin_um=_OFF))
    rc, rep, _ = _run(tmp_path)
    assert rc == 1
    assert rep["blocks"][0]["lef_frame_source"] == "ORIGIN"


def test_lef_with_no_origin_at_all_defaults_to_zero(tmp_path):
    """LEF's default macro origin is 0 0; a MACRO that omits ORIGIN still
    promises the box starts there."""
    _block_list(tmp_path, ["ds"])
    _lef(tmp_path, "ds", 80.0, 60.0, origin=None)
    _gds(tmp_path, "ds", build_gds(80.0, 60.0, origin_um=(0.0, 0.0)))
    rc, rep, _ = _run(tmp_path)
    assert rc == 0
    assert rep["blocks"][0]["lef_frame_source"] == "LEF-default"


def test_registration_tolerance_band(tmp_path):
    """Inside --tol-um is a grid artefact; outside it is a displacement."""
    _block_list(tmp_path, ["ds"])
    _lef(tmp_path, "ds", 80.0, 60.0)
    _gds(tmp_path, "ds", build_gds(80.0, 60.0, origin_um=(0.0, 0.005)))
    rc, rep, _ = _run(tmp_path)
    assert rc == 0 and rep["verdict"] == "PASS"
    rc, rep, _ = _run(tmp_path, "--tol-um", "0.001")
    assert rc == 1
    assert [f["rule"] for f in rep["blocks"][0]["findings"]] == [
        "A8_LEF_GDS_REGISTRATION_MISMATCH"]
    assert rep["tol_um"] == 0.001


def test_outline_and_registration_are_reported_together(tmp_path):
    """Two independent defects → two findings, neither masking the other."""
    _block_list(tmp_path, ["ds"])
    _lef(tmp_path, "ds", 100.0, 100.0)
    _gds(tmp_path, "ds", build_gds(250.0, 80.0, origin_um=(-5.0, -7.0)))
    rc, rep, _ = _run(tmp_path)
    assert rc == 1
    rules = sorted(f["rule"] for f in rep["blocks"][0]["findings"])
    assert rules == ["A8_LEF_GDS_OUTLINE_MISMATCH",
                     "A8_LEF_GDS_REGISTRATION_MISMATCH"]


# ─────────────────────────── unit: parsers ─────────────────────────

def test_parse_gds_bbox_extent_keeps_the_origin(tmp_path):
    raw = build_gds(80.0, 60.0, origin_um=(-1.5, -2.5))
    assert mod.parse_gds_bbox_extent(raw) == pytest.approx(
        (-1.5, -2.5, 78.5, 57.5), abs=1e-6)
    # the width/height projection is unchanged — old callers keep working
    assert mod.parse_gds_bbox(raw) == pytest.approx((80.0, 60.0), abs=1e-6)


def test_parse_gds_bbox_extent_none_on_garbage():
    assert mod.parse_gds_bbox_extent(b"not a gds") is None
    assert mod.parse_gds_bbox(b"not a gds") is None


@pytest.mark.parametrize("text,expected,src", [
    ("MACRO m\n ORIGIN 0 0 ;\n", (0.0, 0.0), "ORIGIN"),
    ("MACRO m\n ORIGIN 0.62 30.32 ;\n", (-0.62, -30.32), "ORIGIN"),
    ("MACRO m\n FOREIGN m -0.62 -30.32 ;\n ORIGIN 0 0 ;\n",
     (-0.62, -30.32), "FOREIGN"),
    ("MACRO m\n SIZE 1 BY 1 ;\n", (0.0, 0.0), "LEF-default"),
])
def test_parse_lef_frame_ll(text, expected, src):
    x, y, s = mod.parse_lef_frame_ll(text)
    assert (x, y) == pytest.approx(expected, abs=1e-9)
    assert s == src


def test_parse_lef_frame_ll_never_returns_negative_zero():
    """-0.0 renders as "-0.000" in the finding text and reads as a real
    displacement to anyone triaging the report."""
    x, y, _ = mod.parse_lef_frame_ll("MACRO m\n ORIGIN 0 0 ;\n")
    assert str(x) == "0.0" and str(y) == "0.0"
