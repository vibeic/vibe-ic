"""CVDP spec-extraction: prose-derived parameter defaults.

A port width `[ENCODED_DATA-1:0]` stays a `param_expression_width` EXTRACTION_GAP
when ENCODED_DATA's value is stated in PROSE as an arithmetic expression over known
params ("ENCODED_DATA: Calculated as `PARITY_BIT + DATA_WIDTH + 1`") rather than a
`localparam` line. param_defaults now harvests these and resolves them at a fixed
point AFTER every literal default is known. Field-measured: COMPLETE 221 -> 222.

§4.05 NO-LEAK: the binding is added ONLY when the backticked expression is arithmetic
AND fully resolves to an int from STATED params — a non-arithmetic prose value
("the minimum number of bits to index ENCODED_DATA") or an unknown-param expr drops.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROG = Path(__file__).resolve().parents[1]
if str(_PROG) not in sys.path:
    sys.path.insert(0, str(_PROG))

import verilog_width_resolve as W  # noqa: E402
from _hostpaths import require_corpus  # noqa: E402


def test_prose_derived_sum_resolves():
    txt = ("- **DATA_WIDTH**: The default is 4.\n"
           "- **PARITY_BIT**: The default is 3.\n"
           "- **ENCODED_DATA**: Calculated as the sum of `PARITY_BIT + DATA_WIDTH + 1`.")
    pd = W.param_defaults(txt, "")
    assert pd.get("ENCODED_DATA") == 8


def test_prose_derived_chain_settles():
    """A chain ENC -> uses A,B where A,B are themselves derived resolves to a fixed point."""
    txt = ("- A = 4\n- B = 3\n"
           "- **MID**: defined as `A * 2`\n"
           "- **TOP**: computed as `MID + B`")
    pd = W.param_defaults(txt, "")
    assert pd.get("MID") == 8 and pd.get("TOP") == 11


def test_table_cell_derived():
    # the param-table default-cell harvest only fires when the prompt frames a
    # parameter section (the guard that avoids harvesting a generic numeric table),
    # so include the framing word as a real prompt would.
    txt = ("## Parameters\n"
           "| `DATA_WIDTH` | width | 16 |\n"
           "| `NBW` | Bit-width. It is defined as `2 * DATA_WIDTH + 1` to avoid overflow | |")
    pd = W.param_defaults(txt, "")
    assert pd.get("NBW") == 33


def test_no_leak_non_arithmetic_prose():
    txt = "- **ENCODED_DATA_BIT**: Calculated as the minimum number of bits to index `ENCODED_DATA`."
    assert "ENCODED_DATA_BIT" not in W.param_defaults(txt, "")


def test_no_leak_unknown_param_expr():
    txt = "- **FOO**: defined as `UNKNOWN_X + 1`."
    assert "FOO" not in W.param_defaults(txt, "")


def test_no_leak_no_backtick_expr():
    txt = "- **BAR**: calculated as the sum of all inputs."
    assert "BAR" not in W.param_defaults(txt, "")


def test_dataset_hamming_encoded_data():
    ds = require_corpus("_extbench/cvdp_open_v110/"
                        "cvdp_v1.1.0_nonagentic_code_generation_no_commercial.jsonl")
    if not ds.exists():
        import pytest
        pytest.skip("dataset not present")
    import json
    recs = {json.loads(l)["id"]: json.loads(l) for l in ds.read_text().splitlines()}
    r = recs.get("cvdp_copilot_hamming_code_tx_and_rx_0009")
    if r is None:
        import pytest
        pytest.skip("record not present")
    pd = W.param_defaults(r["input"]["prompt"], "")
    assert pd.get("ENCODED_DATA") == 8  # PARITY_BIT(3) + DATA_WIDTH(4) + 1
