"""tests/test_analog_a4_corner_sweep_check.py — v1.6.35"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent / "analog_a4_corner_sweep_check.py")


def _block_list(project: Path, blocks: list) -> None:
    p = project / "phase3" / "analog"
    p.mkdir(parents=True, exist_ok=True)
    (p / "analog_block_list.json").write_text(
        json.dumps({"blocks": blocks}))


def _corners(project: Path, block: str, doc: dict) -> None:
    d = project / "phase3" / "analog" / block
    d.mkdir(parents=True, exist_ok=True)
    (d / "corner_results.json").write_text(json.dumps(doc))


def _a3_netlist(project: Path, block: str) -> None:
    """A4's declared upstream input. A sweep that produced corner results ran
    on a netlist; the gate's A4_NETLIST_ABSENT rule declines to certify one
    that has none. Fixtures asserting a clean A4 carry it."""
    d = project / "phase3" / "analog" / block
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{block}.sp").write_text(
        f"* {block} — synthetic block netlist\n"
        f".subckt {block} vdd vss vin vout\n"
        f"xm1 vout vin vss vss nch w=8 l=1\n"
        f"r1 vout vss 100k\n"
        f".ends {block}\n")


def _run(project: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(project),
         "--json", str(project / "report.json"), *args],
        capture_output=True, text=True,
    )


def test_happy_path(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    _corners(tmp_path, "ldo", {
        # WAS: no `design_content` at all. That made this "happy path" the
        # assertion that an artefact declaring simulated corners and refusing
        # to say what circuit produced them is the certifiable shape — which
        # is the pre-disclosure shape, and every stale artefact's shape.
        # A complete run says what it measured; the happy path now does too.
        "design_content": "structure_and_geometry",
        "corners": [
            {"process": "TT", "temp_c": 27, "vdd_v": 1.8,
             "simulator_run": True},
            {"process": "SS", "temp_c": -40, "vdd_v": 1.62,
             "simulator_run": True},
        ],
        "spec_results": [
            {"spec": "vout", "corner": "TT_27C", "status": "PASS"},
        ],
    })
    _a3_netlist(tmp_path, "ldo")
    r = _run(tmp_path)
    assert r.returncode == 0, r.stderr
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert rpt["verdict"] == "PASS"


def test_missing_per_block_waived(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    r = _run(tmp_path, "--block", "ldo")
    assert r.returncode == 2
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert rpt["suggested_skill"] == "ams-sim"


def test_no_simulator_run_fails(tmp_path: Path) -> None:
    """v10632 escape — every corner says simulator_run: false."""
    _block_list(tmp_path, ["ldo"])
    _corners(tmp_path, "ldo", {
        "corners": [
            {"process": "TT", "simulator_run": False},
            {"process": "SS", "simulator_run": False},
        ],
        "spec_results": [
            {"spec": "vout", "status": "PASS"},  # claim is moot
        ],
    })
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert any("A4_NO_SIMULATOR_RUN" in f["rule"]
               for f in rpt["findings"])


def test_spec_fail_at_corner_fails(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    _corners(tmp_path, "ldo", {
        "corners": [{"process": "TT", "simulator_run": True}],
        "spec_results": [
            {"spec": "vout", "corner": "SS_125C", "status": "FAIL"},
        ],
    })
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert any("A4_NO_PASS_SPEC" in f["rule"] for f in rpt["findings"])


def test_no_corners_fails(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    _corners(tmp_path, "ldo", {"corners": []})
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert any("A4_NO_CORNERS" in f["rule"] for f in rpt["findings"])


def test_no_block_list_vacuous(tmp_path: Path) -> None:
    r = _run(tmp_path)
    assert r.returncode == 0
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert rpt["verdict"] == "VACUOUS_PASS"
