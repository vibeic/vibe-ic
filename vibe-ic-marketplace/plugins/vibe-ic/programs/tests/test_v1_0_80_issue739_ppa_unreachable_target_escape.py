#!/usr/bin/env python3
"""ORGANIC #739 — ppa_area_threshold_check unreachable-target NOT-APPLICABLE
escape.

THE DEFECT (#739)
=================
On a near-minimal design the stated reduction target (e.g. 20% cells+wires) is
UNACHIEVABLE by ANY functionally-equivalent rewrite — INCLUDING the golden —
because synthesis already shares the source redundancy and the cmos2-mapped
floor is reached. ppa_area_threshold_check MEASURES the mapped reduction
correctly and would BLOCK at 20%, but it would block EVERY equivalent answer
including the golden. The measurement is right; the all-or-nothing BLOCK on an
unreachable target is the gap (§4.05 — a false BLOCK is irreversible).

THE FIX (chip-AGNOSTIC, program-first)
======================================
The recipe now emits `stat` TWICE: a GENERIC (technology-INDEPENDENT,
pre-techmap/pre-abc — the coarse $add/$mul/$xor/$dff cells) stat AND the MAPPED
(post abc -g cmos2) stat. `decide()` takes the GENERIC reductions too:

  * a bound metric's MAPPED reduction < threshold AND its GENERIC reduction
    ALSO < threshold  → proven near-minimal / UNREACHABLE target → the new
    NOT_APPLICABLE / advisory verdict (rc 0), NOT a hard BLOCK.
  * a bound metric's MAPPED reduction < threshold while its GENERIC reduction
    shows HEADROOM (>= threshold, or no generic evidence at all) → the design
    COULD have reached the target → STILL a BLOCK (rc 1). This is the CRUCIAL
    no-leak: a lazily-optimized design is never downgraded.
  * every bound metric's MAPPED reduction >= threshold → PASS (unchanged).

PURE-FUNCTION END-STATE (no yosys needed)
=========================================
`split_generic_mapped_stat` + `parse_stat` + `compute_reduction_pct` +
`decide` are PURE; the downgrade math + no-leak are proven on SYNTHETIC
generic/mapped stat pairs WITHOUT a container. The marker-split is proven robust
against yosys ECHOING the whole command line (both markers appear mid-line in
that echo and must NOT be mistaken for the real `log` output). The live yosys
path is guarded behind a docker/vibeic-eda skip.

chip-AGNOSTIC: pure measurement + arithmetic; no chip/SKU literal (enforced by
source_chip_agnostic_check).
"""
from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

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
        cp = subprocess.run(
            ["docker", "inspect", "-f", "{{.State.Running}}", container],
            capture_output=True, text=True, timeout=10)
        return cp.returncode == 0 and cp.stdout.strip() == "true"
    except Exception:
        return False


_HAVE_CONTAINER = _container_up()


# ════════════════════════════════════════════════════════════════════════════
# A realistic ONE-RUN transcript that BOTH yosys command-line echo AND the
# real `log` markers appear in. The recipe is echoed by yosys as
#   -- Running command `...; log PPA_AREA_GENERIC_STAT; stat; ...; log
#      PPA_AREA_MAPPED_STAT; stat' --
# so BOTH markers appear MID-LINE in that echo. The real `log` output puts each
# marker ALONE on a line followed by its stat block. The split MUST key on the
# standalone-line marker, never the command-echo copy.
# ════════════════════════════════════════════════════════════════════════════

# GENERIC stat: 8 cells / 12 wires.  MAPPED stat: 30 cells / 50 wires.
# Real yosys order (verified live): `log MARK` prints the marker FIRST, then the
# following `stat` prints its block — so each stat block comes AFTER its marker,
# and the generic stat lives BETWEEN the GENERIC and MAPPED markers.
_NEAR_MINIMAL_BLOB = """\
-- Running command `read_verilog -sv x.sv; synth -top m -flatten; opt; \
log PPA_AREA_GENERIC_STAT; stat; abc -g cmos2; log PPA_AREA_MAPPED_STAT; \
stat' --

PPA_AREA_GENERIC_STAT

7. Printing statistics.

=== m ===

   Number of wires:                 12
   Number of cells:                  8
     $_XOR_                           8

PPA_AREA_MAPPED_STAT

9. Printing statistics.

=== m ===

   Number of wires:                 50
   Number of cells:                 30
"""


