"""dice_roller_synth — general digital dice-roller solver (T2->T1 promotion).

Promotes the single-die button-gated dice roller (digital_dice_roller_0001, a 0/5
problem) to a deterministic Tier-1 emit. GENERAL: DICE_MAX parsed from prose; the
IDLE/ROLLING FSM + 1..MAX wrap are the dice invariant. The reset port NAME and
polarity come ONLY from the prompt prose (`reset_n`, active LOW) — the hidden
cocotb TB is an OFF-LIMITS oracle and is never read. These tests pin the emit, the
prompt-only reset sourcing (harness ignored even when it disagrees), and the §4.05
SKIPs.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROG = Path(__file__).resolve().parents[1]
if str(_PROG) not in sys.path:
    sys.path.insert(0, str(_PROG))

import dice_roller_synth as S  # noqa: E402
from _hostpaths import corpus_path  # noqa: E402

_DATASET = corpus_path("_extbench/cvdp_open_v110/"
                       "cvdp_v1.1.0_nonagentic_code_generation_no_commercial.jsonl")

_PROMPT = (
    "Design a Digital Dice Roller for a 6-sided die. A counter counts between 1 "
    "and 6 on every positive clock edge while button is HIGH, and outputs the dice "
    "value when the button becomes LOW.\n"
    "- `clk`: clock.\n- `reset_n`: Asynchronous active LOW reset.\n"
    "- `button` (1-bit): when HIGH the FSM cycles dice values 1 to 6; when LOW it "
    "stops and holds the last value.\n"
    "- `dice_value[2:0]` (3-bit): the dice result, 1 to 6.\n"
    "The FSM operates between IDLE and ROLLING states with an internal counter."
)


def _rec(top, prompt, *, ctx=None, tb_reset="reset"):
    tb = (f"import cocotb\nasync def t(dut):\n    dut.{tb_reset}.value = 0\n"
          f"    dut.button.value = 1\n")
    return {
        "id": f"test_{top}",
        "input": {"prompt": prompt, "context": ctx or {}},
        "output": {"response": "", "context": {f"rtl/{top}.sv": ""}},
        "harness": {"files": {
            "src/.env": f"TOPLEVEL        = {top}\n",
            "src/test_dice.py": tb,
        }},
    }


def test_emit_shape_and_dicemax():
    rtl = S.solve(_rec("digital_dice_roller", _PROMPT))
    assert rtl is not None
    assert "module digital_dice_roller" in rtl
    assert "parameter DICE_MAX = 6" in rtl
    assert "IDLE" in rtl and "ROLLING" in rtl
    assert "counter == DICE_MAX[2:0]" in rtl


def test_reset_name_from_prose_not_harness():
    """Prose names the reset `reset_n`; even though the hidden cocotb TB drives a
    DIFFERENT net (`dut.reset`), the compliant solver reads ONLY the prompt, so the
    emit binds `reset_n` (harness ignored) with active-low polarity from the prose."""
    rtl = S.solve(_rec("digital_dice_roller", _PROMPT, tb_reset="reset"))
    assert "input reset_n," in rtl
    assert "negedge reset_n)" in rtl and "if (!reset_n)" in rtl  # active-low from prose
    assert "input reset," not in rtl  # the off-limits harness net name is NOT used


def test_general_not_overfit_dicemax():
    """A different sided count emits the corresponding DICE_MAX."""
    p = _PROMPT.replace("6-sided", "4-sided").replace("1 and 6", "1 and 4").replace(
        "1 to 6", "1 to 4")
    rtl = S.solve(_rec("digital_dice_roller", p))
    assert "parameter DICE_MAX = 4" in rtl


def test_skip_modify_partial():
    p = _PROMPT + " Complete the given partial code; retain the already written part."
    assert S.solve(_rec("digital_dice_roller", p)) is None


def test_skip_with_context():
    assert S.solve(_rec("dr", _PROMPT, ctx={"rtl/x.sv": "module x;"})) is None


def test_skip_seven_segment_variant():
    p = _PROMPT + " The dice value drives a seven-segment display decoder."
    assert S.solve(_rec("digital_dice_roller", p)) is None


def test_skip_non_dice():
    assert S.solve(_rec("c", "Design a 4-bit up counter. clk reset button.")) is None


def test_dataset_record_emits_when_present():
    if not _DATASET.exists():
        pytest.skip("dataset not present")
    recs = {json.loads(l)["id"]: json.loads(l) for l in _DATASET.read_text().splitlines()}
    r = recs.get("cvdp_copilot_digital_dice_roller_0001")
    if r is None:
        pytest.skip("record not present")
    rtl = S.solve(r)
    assert rtl is not None and "module digital_dice_roller" in rtl
    assert "input reset_n," in rtl  # reset name from the PROMPT prose (harness TB off-limits)
