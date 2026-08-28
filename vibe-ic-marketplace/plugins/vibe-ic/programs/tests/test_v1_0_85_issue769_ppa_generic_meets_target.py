#!/usr/bin/env python3
"""ORGANIC #769 — ppa_area_threshold_check false-blocks when MAPPED cell
reduction < threshold but GENERIC reduction MEETS it (mapped-vs-generic headroom
interaction).

THE DEFECT (reproduced on shipped 1.0.84)
=========================================
`_generic_headroom()` / `_classify_single()` / `decide()` treated
"mapped < thr & generic >= thr" as a lazy-headroom BLOCK. But the CVDP reference
scorer (harness synth.tcl ends at `synth -top; clean` with NO `abc -g cmos2`,
.env CELLS/PERCENT_CELLS) measures the GENERIC count — so the gate blocked
exactly the count the scorer PASSES.

For image_rotate_0015: generic 31.23% >= 25% (scorer PASS) yet the gate BLOCKed
on the MAPPED 21.84% (diluted by a shared/irreducible 1812-cell permutation-mux
combinational floor). REPRO:
    decide(21.84, None, 25.0, 'cells', cells_red_generic=31.23)  → BLOCK (wrong)

THE FIX (chip-AGNOSTIC, Bucket A)
=================================
A pure `_generic_meets_target(mapped, generic, thr)` (True iff mapped >= 0 and
generic >= thr) classifies such a metric as SATISFIED (PASS, the GENERIC count
— the one the scorer measures — meets the bar), checked BEFORE the headroom/
escape logic. GROWN (negative-mapped) metrics move into a dedicated bucket that
DOMINATES even under OR so no disjunctive PASS can mask a regression.

§4.05 NO-LEAK (this is a BLOCKING gate)
=======================================
A design whose MAPPED reduction is NEGATIVE (the optimized count is LARGER than
the original — the submission made the metric WORSE) MUST STILL BLOCK even when
the GENERIC reduction meets/exceeds the threshold. metric_red >= 0.0 is the FIRST
condition in _generic_meets_target, so a grown metric never satisfies it and
always falls through to the grown bucket (which dominates OR and AND).

chip-AGNOSTIC: pure arithmetic on synth-stat reductions; no chip/SKU literal.
"""
from __future__ import annotations

import importlib.util
import json
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
    if str(_PROGRAMS) not in sys.path:
        sys.path.insert(0, str(_PROGRAMS))
    spec.loader.exec_module(mod)
    return mod


ppa = _load("ppa_area_threshold_check", "ppa_area_threshold_check.py")


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
# (0) the exact REPRO from the issue: shipped code returned BLOCK; the fix → PASS
# ════════════════════════════════════════════════════════════════════════════
def test_repro_image_rotate_0015_mapped_subthreshold_generic_meets_now_passes():
    """THE #769 REPRO: cells_mapped=21.84% (< 25%), cells_generic=31.23%
    (>= 25%). Shipped 1.0.84 → BLOCK (wrong). Fixed → PASS (the GENERIC count,
    which the CVDP reference scorer measures, MEETS the bar)."""
    verdict, reason = ppa.decide(
        21.84, None, 25.0, "cells", cells_red_generic=31.23)
    assert verdict == "PASS", reason
    assert "generic meets" in reason.lower(), reason


# ════════════════════════════════════════════════════════════════════════════
# (a) NEW-PATH assertion — the wrongly-flagged case now returns the right verdict
# ════════════════════════════════════════════════════════════════════════════
def test_generic_meets_target_pure_unit():
    """_generic_meets_target: True iff mapped >= 0 AND generic >= thr."""
    assert ppa._generic_meets_target(21.84, 31.23, 25.0) is True
    # mapped negative → never satisfied (the no-leak FIRST condition).
    assert ppa._generic_meets_target(-5.0, 31.23, 25.0) is False
    # generic below the bar → not satisfied (a lazy/shallow miss).
    assert ppa._generic_meets_target(21.84, 15.0, 25.0) is False
    # either input None → False (never a fabricated satisfy).
    assert ppa._generic_meets_target(None, 31.23, 25.0) is False
    assert ppa._generic_meets_target(21.84, None, 25.0) is False
    # boundary: mapped exactly 0 (no growth) + generic exactly at bar → True.
    assert ppa._generic_meets_target(0.0, 25.0, 25.0) is True


