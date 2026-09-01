"""Two MEASURED defects from one subservient x gf180mcuD acceptance run on
plugin 1.15.36.

D. THE EXPERT-TB CONVENTION WAS UNDISCOVERABLE.
   `cpu_functional_oracle_waiver_check` refuses its capability-gap waiver with
   the instruction "fill ... with the testbench-gen expert fallback and re-run
   Step 4". The mechanism that makes that work already exists and is well
   built: an oracle written to `expert_reference_tb.py` is loaded by
   `professional_tb_gen._load_expert_reference_tb`, promotes the run to
   `dut_kind=expert_reference`, and is deliberately stored apart so
   regeneration cannot erase it.

   But the string `expert_reference_tb` appeared in exactly TWO files -- that
   loader and its own test. No gate message, no skill, no doc named it, while
   the generated scaffold said "fill `reference_model()`" pointing INTO the
   file that Step 4 regenerates. An agent following the only instruction it
   could see wrote a full 7-oracle testbench into `tb_<top>.py` and the next
   Step-4 run deleted it. The instructed repair had no fixed point, and the
   resulting record was indistinguishable from one where no oracle was ever
   written.

C. AN ADVISORY ROW FAILED ITS STEP.
   `flow_compliance_check` failed a step on a refusal from an
   `advisory_program_exit_zero` row, and counted an advisory-declared
   structural gate as a blocking FAIL. An advisory row that fails its step is
   the blocking row under a different name.

ENFORCEMENT: D is documentation-and-message only -- it changes no verdict.
C decides whether a step verdict flips, which is why its tests read REAL
in-repo artefacts (the shipped gate modules and the canonical flow YAML)
rather than fixtures authored beside the fix.

chip-AGNOSTIC: no design, PDK or vendor name appears here.

THE PRE-FIX CONTROL, GRADED (not merely asserted)
=================================================
Run on clean origin/main with the three changed files restored, then graded by
`control_substance_check --junit`:

    12 failed, 2 passed
    6 of 12 reported failures observed a VALUE
    (c) observed value 6   (b) presence-only 5   undecided 1

Read honestly:

  * The 6 substantive failures are the ones that matter -- they read the real
    shipped artefacts (the scaffold body, the skill, the loader source) and
    failed on their CONTENT, not on a missing symbol.
  * The 5 presence-only failures are the `_gate_is_two_source_advisory` tests:
    pre-fix the helper does not exist, so they die on AttributeError. They are
    weaker controls and are reported as such rather than counted as six more.
  * TWO TESTS PASSED ON THE CONTROL AND ARE THEREFORE NOT CONTROLS AT ALL:
    `test_the_loader_requires_an_assertion_and_a_dut_observation` and
    `test_a_promoted_expert_tb_reaches_a_run_kind_the_runner_executes`.
    Both describe behaviour that was ALREADY correct -- the loader and the
    runner needed no change; only the documentation did. They are PINS that
    stop a future edit from quietly removing the mechanism this fix now points
    authors at. They must not be read as evidence that this change works.
"""
import ast
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import professional_tb_gen as PTG  # noqa: E402
import flow_compliance_check as FCC  # noqa: E402

PLUGIN = Path(__file__).resolve().parent.parent.parent
_PTG_SRC = (PLUGIN / "programs" / "professional_tb_gen.py").read_text()
_SKILL = PLUGIN / "skills" / "testbench-gen" / "SKILL.md"
_EXPERT_FILE = "expert_reference_tb.py"
_MARKER = "PROFESSIONAL_TB PASS"


def _loader_src() -> str:
    tree = ast.parse(_PTG_SRC)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and \
                node.name == "_load_expert_reference_tb":
            return ast.get_source_segment(_PTG_SRC, node) or ""
    raise AssertionError("_load_expert_reference_tb not found")


# ─────────────── D. the convention an author must follow is findable ───────
def _generic_scaffold() -> str:
    """The generic scaffold as an author receives it. Synthetic neutral shape:
    no design, PDK or vendor name."""
    return PTG.emit_generic_tb({
        "kind": "generic",
        "top": "dut",
        "ports": [{"name": "d_in", "dir": "input", "width": 8},
                  {"name": "d_out", "dir": "output", "width": 8}],
        "cr": {"clk": "clk", "rst": "rst", "period_ns": 10,
               "active_high": True},
    })


def test_the_scaffold_names_the_file_an_author_must_actually_write():
    """The generated hook is the ONE artefact the author is holding when they
    go looking for where to put an oracle."""
    body = _generic_scaffold()
    assert _EXPERT_FILE in body, (
        "the scaffold does not name expert_reference_tb.py, so the only "
        "discoverable place to write an oracle is the file Step 4 regenerates")


def test_the_scaffold_says_not_to_edit_itself():
    body = _generic_scaffold().lower()
    assert "regenerat" in body, (
        "an author must be told this file is regenerated; without that, "
        "editing it is the obvious and wrong move")


def test_the_skill_the_gate_routes_to_documents_the_convention():
    """`cpu_functional_oracle_waiver_check` routes to the testbench-gen skill
    by name; that skill is where the contract has to be written down."""
    assert _SKILL.is_file(), f"missing {_SKILL}"
    text = _SKILL.read_text()
    assert _EXPERT_FILE in text
    assert _MARKER in text
    assert "TestSkip" in text


