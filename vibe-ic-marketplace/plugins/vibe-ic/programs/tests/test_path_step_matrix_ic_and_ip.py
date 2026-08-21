#!/usr/bin/env python3
"""The two terminal paths — CHIP/IC and CELL/IP — as a DESIGN CLASS x PATH STEP matrix.

WHY A SUITE OF ITS OWN, AND WHY IT LOOKS LIKE THIS
--------------------------------------------------
Every defect measured in this area was a CONDITION mistake, never a logic
mistake — a step conditioned on the wrong thing, so it silently skipped for a
whole class of design:

  * 15.5ic (pad ring) and 26.5ic (seal ring + die id) were conditioned on the
    shuttle OPERATOR's template, so a die taping itself out shipped with
    neither;
  * `phase3/stage3/pnr/pad_assignment.json` had NO PRODUCER, so 15.5ic could
    only ever take `pad_ring_gen`'s SKIP branch — on the shuttle path too;
  * `37.5self` existed as a THIRD route, so a design routed to one authority
    was never shown the other.

A skipped step and a passed step look the same in a summary. That is the whole
problem and it is what this file exists to make impossible.

THE ONE METHOD RULE
-------------------
Every cell is decided by driving the FLOW'S OWN PREDICATES over a real project
tree — `flow_compliance_check._check_condition` for the condition layer and
`flow_compliance_check.check_step` for the verdict layer. Nothing here reads
the yaml and asserts what it thinks it says. That distinction is not
stylistic: `test_pad_and_seal_ring_on_the_chip_path.py` asserts the condition's
TEXT, which pins the two steps' spelling to each other and to 37.5ic's, and a
condition can be spelled identically on all three and still be WRONG for a
class of design. Only running it on a tree of that class can say.

THE THREE STATES, AND THE ONE THAT MUST NEVER BE CONFUSED
---------------------------------------------------------
Each (class, step) cell resolves to exactly one of:

  RUNS               the condition is met; the step is the design's to satisfy
  SKIPPED-CONDITION  the condition is legitimately unmet for this class
  MISSING            nobody wired it, or it ran and produced nothing

MISSING MUST NEVER READ AS SKIPPED-CONDITION. A step absent because nobody
wired it is a defect; a step skipped because its condition is legitimately
unmet is correct; every summary that has ever hidden this class of bug hid it
by rendering the two the same. `_state()` below therefore reports MISSING for a
step id the flow does not carry at all, and the verdict layer asserts that a
cell that should RUN lands on MISSING/FAIL on a bare tree — never on a skip.
"""
from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

import _submission_template as ST          # noqa: E402
import _tapeout_declaration as TD          # noqa: E402
import flow_compliance_check as FCC        # noqa: E402
import tapeout_readiness_check as TRC      # noqa: E402

PLUGIN = PROGRAMS.parent
FLOW = PLUGIN / "flow" / "phase1_phase2_phase3.yaml"

# The three states. Named rather than spelled inline so a cell can never be
# written with a typo that quietly matches nothing.
RUNS = "RUNS"
SKIPPED = "SKIPPED-CONDITION"
MISSING = "MISSING"


# --------------------------------------------------------------------------- #
# The step set is DERIVED, never re-typed
# --------------------------------------------------------------------------- #
def _steps():
    yaml = pytest.importorskip("yaml")
    return yaml.safe_load(FLOW.read_text())["steps"]


def _path_steps() -> dict:
    """Every path-specific step the flow declares, keyed by id.

    DERIVED FROM THE FLOW, so a SIXTH path step added tomorrow arrives in this
    matrix as a cell nobody has an expectation for — which reddens
    `test_the_matrix_covers_every_path_step_the_flow_declares` — instead of
    being covered by a hardcoded list of five that silently stops describing
    the flow. That failure mode is the same one this whole file is about, one
    level up.
    """
    return {str(s["id"]): s for s in _steps()
            if str(s["id"]).endswith(("ic", "ip"))}


#: The five the brief names, and the ones the matrix carries expectations for.
#: This is the EXPECTATION side; `_path_steps()` is the OBSERVED side, and the
#: test that compares them is what makes a new path step visible.
DECLARED_PATH_STEPS = ("0.5ic", "15.5ic", "26.5ic", "37.5ic", "37.5ip")


# --------------------------------------------------------------------------- #
# The design classes — one tree-builder each
# --------------------------------------------------------------------------- #
#: A PDK the shuttle registry names a LIVE operator precheck for, and one it
#: names none for. Both read LIVE off the registry by the assertions below, so
#: a registry change reaches this file rather than leaving it describing an
#: older world.
PDK_WITH_SHUTTLE = "gf180mcuD"
PDK_WITHOUT_SHUTTLE = "ihp-sg13g2"