def test_decide_generic_meets_target_passes():
    """decide(): mapped sub-threshold but generic meets the bar → PASS, and the
    reason discloses the generic-meets-target basis."""
    verdict, reason = ppa.decide(
        21.84, None, 25.0, "cells",
        cells_red_generic=31.23, wires_red_generic=None)
    assert verdict == "PASS", reason
    assert "generic meets" in reason.lower(), reason


def test_decide_clauses_generic_meets_target_or_passes():
    """decide_clauses OR: a single clause whose MAPPED is sub-threshold but
    GENERIC meets the bar PASSES the disjunction."""
    verdict, reason = ppa.decide_clauses(
        21.84, None, [(25.0, "cells")], ppa._COMBINATOR_OR,
        cells_red_generic=31.23)
    assert verdict == "PASS", reason
    assert "generic meets" in reason.lower(), reason


def test_decide_clauses_generic_meets_target_and_passes():
    """decide_clauses AND: every clause whose GENERIC meets the bar PASSES."""
    verdict, reason = ppa.decide_clauses(
        21.84, 22.0, [(25.0, "cells"), (25.0, "wires")], ppa._COMBINATOR_AND,
        cells_red_generic=31.23, wires_red_generic=30.0)
    assert verdict == "PASS", reason
    assert "generic meets" in reason.lower(), reason


# ════════════════════════════════════════════════════════════════════════════
# (b) REGRESSION GUARD — the prior correct behaviour is unchanged
# ════════════════════════════════════════════════════════════════════════════
def test_real_mapped_pass_unchanged():
    """A mapped reduction that clears the bar still PASSES exactly as before
    (the generic-meets path only ever touches a sub-threshold mapped verdict)."""
    verdict, reason = ppa.decide(
        32.0, 28.0, 20.0, "both",
        cells_red_generic=5.0, wires_red_generic=5.0)
    assert verdict == "PASS", reason
    # mapped cleared directly — NOT via the generic-meets path.
    assert "generic meets" not in reason.lower(), reason


def test_real_underreduction_with_subthreshold_generic_still_blocks_with_reference():
    """A genuine lazy under-reduction (mapped AND generic both sub-threshold)
    with a reference golden that PROVES reachability still BLOCKs — the
    generic-meets path does NOT fire (generic < bar) and the reference anchor
    blocks. Confirms the fix did not weaken the real-miss detection."""
    verdict, reason = ppa.decide(
        5.0, None, 20.0, "cells",
        cells_red_generic=8.0, cells_red_ref_generic=45.0)
    assert verdict == "BLOCK", reason


def test_unmeasurable_metric_still_not_applicable():
    """A bound metric whose MAPPED reduction is None is still NOT_APPLICABLE —
    the generic-meets path requires a measurable mapped reduction."""
    verdict, reason = ppa.decide(
        None, 25.0, 20.0, "both", cells_red_generic=50.0, wires_red_generic=50.0)
    assert verdict == "NOT_APPLICABLE", reason


# ════════════════════════════════════════════════════════════════════════════
# (c) §4.05 NEGATIVE NO-LEAK — a GROWN metric must STILL BLOCK even when the
#     GENERIC reduction meets/exceeds the threshold. (boundary-outside genuine
#     defect from the invariant.)
# ════════════════════════════════════════════════════════════════════════════
def test_noleak_decide_negative_mapped_blocks_despite_generic_meeting_bar():
    """§4.05: cells_mapped=-5.0% (GREW) with cells_generic=31.23% (>= 25%) MUST
    BLOCK — the design made the post-map count WORSE; a generic count that meets
    the bar can NEVER excuse a real regression."""
    verdict, reason = ppa.decide(
        -5.0, None, 25.0, "cells", cells_red_generic=31.23)
    assert verdict == "BLOCK", reason
    assert "grew" in reason.lower(), reason


