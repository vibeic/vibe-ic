"""tests/test_analog_hil_three_way_verdict.py

Covers the four-row decision table + honest SKIP/FAIL on absent / garbage input.
"""
from __future__ import annotations

import json
from pathlib import Path

from programs.analog_hil_three_way_verdict import (
    main, evaluate_file, _table_lookup, HW_SPICE_WARN_PCT,
)


def _write(path: Path, body: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body))
    return path


# ---- pure table lookup -----------------------------------------------------

def test_table_lookup_all_four_rows():
    assert _table_lookup(True, True, 5.0) == "CONVERGED"
    assert _table_lookup(True, True, HW_SPICE_WARN_PCT + 1) == "CONVERGED_WARNING"
    assert _table_lookup(True, False, 0.0) == "MODEL_INACCURACY"
    assert _table_lookup(False, True, 0.0) == "BACK_TO_PHASE1"
    assert _table_lookup(False, False, 99.0) == "BACK_TO_PHASE1"


# ---- PASS: ideal convergence -----------------------------------------------

def test_pass_ideal(tmp_path):
    f = _write(tmp_path / "hw_tuning_report.json", {
        "block_name": "ldo_1v8",
        "final_comparison": {
            "vout_dc": {"spec": 1.80, "spice": 1.8002, "hw": 1.803, "tol_pct": 2.0},
        },
    })
    bv = evaluate_file(f)
    assert bv.verdict == "CONVERGED"
    assert main(["--file", str(f)]) == 0


def test_pass_converged_warning(tmp_path):
    # hw and spice both within spec but >20% apart from each other → WARNING (still PASS)
    f = _write(tmp_path / "hw_tuning_report.json", {
        "block_name": "amp",
        "final_comparison": {
            "gain": {"spec": 100.0, "spice": 100.0, "hw": 130.0,
                     "spec_min": 80.0, "spec_max": 140.0},
        },
    })
    bv = evaluate_file(f)
    assert bv.verdict == "CONVERGED_WARNING"
    assert main(["--file", str(f)]) == 0


# ---- FAIL: model inaccuracy + back-to-phase1 -------------------------------

def test_fail_model_inaccuracy(tmp_path):
    # spice in spec, hw out of spec → MODEL_INACCURACY → FAIL
    f = _write(tmp_path / "hw_tuning_report.json", {
        "block_name": "ldo",
        "final_comparison": {
            "vout_dc": {"spec": 1.80, "spice": 1.80, "hw": 1.50,
                        "spec_min": 1.75, "spec_max": 1.85},
        },
    })
    assert evaluate_file(f).verdict == "MODEL_INACCURACY"
    assert main(["--file", str(f)]) == 1


def test_fail_back_to_phase1(tmp_path):
    # spice itself out of spec → BACK_TO_PHASE1 → FAIL
    f = _write(tmp_path / "hw_tuning_report.json", {
        "block_name": "ldo",
        "final_comparison": {
            "vout_dc": {"spec": 1.80, "spice": 1.50, "hw": 1.50,
                        "spec_min": 1.75, "spec_max": 1.85},
        },
    })
    assert evaluate_file(f).verdict == "BACK_TO_PHASE1"
    assert main(["--file", str(f)]) == 1


def test_worst_case_wins(tmp_path):
    # one CONVERGED metric + one MODEL_INACCURACY metric → block FAILs
    f = _write(tmp_path / "hw_tuning_report.json", {
        "block_name": "ldo",
        "final_comparison": {
            "vout": {"spec": 1.80, "spice": 1.80, "hw": 1.80,
                     "spec_min": 1.75, "spec_max": 1.85},
            "psrr": {"spec": 60.0, "spice": 60.0, "hw": 20.0,
                     "spec_min": 50.0, "spec_max": 80.0},
        },
    })
    assert evaluate_file(f).verdict == "MODEL_INACCURACY"
    assert main(["--file", str(f)]) == 1


# ---- honest SKIP / ERROR ---------------------------------------------------

def test_skip_no_metrics(tmp_path):
    f = _write(tmp_path / "hw_tuning_report.json", {"block_name": "x",
                                                    "final_comparison": {}})
    assert evaluate_file(f).verdict == "SKIP"


def test_skip_empty_project(tmp_path):
    (tmp_path / "phase3" / "analog").mkdir(parents=True)
    assert main([str(tmp_path)]) == 0  # SKIP exits 0


def test_garbage_file_is_error_not_pass(tmp_path):
    f = tmp_path / "hw_tuning_report.json"
    f.write_text("{ this is not json")
    assert evaluate_file(f) is None
    assert main(["--file", str(f)]) == 2


def test_missing_file_errors(tmp_path):
    assert main(["--file", str(tmp_path / "nope.json")]) == 2
