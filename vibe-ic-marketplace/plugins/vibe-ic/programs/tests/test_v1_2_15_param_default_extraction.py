"""CVDP spec-extraction: two general param-default forms the resolver missed.

Both left a `[NAME-1:0]` port as a `param_expression_width` EXTRACTION_GAP even
though the default IS stated, so the AI author was under-constrained (a T3 that
should be a COMPLETE-spec T2). Field-measured: COMPLETE 219 -> 221.

  (1) MULTI-PARAM HEADER: `#(parameter ADDR_WIDTH = 8, PAGE_WIDTH = 8, TLB_SIZE = 4)`
      shares ONE `parameter` keyword across comma-separated items; the resolver
      caught only the first (ADDR_WIDTH) and dropped PAGE_WIDTH/TLB_SIZE.
  (2) BULLET DEFAULT: a standalone markdown line `- **WIDTH = 32**` (ALL-CAPS name =
      int literal) was not any of the existing default forms.

§4.05 NO-LEAK: the new patterns are whole-line / header-scoped + ALL-CAPS, so a
mid-prose `x = 5` or `COUNT = 3` (not alone on its line) never fabricates a default.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROG = Path(__file__).resolve().parents[1]
if str(_PROG) not in sys.path:
    sys.path.insert(0, str(_PROG))

import verilog_width_resolve as W  # noqa: E402
from _hostpaths import require_corpus  # noqa: E402


def test_multi_param_header_all_items():
    txt = "module m #(parameter ADDR_WIDTH = 8, PAGE_WIDTH = 8, TLB_SIZE = 4) ("
    pd = W.param_defaults(txt, "")
    assert pd == {"ADDR_WIDTH": 8, "PAGE_WIDTH": 8, "TLB_SIZE": 4}


def test_multi_param_header_with_types_and_hex():
    txt = "#(parameter integer N = 16, signed [3:0] M = 4, SEED = 0xFF)"
    pd = W.param_defaults(txt, "")
    assert pd["N"] == 16 and pd["M"] == 4 and pd["SEED"] == 255


def test_bullet_bold_default():
    assert W.param_defaults("- **WIDTH = 32**", "")["WIDTH"] == 32


def test_bullet_code_default():
    assert W.param_defaults("* `DATA_WIDTH = 16`", "")["DATA_WIDTH"] == 16


def test_bullet_plain_numbered():
    assert W.param_defaults("1. CNT_W = 12", "")["CNT_W"] == 12


def test_explicit_default_outranks_later_worked_example_assignment():
    text = ("- `WIDTH` (default value = 6): operand width.\n"
            "## Worked Example\n"
            "- WIDTH = 3\n")
    assert W.param_defaults(text, "")["WIDTH"] == 6


def test_no_leak_mid_prose_lowercase():
    assert W.param_defaults("The value x = 5 is used internally.", "") == {}


def test_no_leak_mid_sentence_caps():
    # ALL-CAPS but NOT alone on its line -> must not be harvested as a default
    assert "COUNT" not in W.param_defaults(
        "When COUNT = 3 the FSM advances, then resets.", "")


def test_no_leak_prose_sentence_with_assignment():
    assert W.param_defaults(
        "- Set the gain such that GAIN = 2 only at boot, otherwise variable.", "") \
        == {} or "GAIN" not in W.param_defaults(
        "- Set the gain such that GAIN = 2 only at boot, otherwise variable.", "")


def test_dataset_tlb_resolves_page_width():
    ds = require_corpus("_extbench/cvdp_open_v110/"
                        "cvdp_v1.1.0_nonagentic_code_generation_no_commercial.jsonl")
    if not ds.exists():
        import pytest
        pytest.skip("dataset not present")
    import json
    recs = {json.loads(l)["id"]: json.loads(l) for l in ds.read_text().splitlines()}
    r = recs.get("cvdp_copilot_virtual2physical_tlb_0001")
    if r is None:
        import pytest
        pytest.skip("record not present")
    pd = W.param_defaults(r["input"]["prompt"], "")
    assert pd.get("PAGE_WIDTH") == 8 and pd.get("ADDR_WIDTH") == 8


def test_dataset_gf_resolves_bullet_width():
    ds = require_corpus("_extbench/cvdp_open_v110/"
                        "cvdp_v1.1.0_nonagentic_code_generation_no_commercial.jsonl")
    if not ds.exists():
        import pytest
        pytest.skip("dataset not present")
    import json
    recs = {json.loads(l)["id"]: json.loads(l) for l in ds.read_text().splitlines()}
    r = recs.get("cvdp_copilot_gf_multiplier_0013")
    if r is None:
        import pytest
        pytest.skip("record not present")
    assert W.param_defaults(r["input"]["prompt"], "").get("WIDTH") == 32
