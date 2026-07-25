"""Guard the MEASURED configuration of the ABC delay target.

Two facts, both measured, that point in OPPOSITE directions:

  (a) `-D` alone is INERT on the non `-constr` path. Proof: same RTL, same PDK,
      one clock — `-D <period>` produced a netlist BYTE-IDENTICAL to no `-D`
      (identical worst-path arrival 65.507 ns, identical cell count and area).
      The fork's own help says `-sizing` exists so `-D` "actually takes effect
      ... (the default '&nf' mapper IGNORES -D there)".

  (b) Making it bind made the SHIPPED design WORSE. Controlled post-route A/B,
      same RTL, both freshly synthesised, differing only in these flags:

          arm                       cells   SHIP_WNS_POSTROUTE (ss corner)
          -D only                    8079        -2.519 ns
          -D -sizing -area_recover    8451        -4.386 ns   <-- WORSE

      +4.6% cells bought a 22% PRE-PnR win and a 1.87 ns POST-ROUTE regression.
      OpenROAD's repair_design / repair_timing already resizes after placement,
      so synth-time sizing is redundant with it and pays only its area cost —
      the same mechanism that makes dch -f / dc2 (+26% area) a net loss.

So the delay target is deliberately left INERT: that is the measured-better
configuration. This test exists so nobody "fixes" (a) without redoing (b) — the
obvious-looking improvement is the one that regressed the shipped corner.

Chip-AGNOSTIC: asserts flow configuration, no chip / vendor / PDK literal.
"""
import re
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))

RUNNER_SRC = (PROG / "phase3_one_shot_runner.py").read_text()


def _abc_timing_expr() -> str:
    m = re.search(r"_abc_timing = .*(?:\n\s+.*)?", RUNNER_SRC)
    assert m, "_abc_timing assignment not found"
    return m.group(0)


def test_sizing_is_not_enabled_without_post_route_evidence():
    """`-sizing` regressed the shipped corner; it must not reappear silently."""
    expr = _abc_timing_expr()
    assert "-sizing" not in expr, (
        "-sizing was re-enabled. It improves PRE-PnR delay ~22% and REGRESSED "
        "post-route SS WNS by 1.87 ns (-2.519 -> -4.386) on the measured "
        "design, at +4.6% cells. Re-enable ONLY with a fresh post-route A/B on "
        "the shipped SPEF showing it helps.")
    assert "-area_recover" not in expr, (
        "-area_recover was re-enabled; see -sizing above (same A/B)")


def test_the_false_binding_claim_stays_out_of_the_source():
    """The comment that caused this must not come back."""
    assert not re.search(r"abc binds -D on the non -constr path", RUNNER_SRC), (
        "source again claims bare -D binds on the non -constr path; measured "
        "byte-identical netlists prove it does not")


def test_the_measured_regression_is_documented_where_the_lever_lives():
    """A future reader must meet the counter-evidence at the lever itself."""
    i = RUNNER_SRC.find("_abc_timing = ")
    assert i != -1
    context = RUNNER_SRC[max(0, i - 3000):i]
    assert "SHIP_WNS_POSTROUTE" in context, (
        "the post-route A/B result is not recorded next to the delay-target "
        "lever; without it the next reader re-runs the same regression")
