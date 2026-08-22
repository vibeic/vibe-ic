"""conv_encoder_synth — general convolutional-encoder solver (T2->T1 promotion).

Promotes the feed-forward rate-1/n convolutional encoder to a deterministic Tier-1
emit. GENERAL: K and every generator polynomial tap string are PARSED from the
prompt prose; no tap is hardcoded. Verified PASS against the design's own cocotb
harness (in the campaign run); these tests pin the emit shape + the §4.05 SKIPs.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

_PROG = Path(__file__).resolve().parents[1]
if str(_PROG) not in sys.path:
    sys.path.insert(0, str(_PROG))

import conv_encoder_synth as S  # noqa: E402
from _hostpaths import corpus_path  # noqa: E402

_DATASET = corpus_path("_extbench/cvdp_open_v110/"
                       "cvdp_v1.1.0_nonagentic_code_generation_no_commercial.jsonl")


def _rec(top, prompt, *, ctx=None):
    return {
        "id": f"test_{top}",
        "input": {"prompt": prompt, "context": ctx or {}},
        "output": {"response": "", "context": {f"rtl/{top}.sv": ""}},
        "harness": {"files": {"src/.env": f"TOPLEVEL        = {top}\n"}},
    }


_K3_PROMPT = (
    "Implement a fixed constraint k=3 and a generator polynomial convolutional "
    "encoder. The constraint length (K) is fixed at 3. The generator polynomial "
    'g1 is "111" and g2 is "101". '
    "Inputs: clk, rst (asynchronous reset, active high), data_in. "
    "Outputs: encoded_bit1, encoded_bit2."
)


def test_k3_emit_taps_match_harness_model():
    """g1='111' -> in ^ sr[0] ^ sr[1]; g2='101' -> in ^ sr[1] (the harness model)."""
    rtl = S.solve(_rec("convolutional_encoder", _K3_PROMPT))
    assert rtl is not None
    assert "module convolutional_encoder" in rtl
    assert "reg [1:0] shift_reg" in rtl
    assert "encoded_bit1 <= data_in ^ shift_reg[0] ^ shift_reg[1]" in rtl
    assert "encoded_bit2 <= data_in ^ shift_reg[1]" in rtl
    # async active-high reset clears state + outputs
    assert "posedge clk or posedge rst" in rtl
    assert "shift_reg <= 2'b0" in rtl


def test_general_not_overfit_different_polys():
    """A DIFFERENT (K, polys) instance emits the correspondingly different taps —
    proves the solver reads the spec, not a memorized 111/101."""
    prompt = _K3_PROMPT.replace('g1 is "111"', 'g1 is "110"').replace(
        'g2 is "101"', 'g2 is "111"')
    rtl = S.solve(_rec("convolutional_encoder", prompt))
    assert rtl is not None
    # g1='110' -> in ^ sr[0] (no sr[1]); g2='111' -> in ^ sr[0] ^ sr[1]
    assert "encoded_bit1 <= data_in ^ shift_reg[0];" in rtl
    assert "encoded_bit2 <= data_in ^ shift_reg[0] ^ shift_reg[1]" in rtl


def test_skip_non_convolutional():
    assert S.solve(_rec("enc", "Design a priority encoder. Inputs clk, data_in.")) is None


def test_skip_recursive_or_punctured():
    p = _K3_PROMPT + " This is a recursive systematic convolutional (RSC) encoder."
    assert S.solve(_rec("convolutional_encoder", p)) is None


def test_skip_partial_completion_task():
    p = _K3_PROMPT + " Complete the given partial SystemVerilog code; retain the " \
        "already written part unchanged."
    assert S.solve(_rec("convolutional_encoder", p)) is None


def test_skip_missing_generators():
    p = ("Implement a convolutional encoder with constraint length K=3. "
         "Inputs: clk, rst, data_in. Outputs: encoded_bit1, encoded_bit2.")
    assert S.solve(_rec("convolutional_encoder", p)) is None  # no tap strings stated


def test_dataset_record_emits_when_present():
    if not _DATASET.exists():
        pytest.skip("dataset not present")
    recs = {json.loads(l)["id"]: json.loads(l) for l in _DATASET.read_text().splitlines()}
    r = recs.get("cvdp_copilot_convolutional_encoder_0001")
    if r is None:
        pytest.skip("record not present")
    rtl = S.solve(r)
    assert rtl is not None
    assert "module convolutional_encoder" in rtl
    # the harness reads dut.shift_reg by name
    assert "shift_reg" in rtl


# ── polarity: a PROMPT states a retired polynomial as readily as a live one ──
#
# Found by `prose_polarity_census`. `_parse_generators` published a denied
# generator polynomial as a stated one, and that value decides which encoder is
# SYNTHESISED. It compounds with `setdefault`, which keeps the first match: a
# retired polynomial stated before the live one took its place outright.

def _gens(prompt):
    import conv_encoder_synth as M
    return M._parse_generators(prompt)


def test_a_retired_polynomial_is_not_read_as_stated():
    assert _gens('g1 = "111" is no longer used. The encoder uses g2 = "101".') \
        == [(2, "101")]


def test_an_explicitly_negated_polynomial_is_not_read():
    assert _gens('The encoder does not use g1 = "111".') == []


def test_a_retired_value_does_not_take_the_live_one_s_place():
    """`setdefault` keeps the FIRST match, so a denial stated before the live
    statement did not merely add a wrong entry -- it displaced the right one."""
    assert _gens('g1 = "111" is no longer used.\nThe encoder uses g1 = "110".') \
        == [(1, "110")]


def test_a_denial_wrapped_across_two_lines_is_still_a_denial():
    """Breaking on every "\\n" would have missed this -- the under-reach that
    publishes the denied value, which is the failure being fixed."""
    assert _gens('g1 = "111" is no\nlonger used.') == []


def test_a_plainly_stated_prompt_still_yields_both():
    """The control arm: a fix that refused everything would pass the rest."""
    assert _gens('The encoder uses g1 = "111" and g2 = "101".') \
        == [(1, "111"), (2, "101")]
