#!/usr/bin/env python3
"""RTL collectors exclude generated flow output and retain design sources."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import gate_utils  # noqa: E402
import rtl_scan_scope  # noqa: E402


BIG = "module big(); endmodule\n" + ("// filler\n" * 200)
SMALL = "module small(input clk); endmodule\n"


@pytest.fixture
def proj(tmp_path):
    """A project shaped like a real post-synthesis run."""
    p = tmp_path / "proj"
    (p / "phase2/stage1/rtl").mkdir(parents=True)
    (p / "phase2/stage1/rtl/design.v").write_text(SMALL)
    # the flow's own outputs, in the two shapes that matter
    (p / "phase2/stage2/synth").mkdir(parents=True)
    (p / "phase2/stage2/synth/netlist.v").write_text(BIG)
    for step in ("9_synthesis_yosys_mapped_netlist",
                 "14_synthesis_handoff_gate_pre_pnr_yosys_script_netl"):
        d = p / "steps/phase2/stage2" / step
        d.mkdir(parents=True)
        (d / "netlist.v").write_text(BIG)
    return p


def _names(files):
    return sorted(Path(f).name for f in files)


# ------------------------------------------------------------- the defect

def test_gate_utils_skips_the_publication_view(proj):
    """FAILS PRE-FIX. `steps/` is the flow's own output, not design RTL."""
    got = gate_utils.find_rtl_files(proj)
    assert not any("steps" in Path(f).parts for f in got), (
        f"gate_utils read the flow's own publication view: {[str(f) for f in got]}")
    assert _names(got) == ["design.v"]


def test_the_collectors_now_agree(proj):
    """The retained lint and authoritative-RTL collectors agree on flow output."""
    expect = _names(gate_utils.find_rtl_files(proj))
    assert _names(rtl_scan_scope.authoritative_rtl_files(proj)) == expect


# ------------------------------------- guards (must pass BOTH ways)

def test_real_rtl_is_still_collected(proj):
    """The design's own RTL must never be dropped by an exclusion."""
    for got in (gate_utils.find_rtl_files(proj), rtl_scan_scope.authoritative_rtl_files(proj)):
        assert "design.v" in _names(got)


def test_input_is_deliberately_still_in_scope_for_gate_utils(tmp_path):
    """`input` is NOT added: a staged macro stub stays lintable.

    rtl_scan_scope excludes `input` because staged vendor enablement is not the
    design's authoritative RTL. These lint gates legitimately want to see it,
    and it is small. Adding it would be a silent COVERAGE change, not a
    performance fix — this test pins that decision so it is not made by
    accident later.
    """
    p = tmp_path / "proj"
    (p / "input/pdk_local/fakeram").mkdir(parents=True)
    (p / "input/pdk_local/fakeram/fakeram.v").write_text(SMALL)
    assert "fakeram.v" in _names(gate_utils.find_rtl_files(p))


def test_shared_contract_still_excludes_what_it_always_did():
    """The names gate_utils already had must all survive."""
    for name in ("db", "incremental_db", "output_files", "build", "sim",
                 "synth", "formal", "dft", "pnr", "gds", "reports",
                 ".git", "__pycache__", "node_modules"):
        assert name in gate_utils.EXCLUDED_DIRS


def test_added_names_match_the_other_contract():
    """The two names added are exactly the flow-output ones rtl_scan_scope has."""
    for name in ("steps", "oracle_run"):
        assert name in gate_utils.EXCLUDED_DIRS
        assert name in rtl_scan_scope.EXCLUDED_DIR_NAMES
