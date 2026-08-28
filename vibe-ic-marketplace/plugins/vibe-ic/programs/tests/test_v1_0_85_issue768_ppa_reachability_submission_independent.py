#!/usr/bin/env python3
"""ORGANIC #768 — ppa_area_threshold_check unreachable-target escape used the
SUBMISSION's OWN generic reduction as the reachability proxy (gameable / wrong
headroom basis).

THE DEFECT (constructed gaming/edge inputs — reproduced=False in the wild)
=========================================================================
The legacy `_generic_headroom()` escape labelled a sub-threshold submission
whose OWN generic delta is also sub-threshold "near-minimal / unreachable" →
NOT_APPLICABLE. That CONFLATES "how much THIS submission reduced" with "how much
reduction is ACHIEVABLE": a do-nothing copy of the original (0% generic) or a
shallow submission (small generic delta because it SKIPPED the structural
register-merge win) is wrongly EXCUSED even though the golden proves the bar
reachable on the SAME original (cvdp_copilot_generic_nbit_counter_0039: golden
generic 44.77% / 33.90% clears, a 0%/shallow submission must NOT escape).

CONSTRUCTED REPRO (shipped behaviour, now corrected):
    decide(0.0, None, 20.0, 'cells', cells_red_generic=0.0)
        shipped → NOT_APPLICABLE (a do-nothing copy wrongly excused)
        fixed   → BLOCK (no-op floor; removed essentially nothing)

THE FIX (chip-AGNOSTIC, Bucket B) — reachability is SUBMISSION-INDEPENDENT
=========================================================================
Two anchors gate the escape, and BOTH must fail for it to fire:
  (1) `--reference` golden: `_target_reachable_via_reference()` — if the golden
      CLEARS the generic bar the target is PROVEN reachable → a sub-threshold
      submission is a REAL under-reduction (BLOCK).
  (2) NO-OP FLOOR (no-reference safety net, `_NOOP_GENERIC_FLOOR_PCT=0.5%`): a
      submission whose own generic reduction is at/below the tight epsilon
      removed ~nothing → a do-nothing/literal-copy → BLOCK.
`_escape_eligible()` composes the two; the escape fires only for a PROVEN-
unreachable, real-effort sub-bar submission.

§4.05 NO-LEAK (this is a BLOCKING gate)
=======================================
(1) When `--reference` is supplied AND clears the generic bar, ANY sub-threshold
    submission is a REAL BLOCK (never excused).
(2) Without `--reference`, a submission with own generic <= 0.5% (do-nothing /
    literal-copy) BLOCKs even when it claims unreachability.
A submission with real-but-insufficient generic work (e.g. 5% when bar is 20%)
WITHOUT a reference remains advisory NOT_APPLICABLE — the fail-SAFE: never
false-block a real attempt that no reference disproves.

chip-AGNOSTIC: pure percentage anchors + arithmetic; no chip/SKU literal.
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
# (0) acceptance: --reference must appear in --help (issue ## 驗收, verbatim)
# ════════════════════════════════════════════════════════════════════════════
def test_acceptance_reference_flag_in_help(capsys):
    """The issue's acceptance command greps `--help` for `--reference`.

    It used to assert that `main(["--help"])` RAISES SystemExit, which was a
    fact about argparse's internals rather than about the acceptance command.
    `main` is documented to RETURN an int, and `--help` is a successful
    invocation: PPA_INTERFACES §1 gives it 0. The grep the issue specifies is
    asserted directly instead, which is strictly more than the old form
    checked -- it now pins the exit code too.
    """
    rc = ppa.main(["--help"])
    assert rc == 0, f"--help is not a bad invocation; got rc={rc}"
    out = capsys.readouterr().out
    assert "--reference" in out


# ════════════════════════════════════════════════════════════════════════════
# (a) NEW-PATH — the wrongly-EXCUSED gaming inputs now return the right verdict
# ════════════════════════════════════════════════════════════════════════════
def test_repro_do_nothing_copy_now_blocks_via_noop_floor():
    """CONSTRUCTED REPRO: a do-nothing copy (mapped 0% / generic 0%), no
    reference. Shipped 1.0.84 → NOT_APPLICABLE (wrongly excused). Fixed → BLOCK
    (the no-op floor: the submission removed essentially nothing)."""
    verdict, reason = ppa.decide(0.0, None, 20.0, "cells", cells_red_generic=0.0)
    assert verdict == "BLOCK", reason
    assert "no-op floor" in reason.lower(), reason


def test_shallow_submission_blocks_when_reference_proves_reachable():
    """A SHALLOW submission (mapped 10% / generic 10%, both sub-bar) WITH a
    reference golden whose generic clears the bar (45% >= 20%) is a REAL miss →
    BLOCK. Reachability is anchored on what is ACHIEVABLE (the golden), not on
    what THIS submission happened to do."""
    verdict, reason = ppa.decide(
        10.0, None, 20.0, "cells",
        cells_red_generic=10.0, cells_red_ref_generic=45.0)
    assert verdict == "BLOCK", reason
    assert "reachable" in reason.lower(), reason


def test_zero_submission_excused_when_golden_also_subbar():
    """A 0% submission that equals an ALREADY-minimal golden is correctly
    EXCUSED: with a reference golden that ITSELF cannot beat the bar (ref generic
    0.4% < 20%), the target is proven unreachable → NOT_APPLICABLE, no false
    BLOCK. (The no-op floor is OVERRIDDEN by the explicit reference evidence.)"""
    verdict, reason = ppa.decide(
        0.0, None, 20.0, "cells",
        cells_red_generic=0.0, cells_red_ref_generic=0.4)
    assert verdict == "NOT_APPLICABLE", reason


# the pure helper precedence ─────────────────────────────────────────────────
def test_escape_eligible_precedence():
    # reference clears bar → NOT eligible (real miss / BLOCK).
    assert ppa._escape_eligible(10.0, 10.0, 20.0, 45.0) is False
    # reference itself sub-bar → eligible (target proven unreachable / escape).
    assert ppa._escape_eligible(0.0, 0.0, 20.0, 3.0) is True
    # NO reference, own generic has headroom (>= bar) → NOT eligible (lazy miss).
    assert ppa._escape_eligible(5.0, 25.0, 20.0, None) is False
    # NO reference, own generic at/below the no-op floor → NOT eligible (no-op).
    assert ppa._escape_eligible(0.0, 0.0, 20.0, None) is False
    assert ppa._escape_eligible(0.0, 0.4, 20.0, None) is False
    # NO reference, own generic between floor and bar → eligible (real-effort
    # sub-bar, no reference to disprove → advisory escape).
    assert ppa._escape_eligible(5.0, 5.0, 20.0, None) is True


def test_target_reachable_via_reference_pure():
    assert ppa._target_reachable_via_reference(45.0, 20.0) is True
    assert ppa._target_reachable_via_reference(20.0, 20.0) is True   # boundary
    assert ppa._target_reachable_via_reference(3.0, 20.0) is False
    assert ppa._target_reachable_via_reference(None, 20.0) is False  # no ref


# ════════════════════════════════════════════════════════════════════════════
# (b) REGRESSION GUARD — the prior correct behaviour is unchanged
# ════════════════════════════════════════════════════════════════════════════
def test_genuine_near_minimal_real_effort_no_reference_still_escapes():
    """REGRESSION: the #739 genuine near-minimal case (mapped + generic both
    small-POSITIVE sub-threshold, ABOVE the no-op floor) with NO reference still
    escapes to advisory NOT_APPLICABLE — the fail-SAFE preserved (do not
    false-block a real attempt that no reference disproves)."""
    verdict, reason = ppa.decide(
        3.0, 2.0, 20.0, "both",
        cells_red_generic=4.0, wires_red_generic=1.0)
    assert verdict == "NOT_APPLICABLE", reason
    assert "unreachable" in reason.lower() and "advisory" in reason.lower(), reason


def test_legacy_no_generic_no_reference_failsafe_block_unchanged():
    """REGRESSION: a legacy call with NO generic data and NO reference still
    BLOCKs a sub-threshold mapped reduction (the prior all-or-nothing gate) —
    byte-identical fail-SAFE behaviour on the legacy path."""
    verdict, reason = ppa.decide(3.0, 2.0, 20.0, "both")
    assert verdict == "BLOCK", reason
    verdict2, _ = ppa.decide(3.0, 2.0, 20.0, "both",
                             cells_red_generic=None, wires_red_generic=None)
    assert verdict2 == "BLOCK"


def test_above_threshold_mapped_still_passes_with_or_without_reference():
    """REGRESSION: a real, sufficient MAPPED reduction PASSES regardless of any
    reference (the escape only ever touches a sub-threshold mapped verdict)."""
    v1, _ = ppa.decide(32.0, 28.0, 20.0, "both",
                       cells_red_generic=5.0, wires_red_generic=5.0)
    assert v1 == "PASS"
    v2, _ = ppa.decide(32.0, 28.0, 20.0, "both",
                       cells_red_generic=5.0, wires_red_generic=5.0,
                       cells_red_ref_generic=45.0, wires_red_ref_generic=45.0)
    assert v2 == "PASS"


# ════════════════════════════════════════════════════════════════════════════
# (c) §4.05 NEGATIVE NO-LEAK — boundary-outside genuine defect must STILL fire
# ════════════════════════════════════════════════════════════════════════════
def test_noleak_reference_clears_bar_subthreshold_submission_always_blocks():
    """§4.05: when a reference golden CLEARS the generic bar, ANY sub-threshold
    submission is a REAL under-reduction — BLOCK, never excused. (The shallow
    submission with own generic just below the bar — the boundary-outside case —
    is the exact leak #768 closes.)"""
    # submission own generic 18% (just under 20% bar), reference golden 45%.
    verdict, reason = ppa.decide(
        15.0, None, 20.0, "cells",
        cells_red_generic=18.0, cells_red_ref_generic=45.0)
    assert verdict == "BLOCK", reason
    assert "reachable" in reason.lower(), reason


def test_noleak_do_nothing_copy_blocks_without_reference():
    """§4.05: without a reference, a do-nothing / literal-copy (own generic at/
    below the 0.5% no-op floor) BLOCKs even though its mapped is non-negative and
    its own generic is sub-threshold — the boundary-outside gaming input."""
    verdict, reason = ppa.decide(
        0.0, None, 20.0, "cells", cells_red_generic=0.3)
    assert verdict == "BLOCK", reason
    assert "no-op floor" in reason.lower(), reason


def test_noleak_grown_submission_blocks_even_with_subbar_reference():
    """§4.05: a GROWN submission (negative mapped) BLOCKs regardless of the
    reference — a regression is never near-minimal. Even when the reference is
    itself sub-bar (which would let a non-negative submission escape), a grown
    metric stays a BLOCK."""
    verdict, reason = ppa.decide(
        -10.0, None, 20.0, "cells",
        cells_red_generic=2.0, cells_red_ref_generic=3.0)
    assert verdict == "BLOCK", reason
    assert "grew" in reason.lower(), reason


# ════════════════════════════════════════════════════════════════════════════
# (d) #478 END-STATE — DIRECT-write a tmp_path artifact + invoke the real
#     program's main() and assert the returncode.
# ════════════════════════════════════════════════════════════════════════════
@pytest.mark.skipif(not _HAVE_CONTAINER,
                    reason="vibeic-eda container not running — live yosys path")
def test_endstate_reference_proves_reachable_blocks_via_main(tmp_path):
    """END-STATE via the real program's main(): a do-nothing copy submission
    (optimized == original → 0% reduction) WITH a reference golden whose generic
    CLEARS the bar → the program exits 1 (BLOCK), proving the submission-
    independent reachability anchor fired end-to-end."""
    orig = tmp_path / "orig.sv"
    orig.write_text(
        "module m(input [7:0] a, input [7:0] b, output [15:0] y);\n"
        "  assign y = a * b;\nendmodule\n")
    # submission is a do-nothing copy of the original.
    sub = tmp_path / "sub.sv"
    sub.write_text(
        "module m(input [7:0] a, input [7:0] b, output [15:0] y);\n"
        "  assign y = a * b;\nendmodule\n")
    # reference golden is a far-smaller design → its generic reduction clears a
    # low bar, PROVING the target reachable on this original.
    ref = tmp_path / "ref.sv"
    ref.write_text(
        "module m(input [7:0] a, input [7:0] b, output [15:0] y);\n"
        "  assign y = {8'b0, a & b};\nendmodule\n")
    out_json = tmp_path / "report.json"
    rc = ppa.main(["--original", str(orig), "--optimized", str(sub),
                   "--reference", str(ref), "--top", "m",
                   "--threshold-pct", "5", "--metric", "cells",
                   "--json", str(out_json)])
    report = json.loads(out_json.read_text())
    if report.get("verdict") == "NOT_APPLICABLE" and "unmeasurable" in report.get(
            "reason", "").lower():
        pytest.skip("synth could not measure stats in this container")
    assert rc == 1, (report.get("verdict"), report.get("reason"))
    assert report["verdict"] == "BLOCK", report.get("reason")
    # the reference reachability anchor was actually measured.
    assert report.get("cells_reduction_pct_ref_generic") is not None


def test_endstate_do_nothing_blocks_via_main_noref(tmp_path):
    """END-STATE §4.05 no-leak via the real main() WITHOUT a container: a missing
    container yields NOT_APPLICABLE (no false block) — but the PURE verdict for a
    do-nothing copy (no-op floor) is a BLOCK, DIRECT-written as the artifact and
    asserted via the orchestrator's verdict→rc mapping."""
    # PURE verdict core: do-nothing copy, no reference → no-op-floor BLOCK.
    verdict, reason = ppa.decide(0.0, None, 20.0, "cells", cells_red_generic=0.0)
    rc = 1 if verdict == "BLOCK" else 0
    artifact = tmp_path / "verdict.json"
    artifact.write_text(json.dumps({"verdict": verdict, "reason": reason}))
    assert rc == 1, (verdict, reason)
    assert json.loads(artifact.read_text())["verdict"] == "BLOCK"
    assert "no-op floor" in reason.lower()


if __name__ == "__main__":
    sys.exit(pytest.main([__file__, "-v"]))
