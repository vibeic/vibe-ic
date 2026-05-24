"""tests/test_analog_a5_layout_check.py — v1.6.35"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent
        / "programs" / "analog_a5_layout_check.py")


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


def test_happy_path_gds_alternative(tmp_path: Path) -> None:
    """Either layout.mag OR <block>.gds satisfies A5."""
    _block_list(tmp_path, ["ldo"])
    d = tmp_path / "phase3" / "analog" / "ldo"
    d.mkdir(parents=True, exist_ok=True)
    (d / "ldo.gds").write_bytes(b"\x00\x06\x00\x02" + b"\x00" * 508)
    (d / "drc_clean.flag").write_text("clean\n")
    (d / "lvs_match.flag").write_text("match\n")
    r = _run(tmp_path)
    assert r.returncode == 0


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
