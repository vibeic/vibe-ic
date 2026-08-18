"""tests/test_analog_hil_convergence_log_check.py — v1.6.24

Seven cases covering the HIL convergence log gate:
  1. happy path — 7-iter SPICE→HW→post-layout, final CONVERGED        PASS
  2. only 3 iters (below min_iters=5)                                  FAIL
  3. only 2 distinct stages (below min_stages=3)                       FAIL
  4. iterations span SPICE only (no HW prefix)                         FAIL
  5. final_verdict = "DIVERGED"                                        FAIL
  6. log accepts non-strict JSON with leading `+` on numbers           PASS
  7. no analog_block_list.json                                         VACUOUS_PASS
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from programs.analog_hil_convergence_log_check import (
    audit, _DEFAULT_MIN_ITERS, _DEFAULT_MIN_STAGES,
)


def _block_list(project: Path, blocks) -> None:
    p = project / "phase3" / "analog"
    p.mkdir(parents=True, exist_ok=True)
    (p / "analog_block_list.json").write_text(
        json.dumps({"blocks": blocks}))


def _hil_log(project: Path, block: str, body: dict, *, raw: str = "") -> None:
    log_dir = project / "phase3" / "analog" / block / "hil_log"
    log_dir.mkdir(parents=True, exist_ok=True)
    log_path = log_dir / "convergence_log.json"
    if raw:
        log_path.write_text(raw)
    else:
        log_path.write_text(json.dumps(body))


_HAPPY_LOG = {
    "block": "ldo_1v8",
    "loop_kind": "SPICE → HW → measure → adjust → re-converge",
    "iterations": [
        {"iter": 1, "stage": "SPICE_TT",       "verdict": "FAIL_PSRR"},
        {"iter": 2, "stage": "SPICE_TT_after_resize", "verdict": "PASS_SPICE"},
        {"iter": 3, "stage": "HW_TT_27C",      "verdict": "FAIL_VOUT_LOW"},
        {"iter": 4, "stage": "HW_TT_27C_after_trim", "verdict": "PASS_HW_TT"},
        {"iter": 5, "stage": "HW_SS_-40C",     "verdict": "PASS_HW_SS"},
        {"iter": 6, "stage": "HW_FF_125C",     "verdict": "PASS_HW_FF"},
        {"iter": 7, "stage": "post_layout_resim_TT", "verdict": "PASS_POST_LAYOUT"},
    ],
    "final_verdict": "CONVERGED",
}


def test_happy_path_passes(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    _block_list(p, ["ldo_1v8"])
    _hil_log(p, "ldo_1v8", _HAPPY_LOG)
    verdict, results = audit(p, _DEFAULT_MIN_ITERS, _DEFAULT_MIN_STAGES)
    assert verdict == "PASS"
    assert any(r.converged for r in results)


def test_too_few_iters_fails(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    _block_list(p, ["ldo_1v8"])
    short = dict(_HAPPY_LOG)
    short["iterations"] = _HAPPY_LOG["iterations"][:3]
    _hil_log(p, "ldo_1v8", short)
    verdict, results = audit(p, _DEFAULT_MIN_ITERS, _DEFAULT_MIN_STAGES)
    assert verdict == "FAIL"
    assert any("only 3 iter" in " ".join(r.reasons) for r in results)


def test_too_few_distinct_stages_fails(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    _block_list(p, ["ldo_1v8"])
    body = {
        "block": "ldo_1v8",
        "iterations": [
            {"iter": i, "stage": "SPICE_TT", "verdict": "x"} for i in range(1, 8)
        ],
        "final_verdict": "CONVERGED",
    }
    _hil_log(p, "ldo_1v8", body)
    verdict, results = audit(p, _DEFAULT_MIN_ITERS, _DEFAULT_MIN_STAGES)
    assert verdict == "FAIL"
    assert any("distinct stage" in " ".join(r.reasons) for r in results)


def test_no_hw_stage_fails(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    _block_list(p, ["ldo_1v8"])
    body = {
        "block": "ldo_1v8",
        "iterations": [
            {"iter": 1, "stage": "SPICE_TT",          "verdict": "x"},
            {"iter": 2, "stage": "SPICE_TT_resize",   "verdict": "x"},
            {"iter": 3, "stage": "SPICE_FF",          "verdict": "x"},
            {"iter": 4, "stage": "SPICE_SS",          "verdict": "x"},
            {"iter": 5, "stage": "post_layout_resim", "verdict": "x"},
        ],
        "final_verdict": "CONVERGED",
    }
    _hil_log(p, "ldo_1v8", body)
    verdict, results = audit(p, _DEFAULT_MIN_ITERS, _DEFAULT_MIN_STAGES)
    assert verdict == "FAIL"
    assert any("no HW-prefixed stage" in " ".join(r.reasons) for r in results)


def test_diverged_final_verdict_fails(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    _block_list(p, ["ldo_1v8"])
    bad = dict(_HAPPY_LOG)
    bad["final_verdict"] = "DIVERGED"
    _hil_log(p, "ldo_1v8", bad)
    verdict, results = audit(p, _DEFAULT_MIN_ITERS, _DEFAULT_MIN_STAGES)
    assert verdict == "FAIL"
    assert any("final_verdict" in " ".join(r.reasons) for r in results)


def test_tolerant_json_loader_handles_leading_plus(tmp_path: Path) -> None:
    """Real v10619-vendor log had `"dropout_mV": +11` (JSON forbids
    leading `+` on numbers). The gate must still parse it."""
    p = tmp_path / "proj"
    _block_list(p, ["ldo_1v8"])
    raw = """{
      "block": "ldo_1v8",
      "iterations": [
        {"iter": 1, "stage": "SPICE_TT",       "verdict": "x", "delta_mV": +5},
        {"iter": 2, "stage": "SPICE_TT_after", "verdict": "x", "delta_mV": +3},
        {"iter": 3, "stage": "HW_TT_27C",      "verdict": "x", "delta_mV": +1},
        {"iter": 4, "stage": "HW_TT_after",    "verdict": "x", "delta_mV": -2},
        {"iter": 5, "stage": "post_layout",    "verdict": "x", "delta_mV": +0}
      ],
      "final_verdict": "CONVERGED"
    }
    """
    _hil_log(p, "ldo_1v8", {}, raw=raw)
    verdict, results = audit(p, _DEFAULT_MIN_ITERS, _DEFAULT_MIN_STAGES)
    assert verdict == "PASS"


def test_no_block_list_is_vacuous(tmp_path: Path) -> None:
    p = tmp_path / "proj"
    p.mkdir()
    verdict, results = audit(p, _DEFAULT_MIN_ITERS, _DEFAULT_MIN_STAGES)
    assert verdict == "VACUOUS_PASS" and results == []


# --- the exit code is what the flow reads, and no test called main()

def test_main_exits_non_zero_when_no_block_converged(monkeypatch, tmp_path):
    """`gate_cli_mutation_probe` reported this gate SILENT: neutering `main()`
    reddened nothing.

    Every test above drives `audit()` and asserts the VERDICT it returns. The
    flow reads the EXIT CODE, and nothing exercised the mapping between them —
    so the gate could have started answering 0 to every unconverged HIL log
    with the suite still green.
    """
    import analog_hil_convergence_log_check as M
    (tmp_path / "phase3").mkdir()
    monkeypatch.setattr(M, "audit", lambda p, i, s: ("FAIL", []))
    assert M.main([str(tmp_path)]) == 1


def test_main_exits_zero_on_a_converged_run(monkeypatch, tmp_path):
    """The other direction, or the test above is met by a gate that always
    fails."""
    import analog_hil_convergence_log_check as M
    (tmp_path / "phase3").mkdir()
    monkeypatch.setattr(M, "audit", lambda p, i, s: ("PASS", []))
    assert M.main([str(tmp_path)]) == 0


def test_main_exits_zero_and_says_why_when_the_gate_is_inapplicable(
        monkeypatch, tmp_path):
    """VACUOUS_PASS carries a written reason — a zero with no reason is the
    shape this repo keeps retiring."""
    import analog_hil_convergence_log_check as M
    (tmp_path / "phase3").mkdir()
    monkeypatch.setattr(M, "audit", lambda p, i, s: ("VACUOUS_PASS", []))
    out = tmp_path / "r.json"
    assert M.main([str(tmp_path), "--json", str(out)]) == 0
    import json
    assert json.loads(out.read_text()).get("reason"), \
        "VACUOUS_PASS was emitted with no reason recorded"


def test_main_refuses_on_a_missing_project(tmp_path):
    """rc 2: the question could not be asked, which is not a pass."""
    import analog_hil_convergence_log_check as M
    assert M.main([str(tmp_path / "nope")]) == 2
