"""ORGANIC #587 — phase2's sv2v synth fallback could not convert
canonical assertion-macro SystemVerilog: it (a) docker-cp'd only files
in the synth-source set so `include'd .svh headers never reached the
container, (b) passed no -I include path, (c) hardcoded -DSIMULATION so
the prim_assert `ifdef VERILATOR / `elsif SYNTHESIS / `else chain always
took the `else arm and included a never-staged sim-only header → sv2v
died on every such IP. Both round-6 glue agents hand-rolled the
conversion (sv2v -DSYNTHESIS -I . with .svh staged) outside the runner.

Fix in _phase2_sv_synth_fallback: stage the full .svh/.vh/pkg closure,
pass -I <workdir>, convert with -DSYNTHESIS (synth-bound; the TB path
keeps -DSIMULATION), and chain sv2v_mixed_driver_fixup over the output.
"""
import inspect
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import design_one_shot_runner as P2  # noqa: E402

_SRC = inspect.getsource(P2._phase2_sv_synth_fallback)


def test_fallback_passes_include_path():
    """Both frontends must pass -I <inc_dir> so `include resolves."""
    assert "-I " in _SRC
    assert "inc_dir" in _SRC
    # read_slang AND sv2v both get the include dir
    assert _SRC.count("-I {inc_dir}") >= 1 or _SRC.count("-I ") >= 2


def test_fallback_uses_synthesis_define_not_simulation():
    """Synth-bound conversion must define SYNTHESIS (so the `elsif
    SYNTHESIS assertion-macro arm is taken), not SIMULATION."""
    assert "-DSYNTHESIS" in _SRC
    # the synth fallback no longer hardcodes -DSIMULATION
    assert "sv2v -DSIMULATION" not in _SRC
    assert "read_slang {reads_join} --top {synth_top} -DSIMULATION" not in _SRC


def test_fallback_stages_header_and_package_closure():
    """The header/package closure (.svh/.vh/.h + *_pkg.*) is discovered
    and staged so `include + import resolve under -I."""
    assert "*.svh" in _SRC
    assert "closure_extra" in _SRC
    assert "_pkg" in _SRC


def test_fallback_chains_mixed_driver_fixup():
    """sv2v output is run through the #546 mixed-driver fixup before
    yosys reads it."""
    assert "sv2v_mixed_driver_fixup" in _SRC
    assert "fixup_file" in _SRC


def test_conversion_separated_from_yosys_read():
    """sv2v conversion + fixup + yosys read are distinct steps (so the
    fixup can run between them), not one chained shell pipeline."""
    # the old single `sv2v ... && yosys ...` pipeline is gone
    assert "2>sv2v.err && " not in _SRC
    assert "SV2V PRE-PASS CONVERSION" in _SRC


# ── the assertion-macro header pattern the fix targets (documentation
#    fixture: -DSYNTHESIS resolves the synthesisable arm) ──────────────────

_PRIM_ASSERT = """\
`ifdef VERILATOR
  `include "prim_assert_dummy_macros.svh"
`elsif SYNTHESIS
  `include "prim_assert_dummy_macros.svh"
`else
  `include "prim_assert_standard_macros.svh"
`endif
"""


def test_synthesis_define_selects_synthesisable_header():
    """Document the root cause via the shared ifdef-evaluator (#589):
    under -DSYNTHESIS the `elsif arm (dummy macros, synthesisable) is
    taken; under neither define the `else arm (sim-only, never staged)
    is taken — which is why the pre-fix -DSIMULATION path died."""
    import sv_package_closure_check as C
    segs_synth = C._annotate_conditionals(_PRIM_ASSERT, {"SYNTHESIS"})
    reachable = "".join(s for s, ok, _g in segs_synth if ok)
    assert "prim_assert_dummy_macros.svh" in reachable
    assert "prim_assert_standard_macros.svh" not in reachable
    # under SIMULATION-only (neither VERILATOR nor SYNTHESIS) → else arm
    segs_sim = C._annotate_conditionals(_PRIM_ASSERT, {"SIMULATION"})
    reachable_sim = "".join(s for s, ok, _g in segs_sim if ok)
    assert "prim_assert_standard_macros.svh" in reachable_sim