def _base(root: Path, pdk: str) -> Path:
    (root / ST.INGEST_DIR_REL).mkdir(parents=True, exist_ok=True)
    (root / "input").mkdir(parents=True, exist_ok=True)
    (root / "input" / "project.json").write_text(json.dumps({"pdk": pdk}))
    return root


def _self_tapeout(root: Path, pdk: str) -> Path:
    _base(root, pdk)
    (root / TD.SELF_TAPEOUT_REL).write_text(TD.SELF_TAPEOUT_MARKER + "\n")
    return root


def _shuttle_fetched(root: Path, pdk: str) -> Path:
    _base(root, pdk)
    d = root / ST.SLOTS_DIR_REL
    d.mkdir(parents=True, exist_ok=True)
    (d / "1x1.yaml").write_text("SLOT: 1x1\nDIE_AREA: [0, 0, 100.0, 80.0]\n")
    return root


def _ip(root: Path, pdk: str) -> Path:
    _base(root, pdk)
    (root / ST.NO_TEMPLATE_REL).write_text(ST.NO_TEMPLATE_MARKER + "\n")
    return root


def _no_router(root: Path, pdk: str) -> Path:
    """0.5ic NEVER RAN. No router file of any kind.

    This is the "someone forgot" class, and the flow's stated defence against
    it is that 0.5ic's own gate refuses rather than leaving the absence to be
    inferred from four downstream skips. That defence is a claim, so it is
    tested here rather than believed.
    """
    return _base(root, pdk)


def _two_routers(root: Path, pdk: str) -> Path:
    """A tree carrying TWO mutually exclusive router files at once.

    Three separate step comments assert "no tree ever holds both", and the
    `any_of` reading of 15.5ic / 26.5ic / 37.5ic's condition is only sound
    BECAUSE of that. A tree that holds both makes every path step run at once,
    chip and IP terminals together, which is not a design any silicon
    corresponds to. `tapeout_declaration_check` is named as the refusal; that
    is what this class exists to drive.
    """
    _base(root, pdk)
    (root / TD.SELF_TAPEOUT_REL).write_text(TD.SELF_TAPEOUT_MARKER + "\n")
    (root / ST.NO_TEMPLATE_REL).write_text(ST.NO_TEMPLATE_MARKER + "\n")
    return root


#: class name -> (builder, pdk). The two shuttle-PDK self classes are BOTH
#: kept even though their trees are byte-identical: see
#: `test_the_flow_cannot_tell_a_self_tapeout_from_an_unfetched_shuttle`, which
#: is the measured statement of why, and which would be unwritable if the
#: matrix collapsed them.
CLASSES = {
    "self_tapeout_pdk_ships_no_shuttle":  (_self_tapeout, PDK_WITHOUT_SHUTTLE),
    "self_tapeout_pdk_ships_a_shuttle":   (_self_tapeout, PDK_WITH_SHUTTLE),
    "shuttle_chip_template_fetched":      (_shuttle_fetched, PDK_WITH_SHUTTLE),
    "shuttle_chip_template_not_fetched":  (_self_tapeout, PDK_WITH_SHUTTLE),
    "ip_hardmacro":                       (_ip, PDK_WITH_SHUTTLE),
    "no_router_file_step_0_5ic_never_ran": (_no_router, PDK_WITH_SHUTTLE),
    "two_router_files_at_once":           (_two_routers, PDK_WITH_SHUTTLE),
}


#: THE MATRIX. Every (class, step) cell states the step's condition-layer state
#: EXPLICITLY. There is no default and no wildcard: a cell nobody wrote is a
#: KeyError, not a silent pass.
MATRIX = {
    # 0.5ic has NO condition on purpose — it is the step that DECIDES the
    # route, so it is the one step every design passes through, including the
    # design that has no route yet.
    "self_tapeout_pdk_ships_no_shuttle": {
        "0.5ic": RUNS, "15.5ic": RUNS, "26.5ic": RUNS,
        "37.5ic": RUNS, "37.5ip": SKIPPED},
    "self_tapeout_pdk_ships_a_shuttle": {
        "0.5ic": RUNS, "15.5ic": RUNS, "26.5ic": RUNS,
        "37.5ic": RUNS, "37.5ip": SKIPPED},
    "shuttle_chip_template_fetched": {
        "0.5ic": RUNS, "15.5ic": RUNS, "26.5ic": RUNS,
        "37.5ic": RUNS, "37.5ip": SKIPPED},
    "shuttle_chip_template_not_fetched": {
        "0.5ic": RUNS, "15.5ic": RUNS, "26.5ic": RUNS,
        "37.5ic": RUNS, "37.5ip": SKIPPED},
    # An IP is placed inside somebody else's die: no die edge, so no pad ring,
    # no seal ring, no tape-out precheck of its own. Three legitimate skips.
    "ip_hardmacro": {
        "0.5ic": RUNS, "15.5ic": SKIPPED, "26.5ic": SKIPPED,
        "37.5ic": SKIPPED, "37.5ip": RUNS},
    # THE DANGEROUS ROW. Every path step skips, and each skip is individually
    # indistinguishable from a legitimate one. What must hold is that 0.5ic —
    # the unconditioned router — does NOT skip, so the absence is reported once
    # rather than inferred four times.
    "no_router_file_step_0_5ic_never_ran": {
        "0.5ic": RUNS, "15.5ic": SKIPPED, "26.5ic": SKIPPED,
        "37.5ic": SKIPPED, "37.5ip": SKIPPED},
    # THE OTHER DANGEROUS ROW, and it is dangerous in the opposite direction:
    # every terminal runs at once. The condition layer cannot refuse it —
    # `files_exist` cannot express "and not" — so the refusal must come from
    # 0.5ic's gate, which the verdict layer below pins.
    "two_router_files_at_once": {
        "0.5ic": RUNS, "15.5ic": RUNS, "26.5ic": RUNS,
        "37.5ic": RUNS, "37.5ip": RUNS},
}

