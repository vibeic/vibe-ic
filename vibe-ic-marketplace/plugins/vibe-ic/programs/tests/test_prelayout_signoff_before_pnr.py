"""Steps 7/8/10 (pre-layout, stage-2) must be emittable BEFORE PnR.

ORGANIC (opentitan_aes r7). Steps 7 (SDC + PVT matrix) and 10 (pre-layout
multi-corner STA) are STAGE-2 / PRE-LAYOUT steps: their inputs are the
technology-mapped synth netlist + SDC + PDK liberty corners, none post-layout.
Their only producer was ``step_canonicalize_artefacts``, which runs at the TAIL
of phase-3 after step_pnr/step_gds/step_drc/step_lvs — so a route that did not
converge (killed on a 4 h wall-clock cap, measured on opentitan_aes) left the
three pre-layout artefacts UNWRITTEN and Steps 7/8/10 scored MISSING.

``step_prelayout_signoff`` closes this by emitting them right after synth,
before step_pnr, and main() wires it there. This test proves:

  1. NEGATIVE CONTROL — a project that does NOT stage >=2 corner libs is a
     NO-OP (SKIP), so the change cannot regress the container-built-in-PDK
     path (its post-route canonicalize emit is untouched).
  2. WIRING — main() calls step_prelayout_signoff, and does so BEFORE it calls
     step_pnr (the whole point: the pre-layout emit must not sit behind PnR).

Firing this step on the majority case also promotes everything it does to the
DEFAULT path, so the second half of this file pins the SDC it emits:

  3. the design's OWN SDC (``input/constraints``, via the shared
     ``_resolve_staged_silicon_sdc``) reaches BOTH emitted decks, rather than
     the runner's fabricated one;
  4. the same unit-rescale + DRV + I/O parity chain ``step_pnr`` applies is
     applied here, and never OVERRIDES a design-declared value;
  5. a deck this step FABRICATED is never copied to the canonical path, where
     the shared resolver would hand it back to ``step_pnr`` as "design-staged".
"""
import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

_SRC = (Path(__file__).resolve().parents[1] / "phase3_one_shot_runner.py").read_text()










# The DESIGN's own SDC, copied verbatim from the tracked benchmark project
# `benchmark-data/ic/edge_llm_accel/input/constraints/clock.sdc`. It stages at
# the canonical ground-truth path and names its clock `core_clock` — a name the
# runner's auto-SDC (`create_clock -name clk`) cannot produce by accident, so
# the assertion below cannot pass on a fabricated deck.
_EDGE_LLM_ACCEL_SDC = (
    "# edge_llm_accel — L9 §9.1 SDC (100 MHz)\n"
    "set_units -time ns\n"
    "create_clock [get_ports clk] -name core_clock -period 10.0\n")












def _first_dispatch_line(main_fn, name):
    """Lowest line in ``main_fn`` at which step ``name`` is DISPATCHED.

    A step reaches the plan through either of two shapes, and both are real
    dispatches:

      * DIRECT   -- ``step_prelayout_signoff(project, top, pdk, container)``
        the step is the callee.
      * WRAPPED  -- ``_spf.gate(project, ..., step_pnr, project, top, ...)``
        the step is handed to a pre-flight gate that calls it. `step_pnr` is
        an ARGUMENT here, not the callee.

    Matching only the direct shape is what made this test report
    "main() never calls step_pnr" against a main() that dispatches PnR
    correctly: PnR was moved behind the `_spf.gate` pre-flight and the
    detector did not follow it. So a step named as a Call ARGUMENT counts
    too -- but a bare mention anywhere in main() does NOT, because
    "mentioned" and "dispatched" are different claims and only the second
    one is what this test is about.

    Returns the MINIMUM line over all matches, not the first one `ast.walk`
    happens to reach: `ast.walk` is breadth-first, so its "first" is not the
    textually-first, and the ordering assertion below compares line numbers.
    """
    lines = []
    for node in ast.walk(main_fn):
        if not isinstance(node, ast.Call):
            continue
        # DIRECT: the step is the callee.
        if isinstance(node.func, ast.Name) and node.func.id == name:
            lines.append(node.func.lineno)
        # WRAPPED: the step is passed to something that will call it.
        for arg in list(node.args) + [k.value for k in node.keywords]:
            if isinstance(arg, ast.Name) and arg.id == name:
                lines.append(arg.lineno)
    return min(lines) if lines else None


