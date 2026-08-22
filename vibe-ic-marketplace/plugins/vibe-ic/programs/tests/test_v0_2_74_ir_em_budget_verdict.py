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
    """The IR verdict is derived from a configurable pct-of-VDD budget, and the
    hardwired MEASURED verdict is gone from the IR emitter.

    SCOPED STRUCTURALLY, and that is the fix. This used to slice the runner's
    source by CHARACTER COUNT (`_P3_SRC[i - 1700:i + 2500]`) and had been
    widened twice as the file grew. `_source_pin.func_src` — already used by the
    test below in this same file — states the failure mode exactly: a magic
    window is wrong in BOTH directions, too short giving a false FAIL on correct
    code, too long letting a NEIGHBOURING function satisfy the assertion.

    Both directions had already happened here. It was RED ON origin/main before
    this change: `Supply voltage` lives in `_ir_supply_from_psm_log`, a
    different function that the window used to reach and no longer does — the
    assertion was being satisfied by a neighbour, exactly as that docstring
    warns, and stopped being satisfied when the distance changed.

    The scope is now the IR report block itself: from the end of `ir_drop.rpt`
    to the start of the EM block, so `"verdict": "MEASURED"` — which is the EM
    emitter's correct answer — cannot leak in and cannot be mistaken for the IR
    one."""
    emitter = func_src(_P3_SRC, "_emit_ir_em_reports")
    ir_block = emitter[emitter.index('"# end of ir_drop.rpt'):
                       emitter.index('"# end of em.rpt')]

    # the budget is a configurable pct of the VDD parsed from the PSM log
    assert '_ir_budget_uv = (_budget_pct / 100.0) * _vdd_v * 1e6' in ir_block
    assert '"worst_ir_uv": _worst_ir_uv' in ir_block
    assert "#444" in ir_block
    # the verdict is DERIVED from that budget, however it is spelled — the
    # inline conditional this test used to pin verbatim has since been factored
    # into `ir_verdict()` with an UNMEASURED arm, which is a better answer, and
    # a literal-text assertion would have called that a regression.
    assert '"verdict"' in ir_block and "_ir_budget_uv" in ir_block
    # and the hardwired measurement-only verdict is not the IR emitter's answer
    assert '"verdict": "MEASURED"' not in ir_block

    # the VDD really is parsed, in the function whose job that is
    assert "Supply voltage" in func_src(_P3_SRC, "_ir_supply_from_psm_log")



def test_perc_auto_maps_measured_to_incomplete():
    window = func_src(_P3_SRC, "_auto")
    assert '"INCOMPLETE" if verdict == "MEASURED" else "FAIL"' in window
    assert "#444" in window