# ── the split survives the command-echo decoy ───────────────────────────────
def test_split_ignores_midline_command_echo_marker():
    """Both markers appear MID-LINE in yosys's command echo; the split keys on
    the STANDALONE-line marker only — so the GENERIC section is the 8-cell /
    12-wire block, NOT the rest of the echoed command string (the #739 bug
    where the command-echo copy stole the GENERIC slot and left it None)."""
    generic_txt, mapped_txt = ppa.split_generic_mapped_stat(_NEAR_MINIMAL_BLOB)
    g = ppa.parse_stat(generic_txt)
    m = ppa.parse_stat(mapped_txt)
    assert g["cells"] == 8 and g["wires"] == 12, (g, generic_txt[:120])
    assert m["cells"] == 30 and m["wires"] == 50, (m, mapped_txt[:120])


def test_split_new_yosys_form_standalone_marker():
    """The NEW 'N cells' yosys spelling with the standalone `log` markers also
    splits cleanly (and the decoy 'wire bits' / command echo do not poison it)."""
    blob = (
        "-- Running command `synth; opt; log PPA_AREA_GENERIC_STAT; stat; "
        "abc -g cmos2; log PPA_AREA_MAPPED_STAT; stat' --\n"
        "PPA_AREA_GENERIC_STAT\n"
        "        5 wires\n        7 wire bits\n        2 cells\n"
        "        2   $_XOR_\n"
        "PPA_AREA_MAPPED_STAT\n"
        "       18 wires\n       40 wire bits\n       10 cells\n")
    generic_txt, mapped_txt = ppa.split_generic_mapped_stat(blob)
    assert ppa.parse_stat(generic_txt) == {"cells": 2, "wires": 5}
    assert ppa.parse_stat(mapped_txt) == {"cells": 10, "wires": 18}


def test_split_missing_marker_degrades_to_mapped_only():
    """A marker-LESS transcript (legacy / odd output) puts everything in the
    MAPPED slot and leaves GENERIC empty — degrade, never crash."""
    legacy = "=== m ===\n   Number of cells:   30\n   Number of wires:   50\n"
    generic_txt, mapped_txt = ppa.split_generic_mapped_stat(legacy)
    assert ppa.parse_stat(generic_txt) == {"cells": None, "wires": None}
    assert ppa.parse_stat(mapped_txt) == {"cells": 30, "wires": 50}


# ── the unreachable-target ESCAPE (the #739 end-state) ───────────────────────
def test_decide_unreachable_target_downgrades_to_not_applicable():
    """THE #739 END-STATE: mapped reduction sub-threshold AND generic reduction
    ALSO sub-threshold (a proven-near-minimal design) → NOT_APPLICABLE/advisory,
    NOT a hard BLOCK. Synthetic generic-stat pair — no yosys needed."""
    # near-minimal: 3% mapped, 4% generic — neither clears a 20% both bar.
    verdict, reason = ppa.decide(
        3.0, 2.0, 20.0, "both", cells_red_generic=4.0, wires_red_generic=1.0)
    assert verdict == "NOT_APPLICABLE", reason
    assert "unreachable" in reason.lower()
    assert "advisory" in reason.lower()


def test_decide_generic_meets_target_passes_when_mapped_subthreshold():
    """ORGANIC #769 RE-ANCHOR (supersedes the inverted 'generic headroom →
    BLOCK' premise): mapped reduction sub-threshold BUT generic reduction MEETS
    the bar (>= threshold) → the GENERIC count is the one the CVDP reference
    scorer measures (synth -top; clean; stat, NO abc -g cmos2), so the area
    target IS met → PASS, not a headroom-BLOCK. The mapped shortfall is only a
    shared/irreducible post-techmap combinational floor diluting the
    percentage."""
    # mapped 3%/2% miss the 20% bar, but generic 40%/30% MEET it → PASS.
    verdict, reason = ppa.decide(
        3.0, 2.0, 20.0, "both", cells_red_generic=40.0, wires_red_generic=30.0)
    assert verdict == "PASS", reason
    assert "generic meets" in reason.lower()


