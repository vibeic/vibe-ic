#!/usr/bin/env python3
"""The PDK sniff must read the WHOLE netlist, not a fixed-size head.

Both sniffs used to classify an entire netlist from a head slice
(`fault_atpg_run` 200 KB, `design_one_shot_runner` 20 KB). A design that emits
hard macros and generic primitives before its standard cells pushes the first
library token past that window, and the LARGER the design the likelier that
is — so the truncation failed hardest on the designs it mattered most for.

It failed SILENTLY: "no library token found" is also what a genuinely generic
netlist yields, so the caller could not distinguish "this netlist is unmapped"
from "we stopped reading", and downstream published the difference as an
open-source ATPG capability limit.
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))


def _load(name):
    spec = importlib.util.spec_from_file_location(name, str(PROG / f"{name}.py"))
    m = importlib.util.module_from_spec(spec)
    sys.modules[name] = m
    spec.loader.exec_module(m)
    return m


fa = _load("fault_atpg_run")


def _netlist(pad_chars: int, flop_cell: str) -> str:
    """Hard macros + generic primitives first, ONE std-cell flop last.

    This is an ordinary emission order, not a contrived one: a design's own
    macros and its generic glue routinely precede its mapped std cells.
    """
    filler = "\n".join(
        f"  MY_HARDMACRO u{i} (.a(n{i}), .z(m{i}));" for i in range(pad_chars // 40))
    return (f"module top(clk);\n{filler}\n"
            f"  {flop_cell} ff0 (.CLK(clk), .D(d), .Q(q));\nendmodule\n")


@pytest.mark.parametrize("pad", [10_000, 300_000, 900_000])
def test_pdk_is_found_wherever_the_first_std_cell_sits(tmp_path, pad):
    """The verdict must not depend on the token's BYTE OFFSET."""
    (tmp_path / "n.v").write_text(_netlist(pad, "sky130_fd_sc_hd__dfxtp_1"))
    assert fa.sniff_pdk_over_whole_netlist(tmp_path, "n.v") == "sky130"


def test_the_old_head_slice_would_have_missed_it(tmp_path):
    """Pins the defect: the 200 KB head genuinely does NOT contain the token,
    so this test fails against the pre-fix implementation rather than passing
    for an unrelated reason."""
    nl = _netlist(300_000, "sky130_fd_sc_hd__dfxtp_1")
    (tmp_path / "n.v").write_text(nl)
    head = fa._read_netlist_text(tmp_path, "n.v")          # the old path
    assert "sky130_fd_sc_hd__" not in head
    assert fa.sniff_pdk_from_netlist(head) is None
    # ...and the whole-file scan finds it anyway.
    assert fa.sniff_pdk_over_whole_netlist(tmp_path, "n.v") == "sky130"


def test_a_token_straddling_a_chunk_boundary_is_still_found(tmp_path):
    """Chunked reads must overlap, or a prefix split across the 1 MiB seam
    disappears — a truncation bug reintroduced at a different offset."""
    tok = "sky130_fd_sc_hd__dfxtp_1"
    for split in range(1, len(tok)):
        pad = (1 << 20) - split
        (tmp_path / "n.v").write_text("/" * pad + f"\n  {tok} ff0 (.CLK(c));\n")
        assert fa.sniff_pdk_over_whole_netlist(tmp_path, "n.v") == "sky130", split


def test_a_genuinely_generic_netlist_still_returns_none(tmp_path):
    """NEGATIVE CONTROL. Reading further must not invent a PDK — an unmapped
    netlist is exactly the case the caller is supposed to report honestly."""
    (tmp_path / "n.v").write_text(
        "module top(clk);\n" + "\n".join(
            f"  $_NAND_ g{i} (.A(a{i}), .B(b{i}), .Y(y{i}));" for i in range(20_000))
        + "\n  $_DFF_P_ ff0 (.C(clk), .D(d), .Q(q));\nendmodule\n")
    assert fa.sniff_pdk_over_whole_netlist(tmp_path, "n.v") is None


def test_missing_file_returns_none_not_an_exception(tmp_path):
    assert fa.sniff_pdk_over_whole_netlist(tmp_path, "nope.v") is None


def test_config_order_decides_when_a_netlist_names_two_libraries(tmp_path):
    """Precedence must stay what it was on untruncated text: first in
    PDK_CONFIG order, NOT 'whichever 1 MiB chunk matched first'."""
    prefixes = fa.pdk_cell_prefixes()
    names = list(prefixes)
    if len(names) < 2:
        pytest.skip("needs >=2 configured PDKs")
    first, second = names[0], names[1]
    p_first = sorted(prefixes[first])[0]
    p_second = sorted(prefixes[second])[0]
    # second-in-config-order appears FIRST in the file, and in an earlier chunk
    (tmp_path / "n.v").write_text(
        f"module top;\n  {p_second}x u0 ();\n" + "/" * (1 << 21)
        + f"\n  {p_first}x u1 ();\nendmodule\n")
    assert fa.sniff_pdk_over_whole_netlist(tmp_path, "n.v") == first
