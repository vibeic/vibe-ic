"""CVDP spec-extraction: parameter-table Default-column (not last-cell) defaults.

A parameter table with an explicit `| Parameter | Description | Default | Constraints |`
header puts the default in column 3 of 4; the `_PARAM_TABLE_ROW` last-cell heuristic
missed it, so a port sized by `N*OUT_WIDTH` stayed a `param_expression_width` gap even
though N's and OUT_WIDTH's defaults are in the table. _header_default_table reads the
value from the column under the `Default` (or `Value`) header. Field: COMPLETE 222->223.

§4.05 NO-LEAK: binds ONLY from the Default-header column of a row whose first cell is
a parameter NAME and whose Default cell is a bare integer literal — a table with no
Default header, or a Default cell holding an expression, binds nothing.
"""
from __future__ import annotations

import sys
from pathlib import Path

_PROG = Path(__file__).resolve().parents[1]
if str(_PROG) not in sys.path:
    sys.path.insert(0, str(_PROG))

import verilog_width_resolve as W  # noqa: E402
from _hostpaths import require_corpus  # noqa: E402

_TBL = (
    "| Parameter | Description | Default | Constraints |\n"
    "|---|---|---|---|\n"
    "| `N` | Number of symbols | 4 | >= 2 |\n"
    "| `OUT_WIDTH` | output symbol width | 4 | Fixed at 4 |\n"
    "| `IN_WIDTH` | I/Q width | 3 | Fixed at 3 |"
)


def test_reads_default_column_not_last():
    d = W._header_default_table(_TBL)
    assert d == {"N": 4, "OUT_WIDTH": 4, "IN_WIDTH": 3}


def test_value_header_alias():
    tbl = ("| Name | Value |\n|---|---|\n| `DEPTH` | 16 |")
    assert W._header_default_table(tbl) == {"DEPTH": 16}


def test_no_default_header_binds_nothing():
    tbl = ("| Name | Width | Description |\n|---|---|---|\n"
           "| `bits` | N*OUT_WIDTH | output |")
    assert W._header_default_table(tbl) == {}


def test_expression_default_cell_dropped():
    tbl = ("| Parameter | Default |\n|---|---|\n| `OUT` | N*W |\n| `N` | 4 |")
    d = W._header_default_table(tbl)
    assert d == {"N": 4} and "OUT" not in d


def test_param_defaults_uses_header_column():
    # full path: the port `[N*OUT_WIDTH-1:0] bits` is now resolvable.
    pd = W.param_defaults("## Parameters\n" + _TBL, "")
    assert pd["N"] == 4 and pd["OUT_WIDTH"] == 4


def test_dataset_16qam_resolves_table_params():
    ds = require_corpus("_extbench/cvdp_open_v110/"
                        "cvdp_v1.1.0_nonagentic_code_generation_no_commercial.jsonl")
    if not ds.exists():
        import pytest
        pytest.skip("dataset not present")
    import json
    recs = {json.loads(l)["id"]: json.loads(l) for l in ds.read_text().splitlines()}
    r = recs.get("cvdp_copilot_16qam_mapper_0006")
    if r is None:
        import pytest
        pytest.skip("record not present")
    pd = W.param_defaults(r["input"]["prompt"], "")
    assert pd.get("N") == 4 and pd.get("OUT_WIDTH") == 4 and pd.get("IN_WIDTH") == 3
