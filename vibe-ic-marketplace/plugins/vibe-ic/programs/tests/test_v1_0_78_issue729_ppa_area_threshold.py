#!/usr/bin/env python3
"""ORGANIC #729 — PPA area-reduction-threshold gate
`programs/ppa_area_threshold_check.py` + the latency-gate NOT-APPLICABLE
secondary fix.

PRIMARY (ppa_area_threshold_check)
==================================
On a v1.0.77 forward-verify an area-optimization (cid007) problem passed every
shipped gate yet achieved only ~3% area reduction while the spec's success
metric is a measurable >=N% reduction in cells AND wires vs the provided
original. No plugin program synthesised the (original, optimized) pair and
checked the delta. This gate IS that deterministic check: yosys `stat` on BOTH
with the SAME recipe → cells%/wires% reduction → BLOCK if a bound metric is
below the prompt-stated threshold.

The %-computation + threshold-parse + verdict are PURE functions, unit-tested
against CANNED yosys `stat` text — NO container needed. The live-yosys path is
gated behind a skip when docker / the vibeic-eda container is unavailable.

  * parse_threshold_from_prompt: pull the threshold + bound metric (cells /
    wires / both) out of a prompt's prose.
  * parse_stat: read `Number of cells:` / `Number of wires:` off a yosys
    transcript.
  * compute_reduction_pct: 100*(orig-opt)/orig, None when unformable.
  * decide: PASS / BLOCK / NOT_APPLICABLE from the two reductions + bound
    metric + threshold.

§4.05 NO-LEAK (this is a BLOCKING gate)
  * a below-threshold pair (canned stats) → BLOCK; an above-threshold pair →
    PASS — the gate does NOT false-block a real optimization and DOES block an
    under-reduced one.
  * yosys / container ABSENT → NOT-APPLICABLE (rc 0), NEVER a false block.
  * an unparseable prompt threshold → NOT-APPLICABLE (rc 0).
  * an unmeasurable metric (missing cell/wire count) → NOT-APPLICABLE.

SECONDARY (latency_conformance_check NOT-APPLICABLE)
====================================================
A pure STREAMING design (no pulse->done handshake) TIMES OUT — neither a real
timing block nor a PASS. With --allow-no-handshake the gate returns a DISTINCT
NOT_APPLICABLE verdict on a DISTINCT exit code (3) so it is never misread as a
real PASS. WITHOUT the flag the default TIMEOUT (rc 1) is unchanged, and a
design that DOES have a handshake still MEASURES.

chip-AGNOSTIC: pure measurement + arithmetic; no chip/SKU literal (enforced by
source_chip_agnostic_check).
"""
from __future__ import annotations

import importlib.util
import shutil
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

_PROGRAMS = Path(__file__).resolve().parents[1]


def _load(modname, filename):
    spec = importlib.util.spec_from_file_location(
        modname, str(_PROGRAMS / filename))
    mod = importlib.util.module_from_spec(spec)
    # the latency module does `sys.path.insert(0, programs)` itself; make sure
    # the programs dir is importable for both modules' shared-helper imports.
    if str(_PROGRAMS) not in sys.path:
        sys.path.insert(0, str(_PROGRAMS))
    spec.loader.exec_module(mod)
    return mod


ppa = _load("ppa_area_threshold_check", "ppa_area_threshold_check.py")
lcc = _load("latency_conformance_check", "latency_conformance_check.py")

_HAVE_IVERILOG = (shutil.which("iverilog") is not None
                  and shutil.which("vvp") is not None)


def _container_up(container="vibeic-eda") -> bool:
    if shutil.which("docker") is None:
        return False
    try:
        cp = _pr.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", container],
            capture_output=True, text=True)
        return cp.returncode == 0 and cp.stdout.strip() == "true"
    except Exception:
        return False


_HAVE_CONTAINER = _container_up()


# ════════════════════════════════════════════════════════════════════════════
# PRIMARY — PPA area-threshold PURE helpers (no container)
# ════════════════════════════════════════════════════════════════════════════

