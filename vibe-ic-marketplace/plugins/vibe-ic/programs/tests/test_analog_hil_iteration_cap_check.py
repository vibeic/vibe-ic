"""tests/test_analog_hil_iteration_cap_check.py

Covers the hard 3-iteration cap counter + honest SKIP/ERROR on absent / garbage.
"""
from __future__ import annotations

import json
from pathlib import Path

from programs.analog_hil_iteration_cap_check import (
    main, evaluate_file, DEFAULT_MAX_HW_ITERS,
)


def _write(path: Path, body: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body))
    return path


def test_pass_at_cap(tmp_path):
    f = _write(tmp_path / "hw_tuning_report.json", {
        "block_name": "ldo", "total_iterations": {"spice": 5, "hardware": 3},
    })
    bc = evaluate_file(f, DEFAULT_MAX_HW_ITERS)
    assert bc.verdict == "PASS" and bc.hw_iterations == 3
    assert main(["--file", str(f)]) == 0


def test_pass_zero_iters(tmp_path):
    f = _write(tmp_path / "hw_tuning_report.json", {
        "block_name": "ldo", "total_iterations": {"spice": 1, "hardware": 0},
    })
    assert evaluate_file(f, DEFAULT_MAX_HW_ITERS).verdict == "PASS"


def test_fail_exceeds_cap(tmp_path):
    f = _write(tmp_path / "hw_tuning_report.json", {
        "block_name": "ldo", "total_iterations": {"spice": 5, "hardware": 4},
    })
    bc = evaluate_file(f, DEFAULT_MAX_HW_ITERS)
    assert bc.verdict == "FAIL" and bc.hw_iterations == 4
    assert main(["--file", str(f)]) == 1


def test_count_from_list_form(tmp_path):
    f = _write(tmp_path / "hw_tuning_report.json", {
        "block_name": "ldo",
        "hardware_iterations": [{"iter": 1}, {"iter": 2}, {"iter": 3}, {"iter": 4}],
    })
    bc = evaluate_file(f, DEFAULT_MAX_HW_ITERS)
    assert bc.verdict == "FAIL" and bc.hw_iterations == 4


def test_custom_cap_overrides(tmp_path):
    f = _write(tmp_path / "hw_tuning_report.json", {
        "block_name": "ldo", "total_iterations": {"spice": 5, "hardware": 5},
    })
    assert evaluate_file(f, 5).verdict == "PASS"
    assert evaluate_file(f, 4).verdict == "FAIL"
    assert main(["--file", str(f), "--max-iters", "5"]) == 0


def test_missing_count_is_error(tmp_path):
    # report exists but has no hardware iteration field → ERROR, never vacuous PASS
    f = _write(tmp_path / "hw_tuning_report.json", {"block_name": "ldo"})
    assert evaluate_file(f, DEFAULT_MAX_HW_ITERS).verdict == "ERROR"
    assert main(["--file", str(f)]) == 2


def test_negative_count_is_error(tmp_path):
    f = _write(tmp_path / "hw_tuning_report.json", {
        "block_name": "ldo", "total_iterations": {"spice": 1, "hardware": -2},
    })
    assert evaluate_file(f, DEFAULT_MAX_HW_ITERS).verdict == "ERROR"


def test_garbage_file_is_error(tmp_path):
    f = tmp_path / "hw_tuning_report.json"
    f.write_text("not json at all")
    assert evaluate_file(f, DEFAULT_MAX_HW_ITERS).verdict == "ERROR"
    assert main(["--file", str(f)]) == 2


def test_skip_empty_project(tmp_path):
    (tmp_path / "phase3" / "analog").mkdir(parents=True)
    assert main([str(tmp_path)]) == 0


def test_missing_file_errors(tmp_path):
    assert main(["--file", str(tmp_path / "nope.json")]) == 2
