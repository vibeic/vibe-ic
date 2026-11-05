"""FP-20 — `tapeout_precheck` must be told the PDK the run was invoked with.

THE DEFECT, MEASURED.  `_DECLARED_SIGNOFF_GATES`' `tapeout_precheck` entry
carried an EMPTY argv tail, so a run invoked `--pdk gf180mcuD` passed nothing.
`tapeout_precheck.resolve_pdk` then falls back to scraping the run's own tool
logs and yields the FAMILY, `gf180mcu`. Re-measured on this tree with
`pdk_metal_density_windows.windows_for_pdk`:

    gf180mcuD -> status=stated       6 layers, metal1 min 0.30
    gf180mcu  -> status=unknown-pdk  0 layers

`general_precheck` forwards whatever it got to `metal_layer_density_check`, so
all five metal layers came back UNCHECKED and `Checker.KLayoutDensity` FAILED a
die whose measured densities are 0.4175 .. 0.4594 — INSIDE the 0.30 minimum.
(Evidence: lane czspmfp, MEASUREMENTS.md §17.2, copied read-only to
`from_other_lanes/czspmfp_MEASUREMENTS.md`; the registry asymmetry above is
re-measured here rather than quoted.)

WHY THE FIX IS NOT "PUT IT IN THE TABLE".  `_DECLARED_SIGNOFF_GATES` is a module
CONSTANT; `pdk` is a per-RUN value and is not in scope there. The landed
precedent one level down says the same thing in its own words —
`general_precheck._step_delegate`: "Forwarded here rather than frozen into
`argv_tail` because the PDK is resolved per RUN, not per step."

MUTATIONS THESE MUST KILL:
  * Reverting the entry/forwarding so no `--pdk` reaches the gate fails
    `test_the_pdk_aware_gate_is_given_the_runs_own_distribution`.
  * Forwarding to EVERY gate fails `test_every_other_gate_argv_is_byte_identical`.
  * Forwarding the family instead of the distribution fails
    `test_the_value_forwarded_is_the_distribution_not_the_family`.
  * Dropping the call-site argument fails `test_the_call_site_passes_the_runs_pdk`.
"""

import ast
import sys
from pathlib import Path


PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import pdk_metal_density_windows as W       # noqa: E402




# --- the registry asymmetry that makes this load-bearing ------------------- #

def test_the_family_and_the_distribution_are_not_interchangeable():
    """NEGATIVE CONTROL for the whole finding: if the registry answered the
    same for both, passing `--pdk` would change nothing and every test below
    would be theatre."""
    dist, dist_prov = W.windows_for_pdk("gf180mcuD")
    fam, fam_prov = W.windows_for_pdk("gf180mcu")
    assert dist_prov["status"] == "stated" and len(dist) > 0
    assert fam_prov["status"] == "unknown-pdk" and len(fam) == 0
    # and the die densities czspmfp measured are INSIDE the stated minimum
    lo, _hi = dist["metal1"]
    assert lo is not None
    for measured in (0.4175, 0.4555, 0.4560, 0.4583, 0.4594):
        assert measured > lo, (measured, lo)


# --- the forwarding itself -------------------------------------------------- #











def test_the_gate_actually_accepts_the_flag():
    """Forwarding an argument the program rejects would turn a FAIL into a
    crash — worse, not better."""
    src = (PROGRAMS / "tapeout_precheck.py").read_text()
    assert 'add_argument("--pdk"' in src


#: The ARGUMENT LIST the wired call site must pass, in order — the MEMBERS,
#: not their number. `len(calls[0].args) == 2` stood here alone and is a count
#: pinned against a live re-derivation of the checkout with nothing pinning the
#: identities: `population_pin_without_its_member_set` names it, and it is
#: right to. One departure and one arrival in the same edit leave the count at
#: 2 and change what is forwarded — `step_declared_signoff_gates(project,
#: pdk.name)` becoming `step_declared_signoff_gates(project, args.pdk)` is
#: exactly that shape, and it is the defect this file exists to catch: what the
#: gate is told must be the pdk the RUN BUILT, never the word the operator
#: typed.
#: THIRD MEMBER RECORDED with the commit that adds it (icspm5, 2026-09-18).
#: `args.container` is the same shape of fact as `pdk.name` and is forwarded
#: for the same reason: the precheck's technology rungs read the PDK volume,
#: whose paths are CONTAINER paths, from a HOST process. MEASURED on spm x
#: gf180mcuD (v1.22.10, run5): both attempts were `/foss/pdks/gf180mcuD`, the
#: host has no `/foss`, and `General.ForbiddenLayers` reported NOT_DETERMINED
#: over 37 layer/datatype pairs. The member SET is what this pin guards, so a
#: new member is added here, in the same edit, with its reason — never by
#: loosening the comparison to a count.
_EXPECTED_CALL_ARGS = ("project", "pdk.name", "args.container")