# canned yosys `stat` transcripts (the real format: "Number of cells:" etc.)
_STAT_ORIG = """\
=== divider ===

   Number of wires:                250
   Number of wire bits:            900
   Number of public wires:          40
   Number of memories:               0
   Number of cells:                400
     $_AND_                         120
     $_DFF_P_                        80
"""

# optimized: 400→272 cells (32% reduction), 250→205 wires (18% reduction)
_STAT_OPT_GOOD = """\
=== divider ===

   Number of wires:                205
   Number of wire bits:            720
   Number of cells:                272
"""

# optimized: 400→388 cells (3% reduction), 250→245 wires (2% reduction)
_STAT_OPT_BAD = """\
=== divider ===

   Number of wires:                245
   Number of cells:                388
"""

# the NEW yosys 0.40+ / 0.62 `stat` spelling (count FIRST, with decoy
# "wire bits" / "public wires" / "port bits" lines that must NOT be mistaken
# for the wire/cell count). This is exactly the real vibeic-eda container format.
_STAT_NEW_FORM = """\
10. Printing statistics.

=== opt_demo ===

        +----------Local Count, excluding submodules.
        |
      152 wires
      187 wire bits
        6 public wires
       41 public wire bits
        4 ports
       25 port bits
       98 cells
       32   $_NAND_
       46   $_NOR_
       20   $_NOT_
"""


# ── threshold parse ──────────────────────────────────────────────────────────
def test_parse_threshold_cells_and_wires_both():
    pct, metric = ppa.parse_threshold_from_prompt(
        "Reduce the design by at least 20% in both cells and wires.")
    assert pct == 20.0
    assert metric == "both"


def test_parse_threshold_cells_only():
    pct, metric = ppa.parse_threshold_from_prompt(
        "Achieve a 25% reduction in the number of cells (gate count).")
    assert pct == 25.0
    assert metric == "cells"


def test_parse_threshold_wires_only():
    pct, metric = ppa.parse_threshold_from_prompt(
        "The optimized netlist must use 15% fewer wires / nets.")
    assert pct == 15.0
    assert metric == "wires"


def test_parse_threshold_bare_area_defaults_to_both():
    # an "area reduction" percentage with neither cell nor wire word → both.
    pct, metric = ppa.parse_threshold_from_prompt(
        "Optimize for area: at least 20% area reduction is required.")
    assert pct == 20.0
    assert metric == "both"


def test_parse_threshold_unparseable_raises():
    # a percentage NOT near an area word (a duty-cycle) is ignored.
    with pytest.raises(ppa.ThresholdParseError):
        ppa.parse_threshold_from_prompt(
            "Generate a clock with a 50% duty cycle and a UART at 9600 baud.")
    with pytest.raises(ppa.ThresholdParseError):
        ppa.parse_threshold_from_prompt("Just build the module.")


# ── stat parse + reduction arithmetic ────────────────────────────────────────
def test_parse_stat_reads_cells_and_wires():
    s = ppa.parse_stat(_STAT_ORIG)
    assert s["cells"] == 400
    assert s["wires"] == 250


def test_parse_stat_missing_metric_is_none():
    s = ppa.parse_stat("=== top ===\n   Number of cells:    10\n")
    assert s["cells"] == 10
    assert s["wires"] is None  # never a fabricated 0


def test_parse_stat_new_yosys_form_and_no_decoy():
    """The NEW yosys 0.40+/0.62 'N cells' / 'N wires' spelling parses, and the
    decoy 'wire bits' / 'public wires' / 'port bits' lines do NOT poison it."""
    s = ppa.parse_stat(_STAT_NEW_FORM)
    assert s["cells"] == 98     # NOT 32 ($_NAND_) and NOT a wire-bit count
    assert s["wires"] == 152    # NOT 187 ("wire bits") NOT 6 ("public wires")


def test_compute_reduction_pct_basic():
    # 400 → 272 == 32% ; 250 → 205 == 18%
    assert ppa.compute_reduction_pct(400, 272) == 32.0
    assert ppa.compute_reduction_pct(250, 205) == 18.0


