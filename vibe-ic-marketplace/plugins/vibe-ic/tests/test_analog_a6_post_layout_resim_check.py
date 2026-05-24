"""tests/test_analog_a6_post_layout_resim_check.py — v1.6.35"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent
        / "programs" / "analog_a6_post_layout_resim_check.py")


def _block_list(project: Path, blocks: list) -> None:
    p = project / "phase3" / "analog"
    p.mkdir(parents=True, exist_ok=True)
    (p / "analog_block_list.json").write_text(
        json.dumps({"blocks": blocks}))


def _resim(project: Path, block: str, doc: dict) -> None:
    d = project / "phase3" / "analog" / block
    d.mkdir(parents=True, exist_ok=True)
    (d / "pre_vs_post.json").write_text(json.dumps(doc))


def _corners(project: Path, block: str, doc: dict) -> None:
    d = project / "phase3" / "analog" / block
    d.mkdir(parents=True, exist_ok=True)
    (d / "corner_results.json").write_text(json.dumps(doc))


def _run(project: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(project),
         "--json", str(project / "report.json"), *args],
        capture_output=True, text=True,
    )


def test_happy_path_specs(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    _resim(tmp_path, "ldo", {
        "specs": [
            {"name": "vout", "pre_value": 1.8, "post_value": 1.78,
             "delta_pct": -1.1},
            {"name": "psrr", "pre_value": 60, "post_value": 58,
             "delta_pct": -3.3},
        ],
    })
    r = _run(tmp_path)
    assert r.returncode == 0, r.stderr
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert rpt["verdict"] == "PASS"


def test_happy_path_pre_post_dict(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    _resim(tmp_path, "ldo", {
        "pre": {"vout": 1.8, "psrr": 60},
        "post": {"vout": 1.78, "psrr": 58},
    })
    r = _run(tmp_path)
    assert r.returncode == 0


def test_missing_per_block_waived(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    r = _run(tmp_path, "--block", "ldo")
    assert r.returncode == 2
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert rpt["suggested_skill"] == "analog-extraction-resim"


def test_delta_too_big_fails(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    _resim(tmp_path, "ldo", {
        "specs": [
            {"name": "vout", "pre_value": 1.8, "post_value": 1.5,
             "delta_pct": -16.7},
        ],
    })
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert any("A6_POSTSIM_DELTA_TOO_BIG" in f["rule"]
               for f in rpt["findings"])


def test_a4_no_simulator_run_forces_a6_fail(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    _corners(tmp_path, "ldo", {
        "corners": [{"process": "TT", "simulator_run": False}]})
    _resim(tmp_path, "ldo", {
        "specs": [
            {"name": "vout", "pre_value": 1.8, "post_value": 1.78,
             "delta_pct": -1.1},
        ],
    })
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert any("A6_POSTSIM_NO_A4_SIM" in f["rule"]
               for f in rpt["findings"])


def test_no_specs_fails(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    _resim(tmp_path, "ldo", {"comment": "nothing useful"})
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert any("A6_POSTSIM_NO_SPECS" in f["rule"]
               for f in rpt["findings"])


def test_no_block_list_vacuous(tmp_path: Path) -> None:
    r = _run(tmp_path)
    assert r.returncode == 0
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert rpt["verdict"] == "VACUOUS_PASS"