def _signoff_gate_call_args():
    """Both Default and Ultra calls, with every argument re-derived."""
    src = (PROGRAMS / "phase3_one_shot_runner.py").read_text()
    calls = [n for n in ast.walk(ast.parse(src))
             if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name)
             and n.func.id == "step_declared_signoff_gates"]
    assert len(calls) == 2, [ast.unparse(c) for c in calls]
    return tuple(tuple(ast.unparse(a) for a in call.args) for call in calls)


def test_the_call_site_passes_the_runs_pdk():
    """The forwarding must be WIRED; a parameter nobody supplies is the same
    empty argv with more code.

    The MEMBER SET first, then the count as `len()` of it. Comparing the whole
    tuple in one assertion is what makes a same-count substitution visible:
    a positional swap, a renamed source, or a second argument replaced by
    another expression all leave the COUNT true and this assertion false.
    """
    for got in _signoff_gate_call_args():
        assert got == _EXPECTED_CALL_ARGS, (
            f"the wired call forwards {got!r}, expected {_EXPECTED_CALL_ARGS!r}")
        assert len(got) == len(_EXPECTED_CALL_ARGS)
        # Check the load-bearing second argument at EVERY wired call.
        assert got[1] == "pdk.name"


def test_a_same_count_substitution_is_caught():
    """MUTATION — the control the count pin could not have.

    Swap one member for another of the SAME COUNT and require the comparison
    to go red. `len(...) == 2` is true of every tuple below; only the member
    comparison separates them, which is the entire claim of the rule this
    repairs.
    """
    for real in _signoff_gate_call_args():
        assert real == _EXPECTED_CALL_ARGS, "the fixture must start from the truth"
        for mutant in (("project", "args.pdk", "args.container"),   # the REQUEST
                       ("project", "pdk", "args.container"),        # not its name
                       ("pdk.name", "project", "args.container"),   # swapped
                       ("run_dir", "pdk.name", "args.container"),   # first replaced
                       ("project", "pdk.name", "args.image")):      # third replaced
            assert len(mutant) == len(_EXPECTED_CALL_ARGS), mutant
            assert mutant != _EXPECTED_CALL_ARGS, mutant


def _code_of(module_name: str, func_name: str) -> str:
    """A function's CODE, with comments AND its docstring removed.

    `ast.unparse` drops comments but KEEPS the docstring, and a docstring that
    explains why a name must not appear contains that name. This bit me twice in
    this lane — first on `_announce_local_atpg_route`, then here — so the strip
    lives in one helper instead of being remembered."""
    src = (PROGRAMS / module_name).read_text()
    fn = [n for n in ast.walk(ast.parse(src))
          if isinstance(n, ast.FunctionDef) and n.name == func_name]
    assert len(fn) == 1, (module_name, func_name, len(fn))
    body = list(fn[0].body)
    if (body and isinstance(body[0], ast.Expr)
            and isinstance(body[0].value, ast.Constant)
            and isinstance(body[0].value.value, str)):
        body = body[1:]
    assert body, "function has no code outside its docstring"
    return "\n".join(ast.unparse(n) for n in body)


def test_the_helper_strips_the_docstring():
    """Control for `_code_of` itself: the docstring of the function under test
    DOES contain the forbidden name, so if the strip failed this file would be
    asserting nothing."""
    src = (PROGRAMS / "phase3_one_shot_runner.py").read_text()
    fn = [n for n in ast.walk(ast.parse(src))
          if isinstance(n, ast.FunctionDef)
          and n.name == "step_declared_signoff_gates"][0]
    assert "resolve_pdk" in ast.get_docstring(fn)
    assert "resolve_pdk" not in _code_of("phase3_one_shot_runner.py",
                                         "step_declared_signoff_gates")


def test_there_is_no_second_resolver():
    """The run passes the value it already resolved; nothing here re-derives a
    PDK, which is the defect `resolve_pdk`'s own docstring warns about."""
    code = _code_of("phase3_one_shot_runner.py", "step_declared_signoff_gates")
    for forbidden in ("resolve_pdk", "_detect_pdk", "declared_target"):
        assert forbidden not in code, forbidden