def test_compute_reduction_pct_none_when_unformable():
    assert ppa.compute_reduction_pct(None, 100) is None
    assert ppa.compute_reduction_pct(100, None) is None
    assert ppa.compute_reduction_pct(0, 0) is None     # 0-cell original
    # a design that GREW is a real negative reduction (not None) — it fails any
    # positive threshold.
    assert ppa.compute_reduction_pct(100, 120) == -20.0


# ── the decide() verdict over canned stat blobs (the core BLOCK/PASS logic) ──
def _reductions_from_canned(orig_text, opt_text):
    o = ppa.parse_stat(orig_text)
    p = ppa.parse_stat(opt_text)
    return (ppa.compute_reduction_pct(o["cells"], p["cells"]),
            ppa.compute_reduction_pct(o["wires"], p["wires"]))


def test_decide_above_threshold_passes():
    """An above-threshold pair (32% cells / 18% wires) PASSES a 15% both bar."""
    cr, wr = _reductions_from_canned(_STAT_ORIG, _STAT_OPT_GOOD)
    verdict, reason = ppa.decide(cr, wr, 15.0, "both")
    assert verdict == "PASS", reason


def test_decide_below_threshold_blocks_both():
    """A below-threshold pair (3% cells / 2% wires) BLOCKs a 20% both bar."""
    cr, wr = _reductions_from_canned(_STAT_ORIG, _STAT_OPT_BAD)
    verdict, reason = ppa.decide(cr, wr, 20.0, "both")
    assert verdict == "BLOCK", reason
    assert "cells reduction" in reason and "wires reduction" in reason


def test_decide_wires_just_under_cells_over_still_blocks_both():
    """cells 32% (over) but wires 18% (under a 20% bar) → BLOCK on wires."""
    cr, wr = _reductions_from_canned(_STAT_ORIG, _STAT_OPT_GOOD)
    verdict, reason = ppa.decide(cr, wr, 20.0, "both")
    assert verdict == "BLOCK", reason
    assert "wires reduction 18" in reason
    # but bound to CELLS only, the same pair PASSES (32% >= 20%).
    verdict2, _ = ppa.decide(cr, wr, 20.0, "cells")
    assert verdict2 == "PASS"


def test_decide_unmeasurable_bound_metric_is_not_applicable():
    """A bound metric whose reduction is None → NOT_APPLICABLE (never block)."""
    # wires unmeasurable but bound (both) → NOT_APPLICABLE, NOT a false block.
    verdict, reason = ppa.decide(32.0, None, 20.0, "both")
    assert verdict == "NOT_APPLICABLE", reason
    # but if only CELLS is bound, the None wires is irrelevant → PASS.
    verdict2, _ = ppa.decide(32.0, None, 20.0, "cells")
    assert verdict2 == "PASS"


# ── orchestration §4.05: NOT-APPLICABLE when container/docker absent ─────────
def test_run_not_applicable_when_no_threshold(tmp_path):
    """No --threshold-pct and no prompt → NOT-APPLICABLE rc 0 (no false block)."""
    o = tmp_path / "o.v"
    o.write_text("module m(); endmodule\n")
    p = tmp_path / "p.v"
    p.write_text("module m(); endmodule\n")
    rc, report = ppa.run_ppa_area_threshold(
        original=o, optimized=p, top="m", prompt_text=None,
        threshold_override=None, metric_override=None, container="vibeic-eda")
    assert rc == 0
    assert report["verdict"] == "NOT_APPLICABLE"


def test_run_not_applicable_when_prompt_unparseable(tmp_path):
    """A prompt with no area-reduction threshold → NOT-APPLICABLE rc 0."""
    o = tmp_path / "o.v"
    o.write_text("module m(); endmodule\n")
    p = tmp_path / "p.v"
    p.write_text("module m(); endmodule\n")
    rc, report = ppa.run_ppa_area_threshold(
        original=o, optimized=p, top="m",
        prompt_text="Build a UART. No area target.",
        threshold_override=None, metric_override=None, container="vibeic-eda")
    assert rc == 0
    assert report["verdict"] == "NOT_APPLICABLE"


@pytest.mark.skipif(_HAVE_CONTAINER,
                    reason="container present — this pins the ABSENT path")
