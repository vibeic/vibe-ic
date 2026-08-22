"""tests/test_analog_hil_single_knob_check.py

Covers the one-knob-per-iteration sizing diff + honest SKIP/ERROR.
"""
from __future__ import annotations

import json
from pathlib import Path

from programs.analog_hil_single_knob_check import main, evaluate_file


def _write(path: Path, body: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body))
    return path


_BASE = {"M1": {"W": 4.0, "L": 0.5, "M": 2},
         "M2": {"W": 8.0, "L": 0.5, "M": 1}, "Rfb": 50000}


def test_pass_single_knob_each_step(tmp_path):
    s1 = json.loads(json.dumps(_BASE))
    s2 = json.loads(json.dumps(_BASE)); s2["Rfb"] = 52000          # 1 knob
    s3 = json.loads(json.dumps(s2));    s3["M1"]["W"] = 4.5        # 1 knob
    f = _write(tmp_path / "hw_sizing_history.json", {
        "block_name": "ldo",
        "iterations": [{"iter": 1, "sizing": s1},
                       {"iter": 2, "sizing": s2},
                       {"iter": 3, "sizing": s3}],
    })
    bk = evaluate_file(f)
    assert bk.verdict == "PASS"
    assert main(["--file", str(f)]) == 0


def test_pass_no_change(tmp_path):
    f = _write(tmp_path / "hw_sizing_history.json", {
        "block_name": "ldo",
        "iterations": [{"iter": 1, "sizing": _BASE},
                       {"iter": 2, "sizing": _BASE}],
    })
    assert evaluate_file(f).verdict == "PASS"


def test_fail_two_knobs_in_one_step(tmp_path):
    s1 = json.loads(json.dumps(_BASE))
    s2 = json.loads(json.dumps(_BASE))
    s2["Rfb"] = 52000
    s2["M1"]["W"] = 5.0     # second knob changed in the SAME transition
    f = _write(tmp_path / "hw_sizing_history.json", {
        "block_name": "ldo",
        "iterations": [{"iter": 1, "sizing": s1}, {"iter": 2, "sizing": s2}],
    })
    bk = evaluate_file(f)
    assert bk.verdict == "FAIL"
    assert bk.steps[0].n_changed == 2
    assert main(["--file", str(f)]) == 1


def test_fail_added_device_counts_as_knob(tmp_path):
    s1 = json.loads(json.dumps(_BASE))
    s2 = json.loads(json.dumps(_BASE))
    s2["Rfb"] = 52000
    s2["Cc"] = 1e-12        # added leaf + changed leaf = 2 knobs
    f = _write(tmp_path / "hw_sizing_history.json", {
        "block_name": "ldo",
        "iterations": [{"iter": 1, "sizing": s1}, {"iter": 2, "sizing": s2}],
    })
    assert evaluate_file(f).verdict == "FAIL"


def test_skip_single_iteration(tmp_path):
    f = _write(tmp_path / "hw_sizing_history.json", {
        "block_name": "ldo", "iterations": [{"iter": 1, "sizing": _BASE}],
    })
    assert evaluate_file(f).verdict == "SKIP"


def test_error_missing_sizing(tmp_path):
    f = _write(tmp_path / "hw_sizing_history.json", {
        "block_name": "ldo",
        "iterations": [{"iter": 1, "sizing": _BASE}, {"iter": 2}],
    })
    assert evaluate_file(f).verdict == "ERROR"
    # #693 — exit 1, NOT 2. Exit 2 is `flow_compliance_check`'s cannot-judge
    # tier (mapped to __VACUOUS_HINT__ = a pass on a blocking slot, "n/a (input
    # not present)" on an advisory one), so "a garbage file must not vacuously
    # pass" was doing exactly that.
    assert main(["--file", str(f)]) == 1


def test_error_iterations_not_list(tmp_path):
    f = _write(tmp_path / "hw_sizing_history.json", {
        "block_name": "ldo", "iterations": "nope",
    })
    assert evaluate_file(f).verdict == "ERROR"


def test_garbage_file_is_error(tmp_path):
    f = tmp_path / "hw_sizing_history.json"
    f.write_text("<<< not json")
    assert evaluate_file(f).verdict == "ERROR"
    assert main(["--file", str(f)]) == 1


def test_no_history_is_not_checked_not_pass(tmp_path):
    # #693 — no artefact is exit 2 = NOT CHECKED, NOT exit 0.
    (tmp_path / "phase3" / "analog").mkdir(parents=True)
    assert main([str(tmp_path)]) == 2


def test_missing_file_errors(tmp_path):
    assert main(["--file", str(tmp_path / "nope.json")]) == 2
