#!/usr/bin/env python3
"""A fixed 30-minute wall was read as "this engine cannot grade this design".

`run_fault` ran the stuck-at ATPG under a hard-coded `timeout=1800`. That asks
"has 30 minutes passed"; the answer was consumed as "can this engine grade this
design". The two agree only on designs small enough for the difference not to
matter.

MEASURED (ibex x sky130A, 2026-08-05). On the sky130-mapped 31k-cell netlist the
engine RUNS: `fault chain` built a real scan chain from `ibex_core_synth.v`
against the PDK liberty with real scan DFFs, and the run's own record says
"the engine was running, not unable ... a BUDGET outcome, not a capability gap".
The fixed wall turned a large design's honest partial coverage into an absent
measurement, and the DFT tail went MISSING behind it.

The at-speed sibling had already fixed exactly this — its comment names "the old
1800 s" — and the same constant was still live in the stuck-at path. The helper
and the port parser are IMPORTED from that sibling rather than copied, so the
two engines cannot drift, and the size signal is the same quantity the
coefficient was measured against: the pseudo-PI/PO pairs the cut exposed.

Both directions are pinned. The floor must be unchanged to the second for a
small design — otherwise this is a blanket timeout increase wearing a
measurement's clothes — and a large design must earn more, monotonically, under
the campaign ceiling.
"""
from __future__ import annotations

import sys
from pathlib import Path

PROGRAMS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROGRAMS))

import transition_fault_atpg_run as tdf  # noqa: E402


def test_a_design_with_no_flops_keeps_the_floor_exactly():
    """The reverse case, and the one that stops this being a blanket bump."""
    assert tdf._scaled_wall_budget(1800, 0) == 1800


def test_a_small_design_moves_only_a_little():
    small = tdf._scaled_wall_budget(1800, 8)
    assert 1800 <= small <= 1800 + 8 * tdf.WALL_PER_SCAN_FLOP + 1


def test_a_large_design_earns_more_wall():
    """ibex-scale. The whole point: 1800 s was measured insufficient here."""
    big = tdf._scaled_wall_budget(1800, 1937)      # ibex's $_DFF_ count
    assert big > 1800
    assert big <= tdf.WALL_BUDGET_MAX


def test_the_budget_is_capped_so_a_huge_design_cannot_run_away():
    assert tdf._scaled_wall_budget(1800, 10_000_000) == tdf.WALL_BUDGET_MAX


def test_the_budget_never_decreases_with_size():
    prev = 0
    for flops in (0, 1, 10, 100, 1272, 1937, 50_000, 10_000_000):
        cur = tdf._scaled_wall_budget(1800, flops)
        assert cur >= prev, f"budget fell at {flops} flops: {cur} < {prev}"
        prev = cur


def test_the_stuck_at_runner_no_longer_hard_codes_the_wall():
    """The call site must consume the scaled value. A helper that exists and is
    not called is the same defect with extra steps.

    Judged on the AST, not on the file's text. The first version of this test
    asserted `"timeout=1800" not in src` and went red on two PROSE mentions of
    the old constant — including the comment explaining why it was removed. A
    guard that fires on its subject being DISCUSSED is the same defect it is
    guarding against, and this repo already fixed one of those today.
    """
    import ast
    tree = ast.parse((PROGRAMS / "fault_atpg_run.py").read_text(encoding="utf-8"))
    literal_walls, scaled_walls = [], []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        for kw in node.keywords:
            if kw.arg != "timeout":
                continue
            if isinstance(kw.value, ast.Constant) and kw.value.value == 1800:
                literal_walls.append(node.lineno)
            if isinstance(kw.value, ast.Name) and kw.value.id == "_atpg_wall":
                scaled_walls.append(node.lineno)
    assert scaled_walls, "no call passes the scaled wall to the launcher"
    assert not literal_walls, (
        f"a hard-coded 1800 s wall still reaches a launcher at line(s) "
        f"{literal_walls}")


def test_the_runner_records_the_budget_it_used():
    """"Exceeded its wall budget" without the number is a verdict nobody
    downstream can check or re-plan against."""
    src = (PROGRAMS / "fault_atpg_run.py").read_text(encoding="utf-8")
    assert '"atpg_wall_budget_s"' in src
    assert '"atpg_wall_budget_basis"' in src


def test_the_size_signal_comes_from_the_cut_the_engine_reads():
    """Keyed on the cut's own pseudo-port pairs — the same quantity the
    coefficient was measured against, and a property of the design rather than
    of any chip/PDK/vendor name."""
    src = (PROGRAMS / "fault_atpg_run.py").read_text(encoding="utf-8")
    assert "parse_cut_ports" in src
    assert "_scaled_wall_budget" in src


def test_parse_cut_ports_counts_pseudo_pairs_not_primary_io():
    """The helper being reused must actually measure flops, not ports."""
    # Non-ANSI port declarations — the form `fault cut` actually emits, and the
    # only form `_PORT_RE` matches. An ANSI-header fixture parses to zero pairs
    # and would have made this test pass for the wrong reason.
    cut = (
        "module core(clk, rst, y, \\ff1 , \\ff1.d , \\ff2 , \\ff2.d );\n"
        "  input clk;\n  input rst;\n  output y;\n"
        "  input \\ff1 ;\n  output \\ff1.d ;\n"
        "  input \\ff2 ;\n  output \\ff2.d ;\n"
        "endmodule\n")
    _top, _pi, _po, pairs = tdf.parse_cut_ports(cut)
    assert len(pairs) == 2, pairs