CELLS = [(cls, sid) for cls in CLASSES for sid in DECLARED_PATH_STEPS]


@pytest.fixture(scope="module")
def trees(tmp_path_factory):
    out = {}
    for name, (build, pdk) in CLASSES.items():
        out[name] = build(tmp_path_factory.mktemp(name[:24]) / "proj", pdk)
    return out


# --------------------------------------------------------------------------- #
# The state resolver — the flow's predicate, never our reading of the yaml
# --------------------------------------------------------------------------- #
def _state(project: Path, sid: str) -> str:
    """The condition-layer state of one step for one project.

    MISSING here means the flow does not carry the step AT ALL. It is returned
    as its own value and never folded into SKIPPED-CONDITION, because a step
    nobody wired and a step legitimately skipped are the two facts this whole
    file exists to keep apart.
    """
    step = _path_steps().get(sid)
    if step is None:
        return MISSING
    cond = step.get("condition")
    if cond and not FCC._check_condition(project, cond):
        kind = step.get("condition_kind", "design_dependent")
        return ("SKIPPED-SETUP-REQUIRED" if kind == "setup_required"
                else SKIPPED)
    return RUNS


# ══════════════════════════════════════════════════════════════════════════
# 0. THE MATRIX IS COMPLETE — no path step is outside it
# ══════════════════════════════════════════════════════════════════════════
def test_the_matrix_covers_every_path_step_the_flow_declares():
    """A sixth path step must arrive as a red cell, not as silence."""
    observed = set(_path_steps())
    assert observed == set(DECLARED_PATH_STEPS), (
        "the flow's path-specific steps and this matrix's rows disagree; a "
        "path step outside the matrix is exactly the silent-absence failure "
        "this file exists to prevent",
        sorted(observed), sorted(DECLARED_PATH_STEPS))


def test_every_class_states_every_cell():
    for cls in CLASSES:
        assert set(MATRIX[cls]) == set(DECLARED_PATH_STEPS), (
            f"class {cls} does not state every path step; a cell with no "
            f"stated expectation is not a covered cell",
            sorted(MATRIX[cls]))


def test_a_step_the_flow_does_not_carry_reads_MISSING_and_never_a_skip(trees):
    """THE LOAD-BEARING DISCRIMINATOR, proved on a step id nobody wired.

    `37.5self` is the retired third route. It is not in the flow, and asking
    for its state must produce MISSING — the answer for "nobody wired it" —
    and must not produce SKIPPED-CONDITION, the answer for "correctly not
    applicable". If this resolver ever conflated them, every other assertion
    in this file would be reading a summary that cannot tell a defect from
    correct behaviour.
    """
    proj = trees["self_tapeout_pdk_ships_no_shuttle"]
    assert "37.5self" not in _path_steps(), (
        "37.5self was retired into 37.5ic as an ARM; if it is back as a step, "
        "the three-route defect it caused is back with it")
    assert _state(proj, "37.5self") == MISSING
    assert _state(proj, "37.5self") != SKIPPED


# ══════════════════════════════════════════════════════════════════════════
# 1. THE CONDITION LAYER — every cell, driven through the flow's predicate
# ══════════════════════════════════════════════════════════════════════════
@pytest.mark.parametrize("cls,sid", CELLS, ids=[f"{c}::{s}" for c, s in CELLS])
def test_condition_layer_cell(trees, cls, sid):
    expected = MATRIX[cls][sid]
    got = _state(trees[cls], sid)
    assert got == expected, (
        f"({cls}, {sid}): the flow's own condition predicate says {got}, the "
        f"matrix says {expected}. One of the two is wrong and the difference "
        f"is a whole class of design silently skipping a step or running one "
        f"it must not.")