def test_decide_mixed_block_dominates_unreachable():
    """One bound metric is a REAL failure (GROWN — negative mapped), the other is
    proven-near-minimal (would escape) → the BLOCK DOMINATES (no-leak: any real
    failure blocks the whole verdict). ORGANIC #769 RE-ANCHOR: the old version
    used a generic-headroom cells metric as the 'real failure', but generic >=
    threshold now MEETS the scorer-measured target (→ PASS), so the surviving
    hard per-metric failure is a GROWN metric."""
    # cells: mapped -3% (GREW) → real failure → BLOCK.
    # wires: mapped 2% / generic 1%  → unreachable → would escape.
    verdict, reason = ppa.decide(
        -3.0, 2.0, 20.0, "both", cells_red_generic=40.0, wires_red_generic=1.0)
    assert verdict == "BLOCK", reason
    assert "cells reduction" in reason


def test_decide_no_generic_evidence_is_failsafe_block():
    """No generic data at all (legacy call / marker-less transcript) → the
    escape NEVER fires; a sub-threshold mapped reduction BLOCKs exactly as the
    prior all-or-nothing gate did. Fail-SAFE — no surprise downgrade."""
    # default generic params (None) — prior behaviour preserved.
    verdict, reason = ppa.decide(3.0, 2.0, 20.0, "both")
    assert verdict == "BLOCK", reason
    # explicitly-None generic is identical.
    verdict2, _ = ppa.decide(3.0, 2.0, 20.0, "both",
                             cells_red_generic=None, wires_red_generic=None)
    assert verdict2 == "BLOCK"


def test_decide_above_threshold_still_passes_regardless_of_generic():
    """A real, sufficient MAPPED reduction PASSES regardless of the generic
    count — the escape only ever touches a sub-threshold mapped verdict."""
    verdict, _ = ppa.decide(
        32.0, 25.0, 20.0, "both",
        cells_red_generic=5.0, wires_red_generic=5.0)
    assert verdict == "PASS"


def test_decide_escape_only_on_the_bound_metric():
    """When only WIRES is bound, a cells generic headroom is irrelevant: a
    near-minimal wires pair (mapped + generic both sub-threshold) escapes even
    though cells has headroom — the escape is per-bound-metric."""
    # wires: mapped 3% / generic 4% (both < 20%, bound) → near-minimal.
    # cells: 80% headroom but NOT bound → ignored.
    verdict, reason = ppa.decide(
        80.0, 3.0, 20.0, "wires",
        cells_red_generic=80.0, wires_red_generic=4.0)
    assert verdict == "NOT_APPLICABLE", reason


def test_unmeasurable_bound_metric_still_not_applicable():
    """A bound metric whose MAPPED reduction is None (unmeasurable) is still the
    pre-existing NOT_APPLICABLE — the escape did not change the unmeasurable
    contract (and it is NOT the unreachable-target reason)."""
    verdict, reason = ppa.decide(
        None, 25.0, 20.0, "both", cells_red_generic=5.0, wires_red_generic=5.0)
    assert verdict == "NOT_APPLICABLE", reason
    assert "unmeasurable" in reason.lower()
    assert "unreachable" not in reason.lower()


