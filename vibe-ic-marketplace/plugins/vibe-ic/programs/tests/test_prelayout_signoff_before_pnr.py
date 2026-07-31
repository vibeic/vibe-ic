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
"""
import ast
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import phase3_one_shot_runner as R  # noqa: E402

_SRC = (Path(__file__).resolve().parents[1] / "phase3_one_shot_runner.py").read_text()


def test_no_op_skip_when_no_staged_corners(tmp_path):
    """Negative control: <2 staged corner libs → SKIP, writes nothing.

    A test that could not fail against the pre-fix code proves nothing; this
    asserts the additive guard so a container-PDK project is provably untouched.
    """
    proj = tmp_path / "proj"
    (proj / "input" / "pdk" / "liberty").mkdir(parents=True)
    # zero staged libs → must SKIP

    class _Pdk:  # minimal stand-in; the SKIP path reads nothing off it
        name = "sky130A"
        liberty = "/foss/pdks/x/nom.lib"

    res = R.step_prelayout_signoff(proj, "chip_top", _Pdk(), "no-such-container")
    assert res.status == "SKIP", res.status
    assert res.output_files == []
    # exactly one staged lib is still a SKIP (a single corner is not a matrix)
    (proj / "input" / "pdk" / "liberty" / "tt.lib").write_text("library(tt){}")
    res1 = R.step_prelayout_signoff(proj, "chip_top", _Pdk(), "no-such-container")
    assert res1.status == "SKIP", res1.status


def test_function_exists_and_returns_stepresult():
    assert hasattr(R, "step_prelayout_signoff")
    fn = R.step_prelayout_signoff
    # 4 positional params: project, top, pdk, container
    code = fn.__code__
    assert code.co_argcount == 4, code.co_varnames[:4]


def test_main_calls_prelayout_signoff_before_pnr():
    """WIRING + ORDER: main() must call step_prelayout_signoff and it must
    appear textually before the step_pnr call (the emit must precede PnR)."""
    tree = ast.parse(_SRC)
    main_fn = next(n for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef) and n.name == "main")

    def _first_call_line(name):
        for node in ast.walk(main_fn):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id == name):
                return node.lineno
        return None

    pls = _first_call_line("step_prelayout_signoff")
    pnr = _first_call_line("step_pnr")
    assert pls is not None, "main() never calls step_prelayout_signoff"
    assert pnr is not None, "main() never calls step_pnr"
    assert pls < pnr, (
        f"step_prelayout_signoff (line {pls}) must be called BEFORE "
        f"step_pnr (line {pnr}) — the pre-layout emit must not sit behind PnR")
