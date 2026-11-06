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
import re
import sys
from pathlib import Path


_PROGRAMS = Path(__file__).resolve().parent.parent
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import design_one_shot_runner as R  # noqa: E402

DECLARED = "`timescale 1ns / 1ps\nmodule tb; endmodule\n"

def _declare(project: Path, body: str = DECLARED) -> None:
    tb = project / "phase2" / "stage1" / "tb"
    tb.mkdir(parents=True, exist_ok=True)
    (tb / "tb_top.v").write_text(body)


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