# ════════════════════════════════════════════════════════════════════════════
# #739 REMEDIATION (adversarial-review LOW): a GROWN design must NOT escape the
# block. The unreachable-target escape fired on a NEGATIVE mapped reduction
# (optimized LARGER than original) whenever the generic reduction was small/
# sub-threshold — so a submission that made the mapped count WORSE escaped
# blocking. A grown design is never "near-minimal / target-unreachable"; the
# escape must fire ONLY for a genuinely-near-minimal metric (mapped sub-threshold
# but NON-NEGATIVE, generic also sub-threshold). The motivating #739 case
# (small-positive near-minimal → NOT_APPLICABLE) and the generic-headroom no-leak
# (→ BLOCK) must remain intact. Pure decide() math — no yosys.
# ════════════════════════════════════════════════════════════════════════════
def test_decide_grown_design_negative_mapped_still_blocks():
    """THE REVIEWER'S EXACT FAILING INPUT: mapped reductions are NEGATIVE
    (optimized GREW — more cells AND more wires than original) while the generic
    reductions are small-positive sub-threshold. The pre-remediation escape
    returned NOT_APPLICABLE/advisory, letting a WORSE submission escape blocking.
    The CORRECTED end-state is BLOCK — a grown design is never near-minimal."""
    verdict, reason = ppa.decide(
        -50.0, -30.0, 20.0, "both",
        cells_red_generic=2.0, wires_red_generic=1.0)
    assert verdict == "BLOCK", reason
    # it is NOT the escape verdict (which is the advisory NOT_APPLICABLE branch).
    assert "advisory" not in reason.lower(), reason
    assert not reason.startswith("unreachable-target escape"), reason
    # the reason names the growth so the submitter sees WHY it blocked.
    assert "grew" in reason.lower(), reason


def test_decide_one_metric_grew_other_near_minimal_block_dominates():
    """A mixed case: cells GREW (negative mapped) while wires is genuinely
    near-minimal (mapped + generic both small-positive sub-threshold). The grown
    cells metric BLOCKs and dominates — the near-minimal wires escape never wins
    when any bound metric got WORSE."""
    verdict, reason = ppa.decide(
        -10.0, 3.0, 20.0, "both",
        cells_red_generic=2.0, wires_red_generic=4.0)
    assert verdict == "BLOCK", reason
    assert "cells reduction" in reason and "grew" in reason.lower(), reason


def test_decide_zero_reduction_is_not_grown_still_escapes():
    """BOUNDARY: a 0.00% mapped reduction is NOT growth (optimized is the SAME
    size, not larger) — it is still a genuinely-near-minimal design when the
    generic count is also sub-threshold, so the escape still fires. The
    grown-design guard keys on STRICTLY-negative, not non-positive."""
    verdict, reason = ppa.decide(
        0.0, 0.0, 20.0, "both",
        cells_red_generic=2.0, wires_red_generic=1.0)
    assert verdict == "NOT_APPLICABLE", reason
    assert "unreachable" in reason.lower(), reason


def test_decide_grown_only_one_metric_bound_blocks():
    """When only the GROWN metric is bound, the escape still must not fire —
    BLOCK. (Bound wires grew; cells unbound and irrelevant.)"""
    verdict, reason = ppa.decide(
        80.0, -5.0, 20.0, "wires",
        cells_red_generic=80.0, wires_red_generic=1.0)
    assert verdict == "BLOCK", reason
    assert "wires reduction" in reason and "grew" in reason.lower(), reason


def test_decide_motivating_739_near_minimal_still_escapes_post_remediation():
    """GUARD: the ORIGINAL #739 motivating case (two equivalent near-minimal
    RTLs, both small-POSITIVE sub-threshold mapped + generic) must STILL escape
    to NOT_APPLICABLE/advisory after the grown-design remediation. The fix is an
    EXTENSION, not a regression of the original escape."""
    verdict, reason = ppa.decide(
        3.0, 2.0, 20.0, "both",
        cells_red_generic=4.0, wires_red_generic=1.0)
    assert verdict == "NOT_APPLICABLE", reason
    assert "unreachable" in reason.lower() and "advisory" in reason.lower(), reason


def test_decide_generic_meets_target_passes_post_remediation():
    """GUARD (ORGANIC #769 RE-ANCHOR): mapped sub-threshold but POSITIVE while
    the generic reduction MEETS the bar → PASS (the generic count is the one the
    CVDP scorer measures). The grown-design remediation (#739) and the
    generic-meets-target correction (#769) coexist: a GROWN metric still BLOCKs,
    a generic-meeting metric PASSes."""
    verdict, reason = ppa.decide(
        3.0, 2.0, 20.0, "both",
        cells_red_generic=40.0, wires_red_generic=30.0)
    assert verdict == "PASS", reason
    assert "generic meets" in reason.lower(), reason


# ── orchestration: a near-minimal equivalent pair downgrades (no false block) ─
@pytest.mark.skipif(not _HAVE_CONTAINER,
                    reason="vibeic-eda container not running — live yosys path")