def test_the_documented_contract_is_the_one_the_loader_enforces():
    """THE BINDING TEST. Documentation that drifts from the loader is worse
    than none: it sends an author to a file that will be silently rejected.
    Every requirement the skill states must be visibly checked in the loader."""
    loader = _loader_src()
    skill = _SKILL.read_text()
    for requirement, needle in (
            ("the expert file name", _EXPERT_FILE.replace(".py", "")),
            ("the pass marker", _MARKER),
            ("the TestSkip rejection", "TestSkip"),
    ):
        assert needle in loader, (
            f"{requirement} is not enforced by _load_expert_reference_tb")
        assert needle in skill, (
            f"{requirement} is enforced by the loader but undocumented")


def test_the_loader_requires_an_assertion_and_a_dut_observation():
    """The loader's substance rules -- a TB that never reads the DUT, or never
    asserts, is not an oracle. Pinned so a future edit cannot quietly drop
    them and start accepting placeholders."""
    loader = _loader_src()
    assert "ast.Assert" in loader
    assert "cocotb.test" in loader


def test_a_promoted_expert_tb_reaches_a_run_kind_the_runner_executes():
    """The convention is only worth documenting if the promoted kind is one
    the Phase-2 runner actually launches cocotb for."""
    runner = (PLUGIN / "programs" / "design_one_shot_runner.py").read_text()
    assert '"expert_reference"' in runner, (
        "professional_tb_gen promotes a filled hook to dut_kind="
        "expert_reference, but the runner never runs that kind")
    assert "expert_reference" in _PTG_SRC


# ───────────────── C. advisory means advisory (real artefacts) ─────────────
def test_a_two_source_advisory_gate_is_recognised():
    """REAL ARTEFACT: the gate module and the canonical flow, as shipped."""
    assert FCC._gate_is_two_source_advisory(
        "l6_fsm_scaffold_actionable_check"), (
        "this gate's own docstring says `ENFORCEMENT: advisory` and the flow "
        "wires it advisory_program_exit_zero; both sources agree")


def test_a_gate_that_declares_blocking_is_not_downgraded():
    """REAL ARTEFACT, and the load-bearing negative: this gate declares
    'BLOCKS (exit 1)' while the flow wires it advisory. That is a genuine
    disagreement between two authors and must KEEP blocking -- resolving it
    silently is exactly what this predicate must not do."""
    assert not FCC._gate_is_two_source_advisory(
        "l10_test_case_oracle_anchor_check")


def test_prose_discussing_the_token_is_not_a_declaration():
    """REAL ARTEFACT, and a defect this predicate actually had: a first cut
    grepped the whole file, so `flow_compliance_check` matched its OWN prose
    about the convention and would have downgraded the recursive stage audit.
    The declaration must be the module's own docstring."""
    src = (PLUGIN / "programs" / "flow_compliance_check.py").read_text()
    assert "ENFORCEMENT: advisory" in src, (
        "fixture guard: this test is only meaningful while the module still "
        "DISCUSSES the token somewhere outside its own docstring")
    assert not FCC._gate_is_two_source_advisory("flow_compliance_check")


def test_an_unknown_or_malformed_gate_name_is_not_advisory():
    for name in ("", "no_such_gate_at_all", "../etc/passwd", "a b"):
        assert not FCC._gate_is_two_source_advisory(name)


def test_the_structural_denominator_is_not_shrunk():
    """The downgrade must change the VERDICT, never the denominator: dropping
    entries from _STRUCTURAL_RTL_GATES would delete the evidence instead."""
    assert FCC._two_source_advisory_gates() <= set(FCC._STRUCTURAL_RTL_GATES)
    assert len(FCC._STRUCTURAL_RTL_GATES) == len(
        set(FCC._STRUCTURAL_RTL_GATES)), "duplicate gate in the denominator"


def test_the_downgrade_is_narrow():
    """Blast radius is stated, not assumed."""
    downgraded = FCC._two_source_advisory_gates()
    assert len(downgraded) < len(FCC._STRUCTURAL_RTL_GATES) // 10, (
        f"{len(downgraded)} of {len(FCC._STRUCTURAL_RTL_GATES)} structural "
        f"gates downgraded -- too broad to land without a corpus sweep")
    for gate in downgraded:
        assert FCC._gate_is_two_source_advisory(gate)


def test_the_advisory_clause_consults_the_predicate_before_failing_a_step():
    src = (PLUGIN / "programs" / "flow_compliance_check.py").read_text()
    tree = ast.parse(src)
    fn = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            seg = ast.get_source_segment(src, node) or ""
            if "advisory gate refusal" in seg:
                fn = seg
                break
    assert fn, "the advisory-refusal site vanished"
    assert "_gate_is_two_source_advisory" in fn, (
        "an advisory_program_exit_zero row that returns False on a refusal is "
        "the blocking row under another name")


def test_the_refusal_is_still_reported_when_it_is_downgraded():
    """Degrade LOUDLY: downgrading must not silence the finding."""
    src = (PLUGIN / "programs" / "flow_compliance_check.py").read_text()
    i = src.index("advisory gate refusal")
    j = src.index("_gate_is_two_source_advisory", i)
    assert "reasons.append" in src[i:j], (
        "the refusal must be appended to the reasons BEFORE the downgrade, "
        "so a downgraded gate is still named in the report")
