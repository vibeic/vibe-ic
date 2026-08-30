"""The synth smoke measured with a different ruler than the scorer.

The gate ran `read_verilog; synth -top X; stat`. The official harness runs a
`synth.tcl` that first does `proc; opt; fsm; opt; memory; opt; techmap; opt` and
only then `synth`. A different network into `synth` is a different netlist out,
and the cell count is not merely diagnostic — `ppa_area_threshold_check`
computes an area-reduction PERCENTAGE from it, so a cid007 verdict was formed
against a number the scorer never produces.

Measured on cvdp_copilot_gaussian_rounding_div_0022's 33k-cell divider, in the
official cvdp-sim image:

    the scorer's synth.tcl       cells 32598, wires 32583
    the gate's old recipe        cells 32848            <- 250 cells adrift
    this recipe                  cells 32598, wires 32583  (exact)

The recipe is EMBEDDED, not read from the harness: §4.05 keeps the harness out
of this gate, and it is safe to embed because it is a fixed template — all 80
`synth.tcl` in the public benchmark reduce to one synthesis recipe once `-top`
is normalised.
"""
import importlib.util
import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[2]
BENCH = PLUGIN / "benchmark"
if str(BENCH) not in sys.path:
    sys.path.insert(0, str(BENCH))


def _gate():
    spec = importlib.util.spec_from_file_location(
        "gate_recipe_under_test", BENCH / "cvdp_gate.py")
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


# The scorer's synthesis steps, in order. `check -assert` is deliberately NOT
# among them: the scorer runs it against the COMPLETE design (its context files
# staged alongside), while this gate sees the completion ALONE, so a design that
# legitimately instantiates a harness-supplied module has undriven wires and
# `check -assert` hard-fails — the elevator_control_0033/0036 shape, and exactly
# the false-BLOCK the surrounding tolerance exists to prevent. A step copied
# without its precondition is not fidelity.
_REQUIRED = ("hierarchy -check -top", "proc", "opt", "fsm", "memory",
             "techmap", "synth -top", "clean")


def test_the_smoke_script_matches_the_scorers_steps():
    """THE REGRESSION: the old script jumped straight from read_verilog to
    synth, skipping the coarsening the scorer does first."""
    script = _gate()._scorer_synth_script("/tmp/x.sv", "top")
    for step in _REQUIRED:
        assert step in script, f"{step!r} missing from the smoke script: {script}"


def test_the_steps_are_in_the_scorers_order():
    """`techmap` before `synth`, not after — order decides the netlist."""
    s = _gate()._scorer_synth_script("/tmp/x.sv", "top")
    assert s.index("techmap") < s.index("synth -top"), s
    assert s.index("proc") < s.index("techmap"), s


def test_the_path_stays_quoted():
    """`yosys -p` takes a script yosys re-splits on whitespace. An unquoted
    workdir containing a SPACE opened two non-existent files and aborted before
    SYNTH — the #531 silent false-PASS this gate exists to prevent. Pinned by
    test_cvdp_gate_toolpath_must_not_disable_synth_smoke; re-pinned here because
    the recipe now lives in one helper that both call sites share."""
    s = _gate()._scorer_synth_script("/tmp/has space/x.sv", "top")
    assert '"/tmp/has space/x.sv"' in s, s


def test_both_call_sites_go_through_the_one_helper():
    """Two hand-rolled copies is how the smoke and the scorer drifted apart."""
    src = (BENCH / "cvdp_gate.py").read_text(encoding="utf-8")
    assert 'synth -top {top}; stat' not in src, \
        "a call site still builds the old bare recipe inline"
    assert src.count("_scorer_synth_script(") >= 3, \
        "both yosys call sites must use the shared helper"


def test_the_recipe_is_embedded_not_read_from_the_harness():
    """§4.05: the harness is held back from this gate. The recipe is safe to
    embed only because it is a fixed template, and it must stay embedded."""
    src = (BENCH / "cvdp_gate.py").read_text(encoding="utf-8")
    fn = src.split("_SCORER_SYNTH_STEPS", 1)[1].split("\ndef _confirming_rerun", 1)[0]
    for banned in ("synth.tcl", "/src/", "harness"):
        assert banned not in fn, \
            f"the recipe helper must not reach for {banned!r}"


def test_check_assert_is_not_copied_without_its_precondition():
    """The scorer runs `check -assert` on a complete design; this gate does not
    have one. Copying the step would false-BLOCK every completion that
    instantiates a harness-staged context module."""
    s = _gate()._scorer_synth_script("/tmp/x.sv", "top")
    assert "-assert" not in s, s