def test_live_near_minimal_equivalent_is_not_applicable(tmp_path):
    """LIVE END-STATE: two functionally-equivalent near-minimal RTLs (a 3-input
    XOR spelled two ways) — synthesis shares the redundancy so NEITHER the
    mapped NOR the generic count can shrink 20%. ORGANIC #768 RE-ANCHOR: the
    near-minimal escape is now anchored SUBMISSION-INDEPENDENTLY via a
    ``--reference`` golden. Supplying a reference golden that ITSELF cannot beat
    the bar proves the target is genuinely unreachable → the gate reports
    NOT-APPLICABLE / advisory (rc 0), NOT a hard BLOCK. (WITHOUT a reference the
    0%-generic pair now trips the #768 no-op floor → BLOCK, since at the gate a
    do-nothing copy is indistinguishable from an already-minimal design.)"""
    orig = tmp_path / "orig.sv"
    orig.write_text(
        "module m(input a, input b, input c, output y);\n"
        "  assign y = (a ^ b) ^ c;\nendmodule\n")
    equiv = tmp_path / "equiv.sv"
    equiv.write_text(
        "module m(input a, input b, input c, output y);\n"
        "  wire t = a ^ b;\n  assign y = t ^ c;\nendmodule\n")
    # the reference golden is ANOTHER equivalent near-minimal spelling — it too
    # cannot clear 20%, proving the target unreachable (submission-independent).
    ref = tmp_path / "ref.sv"
    ref.write_text(
        "module m(input a, input b, input c, output y);\n"
        "  assign y = a ^ (b ^ c);\nendmodule\n")
    rc, report = ppa.run_ppa_area_threshold(
        original=orig, optimized=equiv, top="m", prompt_text=None,
        threshold_override=20.0, metric_override="both", container="vibeic-eda",
        reference=ref)
    if report["verdict"] == "NOT_APPLICABLE" and "unmeasurable" in report.get(
            "reason", "").lower():
        pytest.skip("synth could not measure both stats in this container")
    assert rc == 0, (report.get("verdict"), report.get("reason"))
    assert report["verdict"] == "NOT_APPLICABLE", report.get("reason")
    assert "unreachable" in report["reason"].lower()
    # the GENERIC stats were actually captured (not None) — proving the
    # dual-stat split worked end-to-end.
    assert report.get("cells_reduction_pct_generic") is not None
    assert report.get("wires_reduction_pct_generic") is not None
    # the reference golden's generic reduction was measured (the reachability
    # anchor fired) and itself sub-bar (proving unreachability).
    assert report.get("cells_reduction_pct_ref_generic") is not None


@pytest.mark.skipif(not _HAVE_CONTAINER,
                    reason="vibeic-eda container not running — live yosys path")
def test_live_no_reference_noop_copy_blocks_via_floor(tmp_path):
    """LIVE §4.05 NO-LEAK (ORGANIC #768): a do-nothing copy (the optimized file
    is byte-identical to the original → 0% generic) WITHOUT a reference trips the
    no-op floor → BLOCK (rc 1). A submission that removed essentially nothing can
    never be 'proven near-minimal' without a reference."""
    orig = tmp_path / "orig.sv"
    orig.write_text(
        "module m(input a, input b, input c, output y);\n"
        "  assign y = (a ^ b) ^ c;\nendmodule\n")
    copy = tmp_path / "copy.sv"
    copy.write_text(
        "module m(input a, input b, input c, output y);\n"
        "  assign y = (a ^ b) ^ c;\nendmodule\n")
    rc, report = ppa.run_ppa_area_threshold(
        original=orig, optimized=copy, top="m", prompt_text=None,
        threshold_override=20.0, metric_override="both", container="vibeic-eda")
    if report["verdict"] == "NOT_APPLICABLE" and "unmeasurable" in report.get(
            "reason", "").lower():
        pytest.skip("synth could not measure both stats in this container")
    assert rc == 1, (report.get("verdict"), report.get("reason"))
    assert report["verdict"] == "BLOCK", report.get("reason")
    assert "no-op floor" in report["reason"].lower()


