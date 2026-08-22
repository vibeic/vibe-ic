#!/usr/bin/env python3
"""The foundry mask spec's `cell_count` must not be decided by filename order.

`_count_netlist_instances` is the fallback the generator uses when
`synth.log` carries no yosys `Number of cells` summary line. It walked
`sorted(synth_dir.glob("*.v"))` and RETURNED ON THE FIRST file that
yielded any instantiation at all.

`sorted()` is filename order, and the synth directory is not a directory
of one file: yosys leaves techmap helper libraries there. `_dlatch_map.v`
is 192 bytes, contains exactly ONE instantiation, and `_` (0x5F) sorts
ahead of every lowercase letter — so it won, and `cell_count = 1` was
written into `mask_spec.json` and the handoff `README.txt` for a design
whose mapped netlist instantiates thousands of cells.

The reducer is MAX, not first-hit: a helper library can only contribute
FEWER instantiations than the netlist that instantiates the design, so
the largest candidate is monotone in the real answer. The two
"still-None / single-netlist" tests below are the over-fix guards — they
pass before AND after, and must keep passing.
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import foundry_handoff_pack_gen as fh  # noqa: E402


def _netlist(n_instances: int, module: str = "top") -> str:
    """A minimal yosys-shaped mapped netlist with `n_instances` cells."""
    body = "\n".join(
        f"  CELL_AND2 _{i}_ (.A(a), .B(b), .Y(y{i}));"
        for i in range(n_instances))
    return f"module {module} (a, b);\n{body}\nendmodule\n"


def test_helper_file_sorting_first_does_not_win(tmp_path):
    """The 192-byte techmap helper must not out-vote the real netlist.

    Reproduces the shipped defect exactly: `_dlatch_map.v` sorts first
    and carries one instantiation; `top_synth.v` carries 9379.
    """
    (tmp_path / "_dlatch_map.v").write_text(_netlist(1, "dlatch_map"))
    (tmp_path / "top_synth.v").write_text(_netlist(9379))
    assert fh._count_netlist_instances(tmp_path) == 9379


def test_order_of_discovery_is_irrelevant(tmp_path):
    """Same two files, names swapped so the BIG one sorts first.

    Directional control. It passes on the shipped code too — that is the
    point: it pins the direction the fix must NOT move in. A "take the
    LAST candidate instead of the first" fix satisfies the test above and
    breaks this one, so the pair together admit only an order-independent
    reducer.
    """
    (tmp_path / "aaa_helper.v").write_text(_netlist(9379, "real"))
    (tmp_path / "zzz_helper.v").write_text(_netlist(2, "helper"))
    assert fh._count_netlist_instances(tmp_path) == 9379


def test_still_none_when_there_is_no_netlist(tmp_path):
    """Over-fix guard: an honest None must survive. #446 — the generator
    must never fabricate a count, and `-1` is the placeholder the
    substance gate rightly FAILs on."""
    assert fh._count_netlist_instances(tmp_path) is None


def test_a_single_genuine_netlist_is_still_its_own_count(tmp_path):
    """Over-fix guard: the ordinary one-netlist case is unchanged."""
    (tmp_path / "top_synth.v").write_text(_netlist(42))
    assert fh._count_netlist_instances(tmp_path) == 42
