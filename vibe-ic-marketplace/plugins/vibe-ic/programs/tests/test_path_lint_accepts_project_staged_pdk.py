"""Path lint accepts the project's OWN staged PDK copy (u_hawaii_adc round-5).

WHAT WENT WRONG (measured, v1.14.71): two shipped rules force one binding —
`pdk_analog_completeness_check` REQUIRES the project to carry its model libs
under `input/pdk/**` (a run stands on input/ alone), and the availability
resolver prefers that staged copy — so A3 binds
`<project>/input/pdk/models/<lib>` by absolute path. `analog_netlist_path_lint`
then refused every such deck (`NON_WHITELISTED_ABSOLUTE_PATH`), so A3's own
render was rejected by the shipped checkers and the block dead-ended in WAIVE.
An author following both rules had no legal output.

THE RULE. An absolute include is acceptable when it is a canonical PDK root
(`/foss/pdks/…`) OR resolves INSIDE this project's tree (it travels with the
project — recorded as an INFO `PROJECT_INTERNAL_ABSOLUTE_PATH`, never silent).
An absolute path outside both (a foreign home dir, /tmp) stays refused — the
pre-existing pin, held.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / "analog_netlist_path_lint.py"


def _run(project: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(PROG), str(project), "--json",
         str(project / "r.json")],
        capture_output=True, text=True, timeout=60)


def _project(tmp_path: Path, lib_line: str) -> Path:
    bdir = tmp_path / "phase3" / "analog" / "blk"
    bdir.mkdir(parents=True)
    (bdir / "blk.sp").write_text(
        f"* blk\n{lib_line}\n.subckt blk a b\nr1 a b 1k\n.ends blk\n")
    return tmp_path


def test_project_staged_pdk_copy_is_accepted_and_stated(tmp_path: Path) -> None:
    staged = tmp_path / "input" / "pdk" / "models" / "cornerMOShv.lib"
    staged.parent.mkdir(parents=True)
    staged.write_text("* model lib\n")
    project = _project(tmp_path, f".lib {staged} mos_tt")
    r = _run(project)
    assert r.returncode == 0, r.stdout + r.stderr
    rep = json.loads((project / "r.json").read_text())
    assert rep["passed"] is True
    rules = {f["rule"] for f in rep["findings"]}
    assert "PROJECT_INTERNAL_ABSOLUTE_PATH" in rules, (
        "the accepted project-internal binding must be STATED, not silent")


def test_foreign_absolute_path_still_refused(tmp_path: Path) -> None:
    project = _project(tmp_path,
                       ".lib /home/somebody_else/models/foo.lib tt")
    r = _run(project)
    assert r.returncode == 1
    rep = json.loads((project / "r.json").read_text())
    rules = {f["rule"] for f in rep["findings"]}
    assert "NON_WHITELISTED_ABSOLUTE_PATH" in rules


def test_canonical_pdk_root_still_passes_without_the_info_marker(
        tmp_path: Path) -> None:
    project = _project(
        tmp_path,
        ".lib /foss/pdks/famx/libs.tech/ngspice/models/corner.lib tt")
    r = _run(project)
    assert r.returncode == 0
    rep = json.loads((project / "r.json").read_text())
    rules = {f["rule"] for f in rep["findings"]}
    assert "PROJECT_INTERNAL_ABSOLUTE_PATH" not in rules