@pytest.mark.skipif(not _HAVE_CONTAINER,
                    reason="vibeic-eda container not running — live yosys path")
def test_live_generic_meets_target_passes(tmp_path):
    """LIVE END-STATE (ORGANIC #769): an 8x8 multiplier reduced to a 7x7 one;
    its GENERIC reduction outpaces its MAPPED reduction. At a threshold pinned
    BETWEEN them the MAPPED misses while the GENERIC MEETS the bar — the GENERIC
    count is the one the CVDP reference scorer measures (synth -top; clean;
    stat), so the gate now PASSES (rc 0), NOT a headroom-BLOCK. Proves the
    inverted 'generic headroom → BLOCK' premise is corrected end-to-end."""
    big = tmp_path / "big.sv"
    big.write_text(
        "module m(input [7:0] a, input [7:0] b, output [15:0] y);\n"
        "  assign y = a * b;\nendmodule\n")
    small = tmp_path / "small.sv"
    small.write_text(
        "module m(input [7:0] a, input [7:0] b, output [15:0] y);\n"
        "  assign y = {1'b0, (a[6:0] * b[6:0])};\nendmodule\n")
    # first measure to find a threshold strictly between mapped and generic.
    rc0, rep0 = ppa.run_ppa_area_threshold(
        original=big, optimized=small, top="m", prompt_text=None,
        threshold_override=1.0, metric_override="cells", container="vibeic-eda")
    mapped = rep0.get("cells_reduction_pct")
    generic = rep0.get("cells_reduction_pct_generic")
    if mapped is None or generic is None or not (generic > mapped + 1.0):
        pytest.skip("this container did not produce a generic>mapped gap")
    thr = (mapped + generic) / 2.0   # strictly between → mapped misses, generic MEETS
    rc, report = ppa.run_ppa_area_threshold(
        original=big, optimized=small, top="m", prompt_text=None,
        threshold_override=thr, metric_override="cells", container="vibeic-eda")
    assert rc == 0, (report.get("verdict"), report.get("reason"))
    assert report["verdict"] == "PASS", report.get("reason")
    assert "generic meets" in report["reason"].lower()


# ── #478 defect-artifact + end-state: shape the issue's ## 驗收 artifact DIRECTLY
# in tmp_path and assert the END state via the real program's main() entrypoint.
# Mirrors the issue body:
#   python3 programs/ppa_area_threshold_check.py --original <orig>.sv \
#       --optimized <equiv_near_minimal>.sv --top m --threshold-pct 20 --metric both
@pytest.mark.skipif(not _HAVE_CONTAINER,
                    reason="vibeic-eda container not running — live yosys path")
def test_acceptance_near_minimal_endstate_via_program_main(tmp_path):
    """END-STATE via the real program's main() on a tmp_path-shaped defect
    artifact: two functionally-equivalent near-minimal RTLs (a 3-input XOR spelled
    two ways), with a reference golden that ITSELF cannot beat the bar, are
    reported NOT-APPLICABLE / advisory (rc 0), NOT a hard BLOCK (the #739
    false-block). ORGANIC #768: the near-minimal escape is now anchored on the
    submission-independent ``--reference`` golden."""
    (tmp_path / "orig.sv").write_text(
        "module m(input a, input b, input c, output y);\n"
        "  assign y = (a ^ b) ^ c;\nendmodule\n")
    (tmp_path / "equiv.sv").write_text(
        "module m(input a, input b, input c, output y);\n"
        "  wire t = a ^ b;\n  assign y = t ^ c;\nendmodule\n")
    (tmp_path / "ref.sv").write_text(
        "module m(input a, input b, input c, output y);\n"
        "  assign y = a ^ (b ^ c);\nendmodule\n")
    rc = ppa.main(["--original", str(tmp_path / "orig.sv"),
                   "--optimized", str(tmp_path / "equiv.sv"),
                   "--reference", str(tmp_path / "ref.sv"),
                   "--top", "m", "--threshold-pct", "20", "--metric", "both"])
    assert rc == 0, rc   # equivalent near-minimal: advisory NOT_APPLICABLE, not BLOCK


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
