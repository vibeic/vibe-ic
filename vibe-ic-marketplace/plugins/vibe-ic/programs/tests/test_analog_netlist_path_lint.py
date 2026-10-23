#!/usr/bin/env python3
"""Tests for analog_netlist_path_lint.py."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent / "analog_netlist_path_lint.py"

GOOD = """\
* whitelisted PDK paths + a relative include
.include /foss/pdks/gf180mcuD/libs.tech/ngspice/design.ngspice
.lib /foss/pdks/gf180mcuD/libs.tech/ngspice/sm141064.ngspice typical
.include ./amp_models.inc
.subckt amp vin vout vss
.ends
"""

BAD = """\
* hardcoded absolute non-PDK path
.include /home/testuser/scratch/my_models.lib
.lib /foss/pdks/gf180mcuD/libs.tech/ngspice/sm141064.ngspice typical
.subckt amp vin vout vss
.ends
"""

NO_INCLUDE = """\
* no include directives at all
.subckt amp vin vout vss
XMP1 vout gate vin vin pfet_03v3 W=20u L=4u
.ends
"""


def _run(tmp_path: Path, block=None):
    return subprocess.run(
        [sys.executable, str(PROG), str(tmp_path),
         *(["--block", block] if block is not None else []),
         "--json", str(tmp_path / "r.json")],
        capture_output=True, text=True)


def _write(tmp_path: Path, name: str, content: str):
    d = tmp_path / "analog" / "amp"
    d.mkdir(parents=True, exist_ok=True)
    (d / name).write_text(content)


def test_pass_whitelisted_paths(tmp_path):
    _write(tmp_path, "amp.sp", GOOD)
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    rep = json.loads((tmp_path / "r.json").read_text())
    assert rep["passed"] is True
    assert rep["summary"]["non_whitelisted_absolute_paths"] == 0
    assert rep["summary"]["files_with_includes"] == 1


def test_fail_hardcoded_home_path(tmp_path):
    _write(tmp_path, "amp.sp", BAD)
    r = _run(tmp_path)
    assert r.returncode == 1
    rep = json.loads((tmp_path / "r.json").read_text())
    assert rep["passed"] is False
    rules = {f["rule"] for f in rep["findings"]}
    assert "NON_WHITELISTED_ABSOLUTE_PATH" in rules


def test_edge_no_includes_no_false_pass_claim(tmp_path):
    _write(tmp_path, "amp.sp", NO_INCLUDE)
    r = _run(tmp_path)
    # no absolute paths => PASS, but files_with_includes must be 0 (visible)
    assert r.returncode == 0
    rep = json.loads((tmp_path / "r.json").read_text())
    assert rep["summary"]["files_with_includes"] == 0
    assert rep["summary"]["files_checked"] == 1


def test_edge_no_sp_skips(tmp_path):
    """WAS `assert r.returncode == 0`, and that line WAS the #511 defect: it
    pinned a self-skip as a passing exit, which is what made
    `[PASS] analog_netlist_path_lint` over nothing byte-identical to the same
    line over a linted deck. The skip is unchanged — it is the same branch, the
    same `skipped: True`; what changed is that it now says so and lands in the
    NOT-CHECKED tier. See
    `test_issue511_path_lint_states_what_it_read.py` for the reproduction."""
    (tmp_path / "analog").mkdir()
    r = _run(tmp_path)
    assert r.returncode == 2, r.stdout + r.stderr
    rep = json.loads((tmp_path / "r.json").read_text())
    assert rep["summary"].get("skipped") is True
    assert rep["verdict"] == "VACUOUS_PASS"
    assert rep["summary"]["denominator"]["examined"] == 0


def test_edge_missing_dir_exit2(tmp_path):
    r = subprocess.run(
        [sys.executable, str(PROG), str(tmp_path / "nope")],
        capture_output=True, text=True)
    assert r.returncode == 2


@pytest.mark.parametrize("root", ["phase3/analog", "phase2/analog", "analog"])
@pytest.mark.parametrize("selected,rc,checked", [(None, 1, 2), ("clean", 0, 1),
                                              ("broken", 1, 1), ("absent", 2, 0)])
def test_explicit_block_scope_preserves_default_and_selected_defect(tmp_path, root, selected, rc, checked):
    for name, body in (("clean", GOOD), ("broken", BAD)):
        folder = tmp_path / root / name / "derived"
        folder.mkdir(parents=True)
        (folder / "deck.sp").write_text(body)
    result = _run(tmp_path, selected)
    assert result.returncode == rc, result.stdout + result.stderr
    report = json.loads((tmp_path / "r.json").read_text())
    assert report["summary"]["files_checked"] == checked
