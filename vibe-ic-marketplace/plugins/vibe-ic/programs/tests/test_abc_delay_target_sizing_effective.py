"""Timing-driven ABC: -D alone is silently INERT — it needs -sizing.

Defect (measured on a crypto/arithmetic benchmark IC, sky130A, 25.907 ns):
the phase-3 synth handed ABC a delay target (``-D <period_ps>``) and a code
comment asserted *"the fork's abc binds -D on the non -constr path"*. The
fork's OWN help says the opposite::

    -sizing
        (vibeic) append gate-sizing ('buffer; upsize; dnsize') after
        standard-cell mapping so that a -D delay target actually takes
        effect on the non -constr path (the default '&nf' mapper ignores
        -D there).

So on the non-``-constr`` path ``&nf`` mapped for AREA and the delay target
was ignored. yosys's ``techmap.v`` already builds a Brent-Kung parallel-prefix
adder for ``$lcu``, but an area-mode mapper collapses that log-depth prefix
into a deep carry chain — the setup-limited ripple seen at the slow corner.
The capability existed in the fork; only the wiring was missing.

This locks the wiring: whenever a clock period is known, EVERY standard-cell
mapping invocation must carry the delay target AND the flag that makes it
effective. Chip-AGNOSTIC — no chip / vendor / PDK literal is asserted.
"""
import re
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import phase3_one_shot_runner as R  # noqa: E402

RUNNER_SRC = (PROG / "phase3_one_shot_runner.py").read_text()

# Every std-cell mapping call site in the runner source.
_ABC_LIBERTY_CALL = re.compile(r"abc -liberty \{(\w+)\}([^;\"']*)")


def _sdc(tmp_path, period_ns="25.907"):
    d = tmp_path / "phase2" / "stage2" / "constraints"
    d.mkdir(parents=True)
    (d / "constraint.sdc").write_text(
        f"create_clock -name clk -period {period_ns} [get_ports clk]\n")
    return tmp_path


def test_period_is_resolved_so_the_lever_can_engage(tmp_path):
    """Precondition: without a period there is nothing to hand ABC."""
    assert R._sdc_period_ps(_sdc(tmp_path)) == 25_907


def test_abc_timing_carries_delay_target_and_sizing():
    """-D must never be emitted without the flag that makes it take effect."""
    m = re.search(r"_abc_timing = .*", RUNNER_SRC)
    assert m, "_abc_timing assignment not found"
    expr = m.group(0)
    assert "-D {_period_ps}" in expr or "-D {" in expr, (
        f"_abc_timing no longer passes a delay target: {expr}")
    assert "-sizing" in expr, (
        "_abc_timing passes -D WITHOUT -sizing: on the non -constr path the "
        "default '&nf' mapper IGNORES -D, so the delay target is silently "
        f"inert and arithmetic maps for area. Got: {expr}")


def test_every_stdcell_mapping_call_site_hands_over_timing():
    """No std-cell mapping call site may silently drop the timing hand-off.

    A second call site that maps standard cells with a bare
    ``abc -liberty <lib>`` re-maps the design in area mode and undoes the
    timing-driven mapping done elsewhere.
    """
    bare = []
    for m in _ABC_LIBERTY_CALL.finditer(RUNNER_SRC):
        tail = m.group(2)
        # Accept any interpolated timing hand-off (`{_abc_timing}` at the main
        # synth, `{abc_timing}` where it is threaded into a helper).
        if "abc_timing" not in tail and "-fast" not in tail:
            line_no = RUNNER_SRC[:m.start()].count("\n") + 1
            bare.append(f"line {line_no}: abc -liberty {{{m.group(1)}}}{tail}")
    assert not bare, (
        "standard-cell mapping call site(s) with NO timing hand-off — these "
        "re-map in area mode and discard the delay-driven result:\n  "
        + "\n  ".join(bare))


def test_no_stale_claim_that_bare_D_binds():
    """The false belief that caused this must not survive in the source."""
    stale = re.search(r"abc binds -D on the non -constr path", RUNNER_SRC)
    assert not stale, (
        "source still claims bare -D binds on the non -constr path; the "
        "fork's help says '&nf' ignores -D there unless -sizing is passed")
