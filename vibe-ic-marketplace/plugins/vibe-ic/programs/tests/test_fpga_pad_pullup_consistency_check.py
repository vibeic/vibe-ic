#!/usr/bin/env python3
"""Tests for fpga_pad_pullup_consistency_check.py — see ROOT_CAUSE Area 5."""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent / \
    "fpga_pad_pullup_consistency_check.py"


def _run(tmp_path: Path):
    return subprocess.run(
        [sys.executable, str(PROG), str(tmp_path)],
        capture_output=True, text=True,
    )


def _l5(tmp_path: Path, pads: list):
    docs = tmp_path / "phase1" / "generated_docs"
    docs.mkdir(parents=True, exist_ok=True)
    (docs / "L5_ADI_SPEC.json").write_text(json.dumps({
        "pad_definitions": pads,
    }))


def _qsf(tmp_path: Path, body: str, name: str = "project.qsf"):
    fpga = tmp_path / "phase2" / "stage1" / "fpga"
    fpga.mkdir(parents=True, exist_ok=True)
    (fpga / name).write_text(body)


def test_no_qsf_silent_pass(tmp_path):
    """No *.qsf → not an FPGA project, skip."""
    _l5(tmp_path, [{"name": "ID_BUS", "external_pullup": True,
                    "fpga_alias": "GPIO_0"}])
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "not an FPGA" in r.stdout


def test_no_l5_silent_pass(tmp_path):
    _qsf(tmp_path, "")
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "no L5" in r.stdout


def test_no_external_pullup_field_silent_pass(tmp_path):
    """L5 has pads but none declare external_pullup → skip."""
    _l5(tmp_path, [{"name": "ID_BUS", "fpga_alias": "GPIO_0"}])
    _qsf(tmp_path, "set_instance_assignment -name WEAK_PULL_UP_RESISTOR "
                   "ON -to GPIO_0\n")
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "no pad declares external_pullup" in r.stdout


def test_external_true_no_qsf_pullup_passes(tmp_path):
    """external_pullup=true (board has 5.1kΩ) AND QSF has no pull-up → PASS."""
    _l5(tmp_path, [{"name": "ID_BUS", "external_pullup": True,
                    "fpga_alias": "GPIO_0"}])
    _qsf(tmp_path, "set_instance_assignment -name IO_STANDARD "
                   "\"3.3-V LVCMOS\" -to GPIO_0\n")
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


def test_external_true_with_qsf_pullup_fails(tmp_path):
    """external_pullup=true AND QSF adds pull-up → FAIL (benchmark_a fingerprint)."""
    _l5(tmp_path, [{"name": "ID_BUS", "external_pullup": True,
                    "fpga_alias": "GPIO_0"}])
    _qsf(tmp_path, "set_instance_assignment -name WEAK_PULL_UP_RESISTOR "
                   "ON -to GPIO_0\n")
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "REMOVE the QSF pull-up" in r.stdout


def test_external_false_with_qsf_pullup_passes(tmp_path):
    """external_pullup=false (chip relies on internal source) AND QSF
    provides one → PASS."""
    _l5(tmp_path, [{"name": "WAKE", "external_pullup": False,
                    "fpga_alias": "GPIO_1"}])
    _qsf(tmp_path, "set_instance_assignment -name WEAK_PULL_UP_RESISTOR "
                   "ON -to GPIO_1\n")
    r = _run(tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


def test_external_false_no_qsf_pullup_fails(tmp_path):
    """external_pullup=false AND QSF has no pull-up → bus floats, FAIL."""
    _l5(tmp_path, [{"name": "WAKE", "external_pullup": False,
                    "fpga_alias": "GPIO_1"}])
    _qsf(tmp_path, "set_instance_assignment -name IO_STANDARD "
                   "\"3.3-V LVCMOS\" -to GPIO_1\n")
    r = _run(tmp_path)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "WEAK_PULL_UP_RESISTOR ON -to GPIO_1" in r.stdout


def test_waiver_skips(tmp_path):
    _l5(tmp_path, [{"name": "ID_BUS", "external_pullup": True,
                    "fpga_alias": "GPIO_0"}])
    _qsf(tmp_path, "set_instance_assignment -name WEAK_PULL_UP_RESISTOR "
                   "ON -to GPIO_0\n")
    (tmp_path / "waivers.json").write_text(json.dumps({
        "fpga_pad_pullup_consistency_alternative":
            "Lab board lacks 5.1kΩ; rely on FPGA pull-up for prototype",
    }))
    r = _run(tmp_path)
    assert r.returncode == 0
    assert "PASS_WITH_WAIVER" in r.stdout


def test_alias_list_form_handled(tmp_path):
    """fpga_alias as a list of strings → check each alias."""
    _l5(tmp_path, [{"name": "ID_BUS", "external_pullup": True,
                    "fpga_alias": ["GPIO_0", "GPIO_5"]}])
    _qsf(tmp_path, "set_instance_assignment -name WEAK_PULL_UP_RESISTOR "
                   "ON -to GPIO_5\n")
    r = _run(tmp_path)
    # Either alias matching the pull-up assignment counts as failing
    # (chip declares external pull-up but QSF has internal one).
    assert r.returncode == 1
    assert "GPIO_5" in r.stdout