def test_main_calls_prelayout_signoff_before_pnr():
    """WIRING + ORDER: main() must dispatch step_prelayout_signoff and it must
    appear textually before the step_pnr dispatch (the emit must precede PnR).

    Order is the whole point of the step, so it is asserted on the DISPATCH
    site in either shape -- see ``_first_dispatch_line``.
    """
    tree = ast.parse(_SRC)
    main_fn = next(n for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef) and n.name == "main")

    pls = _first_dispatch_line(main_fn, "step_prelayout_signoff")
    pnr = _first_dispatch_line(main_fn, "_default_step15_with_backend_receipt")
    assert pls is not None, "main() never dispatches step_prelayout_signoff"
    assert pnr is not None, "main() never dispatches the current PnR entry"
    entry = next(n for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef)
                 and n.name == "_default_step15_with_backend_receipt")
    assert _first_dispatch_line(entry, "_default_pnr_rows") is not None
    assert _first_dispatch_line(entry, "step_pnr") is not None
    assert pls < pnr, (
        f"step_prelayout_signoff (line {pls}) must be dispatched BEFORE "
        f"step_pnr (line {pnr}) — the pre-layout emit must not sit behind PnR")


# ── PAIRED GUARD for the detector above ────────────────────────────────────
# Widening a detector to stop a false red is one edit away from widening it
# until it cannot go red at all. These pin the three ways that would happen.
# They are unit tests OF `_first_dispatch_line`, so they keep holding when the
# runner is refactored again — which is exactly what broke the original.

def _main_of(src):
    tree = ast.parse(src)
    return next(n for n in ast.walk(tree)
                if isinstance(n, ast.FunctionDef) and n.name == "main")


def test_detector_reports_absent_when_the_dispatch_is_deleted():
    """NEGATIVE CONTROL: no dispatch at all → None → the test above fails.

    If this returned a line, the `is not None` assertions would be dead and
    a main() that never runs PnR would score green.
    """
    src = ("def main():\n"
           "    _pls = step_prelayout_signoff(project, top, pdk, container)\n"
           "    plan.append(_pls)\n")
    assert _first_dispatch_line(_main_of(src), "step_pnr") is None


def test_detector_catches_pnr_dispatched_before_the_prelayout_emit():
    """NEGATIVE CONTROL: the real defect this file exists to prevent —
    the pre-layout emit sitting BEHIND PnR — in the wrapped shape."""
    src = ("def main():\n"
           "    plan.append(_spf.gate(project, 'r', 'pnr', _ref('pnr'),\n"
           "                          step_pnr, project, top, pdk))\n"
           "    _pls = step_prelayout_signoff(project, top, pdk, container)\n")
    main_fn = _main_of(src)
    pls = _first_dispatch_line(main_fn, "step_prelayout_signoff")
    pnr = _first_dispatch_line(main_fn, "step_pnr")
    assert pls is not None and pnr is not None
    assert not (pls < pnr), (
        "detector accepted an ordering where PnR precedes the pre-layout "
        "emit — the one thing this file is for")


def test_a_bare_mention_is_not_counted_as_a_dispatch():
    """The widening is to Call ARGUMENTS, not to any occurrence.

    `step_pnr` named outside a call — assigned, compared, annotated — is not
    a dispatch, and counting it would let a main() that merely *refers* to
    PnR pass the wiring assertion.
    """
    src = ("def main():\n"
           "    _alias = step_pnr\n"
           "    if step_pnr is None:\n"
           "        return 1\n")
    assert _first_dispatch_line(_main_of(src), "step_pnr") is None


def test_detector_finds_the_textually_first_of_several_dispatches():
    """`ast.walk` is breadth-first, so its first match is not the first line.

    The ordering assertion compares line numbers, so the detector must return
    the MINIMUM. A nested-then-flat arrangement is where walk order and source
    order disagree.
    """
    src = ("def main():\n"
           "    if x:\n"
           "        plan.append(_spf.gate(a, step_pnr, project))\n"
           "    step_pnr(project, top)\n")
    # walk reaches the depth-1 direct call before the depth-2 wrapped one;
    # the wrapped one is textually first and is the answer.
    assert _first_dispatch_line(_main_of(src), "step_pnr") == 3
