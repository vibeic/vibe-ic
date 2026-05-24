"""tests/test_analog_a3_netlist_gen_check.py — v1.6.35"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = (Path(__file__).resolve().parent.parent
        / "programs" / "analog_a3_netlist_gen_check.py")


def _block_list(project: Path, blocks: list) -> None:
    p = project / "phase3" / "analog"
    p.mkdir(parents=True, exist_ok=True)
    (p / "analog_block_list.json").write_text(
        json.dumps({"blocks": blocks}))


def _sp(project: Path, block: str, body: str) -> None:
    d = project / "phase3" / "analog" / block
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{block}.sp").write_text(body)


def _run(project: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(project),
         "--json", str(project / "report.json"), *args],
        capture_output=True, text=True,
    )


_REAL_NETLIST = (
    "* ldo netlist\n"
    ".subckt ldo VDD VSS VOUT VREF EN\n"
    + "M1 net1 VREF VSS VSS nmos w=2u l=0.18u\n" * 6
    + ".ends ldo\n.end\n"
)


def test_happy_path(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    _sp(tmp_path, "ldo", _REAL_NETLIST)
    r = _run(tmp_path)
    assert r.returncode == 0, r.stderr
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert rpt["verdict"] == "PASS"


def test_missing_per_block_waived(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    r = _run(tmp_path, "--block", "ldo")
    assert r.returncode == 2
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert rpt["suggested_skill"] == "analog-netlist-gen"


def test_tiny_stub_fails(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    _sp(tmp_path, "ldo", "* netlist stub\n.end\n")
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert any("A3_NETLIST_TOO_SMALL" in f["rule"]
               for f in rpt["findings"])


def test_no_subckt_fails(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo"])
    _sp(tmp_path, "ldo",
        "* simulation script (no .subckt)\n"
        + "M1 net1 VREF VSS VSS nmos w=2u l=0.18u\n" * 12
        + ".end\n")
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert any("A3_NETLIST_NO_SUBCKT" in f["rule"]
               for f in rpt["findings"])


def test_multiblock_one_fails(tmp_path: Path) -> None:
    _block_list(tmp_path, ["ldo", "bandgap"])
    _sp(tmp_path, "ldo", _REAL_NETLIST)
    _sp(tmp_path, "bandgap", "* stub\n.end\n")
    r = _run(tmp_path)
    assert r.returncode == 1
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert any(f["block"] == "bandgap" for f in rpt["findings"])


def test_no_block_list_vacuous(tmp_path: Path) -> None:
    r = _run(tmp_path)
    assert r.returncode == 0
    rpt = json.loads((tmp_path / "report.json").read_text())
    assert rpt["verdict"] == "VACUOUS_PASS"
