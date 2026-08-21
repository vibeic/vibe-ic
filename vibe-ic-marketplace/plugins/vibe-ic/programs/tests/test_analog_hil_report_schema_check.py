"""tests/test_analog_hil_report_schema_check.py

Covers the hw_tuning_report.json schema/consistency validation + honest SKIP.
"""
from __future__ import annotations

import json
from pathlib import Path

from programs.analog_hil_report_schema_check import main, validate, evaluate_file


_GOOD = {
    "block_name": "ldo_1v8",
    "converged": True,
    "total_iterations": {"spice": 3, "hardware": 1},
    "final_comparison": {
        "vout_dc": {"spec": 1.80, "spice": 1.8002, "hw": 1.803, "discrepancy_pct": 0.16},
    },
    "convergence_status": "IDEAL",
}


def _write(path: Path, body: dict) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(body))
    return path


def test_pass_good_report():
    assert validate(_GOOD) == []
    assert validate(dict(_GOOD, convergence_status="WARNING", converged=False)) == []


def test_pass_via_main(tmp_path):
    f = _write(tmp_path / "hw_tuning_report.json", _GOOD)
    assert evaluate_file(f).verdict == "PASS"
    assert main(["--file", str(f)]) == 0


def test_fail_missing_block_name():
    bad = dict(_GOOD); del bad["block_name"]
    assert any("block_name" in v for v in validate(bad))


def test_fail_bad_status():
    bad = dict(_GOOD, convergence_status="MAYBE")
    assert any("convergence_status" in v for v in validate(bad))


def test_fail_converged_inconsistent():
    # IDEAL but converged false → cross-field violation
    bad = dict(_GOOD, converged=False, convergence_status="IDEAL")
    assert any("converged is not true" in v for v in validate(bad))


# ── #693: the convergence_status vocabulary ────────────────────────────────
# The tests below were the gap that let this ship. The originals used only
# IDEAL / WARNING — both drawn from the SKILL's JSON EXAMPLE — so the half of
# the vocabulary the SKILL's own decision table defines, and that
# `analog_hil_three_way_verdict` actually computes, was never exercised. Every
# one of these three statuses came back as a SCHEMA violation, including
# MODEL_INACCURACY, which is the honest "hardware disagrees with SPICE"
# outcome: a real bench finding reported as a format complaint.

def test_accepts_three_way_verdict_vocabulary():
    for status in ("CONVERGED_WARNING", "MODEL_INACCURACY", "BACK_TO_PHASE1"):
        body = dict(_GOOD, convergence_status=status,
                    converged=status == "CONVERGED_WARNING")
        assert validate(body) == [], f"{status} rejected: {validate(body)}"


def test_non_converged_verdict_cannot_claim_converged():
    # The rule that REPLACES the rejection: a report carrying one of the two
    # verdicts analog_hil_three_way_verdict FAILs on cannot also say it
    # converged. Widening the accepted set without this would have been a pure
    # loosening.
    for status in ("MODEL_INACCURACY", "BACK_TO_PHASE1"):
        bad = dict(_GOOD, convergence_status=status, converged=True)
        assert any("non-converged verdict" in v for v in validate(bad)), status


def test_status_outside_both_vocabularies_still_rejected():
    assert any("convergence_status" in v
               for v in validate(dict(_GOOD, convergence_status="TOTALLY_MADE_UP")))


def test_fail_negative_iterations():
    bad = json.loads(json.dumps(_GOOD))
    bad["total_iterations"]["hardware"] = -1
    assert any("negative" in v for v in validate(bad))


def test_fail_metric_missing_field():
    bad = json.loads(json.dumps(_GOOD))
    del bad["final_comparison"]["vout_dc"]["discrepancy_pct"]
    assert any("discrepancy_pct missing" in v for v in validate(bad))


def test_fail_empty_final_comparison():
    bad = dict(_GOOD, final_comparison={})
    assert any("final_comparison missing or empty" in v for v in validate(bad))


def test_fail_non_numeric_metric():
    bad = json.loads(json.dumps(_GOOD))
    bad["final_comparison"]["vout_dc"]["hw"] = "1.803"
    assert any("hw is not a number" in v for v in validate(bad))


def test_bool_is_not_int_for_iterations():
    bad = json.loads(json.dumps(_GOOD))
    bad["total_iterations"]["spice"] = True
    assert any("total_iterations.spice missing or not an int" in v for v in validate(bad))


def test_garbage_file_is_fail_not_pass(tmp_path):
    f = tmp_path / "hw_tuning_report.json"
    f.write_text("not json")
    assert evaluate_file(f).verdict == "FAIL"
    assert main(["--file", str(f)]) == 1


def test_no_report_is_not_checked_not_pass(tmp_path):
    # #693 — no artefact is exit 2 = NOT CHECKED, NOT exit 0. Nothing in this
    # repo writes hw_tuning_report.json, so this is the tier every published
    # run lands in; it must not read as "schema audited and clean".
    (tmp_path / "phase3" / "analog").mkdir(parents=True)
    assert main([str(tmp_path)]) == 2


def test_missing_file_errors(tmp_path):
    assert main(["--file", str(tmp_path / "nope.json")]) == 2
