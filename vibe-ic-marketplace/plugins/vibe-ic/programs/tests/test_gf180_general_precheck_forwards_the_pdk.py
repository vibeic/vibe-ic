"""The density delegate was never told which PDK, so it could never decide.

MEASURED, gf180mcuD chip path 2026-08-22. With every other refusal on our own
precheck arm closed, both `spm` and `sha256` sat at

    steps_with_evidence=10/11   failed=['Checker.KLayoutDensity']

on dies whose per-layer densities are 0.4381 / 0.4157 / 0.4685 / 0.5169 / 0.4386
against a foundry-stated minimum of 0.30 — comfortably inside the only rule that
process writes.

The cause is one empty tuple:

    Step("Checker.KLayoutDensity", ..., DELEGATED, ...,
         delegate=Delegate("metal_layer_density_check", (),      # <- argv_tail
                           ..., positional="reports_dir"))

`metal_layer_density_check` judges against a PDK's OWN stated per-layer windows
and takes `--pdk` to find them. Never given one, it has no windows, every metal
layer is UNCHECKED, and the step FAILs — a wiring gap reported as a property of
the die.

`--pdk` is forwarded per RUN rather than frozen into `argv_tail`, because which
PDK a project targets is a fact about the run, not about the ladder.

THE HONEST-ABSENCE HALF: when no PDK is known, the delegate is invoked WITHOUT
`--pdk` exactly as before. It then cannot reach a verdict, and that is reported.
An unknown PDK must never be laundered into a clean density result.
"""
import sys
from pathlib import Path
from typing import List

PROG = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROG))
import general_precheck as G  # noqa: E402


def _density_step():
    return next(s for s in G.LADDER if s.step_id == "Checker.KLayoutDensity")


def _capture(pdk, tmp_path):
    """Run just the delegate step with a fake runner; return the argv it built."""
    seen: List[List[str]] = []

    def fake(cmd, timeout):
        seen.append(list(cmd))
        return 0, '{"verdict": "PASS", "per_layer": {}}', ""

    ev = G._blank(_density_step())
    G._step_delegate(ev, _density_step(), tmp_path, fake, PROG,
                     5.0, pdk=pdk)
    assert seen, "the delegate was never invoked"
    return seen[0]


def test_the_pdk_reaches_the_density_delegate(tmp_path):
    """THE DEFECT: the one argument that lets a PDK-aware gate decide."""
    cmd = _capture("somepdk", tmp_path)
    assert "--pdk" in cmd, cmd
    assert cmd[cmd.index("--pdk") + 1] == "somepdk", cmd


def test_NEGATIVE_an_unknown_pdk_adds_no_flag_and_invents_no_name(tmp_path):
    """THE HONEST-ABSENCE HALF. With no PDK known the invocation is exactly what
    it was before this change — no `--pdk`, no placeholder, no default. The gate
    then cannot reach a verdict and says so; it is never credited as clean."""
    cmd = _capture(None, tmp_path)
    assert "--pdk" not in cmd, cmd
    assert not any("pdk" in a.lower() and a.startswith("-") for a in cmd), cmd


def test_NEGATIVE_an_empty_pdk_string_is_treated_as_unknown(tmp_path):
    """`--pdk ""` is not a PDK. It must not be forwarded as one."""
    cmd = _capture("", tmp_path)
    assert "--pdk" not in cmd, cmd


def test_CONTROL_only_pdk_aware_delegates_get_the_flag(tmp_path):
    """A blanket forward would hand `--pdk` to checkers that do not accept it
    and turn a working step into an argparse error. The set is explicit."""
    assert G._PDK_AWARE_DELEGATES == {"metal_layer_density_check"}
    others = [s for s in G.LADDER
              if s.delegate is not None
              and s.delegate.program not in G._PDK_AWARE_DELEGATES]
    assert others, "no non-PDK-aware delegate to check against"
    for step in others:
        seen: List[List[str]] = []

        def fake(cmd, timeout):
            seen.append(list(cmd))
            return 0, "{}", ""

        ev = G._blank(step)
        G._step_delegate(ev, step, tmp_path, fake, PROG, 5.0,
                         seal_required=True, pdk="somepdk")
        if seen:
            assert "--pdk" not in seen[0], (step.step_id, seen[0])


def test_CONTROL_the_positional_and_json_arguments_are_unchanged(tmp_path):
    """Forwarding must not disturb the call shape the delegate already had."""
    cmd = _capture("somepdk", tmp_path)
    assert cmd[2].endswith("reports/phase3"), cmd
    assert "--json" in cmd and cmd[-1].endswith("precheck_density.json"), cmd


def test_CONTROL_evaluate_exposes_the_pdk_parameter():
    import inspect
    assert "pdk" in inspect.signature(G.evaluate).parameters
