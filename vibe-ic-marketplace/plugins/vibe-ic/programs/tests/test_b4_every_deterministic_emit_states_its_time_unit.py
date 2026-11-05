"""#2053, the emitter half, at EVERY deterministic emit — not one of five.

v1.18.7 landed the rule ("state the unit the project DECLARES, never guess one,
refuse BY NAME when nothing declares one") at `_try_spec_artifact_registry_rtl`
alone. MEASURED on v1.18.12 and again on v1.18.24: `design_one_shot_runner` has
FIVE deterministic emit paths and four of them published candidates that stated
no unit at all —

    _try_spec_artifact_registry_rtl       stamped   (v1.18.7)
    _try_deterministic_rtl_dispatch       NOT
    _try_canonical_primitive_rtl          NOT
    _try_phase1_behavioral_fsm_rtl_bound  NOT  (both its publish and its
                                                restore-a-removed-file site)

so the defect #2053 exists to close — a candidate with no `timescale inherits
the unit of whichever source the simulator compiled first, and the same correct
candidate then passes or fails on iverilog's argument order — was still reachable
through four of the five doors.

THE STATEMENT IS PART OF THE EMITTED TEXT, MADE AT EMISSION. Every path hands
`_publish_phase1_rtl_no_clobber` bytes that already state the unit, so the
publisher stays a pure fd-bound byte-mover and the digest it records is the
digest OF THE STAMPED BYTES. That is what keeps the restore-a-removed-file
digest match meaning what it says, and it is asserted here rather than assumed.

The unit is resolved by `_project_declared_timescale` and stated by
`_state_declared_timescale` — v1.18.7's own functions, the only implementations.
"""
import ast
import re
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import design_one_shot_runner as R  # noqa: E402

DECLARED = "`timescale 1ns / 1ps\nmodule tb; endmodule\n"
UNIT = "1ns/1ps"

#: a mechanically-derivable spec — `_try_deterministic_rtl_dispatch` routes it
#: through the REAL `deterministic_rtl_dispatcher` subprocess.
FSM_SPEC = {
    "module": "chip_top", "kind": "moore_comb",
    "input": "in", "state_in": "state", "next_state_out": "next_state",
    "output": "out", "encoding": {"A": 0, "B": 1},
    "transitions": {"A": {"0": "A", "1": "B"}, "B": {"0": "A", "1": "B"}},
    "outputs": {"A": 0, "B": 1},
}

#: prose whose STRUCTURE `canonical_primitive_synth.detect_shape` recognises.
CANONICAL_PULSE = (
    "Module name:\n    pulse_detect\n"
    "Pulse detection: when data_in changes from 0 to 1 to 0 this is a pulse.\n"
    "Input ports:\n clk: Clock.\n rst_n: Reset.\n data_in: One-bit input.\n"
    "Output ports:\n data_out: pulse indicator.\n")



@pytest.fixture(autouse=True)
def _isolated_runner_session(monkeypatch):
    """Each case models one runner process and leaves no atexit target."""
    monkeypatch.setattr(R, "_RTL_SESSION_OWNED", False)
    monkeypatch.setattr(R, "_RTL_SESSION_PROJECT", None)


def _declare(project: Path, body: str = DECLARED) -> None:
    tb = project / "phase2" / "stage1" / "tb"
    tb.mkdir(parents=True, exist_ok=True)
    (tb / "tb_top.v").write_text(body)


# ── the four drivers, each entering ONE emit path for real ──────────────────







#: (id, driver). Each id names the emit path the driver actually enters.
PATHS = [
    ("_try_deterministic_rtl_dispatch", _drive_dispatch),
    ("_try_canonical_primitive_rtl", _drive_canonical),
    ("_try_phase1_behavioral_fsm_rtl_bound", _drive_behavioral),
]








def test_a_candidate_that_states_its_own_unit_is_not_stamped_twice(tmp_path):
    """`_state_declared_timescale` is v1.18.7's, and this pins that the shared
    plumbing did not change what it does."""
    project = tmp_path / "proj"
    project.mkdir()
    _declare(project, "`timescale 10ps / 1ps\nmodule tb; endmodule\n")
    own = "`timescale 1ns/1ps\nmodule m; endmodule\n"
    stamped, ev, extras = R._emit_states_declared_timescale(project, own)
    assert stamped == own
    assert extras["declared_timescale"] == "10ps/1ps"
    assert "10ps/1ps" in ev


