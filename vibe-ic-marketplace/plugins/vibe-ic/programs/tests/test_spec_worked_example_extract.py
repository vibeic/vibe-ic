#!/usr/bin/env python3
"""Tests for spec_worked_example_extract.extract — structural worked-example /
latency extraction with a §4.05 no-leak guarantee and chip-AGNOSTIC behaviour."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import spec_worked_example_extract as cwe  # noqa: E402


def _kinds(items):
    return [it["kind"] for it in items]


def _of_kind(items, kind):
    return [it for it in items if it["kind"] == kind]


# ---------------------------------------------------------------------------
# (a) POSITIVE — a real worked-example pair + a real "N clock cycles" sentence,
#     VERBATIM, must yield the worked_example item + the latency item.
# ---------------------------------------------------------------------------
def test_positive_worked_example_and_latency_verbatim():
    # Verbatim shapes lifted from the CVDP fail-prompt corpus (dot_product_0005
    # style example block + the "three clock cycles" latency sentence).
    prompt = (
        "**Example 1: Real-Only Mode**\n"
        "- **Input**:\n"
        "  - `a_complex_in = 0`, `b_complex_in = 0`\n"
        "  - `vector_a_in = 32'h00000005`\n"
        "  - `vector_b_in = 32'h00000004`\n"
        "  - `dot_length_in = 8'h04`\n"
        "- **Output**:\n"
        "  - `dot_product_out = 32'h00000050`\n"
        "  - `dot_product_valid_out = 1`\n"
        "\n"
        "- Output Latency is three clock cycles.\n"
    )
    items = cwe.extract(prompt)

    # worked_example item: the concrete input->output pair is recovered.
    we = _of_kind(items, "worked_example")
    assert len(we) == 1, we
    pair = we[0]
    assert pair["kind"] == "worked_example"
    # the stimulus + expected values land in example_input / example_output.
    assert "vector_a_in = 32'h00000005" in pair["example_input"]
    assert "vector_b_in = 32'h00000004" in pair["example_input"]
    assert "dot_product_out = 32'h00000050" in pair["example_output"]
    # requirement is the golden TB assertion; evidence is the exact example text.
    assert pair["requirement"].startswith("TB must assert")
    assert "32'h00000050" in pair["requirement"]
    assert "32'h00000005" in pair["evidence"]
    assert pair["provenance"] == "STRUCTURAL"

    # latency item: the stated cycle count N=3 is recorded.
    lat = _of_kind(items, "latency")
    assert len(lat) == 1, lat
    assert lat[0]["latency_cycles"] == 3
    assert "clock cycle" in lat[0]["evidence"].lower()
    assert "3" in lat[0]["requirement"]


def test_positive_inline_arrow_and_numberword_latency():
    # The inline `for input X the output is Y` form + a number-WORD cycle count.
    prompt = ("For input 0x3, the output is 0b1010. "
              "The output becomes valid after five clock cycles.")
    items = cwe.extract(prompt)

    we = _of_kind(items, "worked_example")
    assert len(we) == 1
    assert we[0]["example_input"] == ["0x3"]
    assert we[0]["example_output"] == ["0b1010"]

    lat = _of_kind(items, "latency")
    assert len(lat) == 1
    assert lat[0]["latency_cycles"] == 5  # number-word "five" parsed to 5


def test_positive_example_table():
    # A markdown `| in | out |` example table -> one worked_example per data row.
    prompt = (
        "| input | output |\n"
        "|-------|--------|\n"
        "| 8'd5  | 8'd25  |\n"
        "| 8'd6  | 8'd36  |\n"
    )
    we = _of_kind(cwe.extract(prompt), "worked_example")
    assert len(we) == 2, we
    outs = {tuple(it["example_output"]) for it in we}
    assert ("8'd25",) in outs and ("8'd36",) in outs


# ---------------------------------------------------------------------------
# (b) §4.05 NEGATIVE — vague "compute the output" with NO concrete example /
#     number must yield [] (no phantom worked_example, no phantom latency).
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("vague", [
    "The module shall compute the output from the inputs and produce the result.",
    "Modify the module to handle complex and real modes, ensuring robust output "
    "handling and error detection.",
    "It processes the input stream and returns a value once the computation is "
    "complete.",
    "Perform a lint code review on the module, addressing the listed issues; "
    "only provide the lint-clean RTL code.",
])
def test_405_negative_vague_prose_returns_empty(vague):
    assert cwe.extract(vague) == []


def test_405_negative_no_latency_without_stated_number():
    # "completes on the clock edge" mentions a clock but states NO cycle count.
    prompt = ("The result is produced and the output updates on the rising clock "
              "edge once processing finishes.")
    assert _of_kind(cwe.extract(prompt), "latency") == []


def test_405_negative_malformed_sized_literal_not_partial():
    # A malformed sized literal (`16'200`, missing the base char) must not yield a
    # bogus partial value `16` / `1` as an example.
    prompt = ("## Example of Usage\n"
              "### Inputs\n- `x_in = 16'd10`\n"
              "### Outputs\n- `w = 16'200`\n")
    we = _of_kind(cwe.extract(prompt), "worked_example")
    # either no pair (no valid output value) or a pair whose output never carries
    # the bogus partial `16`/`1`; assert the malformed token is not credited.
    for it in we:
        for v in it["example_output"]:
            assert v.split("=")[-1].strip() not in ("16", "1")


# ---------------------------------------------------------------------------
# (c) CHIP-AGNOSTIC — renaming every signal / module to nonsense leaves the
#     structural extraction unchanged (same number of pairs + same cycle count).
#     The extractor keys on STRUCTURE (Example block, in=lit/out=lit, "N cycles"),
#     never on any chip / vendor / signal-name literal.
# ---------------------------------------------------------------------------
def test_chip_agnostic_rename_invariant():
    base = (
        "**Example 1**\n"
        "- **Input**:\n"
        "  - `sig_a = 32'h00000005`\n"
        "  - `sig_b = 32'h00000004`\n"
        "- **Output**:\n"
        "  - `res_out = 32'h00000050`\n"
        "\n"
        "- The pipeline latency is 3 clock cycles.\n"
    )
    # rename EVERY identifier to unrelated nonsense; keep the structure + values.
    renamed = (base
               .replace("sig_a", "qzx_alpha")
               .replace("sig_b", "qzx_beta")
               .replace("res_out", "qzx_gamma")
               .replace("Example 1", "Example 1"))

    a = cwe.extract(base)
    b = cwe.extract(renamed)

    assert len(_of_kind(a, "worked_example")) == len(_of_kind(b, "worked_example")) == 1
    assert (_of_kind(a, "latency")[0]["latency_cycles"]
            == _of_kind(b, "latency")[0]["latency_cycles"] == 3)
    # the recovered VALUE pair is identical regardless of the names.
    assert (_of_kind(a, "worked_example")[0]["coverage_tokens"]
            == _of_kind(b, "worked_example")[0]["coverage_tokens"])


def test_extract_returns_checklistitem_shape():
    # the dicts carry the ChecklistItem contract fields kind/requirement/evidence.
    items = cwe.extract("For input 0x1 the output is 0x2. Valid after 2 cycles.")
    assert items
    for it in items:
        assert {"kind", "requirement", "evidence"} <= set(it)
        assert it["kind"] in ("worked_example", "latency")
        assert isinstance(it["requirement"], str) and it["requirement"]
        assert isinstance(it["evidence"], str) and it["evidence"]


def test_empty_input_returns_empty():
    assert cwe.extract("") == []
    assert cwe.extract(None) == []  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# §4.05 STRUCTURAL-ARTIFACT — a `X -> Y` whose LHS is the SUFFIX of a larger
# grouped/identifier token is a NOTATIONAL ARTIFACT, not a real I/O pair, and must
# NOT be emitted as a block-eligible coverage requirement (ORGANIC #780: the
# binary-to-BCD `0010_0101_0111 -> 257` phantom hard-blocked correct RTL).
# --------------------------------------------------------------------------- #
def test_grouped_binary_suffix_arrow_is_not_a_phantom_example():
    # `0010_0101_0111 -> 257`: the underscore breaks the numeric run so a naive
    # arrow regex pairs the LAST nibble `0111` with the full decimal `257`. That
    # phantom (0111 != 257; the real per-digit glosses are stated separately) must
    # be SUPPRESSED.
    prompt = ("Binary-to-BCD converter.\n"
              "Worked example: bcd_in = 0010_0101_0111 -> 257.\n"
              "Process MSD: 0010 = 2\nProcess Middle: 0101 = 5\nProcess LSD: 0111 = 7\n")
    we = _of_kind(cwe.extract(prompt), "worked_example")
    reqs = " | ".join(it["requirement"] for it in we)
    assert not any("0111" in it["requirement"] and "257" in it["requirement"] for it in we), reqs


def test_genuine_standalone_arrow_still_emitted():
    # §4.05 NO-LEAK: a GENUINE `X -> Y` whose LHS is NOT a token suffix (preceded by
    # whitespace / start) is a real worked example and MUST still be extracted.
    we = _of_kind(cwe.extract("Worked example: 0111 -> 7.\n"), "worked_example")
    assert any("0111" in it["requirement"] and "7" in it["requirement"] for it in we), \
        "a genuine standalone arrow pair must still be a (block-eligible) worked example"