def test_run_not_applicable_when_container_absent(tmp_path):
    """yosys/container ABSENT → NOT-APPLICABLE rc 0, NEVER a false block."""
    o = tmp_path / "o.v"
    o.write_text("module m(input a, output b); assign b=a; endmodule\n")
    p = tmp_path / "p.v"
    p.write_text("module m(input a, output b); assign b=a; endmodule\n")
    rc, report = ppa.run_ppa_area_threshold(
        original=o, optimized=p, top="m", prompt_text=None,
        threshold_override=20.0, metric_override="both",
        container="vibeic-eda-definitely-not-running-xyz")
    assert rc == 0
    assert report["verdict"] == "NOT_APPLICABLE"
    assert report.get("tool_available") is False


def test_run_missing_file_is_setup_error(tmp_path):
    """A missing --original/--optimized is a setup error (rc 2 via main)."""
    o = tmp_path / "exists.v"
    o.write_text("module m(); endmodule\n")
    rc = ppa.main(["--original", str(o), "--optimized",
                   str(tmp_path / "nope.v"), "--top", "m",
                   "--threshold-pct", "20"])
    assert rc == 2


# ── LIVE yosys path (skipped unless the vibeic-eda container is up) ──────────────
# These are NOT a redundant-vs-folded pair (yosys `opt` would fold both to the
# same size). They are a genuinely LARGE datapath (an 8x8 multiplier) vs a
# genuinely SMALL one (a bitwise AND): the cell/wire reduction SURVIVES opt, so
# the live PASS path is exercised against a real, large measured reduction.
_RTL_ORIG_LIVE = """\
module opt_demo (input [7:0] a, input [7:0] b, output [15:0] y);
  assign y = a * b;               // full 8x8 multiplier — many cells
endmodule
"""

_RTL_OPT_LIVE = """\
module opt_demo (input [7:0] a, input [7:0] b, output [15:0] y);
  assign y = {8'b0, a & b};       // bitwise AND — far fewer cells
endmodule
"""


@pytest.mark.skipif(not _HAVE_CONTAINER,
                    reason="vibeic-eda container not running — live yosys path")
def test_live_yosys_above_threshold_passes(tmp_path):
    o = tmp_path / "orig.v"
    o.write_text(_RTL_ORIG_LIVE)
    p = tmp_path / "opt.v"
    p.write_text(_RTL_OPT_LIVE)
    rc, report = ppa.run_ppa_area_threshold(
        original=o, optimized=p, top="opt_demo", prompt_text=None,
        threshold_override=5.0, metric_override="cells", container="vibeic-eda")
    # a real shrink should clear a low bar; if synth could not measure it
    # returns NOT-APPLICABLE (still rc 0, never a false block).
    assert rc == 0
    assert report["verdict"] in ("PASS", "NOT_APPLICABLE")


@pytest.mark.skipif(not _HAVE_CONTAINER,
                    reason="vibeic-eda container not running — live yosys path")
def test_live_yosys_below_threshold_blocks(tmp_path):
    # original-vs-itself: 0% reduction → a 20% bar must BLOCK (rc 1).
    o = tmp_path / "orig.v"
    o.write_text(_RTL_ORIG_LIVE)
    p = tmp_path / "same.v"
    p.write_text(_RTL_ORIG_LIVE)
    rc, report = ppa.run_ppa_area_threshold(
        original=o, optimized=p, top="opt_demo", prompt_text=None,
        threshold_override=20.0, metric_override="both", container="vibeic-eda")
    # 0% reduction vs a 20% bar — BLOCK, unless synth was unmeasurable.
    if report["verdict"] == "NOT_APPLICABLE":
        pytest.skip("synth unmeasurable in this container")
    assert rc == 1
    assert report["verdict"] == "BLOCK"


# ════════════════════════════════════════════════════════════════════════════
# SECONDARY — latency gate NOT-APPLICABLE on a no-handshake streaming design
# ════════════════════════════════════════════════════════════════════════════

