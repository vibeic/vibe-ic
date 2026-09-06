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

import pytest

PROGRAMS = Path(__file__).resolve().parents[1]
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import phase3_one_shot_runner as R          # noqa: E402
import pdk_metal_density_windows as W       # noqa: E402


@pytest.fixture
def recorded(monkeypatch):
    """Capture the (name, program, out_rel, extra_argv) each gate is run with."""
    seen = []

    def _fake(project, name, program, out_rel, extra_argv=()):
        seen.append((name, program, out_rel, tuple(extra_argv)))
        return R.StepResult(name, "PASS", 0.0, "stub")

    monkeypatch.setattr(R, "_run_declared_signoff_gate", _fake)
    return seen


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

def test_the_pdk_aware_gate_is_given_the_runs_own_distribution(recorded,
                                                               tmp_path):
    R.step_declared_signoff_gates(tmp_path, "gf180mcuD")
    tp = [e for e in recorded if e[0] == "tapeout_precheck"]
    assert len(tp) == 1, recorded
    assert "--pdk" in tp[0][3], tp[0]
    assert tp[0][3][tp[0][3].index("--pdk") + 1] == "gf180mcuD"


def test_the_value_forwarded_is_the_distribution_not_the_family(recorded,
                                                                tmp_path):
    R.step_declared_signoff_gates(tmp_path, "gf180mcuD")
    tp = [e for e in recorded if e[0] == "tapeout_precheck"][0]
    forwarded = tp[3][tp[3].index("--pdk") + 1]
    assert forwarded == "gf180mcuD"
    # the family is exactly the value that made the gate blind
    assert forwarded != "gf180mcu"
    assert W.windows_for_pdk(forwarded)[1]["status"] == "stated"


def test_every_other_gate_argv_is_byte_identical(recorded, tmp_path):
    """THE CONTROL. Only the PDK-aware gate may change."""
    R.step_declared_signoff_gates(tmp_path, "gf180mcuD")
    with_pdk = {e[0]: e[3] for e in recorded}
    recorded.clear()
    R.step_declared_signoff_gates(tmp_path)          # the previous behaviour
    without = {e[0]: e[3] for e in recorded}
    assert set(with_pdk) == set(without)             # membership, not counts
    for name in sorted(without):
        if name == "tapeout_precheck":
            continue
        assert with_pdk[name] == without[name], name
    # and the table's own declaration for the others is preserved verbatim
    declared = {g[0]: tuple(g[3]) for g in R._DECLARED_SIGNOFF_GATES}
    for name in sorted(without):
        if name != "tapeout_precheck":
            assert without[name] == declared[name], name


def test_no_pdk_supplied_is_exactly_the_previous_behaviour(recorded, tmp_path):
    R.step_declared_signoff_gates(tmp_path, "")
    for name, _prog, _out, extra in recorded:
        assert "--pdk" not in extra, (name, extra)


def test_only_the_named_set_receives_it():
    assert R._PDK_AWARE_SIGNOFF_GATES == frozenset({"tapeout_precheck"})
    declared = {g[0] for g in R._DECLARED_SIGNOFF_GATES}
    assert R._PDK_AWARE_SIGNOFF_GATES <= declared, "names a gate that is not declared"


def test_the_gate_actually_accepts_the_flag():
    """Forwarding an argument the program rejects would turn a FAIL into a
    crash — worse, not better."""
    src = (PROGRAMS / "tapeout_precheck.py").read_text()
    assert 'add_argument("--pdk"' in src


def test_the_call_site_passes_the_runs_pdk():
    """The forwarding must be WIRED; a parameter nobody supplies is the same
    empty argv with more code."""
    src = (PROGRAMS / "phase3_one_shot_runner.py").read_text()
    tree = ast.parse(src)
    calls = [n for n in ast.walk(tree)
             if isinstance(n, ast.Call)
             and isinstance(n.func, ast.Name)
             and n.func.id == "step_declared_signoff_gates"]
    assert len(calls) == 1, calls
    assert len(calls[0].args) == 2, ast.unparse(calls[0])
    assert ast.unparse(calls[0].args[1]) == "pdk.name"


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
