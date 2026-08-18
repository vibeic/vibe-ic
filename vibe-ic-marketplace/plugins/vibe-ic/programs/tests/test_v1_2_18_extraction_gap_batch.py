"""CVDP spec-extraction batch: three general gap-closing levers in one pass.

Fixed together (COMPLETE 223 -> 226, EXTRACTION_GAP 5 -> 3; the 5th former gap,
lpf `w_out`, is honestly reclassified SPEC_ABSENT — its width truly is not stated):

  FIX 1 (CRITICAL false-COMPLETE): `localparam NBW_PRED = 2*DATA_WIDTH + 1;` was
    matched by the bare-literal `_LOCALPARAM_RE`/`_CODE_PARAM_RE` capturing the
    leading `2`, WRONGLY binding NBW_PRED=2 (a shipped-wrong width). The readers now
    require the integer to be the WHOLE RHS (an end-of-statement lookahead); an
    EXPRESSION RHS is left for `_DERIVED_PARAM_RE` + the fixed-point loop -> 33.

  FIX 2 (`log2ceil`): a port sized `[log2ceil(MaxRatio_g)-1:0]` did not resolve
    because the evaluator only knew `$clog2`/`clog2`. `log2ceil` and `clogb2` (the
    common user-defined ceil-log2 synonyms) now normalize onto clog2.

  FIX 3 (`_g`-param mis-classified as port): `strobe_divider` declares
    `#(parameter MaxRatio_g = 10, parameter Latency_g = 1)`; these were emitted as
    output ports (false `width_not_stated`). A name that resolved to a default in
    `param_defaults` (i.e. a declared parameter) is now excluded from the port list.

§4.05 NO-LEAK is the load-bearing half: each fix carries a NEGATIVE asserting the
relaxed reader does NOT over-bind / fabricate.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROG = Path(__file__).resolve().parents[1]
if str(_PROG) not in sys.path:
    sys.path.insert(0, str(_PROG))

import verilog_width_resolve as W  # noqa: E402
import cvdp_complete_extract as E  # noqa: E402
from _hostpaths import corpus_path  # noqa: E402

_DATASET = corpus_path("_extbench/cvdp_open_v110/"
                       "cvdp_v1.1.0_nonagentic_code_generation_no_commercial.jsonl")


def _records():
    if not _DATASET.exists():
        pytest.skip("dataset not present")
    return {json.loads(l)["id"]: json.loads(l)
            for l in _DATASET.read_text().splitlines()}


# ── FIX 1 — bare-literal-only param binding (no expression false-COMPLETE) ──
def test_fix1_expression_localparam_not_bound_to_leading_literal():
    pd = W.param_defaults("parameter A = 4,\nlocalparam Z = 2*A + 1;", "")
    assert pd.get("Z") == 9          # resolved, NOT the leading literal 2


def test_fix1_bare_literal_localparam_still_binds():
    assert W.param_defaults("localparam X = 8;", "").get("X") == 8
    assert W.param_defaults("parameter Y = 16,", "").get("Y") == 16
    assert W.param_defaults("localparam P = 0xFF;", "").get("P") == 255


def test_fix1_dataset_lpf_nbw_chain():
    r = _records().get("cvdp_copilot_configurable_digital_low_pass_filter_0011")
    if r is None:
        pytest.skip("record absent")
    pd = W.param_defaults(r["input"]["prompt"], "")
    # NBW_PRED = 2*DATA_WIDTH+1 = 33 (was wrongly 2); chain settles.
    assert pd.get("NBW_PRED") == 33
    assert pd.get("NBW_ERROR") == 34
    assert pd.get("NBW_DELTA") == 53


# ── FIX 2 — log2ceil / clogb2 ceil-log2 synonyms ──
def test_fix2_log2ceil_resolves():
    assert W.eval_width_expr("log2ceil(MaxRatio_g)", {"MaxRatio_g": 10}) == 4
    assert W.eval_width_expr("clogb2(8)", {}) == 3


def test_fix2_no_leak_unknown_param_in_log2ceil():
    assert W.eval_width_expr("log2ceil(UNKNOWN)", {}) is None  # no fabrication


def test_fix2_no_leak_substring_name_untouched():
    # a parameter whose NAME merely contains 'log2ceil' is not rewritten to clog2.
    assert W.eval_width_expr("MY_log2ceil_PARAM", {"MY_log2ceil_PARAM": 7}) == 7


def test_fix2_dataset_strobe_in_ratio_width():
    r = _records().get("cvdp_copilot_strobe_divider_0001")
    if r is None:
        pytest.skip("record absent")
    # MaxRatio_g=10 -> log2ceil(10)=4, so In_Ratio is [3:0]; record is COMPLETE.
    assert E.extract(r).get("completeness") == "COMPLETE"


# ── FIX 3 — declared parameters are not emitted as ports ──
def test_fix3_g_suffix_params_not_ports():
    r = _records().get("cvdp_copilot_strobe_divider_0001")
    if r is None:
        pytest.skip("record absent")
    spec = E.extract(r)
    ports = [p["name"] for p in (spec.get("interface") or [])]
    assert "MaxRatio_g" not in ports and "Latency_g" not in ports
    # a real port is still present
    assert "In_Ratio" in ports


def test_fix3_no_leak_real_output_port_still_emitted():
    # a genuine output port (not a declared parameter) must still appear.
    r = _records().get("cvdp_copilot_strobe_divider_0001")
    if r is None:
        pytest.skip("record absent")
    ports = [p["name"] for p in (E.extract(r).get("interface") or [])]
    assert "Out_Valid" in ports


# ── batch outcome — completeness rose, the residual three stay honest gaps ──
def test_batch_completeness_and_residual_gaps():
    recs = _records()
    comp = gap = absent = 0
    gap_ids = []
    for r in recs.values():
        c = E.extract(r).get("completeness")
        if c == "COMPLETE":
            comp += 1
        elif c == "INCOMPLETE_EXTRACTION_GAP":
            gap += 1
            gap_ids.append(r["id"].replace("cvdp_copilot_", ""))
        elif c == "INCOMPLETE_SPEC_ABSENT":
            absent += 1
    assert comp >= 226, f"COMPLETE regressed: {comp}"
    assert gap <= 3, f"EXTRACTION_GAP rose: {gap} {gap_ids}"
    # the residual gaps are the documented hard cases (cocotb-interface / context-only
    # param / wavedrom-only width) — assert they are a SUBSET of the known set.
    known_residual = {"word_reducer_0008", "pipeline_mac_0017", "matrix_multiplier_0001"}
    assert set(gap_ids) <= known_residual, f"unexpected new gap: {set(gap_ids) - known_residual}"
