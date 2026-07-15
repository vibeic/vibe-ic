"""tests/test_analog_a5_layout_check.py — v1.6.35"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent / "analog_a5_layout_check.py")


def _block_list(project: Path, blocks: list) -> None:
    p = project / "phase3" / "analog"
    p.mkdir(parents=True, exist_ok=True)
    (p / "analog_block_list.json").write_text(
        json.dumps({"blocks": blocks}))


def _layout_full(project: Path, block: str) -> None:
    d = project / "phase3" / "analog" / block
    d.mkdir(parents=True, exist_ok=True)
    (d / "layout.mag").write_text(
        "magic\ntech sky130A\n" + "rect 0 0 100 100\n" * 20)
    (d / "drc_clean.flag").write_text("DRC clean: 0 errors\n")
    (d / "lvs_match.flag").write_text("LVS match: 0 mismatches\n")


def _run(project: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(project),
         "--json", str(project / "report.json"), *args],
        capture_output=True, text=True,
    )


def test_happy_path_mag(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    _layout_full(tmp_path, "ldo")
    r = _run(tmp_path)
    assert r.returncode == 0, r.stderr
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert rpt["verdict"] == "PASS"


# A minimal real GDS stream: one BOUNDARY (0x08) geometry record followed by
# zero padding so it clears the 200-byte size bar AND carries real geometry.
_GDS_WITH_GEOMETRY = b"\x00\x04\x08\x00" + b"\x00" * 508
# An empty-geometry GDS: a HEADER record + padding, NO geometry record — the
# exact shape an `eda_analog_layout` `readspice`+`gds write` (no placement)
# streams. ORGANIC #144: this must now FAIL, not pass on size alone.
_GDS_EMPTY_GEOMETRY = b"\x00\x06\x00\x02" + b"\x00" * 508


def test_happy_path_gds_alternative(tmp_path: Path) -> None:
    """Either layout.mag OR <block>.gds satisfies A5 — when the GDS carries
    real placed geometry (ORGANIC #144: at least one geometry record)."""
    _block_list(tmp_path, ["ldo"])
    d = tmp_path / "phase3" / "analog" / "ldo"
    d.mkdir(parents=True, exist_ok=True)
    (d / "ldo.gds").write_bytes(_GDS_WITH_GEOMETRY)
    (d / "drc_clean.flag").write_text("clean\n")
    (d / "lvs_match.flag").write_text("match\n")
    r = _run(tmp_path)
    assert r.returncode == 0, r.stderr


def test_empty_geometry_gds_fails(tmp_path: Path) -> None:
    """ORGANIC #144 no-leak — a size-passing but geometry-EMPTY GDS (the
    `readspice`+`gds write` empty stream) FAILs the tightened gate."""
    _block_list(tmp_path, ["ldo"])
    d = tmp_path / "phase3" / "analog" / "ldo"
    d.mkdir(parents=True, exist_ok=True)
    (d / "ldo.gds").write_bytes(_GDS_EMPTY_GEOMETRY)
    (d / "drc_clean.flag").write_text("clean\n")
    (d / "lvs_match.flag").write_text("match\n")
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout
    rpt = json.loads((tmp_path / "report.json").read_text())
    rules = {f["rule"] for f in rpt.get("findings", [])}
    assert "A5_LAYOUT_EMPTY_GEOMETRY" in rules, rpt


def test_padded_mag_stub_fails(tmp_path: Path) -> None:
    """ORGANIC #144 no-leak — the runner's own deterministic A5 stub
    (`layout.mag` = magic header + `"x"*400` padding, no placed geometry)
    now FAILs on the geometry assertion instead of passing on size."""
    _block_list(tmp_path, ["ldo"])
    d = tmp_path / "phase3" / "analog" / "ldo"
    d.mkdir(parents=True, exist_ok=True)
    (d / "layout.mag").write_text(
        "magic\ntech sky130A\n# deterministic-stub padding "
        + "x" * 400 + "\n")
    (d / "drc_clean.flag").write_text("clean\n")
    (d / "lvs_match.flag").write_text("match\n")
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout
    rpt = json.loads((tmp_path / "report.json").read_text())
    rules = {f["rule"] for f in rpt.get("findings", [])}
    assert "A5_LAYOUT_EMPTY_GEOMETRY" in rules, rpt


def test_empty_geometry_mag_no_marker_fails(tmp_path: Path) -> None:
    """A geometry-empty .mag with NO stub marker (e.g. just a header + a
    long comment) still FAILs — the geometry parse, not just the marker,
    is load-bearing."""
    _block_list(tmp_path, ["ldo"])
    d = tmp_path / "phase3" / "analog" / "ldo"
    d.mkdir(parents=True, exist_ok=True)
    (d / "layout.mag").write_text(
        "magic\ntech sky130A\ntimestamp 0\n"
        + "# placeholder header only, no paint\n" * 20)
    (d / "drc_clean.flag").write_text("clean\n")
    (d / "lvs_match.flag").write_text("match\n")
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout


def test_real_mag_with_instances_passes(tmp_path: Path) -> None:
    """A .mag whose geometry is cell instances (`use` lines) — no paint
    rects — still passes (instance-based placement is real geometry)."""
    _block_list(tmp_path, ["ldo"])
    d = tmp_path / "phase3" / "analog" / "ldo"
    d.mkdir(parents=True, exist_ok=True)
    body = "magic\ntech sky130A\ntimestamp 0\n"
    for i in range(8):
        body += (f"use sky130_fd_pr__nfet_01v8 m{i}\n"
                 f"transform 1 0 0 0 1 {i*10}\nbox 0 0 100 100\n")
    (d / "layout.mag").write_text(body)
    (d / "drc_clean.flag").write_text("clean\n")
    (d / "lvs_match.flag").write_text("match\n")
    r = _run(tmp_path)
    assert r.returncode == 0, r.stderr


def test_missing_per_block_waived(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    r = _run(tmp_path, "--block", "ldo")
    assert r.returncode == 2
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert rpt["suggested_skill"] == "analog-layout"


def test_drc_flag_missing_fails(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    _layout_full(tmp_path, "ldo")
    (tmp_path / "phase3" / "analog" / "ldo" / "drc_clean.flag").unlink()
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert any("A5_DRC_FLAG_MISSING" in f["rule"]
               for f in rpt["findings"])


def test_lvs_flag_missing_fails(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    _layout_full(tmp_path, "ldo")
    (tmp_path / "phase3" / "analog" / "ldo" / "lvs_match.flag").unlink()
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert any("A5_LVS_FLAG_MISSING" in f["rule"]
               for f in rpt["findings"])


def test_layout_too_small_fails(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    d = tmp_path / "phase3" / "analog" / "ldo"
    d.mkdir(parents=True, exist_ok=True)
    (d / "layout.mag").write_text("magic\n")  # < 200B
    (d / "drc_clean.flag").write_text("clean\n")
    (d / "lvs_match.flag").write_text("match\n")
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert any("A5_LAYOUT_TOO_SMALL" in f["rule"]
               for f in rpt["findings"])


def test_no_block_list_vacuous(tmp_path: Path) -> None:
    r = _run(tmp_path)
    assert r.returncode == 0
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert rpt["verdict"] == "VACUOUS_PASS"
