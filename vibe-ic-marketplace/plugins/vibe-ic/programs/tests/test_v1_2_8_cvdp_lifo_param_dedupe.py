"""CVDP LIFO param-decl hardening (Step-2.7 LOW finding on the T1-solver fix PR).

The parameterized LIFO emit resolves the spec's OWN parameter names: a `*WIDTH`
param for the data width and an entry-count `*_DEPTH` param OR a `2**ADDR_WIDTH`
address param for the depth. A latent §4.05 boundary: a spec that names ONLY an
address param (e.g. `ADDR_WIDTH`) whose DEFAULT happens to equal the data width W
made the resolver pick the SAME name as both the width param and the address param,
emitting a duplicate `parameter ADDR_WIDTH = ...` — an iverilog compile error.

No current dataset record reaches this (sync_lifo_0001 has DATA_WIDTH=8 distinct
from ADDR_WIDTH=3), but the hardening (exclude the chosen width_name from address
candidacy + a final dedupe backstop) makes the emit airtight. This pins it.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

_PROG = Path(__file__).resolve().parents[1]
if str(_PROG) not in sys.path:
    sys.path.insert(0, str(_PROG))

import memory_synth as M  # noqa: E402


def _param_names(decls):
    # decl form: "parameter NAME = VALUE" -> NAME
    return [d.split("=", 1)[0].replace("parameter", "").strip() for d in decls]


def test_addr_param_doubling_as_width_no_duplicate_decl():
    """The latent Step-2.7 case: only ADDR_WIDTH stated, default == data width W.
    The resolver must NOT declare ADDR_WIDTH twice (width binding wins; depth then
    falls back to the literal). Reproduces the exact reviewer input."""
    decls, width_expr, depth_expr = M._lifo_param_decls(
        "depth is 2**ADDR_WIDTH", {"ADDR_WIDTH": 8}, 8, 256)
    names = _param_names(decls)
    # NEGATIVE no-leak: never a duplicate `parameter NAME` (the bug shipped a dup).
    assert len(names) == len(set(names)), f"duplicate parameter decl: {names}"
    # width binds to the param; depth falls back to the literal (not a 2nd ADDR_WIDTH).
    assert width_expr == "ADDR_WIDTH"
    assert depth_expr == "256"


def test_normal_two_distinct_params_still_declared():
    """POSITIVE: distinct width + depth params are BOTH declared (the common case
    must keep working — sync_lifo_0001-shaped: DATA_WIDTH + ADDR_WIDTH)."""
    decls, width_expr, depth_expr = M._lifo_param_decls(
        "depth is 2**ADDR_WIDTH", {"DATA_WIDTH": 8, "ADDR_WIDTH": 3}, 8, 8)
    names = _param_names(decls)
    assert names == ["DATA_WIDTH", "ADDR_WIDTH"], names
    assert width_expr == "DATA_WIDTH"
    assert depth_expr == "(1 << ADDR_WIDTH)"


def test_filo_depth_entry_count_param():
    """POSITIVE: a *_DEPTH entry-count param (filo_0005-shaped) declares both and
    uses the depth param directly."""
    decls, width_expr, depth_expr = M._lifo_param_decls(
        "various data widths and buffer depths", {"DATA_WIDTH": 8, "FILO_DEPTH": 16},
        8, 16)
    names = _param_names(decls)
    assert names == ["DATA_WIDTH", "FILO_DEPTH"], names
    assert width_expr == "DATA_WIDTH"
    assert depth_expr == "FILO_DEPTH"


def test_emitted_lifo_has_no_duplicate_parameter_line():
    """End-state: the FULL emitted LIFO module never contains two identical
    `parameter NAME` declarations (the compile-breaking shape)."""
    prompt = (
        "Design a synchronous LIFO `sync_lifo`.\n"
        "- `ADDR_WIDTH` (default = 8): depth is 2**ADDR_WIDTH.\n"
        "### Input Ports:\n"
        "- `clock` (1 bit): clock.\n"
        "- `reset` (1 bit): synchronous reset, active high.\n"
        "- `write_en` (1 bit): write enable.\n"
        "- `read_en` (1 bit): read enable.\n"
        "- `data_in` (ADDR_WIDTH bits): input data.\n"
        "### Output Ports:\n"
        "- `empty` (1 bit): high when empty.\n"
        "- `full` (1 bit): high when full.\n"
        "- `data_out` (ADDR_WIDTH bits): output data.\n"
        "On reset the output clears to zero."
    )
    rtl = M.solve({
        "id": "test_sync_lifo_dup",
        "input": {"prompt": prompt, "context": {}},
        "output": {"response": "", "context": {"rtl/sync_lifo.sv": ""}},
        "harness": {"files": {"src/.env": "TOPLEVEL        = sync_lifo\n"}},
    })
    if rtl is None:
        # acceptable to SKIP this exotic shape, but if emitted it must be dup-free.
        return
    param_lines = re.findall(r"parameter\s+(\w+)\s*=", rtl)
    assert len(param_lines) == len(set(param_lines)), \
        f"duplicate parameter decl in emit: {param_lines}\n{rtl}"
