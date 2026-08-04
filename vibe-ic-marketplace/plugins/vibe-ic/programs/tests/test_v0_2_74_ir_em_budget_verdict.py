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

from _source_pin import func_src

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
    # budget = configurable pct-of-VDD (v1.3.93: reconciled to the plugin's own
    # ir_drop_budget_check._DEFAULT_BUDGET_PCT, was a hardwired 5%), VDD parsed
    # from the PSM log.
    #
    # v1.6.68 — the budget is now applied PER NET against that net's OWN supply
    # voltage, so the anchor moved from the single-rail `_ir_budget_uv = ...`
    # to the per-net `_bud = ...`. A design with two supplies does not share
    # one millivolt budget; pinning the per-net form is what keeps it that way.
    i = _P3_SRC.index('_bud = (_budget_pct / 100.0) * _v * 1e6')
    # Measured offsets from this anchor: #444 -5057, "Supply voltage" -1585,
    # per-net verdict +275, worst_ir_uv +1753, EM's MEASURED +5633. The window
    # must span #444..worst_ir_uv while still EXCLUDING the EM emitter.
    window = _P3_SRC[i - 5100:i + 2500]
    assert "Supply voltage" in window
    assert '"worst_ir_uv": _worst_ir_uv' in window
    assert '"verdict": "PASS" if _uv <= _bud else "FAIL"' in window
    assert "#444" in window
    # the hardwired measurement-only verdict is gone from the IR emitter
    assert '"verdict": "MEASURED"' not in window
    # ...and the per-net numbers travel with the verdict, so a reader can
    # re-derive EVERY rail's result, not just the worst one.
    assert '"per_net": _measured' in window
    assert '"unmeasured_nets": _unmeasured' in window


def test_perc_auto_maps_measured_to_incomplete():
    window = func_src(_P3_SRC, "_auto")
    assert '"INCOMPLETE" if verdict == "MEASURED" else "FAIL"' in window
    assert "#444" in window
