"""tests/test_analog_a2_topology_select_check.py — v1.6.35"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent
        / "programs" / "analog_a2_topology_select_check.py")


def _block_list(project: Path, blocks: list) -> None:
    p = project / "phase3" / "analog"
    p.mkdir(parents=True, exist_ok=True)
    (p / "analog_block_list.json").write_text(
        json.dumps({"blocks": blocks}))


def _topology(project: Path, block: str, body: str) -> None:
    d = project / "phase3" / "analog" / block
    d.mkdir(parents=True, exist_ok=True)
    (d / "topology.md").write_text(body)


def _run(project: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(project),
         "--json", str(project / "report.json"), *args],
        capture_output=True, text=True,
    )


def test_happy_path(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    _topology(tmp_path, "ldo",
              "# LDO topology\n\n"
              "Topology selected: PMOS pass-transistor regulator with "
              "cascode error amplifier and current-mirror bias network. "
              "Loop bandwidth ~1MHz with phase margin > 60deg.\n"
              + "Stage detail line.\n" * 5)
    r = _run(tmp_path)
    assert r.returncode == 0, r.stderr
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert rpt["verdict"] == "PASS"


def test_missing_per_block_waived(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    r = _run(tmp_path, "--block", "ldo")
    assert r.returncode == 2
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert rpt["suggested_skill"] == "analog-topology-select"


def test_too_small_fails(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    _topology(tmp_path, "ldo", "TBD\n")  # < 200B
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert any("A2_TOPOLOGY_EMPTY" in f["rule"] for f in rpt["findings"])


def test_no_primitive_fails(tmp_path: Path) -> None:
    """Long file but no transistor/circuit primitive keyword → FAIL."""
    _block_list(tmp_path, ["ldo"])
    _topology(tmp_path, "ldo",
              "# Some heading\n\n"
              + "Lorem ipsum dolor sit amet consectetur adipiscing elit "
                "sed do eiusmod tempor incididunt ut labore et dolore "
                "magna aliqua ut enim ad minim veniam quis nostrud "
                "exercitation ullamco laboris nisi ut aliquip ex ea "
                "commodo consequat. Duis aute irure dolor in.\n")
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert any("A2_TOPOLOGY_NO_PRIMITIVE" in f["rule"]
               for f in rpt["findings"])


def test_multiblock_one_failing(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo", "bandgap"])
    _topology(tmp_path, "ldo",
              "Topology selected: cascode amplifier with current "
              "mirror loads and bandgap reference.\n" * 5)
    _topology(tmp_path, "bandgap", "TBD\n")
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert rpt["verdict"] == "FAIL"
    assert any(f["block"] == "bandgap" for f in rpt["findings"])


def test_no_block_list_vacuous(tmp_path: Path) -> None:
    r = _run(tmp_path)
    assert r.returncode == 0
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert rpt["verdict"] == "VACUOUS_PASS"