def test_noleak_decide_clauses_grown_metric_dominates_or():
    """§4.05: under OR, a GROWN metric DOMINATES even when a sibling clause is
    satisfied — a disjunctive PASS must never mask a metric that got WORSE.
    cells GREW (-5%) while wires passed (50%) → BLOCK."""
    verdict, reason = ppa.decide_clauses(
        -5.0, 50.0, [(25.0, "cells"), (25.0, "wires")], ppa._COMBINATOR_OR,
        cells_red_generic=31.23, wires_red_generic=60.0)
    assert verdict == "BLOCK", reason
    assert "grew" in reason.lower(), reason


def test_noleak_decide_clauses_grown_metric_blocks_and():
    """§4.05: under AND, a single GROWN metric blocks even when the other clause
    is satisfied. cells GREW (-5%), wires passed (50%) → BLOCK."""
    verdict, reason = ppa.decide_clauses(
        -5.0, 50.0, [(25.0, "cells"), (25.0, "wires")], ppa._COMBINATOR_AND,
        cells_red_generic=31.23, wires_red_generic=60.0)
    assert verdict == "BLOCK", reason
    assert "grew" in reason.lower(), reason


# ════════════════════════════════════════════════════════════════════════════
# (d) #478 END-STATE — DIRECT-write a tmp_path artifact + invoke the real
#     program's main() and assert the returncode. Mirrors image_rotate_0015:
#     generic ~31% >= 25%, mapped ~22% (sub-threshold) → PASS (rc 0).
# ════════════════════════════════════════════════════════════════════════════
@pytest.mark.skipif(not _HAVE_CONTAINER,
                    reason="vibeic-eda container not running — live yosys path")
def test_endstate_generic_meets_target_passes_via_main(tmp_path):
    """END-STATE via the real program's main(): an 8x8 multiplier reduced to a
    7x7 one (the GENERIC reduction outpaces the MAPPED reduction). At a threshold
    pinned BETWEEN them the MAPPED misses but the GENERIC MEETS the bar → the
    program exits 0 (PASS), matching the CVDP scorer which measures the GENERIC
    count, NOT a headroom-BLOCK."""
    orig = tmp_path / "orig.sv"
    orig.write_text(
        "module m(input [7:0] a, input [7:0] b, output [15:0] y);\n"
        "  assign y = a * b;\nendmodule\n")
    opt = tmp_path / "opt.sv"
    opt.write_text(
        "module m(input [7:0] a, input [7:0] b, output [15:0] y);\n"
        "  assign y = {1'b0, (a[6:0] * b[6:0])};\nendmodule\n")
    out_json = tmp_path / "report.json"
    # measure to find a threshold strictly between mapped and generic.
    rc0, rep0 = ppa.run_ppa_area_threshold(
        original=orig, optimized=opt, top="m", prompt_text=None,
        threshold_override=1.0, metric_override="cells", container="vibeic-eda")
    mapped = rep0.get("cells_reduction_pct")
    generic = rep0.get("cells_reduction_pct_generic")
    if mapped is None or generic is None or not (generic > mapped + 1.0):
        pytest.skip("this container did not produce a generic>mapped gap")
    thr = (mapped + generic) / 2.0    # mapped < thr <= generic
    rc = ppa.main(["--original", str(orig), "--optimized", str(opt),
                   "--top", "m", "--threshold-pct", str(thr),
                   "--metric", "cells", "--json", str(out_json)])
    assert rc == 0, rc
    report = json.loads(out_json.read_text())
    assert report["verdict"] == "PASS", report.get("reason")


def test_endstate_grown_blocks_via_main_canned(tmp_path):
    """END-STATE §4.05 no-leak via the PURE path: a tmp_path-shaped report
    asserting a GROWN metric BLOCKs. We exercise the real decide() (the program's
    verdict core) on the grown input and DIRECT-write the verdict artifact, then
    assert the blocking returncode the orchestrator would emit (rc 1)."""
    # simulate the orchestrator's verdict-to-rc mapping with the real decide().
    verdict, reason = ppa.decide(
        -5.0, None, 25.0, "cells", cells_red_generic=31.23)
    rc = 1 if verdict == "BLOCK" else 0
    artifact = tmp_path / "verdict.json"
    artifact.write_text(json.dumps({"verdict": verdict, "reason": reason}))
    assert rc == 1, (verdict, reason)
    assert json.loads(artifact.read_text())["verdict"] == "BLOCK"


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
