"""test_pnr_scan_netlist_select.py — controls for WHICH netlist gets routed.

THE DEFECT, measured on a cell that PASSED:

    phase3/stage3/pnr/spm_pnr.v   ports: clk, p, rst, y, x …
        sin 0   sout 0   shift 0   tck 0   test 0

Place-and-route read `<top>_synth.v`, the PRE-DFT netlist.  The implemented,
tape-out-bound design carried NO scan chain, while step 11 reported 97 %
stuck-at coverage on a netlist that never becomes silicon.  "Is this chip
testable?" was being answered about a netlist that is not this chip.

The selection now prefers `post_dft_netlist.v`, but ONLY on measured evidence.
The risk in that change is not that it fails to fire — it is that it fires
WRONGLY and hands the router the old ATPG cut view (0 flops) or a stale
artefact.  Most of the tests below are about not firing.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import phase3_one_shot_runner as p3            # noqa: E402


GOOD_META = {
    "published": True,
    "chain_length_matches_flop_count": True,
    "internal_chain_length": 64,
    "boundary_chain_length": 34,
    "area_instances_delta": 200,
    "area_instances_delta_pct": 70.18,
    "dft_ports": ["sin", "shift", "test", "tck", "sout"],
}

SCAN_HEADER = """\
module spm(clk, rst, x, y, p, sin, shift, sout, tck, test);
  input clk;
  input rst;
  input [31:0] x;
  input y;
  output p;
  input sin;
  input shift;
  output sout;
  input tck;
  input test;
endmodule
"""

# What `post_dft_netlist.v` looked like BEFORE this work: an opt_clean of the
# ATPG cut view.  No DFT ports, no flops, `<inst>.d` pseudo-ports.  Handing
# this to the router is the worst outcome available, so it gets its own test.
CUT_HEADER = """\
module spm(clk, rst, x, y, p, \\_442_.d , \\_442_.q );
  input clk;
  input rst;
  input [31:0] x;
  input y;
  output p;
  output \\_442_.d ;
  input \\_442_.q ;
endmodule
"""


def _tree(tmp_path, *, meta=None, post_dft=None, pre_dft=True):
    synth = tmp_path / "phase2/stage2/synth"
    synth.mkdir(parents=True)
    if pre_dft:
        (synth / "spm_synth.v").write_text("module spm(clk); input clk;\nendmodule\n")
    if post_dft is not None:
        (synth / "post_dft_netlist.v").write_text(post_dft)
    if meta is not None:
        j = tmp_path / "reports/phase2/dft/scan_chain.json"
        j.parent.mkdir(parents=True)
        j.write_text(json.dumps(meta))
    return tmp_path


class TestRoutesTheScanNetlistWhenItIsReal:
    """The whole point.  If this fails the chain never reaches silicon."""

    def test_measured_chain_plus_dft_ports_selects_post_dft(self, tmp_path):
        p = _tree(tmp_path, meta=GOOD_META, post_dft=SCAN_HEADER)
        nl, note, is_scan = p3.pnr_input_netlist(p, "spm")
        assert nl.name == "post_dft_netlist.v"
        assert is_scan is True
        assert "POST-DFT" in note
        # The note must carry the COST, so a reader of the PnR row can see what
        # the chain bought and what it charged.
        assert "64 internal + 34 boundary" in note
        assert "+200 instances (70.18%)" in note


class TestNeverRoutesAnythingUnproven:
    """Every one of these must fall back to the pre-DFT netlist — the exact
    behaviour the flow had before this change.  A design with no measured scan
    chain routes byte-identically to before."""

    def test_no_metadata_at_all(self, tmp_path):
        p = _tree(tmp_path, post_dft=SCAN_HEADER)
        nl, note, is_scan = p3.pnr_input_netlist(p, "spm")
        assert nl.name == "spm_synth.v" and is_scan is False
        assert "NO scan chain" in note

    def test_unparseable_metadata(self, tmp_path):
        p = _tree(tmp_path, post_dft=SCAN_HEADER)
        j = p / "reports/phase2/dft/scan_chain.json"
        j.parent.mkdir(parents=True, exist_ok=True)
        j.write_text("{not json")
        nl, _, is_scan = p3.pnr_input_netlist(p, "spm")
        assert nl.name == "spm_synth.v" and is_scan is False

    def test_unpublished_chain(self, tmp_path):
        p = _tree(tmp_path, meta={**GOOD_META, "published": False},
                  post_dft=SCAN_HEADER)
        nl, _, is_scan = p3.pnr_input_netlist(p, "spm")
        assert nl.name == "spm_synth.v" and is_scan is False

    def test_chain_that_misses_flops(self, tmp_path):
        """A chain that leaves flops off it is untestable silicon.  It must not
        be routed under a name that says the design is scan-inserted."""
        p = _tree(tmp_path,
                  meta={**GOOD_META, "chain_length_matches_flop_count": False},
                  post_dft=SCAN_HEADER)
        nl, _, is_scan = p3.pnr_input_netlist(p, "spm")
        assert nl.name == "spm_synth.v" and is_scan is False

    def test_measured_chain_but_no_post_dft_netlist(self, tmp_path):
        p = _tree(tmp_path, meta=GOOD_META)
        nl, note, is_scan = p3.pnr_input_netlist(p, "spm")
        assert nl.name == "spm_synth.v" and is_scan is False
        assert "step 12 left no post_dft_netlist.v" in note

    def test_leftover_cut_view_post_dft_netlist_is_refused(self, tmp_path):
        """THE dangerous case.  A `post_dft_netlist.v` from the old cut-view
        path has no DFT ports and no flops.  Routing it would produce a design
        with no sequential elements at all.  It must be refused BY MEASUREMENT
        (the declared DFT ports are absent from the file), not by trusting the
        metadata alone."""
        p = _tree(tmp_path, meta=GOOD_META, post_dft=CUT_HEADER)
        nl, note, is_scan = p3.pnr_input_netlist(p, "spm")
        assert nl.name == "spm_synth.v" and is_scan is False
        assert "does not carry the DFT port(s)" in note
        assert "must not be routed" in note

    def test_partially_scanned_netlist_is_refused(self, tmp_path):
        """One missing DFT port is enough — a netlist that has `sin` but not
        `sout` is not a chain, it is a broken one."""
        p = _tree(tmp_path, meta=GOOD_META,
                  post_dft=SCAN_HEADER.replace("  output sout;\n", ""))
        nl, note, is_scan = p3.pnr_input_netlist(p, "spm")
        assert nl.name == "spm_synth.v" and is_scan is False
        assert "sout" in note


class TestTheFallbackIsAlwaysNamed:
    """KILLS: a silent fallback.  A run that routed a chainless netlist looking
    exactly like a run that routed a scan one is how this defect survived a
    whole campaign.  Every path returns a note that says which it was and why."""

    @pytest.mark.parametrize("meta,post", [
        (None, SCAN_HEADER),
        ({**GOOD_META, "published": False}, SCAN_HEADER),
        (GOOD_META, None),
        (GOOD_META, CUT_HEADER),
        (GOOD_META, SCAN_HEADER),
    ], ids=["no-meta", "unpublished", "no-post-dft", "cut-view", "real-chain"])
    def test_note_is_never_empty_and_names_the_file(self, tmp_path, meta, post):
        p = _tree(tmp_path, meta=meta, post_dft=post)
        nl, note, _ = p3.pnr_input_netlist(p, "spm")
        assert note and nl.name in note
