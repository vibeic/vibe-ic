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
import sys
from pathlib import Path

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))













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
