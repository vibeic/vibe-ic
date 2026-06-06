"""v0.2.74 — #444: IR/EM measurements get a budget verdict; MEASURED is
INCOMPLETE, never FAIL.

The audited rot: ir_drop.json / em.json hardwired verdict="MEASURED"
with no threshold; the PERC memo's _auto mapped any non-PASS to FAIL
while the step gate PASSed on report presence — two readers, opposite
verdicts on the same artifact.

Pins:
  * runner IR emitter computes worst_ir_uv and compares against the
    same 35 µV budget signoff_ladder_run.check_tier_2_ir uses →
    verdict PASS/FAIL travels WITH the numbers (source pin);
  * PERC _auto maps MEASURED → INCOMPLETE (review), not FAIL;
  * eda_report_audit ir_drop mode applies the budget comparison when
    worst_ir_uv/budget_uv are present (IR_OVER_BUDGET ERROR).

chip-AGNOSTIC: numeric thresholds + structural JSON only.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import eda_report_audit as ERA  # noqa: E402

PLUGIN = Path(__file__).resolve().parent.parent.parent
_P3_SRC = (PLUGIN / "programs" / "phase3_one_shot_runner.py").read_text()


def _ir_project(tmp_path, worst_uv, budget_uv=35.0):
    rpt_dir = tmp_path / "reports" / "phase3"
    rpt_dir.mkdir(parents=True)
    # report body large enough + tool-signed for the authenticity check
    (rpt_dir / "ir_drop.rpt").write_text(
        "# OpenROAD PSM (Power Supply Metal) IR-drop report\n"
        "openroad / PSM: analyze_power_grid invoked\n"
        "IR drop analysis (static): worst voltage drop\n"
        + f"IR drop: {worst_uv / 1e6:.3e} V\n  -> {worst_uv / 1000.0:.6g} mV "
          "(IR drop, normalised)\n" * 40)
    (rpt_dir / "ir_drop.json").write_text(json.dumps({
        "tool": "openroad-psm", "worst_ir_uv": worst_uv,
        "budget_uv": budget_uv,
        "verdict": "PASS" if worst_uv <= budget_uv else "FAIL"}))
    return tmp_path


def test_ir_over_budget_fails_step_gate(tmp_path):
    _ir_project(tmp_path, worst_uv=120.0)
    r = ERA._check_ir_drop(tmp_path)
    assert r.passed is False
    assert any(f.rule == "IR_OVER_BUDGET" for f in r.findings)
    assert r.summary["ir_within_budget"] is False


def test_ir_within_budget_passes(tmp_path):
    _ir_project(tmp_path, worst_uv=12.0)
    r = ERA._check_ir_drop(tmp_path)
    assert r.summary["ir_within_budget"] is True
    assert not any(f.rule == "IR_OVER_BUDGET" for f in r.findings)


def test_runner_ir_emitter_writes_budget_verdict():
    # budget = canonical 5%-of-VDD rule, VDD parsed from the PSM log
    i = _P3_SRC.index('_ir_budget_uv = 0.05 * _vdd_v * 1e6')
    window = _P3_SRC[i - 1100:i + 900]
    assert "Supply voltage" in window
    assert '"worst_ir_uv": _worst_ir_uv' in window
    assert '"verdict": "PASS" if _worst_ir_uv <= _ir_budget_uv else "FAIL"' \
        in window
    assert "#444" in window
    # the hardwired measurement-only verdict is gone from the IR emitter
    assert '"verdict": "MEASURED"' not in window


def test_perc_auto_maps_measured_to_incomplete():
    i = _P3_SRC.index("def _auto(name, verdict, tool, evidence):")
    window = _P3_SRC[i:i + 1800]
    assert '"INCOMPLETE" if verdict == "MEASURED" else "FAIL"' in window
    assert "#444" in window