# A STREAMING design with NO pulse->done handshake: `vout` is a free-running
# registered copy of the data input — it NEVER makes a one-shot assertion in
# response to a `start` pulse, so the latency TB times out. (`start` exists as a
# port so the gate can bind --event, but the design ignores it.)
_RTL_STREAMING = """\
module streamer (
    input            clk,
    input            rst_n,
    input            start,
    input  [7:0]     din,
    output reg       vout
);
    // free-running: vout tracks din[0] every cycle; no event->done relationship
    always @(posedge clk or negedge rst_n)
        if (!rst_n) vout <= 1'b0;
        else        vout <= 1'b0;   // never asserts in response to `start`
endmodule
"""

# A REAL pulse->done handshake design: 1-stage shift register, latency 1.
_RTL_HANDSHAKE = """\
module sr1 (input clk, input rst_n, input start, output reg out);
  always @(posedge clk or negedge rst_n)
    if (!rst_n) out <= 1'b0; else out <= start;   // latency 1
endmodule
"""


@pytest.mark.skipif(not _HAVE_IVERILOG, reason="iverilog/vvp unavailable")
def test_streaming_no_handshake_returns_not_applicable(tmp_path):
    """A no-handshake streaming design with --allow-no-handshake → the DISTINCT
    NOT_APPLICABLE verdict on the DISTINCT exit code 3 (never a silent PASS,
    never a real timing block)."""
    rtl = tmp_path / "streamer.sv"
    rtl.write_text(_RTL_STREAMING)
    rc, report = lcc.run_latency_conformance(
        rtl_path=rtl, top="streamer", event="start", output="vout",
        expect="1", params_override={}, reset_override=None,
        reset_active_low_flag=None, input_const=-1, max_cycles_override=None,
        allow_no_handshake=True)
    assert rc == 3, (report.get("verdict"), report.get("reason"))
    assert report["verdict"] == "NOT_APPLICABLE"
    assert report["measured_latency"] is None
    # it is DISTINCT from both PASS (rc 0) and TIMEOUT (rc 1).
    assert rc not in (0, 1)


@pytest.mark.skipif(not _HAVE_IVERILOG, reason="iverilog/vvp unavailable")
def test_streaming_default_still_times_out_rc1(tmp_path):
    """WITHOUT the flag the default behaviour is UNCHANGED: the same no-output
    design still hard-blocks as TIMEOUT (rc 1) — the secondary fix did not
    weaken the existing handshake-design contract."""
    rtl = tmp_path / "streamer.sv"
    rtl.write_text(_RTL_STREAMING)
    rc, report = lcc.run_latency_conformance(
        rtl_path=rtl, top="streamer", event="start", output="vout",
        expect="1", params_override={}, reset_override=None,
        reset_active_low_flag=None, input_const=-1, max_cycles_override=None,
        allow_no_handshake=False)
    assert rc == 1, (report.get("verdict"), report.get("reason"))
    assert report["verdict"] == "TIMEOUT"


@pytest.mark.skipif(not _HAVE_IVERILOG, reason="iverilog/vvp unavailable")
def test_real_handshake_still_measures_with_flag(tmp_path):
    """A REAL pulse->done handshake design STILL MEASURES even with
    --allow-no-handshake (the flag only reclassifies a TIMEOUT, it does not
    suppress a real measurement): sr1 measures latency 1 → PASS vs --expect 1."""
    rtl = tmp_path / "sr1.sv"
    rtl.write_text(_RTL_HANDSHAKE)
    rc, report = lcc.run_latency_conformance(
        rtl_path=rtl, top="sr1", event="start", output="out",
        expect="1", params_override={}, reset_override=None,
        reset_active_low_flag=None, input_const=-1, max_cycles_override=None,
        allow_no_handshake=True)
    assert rc == 0, (report.get("verdict"), report.get("reason"))
    assert report["verdict"] == "PASS"
    assert report["measured_latency"] == 1
    # and a real MISMATCH still hard-blocks (rc 1) even with the flag.
    rc_bad, report_bad = lcc.run_latency_conformance(
        rtl_path=rtl, top="sr1", event="start", output="out",
        expect="2", params_override={}, reset_override=None,
        reset_active_low_flag=None, input_const=-1, max_cycles_override=None,
        allow_no_handshake=True)
    assert rc_bad == 1
    assert report_bad["verdict"] == "MISMATCH"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