def test_disagreeing_declarations_refuse_by_name_and_change_nothing(tmp_path):
    project = tmp_path / "proj"
    project.mkdir()
    _declare(project, "`timescale 1ns / 1ps\nmodule a; endmodule\n")
    (project / "phase2" / "stage1" / "tb" / "tb_b.v").write_text(
        "`timescale 10ps / 1ps\nmodule b; endmodule\n")
    body = "module m; endmodule\n"
    stamped, _ev, extras = R._emit_states_declared_timescale(project, body)
    assert stamped == body
    assert extras["timescale_refusal"].startswith(
        "RTL_TIMESCALE_DECLARATIONS_DISAGREE")


# ── the restore site: the digest recorded is the digest of the STAMPED bytes ──



# ── the structural guard: a path added LATER cannot silently go unstamped ────

def _candidate_writers(tree: ast.AST):
    """Every top-level function that WRITES THE GENERATED CANDIDATE TEXT, and
    whether it states the unit first.

    Keyed on the act, not on a list of names a reader must maintain: a function
    qualifies when it hands the fd-bound publisher its bytes, or when it writes
    the variable holding the generated RTL straight to disk (the one direct
    writer, `_try_spec_artifact_registry_rtl`). Derived from the tree.
    """
    out = {}
    for node in ast.walk(tree):
        if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        if node.name == "_publish_phase1_rtl_no_clobber":
            continue
        names = {n.func.id for n in ast.walk(node)
                 if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
        writes = "_publish_phase1_rtl_no_clobber" in names
        if not writes:
            for n in ast.walk(node):
                if (isinstance(n, ast.Call)
                        and isinstance(n.func, ast.Attribute)
                        and n.func.attr == "write_text"
                        and len(n.args) == 1
                        and isinstance(n.args[0], ast.Name)
                        and n.args[0].id == "rtl"):
                    writes = True
                    break
        if writes:
            out[node.name] = "_emit_states_declared_timescale" in names
    return out


def test_every_function_that_publishes_a_candidate_states_its_unit_first():
    """The census, by MEMBERSHIP. This is what makes the fix survive: a sixth
    emit path added next year is red the day it is added, without anyone
    remembering #2053. It is keyed on the ACT of writing the candidate, so a new
    path cannot be added outside the population."""
    tree = ast.parse((_PROGRAMS / "design_one_shot_runner.py").read_text())
    states = _candidate_writers(tree)
    # The population itself is asserted, so a refactor that empties it goes RED
    # rather than vacuously green.
    assert set(states) == {
        "_try_spec_artifact_registry_rtl",
        "_try_deterministic_rtl_dispatch",
        "_try_canonical_primitive_rtl",
        "_try_phase1_behavioral_fsm_rtl_bound",
    }, sorted(states)
    unstamped = sorted(n for n, ok in states.items() if not ok)
    assert unstamped == [], (
        f"these emit paths publish a candidate without stating the declared "
        f"time unit: {unstamped}")


def test_the_alias_wrapper_writer_is_an_examined_exclusion_not_an_oversight():
    """`step_leaf_typo_aliases` also writes a `.v` into rtl/, and it is NOT in
    the population above. That is a decision, recorded here so it is auditable
    rather than an artefact of how the census happens to be keyed.

    It writes an ALIAS WRAPPER — a module that instantiates the leaf — not a
    generated candidate, and `leaf_typo_alias_emit.emit_alias_wrapper` produces
    no delay control. #2053 is about a file whose behaviour is defined by DELAY
    CONTROLS being read in a unit it did not declare; a wrapper with no delay
    has no such behaviour to misread, and a source that declares no unit imposes
    none on the files around it. If that emitter ever grows a delay, this test
    is the place the question gets asked again.
    """
    import leaf_typo_alias_emit as _lta
    wrapper = _lta.emit_alias_wrapper(
        "modul_a", "module_a",
        [("input", "", "clk"), ("output", "", "q")])
    # comments stripped first: the emitter's own prose cites issue #517, and a
    # `#` in a comment is not a delay control. This asks about the CODE.
    code = _lta._strip_comments(wrapper)
    assert not re.search(r"#\s*[\d(]", code), code
    tree = ast.parse((_PROGRAMS / "design_one_shot_runner.py").read_text())
    assert "step_leaf_typo_aliases" not in _candidate_writers(tree)


def test_the_publisher_is_not_where_the_unit_is_stated():
    """The publisher stays a pure fd-bound byte-mover. If a future edit moves
    the statement into it, the recorded digest stops being the digest of what
    the emitter produced and the restore match above loses its meaning."""
    tree = ast.parse((_PROGRAMS / "design_one_shot_runner.py").read_text())
    pub = next(n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef)
               and n.name == "_publish_phase1_rtl_no_clobber")
    called = {c.func.id for c in ast.walk(pub)
              if isinstance(c, ast.Call) and isinstance(c.func, ast.Name)}
    assert "_emit_states_declared_timescale" not in called
    assert "_state_declared_timescale" not in called
    assert "_project_declared_timescale" not in called
