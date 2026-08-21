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


# ══════════════════════════════════════════════════════════════════════════
# 2. THE VERDICT LAYER — what the flow's own step evaluator SAYS about the cell
# ══════════════════════════════════════════════════════════════════════════
# The condition layer above proves the predicate. This layer proves the thing
# the predicate is FOR: that a summary reader can tell the two apart. Every
# tree here is BARE — the router file and nothing else — so a step that RUNS
# has nothing to satisfy it and must land on MISSING. That is the shape of the
# original defect stood on its head: 15.5ic on a self tape-out used to report
# SKIPPED-CONDITION (nothing to see) and must now report MISSING (a pad ring
# is owed and is not there).
_NON_SKIP = ("MISSING", "FAIL", "PASS")


@pytest.mark.parametrize("cls,sid", CELLS, ids=[f"{c}::{s}" for c, s in CELLS])
def test_verdict_layer_cell(trees, cls, sid):
    result = FCC.check_step(trees[cls], _path_steps()[sid], {})
    if MATRIX[cls][sid] == RUNS:
        assert not result.status.startswith("SKIPPED"), (
            f"({cls}, {sid}): the step RUNS for this class, and on a tree that "
            f"satisfies none of it the flow reports {result.status!r}. A step "
            f"that is owed and absent must not render as a step that was "
            f"correctly not applicable — that rendering is the entire defect "
            f"class this file exists for.", result.reasons)
        assert result.status in _NON_SKIP, (result.status, result.reasons)
    else:
        assert result.status == SKIPPED, (
            f"({cls}, {sid}): the step is legitimately not applicable to this "
            f"class and the flow reports {result.status!r}", result.reasons)


def test_the_forgotten_route_is_reported_once_by_0_5ic_not_inferred_four_times(
        trees):
    """THE `no_router` ROW, and the claim four step comments rest on.

    15.5ic, 26.5ic, 37.5ic and 37.5ip each say, in almost the same words, that
    the "someone forgot" case is not lost to their silent-skip default because
    "it is 0.5ic never having run, which its own gate refuses". Four steps
    depending on one unwritten assertion is exactly how a defence stops being
    checked. This is that assertion.
    """
    proj = trees["no_router_file_step_0_5ic_never_ran"]
    steps = _path_steps()

    router = FCC.check_step(proj, steps["0.5ic"], {})
    assert router.status == MISSING, (
        "0.5ic carries NO `condition` precisely so that it cannot skip. If it "
        "ever skips, the forgotten-route case becomes four indistinguishable "
        "silences and nothing reports it at all.", router.status, router.reasons)

    for sid in ("15.5ic", "26.5ic", "37.5ic", "37.5ip"):
        assert FCC.check_step(proj, steps[sid], {}).status == SKIPPED, (
            f"{sid} is expected to skip here — the defence is that 0.5ic "
            f"speaks, not that the downstream steps do")


def test_two_router_files_at_once_are_refused_and_the_control_is_not(tmp_path):
    """The other direction, and the `any_of` reading depends on it.

    15.5ic, 26.5ic and 37.5ic all read their condition `any_of` and all three
    justify it with "no tree ever holds both — `tapeout_declaration_check`
    refuses the tree that does". Measured above: a tree that DOES hold both
    makes every path step run at once, chip and IP terminals together. The
    condition layer cannot refuse that (`files_exist` cannot express "and
    not"), so the refusal is owed entirely by 0.5ic's second gate clause.

    THE CONTROL IS THE HALF THAT MAKES THIS A MEASUREMENT. The same tree with
    ONE router file must NOT carry this finding; a refusal that fires on
    everything says as little as one that fires on nothing.
    """
    import tapeout_declaration_check as TDC

    def build(root: Path, *routers) -> Path:
        _base(root, PDK_WITH_SHUTTLE)
        for rel, marker in routers:
            (root / rel).write_text(marker + "\n")
        doc = TD.blank_declaration()
        (root / TD.DECLARATION_REL).write_text(json.dumps(doc, indent=2))
        return root

    SELF = (TD.SELF_TAPEOUT_REL, TD.SELF_TAPEOUT_MARKER)
    NOTMPL = (ST.NO_TEMPLATE_REL, ST.NO_TEMPLATE_MARKER)

    both = build(tmp_path / "both", SELF, NOTMPL)
    one = build(tmp_path / "one", SELF)

    kinds = lambda p: {r["rule"] for r in TDC.evaluate(p)["refusals"]}  # noqa: E731
    assert TDC.RULE_ROUTER_CONTRADICTION in kinds(both), (
        "a tree carrying two mutually exclusive router files selects both "
        "terminals at once; the condition layer cannot see it, so this gate is "
        "the only thing standing between that tree and a chip that is also "
        "an IP", sorted(kinds(both)))
    assert TDC.RULE_ROUTER_CONTRADICTION not in kinds(one), (
        "the control carries ONE router file and must not attract the "
        "contradiction finding", sorted(kinds(one)))


# ══════════════════════════════════════════════════════════════════════════
# 3. THE GATE LAYER — a step whose gate cannot reach a verdict is not a step
# ══════════════════════════════════════════════════════════════════════════
def _gate_commands(sid: str) -> list:
    """The gate command STRINGS this step declares, walked structurally.

    Same walk `flow_compliance_check._evaluate_gate` executes, so a gate shape
    the enforcer would decline to parse is one this list comes back empty for
    — which is itself the finding.
    """
    out = []

    def walk(node):
        if isinstance(node, list):
            for item in node:
                walk(item)
            return
        if not isinstance(node, dict):
            return
        for key in ("all_of", "any_of"):
            sub = node.get(key)
            if isinstance(sub, (list, dict)):
                walk(sub)
        for key in FCC._PROGRAM_GATE_KEYS:
            spec = node.get(key)
            if isinstance(spec, dict):
                spec = spec.get("command")
            if isinstance(spec, str):
                out.append(spec)
    walk(_path_steps()[sid].get("gate"))
    return out


def _run_gate(project: Path, command: str) -> int:
    """Run one declared gate command against a project, and return its rc."""
    import shlex
    import subprocess
    toks = shlex.split(command)
    prog = PROGRAMS / (toks[0] + ".py")
    assert prog.is_file(), f"gate names {toks[0]!r}, which is not a program"
    proc = subprocess.run([sys.executable, str(prog)] + toks[1:],
                          cwd=str(project), capture_output=True, text=True,
                          timeout=600)
    return proc.returncode


@pytest.mark.parametrize("sid", DECLARED_PATH_STEPS)
def test_the_gate_names_a_resolvable_program(sid):
    cmds = _gate_commands(sid)
    assert cmds, f"step {sid} declares no program gate the enforcer can execute"
    for c in cmds:
        import shlex
        assert (PROGRAMS / (shlex.split(c)[0] + ".py")).is_file(), (sid, c)


@pytest.mark.parametrize("cls,sid", CELLS, ids=[f"{c}::{s}" for c, s in CELLS])
def test_no_gate_of_a_running_path_step_passes_on_an_empty_tree(trees, cls, sid):
    """THE VACUOUS-PASS GUARD, per cell.

    Each of these trees carries a router file and NOTHING ELSE: no floorplan,
    no routed DEF, no GDS, no hardmacro kit, no declaration. A gate that exits
    0 here has passed a design it could not have examined, and every downstream
    reader would see a step that ran and was satisfied.

    rc 1 (a finding) and rc 2 (`[CANNOT CHECK]`) are both acceptable answers —
    they are different answers and the flow reads them differently. rc 0 is
    not an answer at all.
    """
    if MATRIX[cls][sid] != RUNS:
        pytest.skip("cell does not run for this class; covered by the "
                    "condition and verdict layers")
    for command in _gate_commands(sid):
        rc = _run_gate(trees[cls], command)
        assert rc != 0, (
            f"({cls}, {sid}): `{command}` exited 0 on a tree carrying only a "
            f"router file. A gate that passes what it cannot have looked at is "
            f"the vacuous pass this campaign exists to refuse.")


# --------------------------------------------------------------------------- #
# RED REACHABILITY — "a path-specific step that can only ever SKIP is not a step"
# --------------------------------------------------------------------------- #
# The vacuous-pass guard above proves no gate says YES about nothing. This
# proves the other end: each gate can say NO — rc 1, a finding about the
# silicon — rather than only ever rc 2, `[CANNOT CHECK]`. A gate stuck on rc 2
# is the same defect as a step stuck on SKIP, one layer down: `pad_ring_gen`
# could only ever take its SKIP branch for a year because the input it reads
# had no producer, and nothing in the flow could say so.
#
# The RED input is CONSTRUCTED per step, and each one is the smallest tree that
# makes that gate report a finding rather than an inability.
def _red_0_5ic(root: Path) -> Path:
    return _self_tapeout(root, PDK_WITHOUT_SHUTTLE)


def _red_15_5ic(root: Path) -> Path:
    return _self_tapeout(root, PDK_WITHOUT_SHUTTLE)


def _red_26_5ic(root: Path) -> Path:
    """A producer report that says the seal ring FAILED.

    The gate RE-REPORTS what `die_finishing_gen` measured and never opens a
    layout, so the seal-ring refusal is reachable only through the producer's
    own document — which is the producer/auditor split working, not a fixture
    shortcut. The `producer` attribution is included because the gate refuses
    an unattributed document, and a fixture that skipped it would prove the
    attribution check rather than the seal-ring one.
    """
    _self_tapeout(root, PDK_WITHOUT_SHUTTLE)
    rep = root / "reports/phase3/die_finishing.json"
    rep.parent.mkdir(parents=True, exist_ok=True)
    rep.write_text(json.dumps({
        "producer": "die_finishing_gen",
        "seal_ring": {"state": "FAIL",
                      "reason": "the generator left no ring geometry behind"},
        "die_id": {"state": "NOT_APPLICABLE",
                   "reason": "not a chip-on-board submission"}}, indent=2))
    return root


def _red_37_5ic(root: Path) -> Path:
    return _self_tapeout(root, PDK_WITHOUT_SHUTTLE)


def _red_37_5ip(root: Path) -> Path:
    """Three of the four views. The kit is delivered so somebody else can
    place, time, simulate and stream the macro; a missing view is the one
    thing they cannot do, and it is a finding about the deliverable rather
    than an inability to look."""
    _ip(root, PDK_WITH_SHUTTLE)
    h = root / "phase3" / "stage4" / "hardmacro"
    h.mkdir(parents=True, exist_ok=True)
    (h / "macro_top.lef").write_text("MACRO macro_top\n  SIZE 10 BY 10 ;\n"
                                     "END macro_top\n")
    (h / "macro_top.lib").write_text("library(k){cell(macro_top){}}\n")
    (h / "macro_top.v").write_text("module macro_top(); endmodule\n")
    return root


RED_INPUT = {
    "0.5ic": _red_0_5ic,
    "15.5ic": _red_15_5ic,
    "26.5ic": _red_26_5ic,
    "37.5ic": _red_37_5ic,
    "37.5ip": _red_37_5ip,
}


@pytest.mark.parametrize("sid", DECLARED_PATH_STEPS)
def test_the_gate_of_every_path_step_can_reach_a_RED_verdict(tmp_path, sid):
    assert set(RED_INPUT) == set(DECLARED_PATH_STEPS), (
        "a path step with no constructed RED input is a step nobody has shown "
        "can refuse anything", sorted(RED_INPUT))
    proj = RED_INPUT[sid](tmp_path / "red")
    rcs = {c: _run_gate(proj, c) for c in _gate_commands(sid)}
    assert 1 in rcs.values(), (
        f"step {sid}: no declared gate command reached rc 1 on an input built "
        f"to be refused. rc 2 is `[CANNOT CHECK]` and rc 0 is a pass; a gate "
        f"that can produce neither a finding is a gate that can only ever "
        f"skip, and a step whose gate can only skip is not a step.", rcs)


# ══════════════════════════════════════════════════════════════════════════
# 4. WHAT THE MATRIX MEASURED AND COULD NOT SETTLE
# ══════════════════════════════════════════════════════════════════════════
def test_the_flow_cannot_tell_a_self_tapeout_from_an_unfetched_shuttle(trees):
    """MEASURED, and it is why two rows of this matrix are byte-identical.

    The brief names "self tape-out, PDK ships one" and "shuttle chip, template
    NOT fetched" as two classes. The flow has ONE artefact for both: a chip
    with no ingested slot geometry gets `SELF_TAPEOUT.txt` from
    `tapeout_declaration_gen` whatever it intended, because `route_of` reads
    `has_slots` and the declared `deliverable` and there is no 19th question
    asking which operator, if any, this design is submitting to.

    Pinned rather than asserted-away: if a submission-target answer is ever
    added, this test goes red and the two rows become genuinely different
    classes — which is the correct outcome, not a regression.
    """
    a = trees["self_tapeout_pdk_ships_a_shuttle"]
    b = trees["shuttle_chip_template_not_fetched"]
    for rel in (TD.SELF_TAPEOUT_REL, ST.NO_TEMPLATE_REL):
        assert (a / rel).is_file() == (b / rel).is_file(), rel
    assert "submission_target" not in TD.blank_declaration()["answers"], (
        "a declared submission target would let 37.5ic's operator arm tell "
        "'there is no operator to ask' from 'we never went and asked'; this "
        "test is the record that it does not exist yet")


def test_a_self_tapeout_on_a_shuttle_pdk_is_refused_at_37_5ic(tmp_path):
    """THE CONSEQUENCE OF THE ABOVE, measured end to end, and REPORTED rather
    than fixed.

    `tapeout_precheck.operator_arm_applicability` decides the operator arm from
    two facts — the PDK's registry entry and whether slot geometry was fetched
    — and never from the ROUTER FILE, although the flow has a canonical route
    predicate (`_tapeout_declaration.route_of`) and `tapeout_declaration_gen`
    writes into `SELF_TAPEOUT.txt`, verbatim, that "the operator's own
    container is the arm it does not get, because there is no operator".

    So a die taping ITSELF out on a PDK some operator happens to serve is
    NOT_DETERMINED at 37.5ic — for a template it was never going to fetch —
    and NOT_DETERMINED exits 1. Our own ladder is stubbed ALL GREEN here, so
    the refusal is attributable to the missing arm and to nothing else.

    THIS TEST DOES NOT CALL THAT A BUG, AND DELIBERATELY SO. Reading the router
    file would close it, and would also make a design that genuinely INTENDED
    the shuttle and forgot to fetch read as "one fewer arm" — a silence, which
    is the disease. The honest remedy is a declared submission target, which is
    a structural change to the declaration and the flow owner's call. What this
    test guarantees meanwhile is that the behaviour cannot change in either
    direction without somebody saying so here.
    """
    import general_precheck as GP
    import tapeout_precheck as TP

    proj = _self_tapeout(tmp_path / "proj", PDK_WITH_SHUTTLE)
    assert (proj / TD.SELF_TAPEOUT_REL).is_file()
    assert TRC.shuttle_for_pdk(PDK_WITH_SHUTTLE) is not None, (
        "this test needs a PDK the registry names a LIVE shuttle for; if the "
        "registry changed, pick another rather than deleting the case")

    def all_green(cmd, timeout):
        out = Path(cmd[cmd.index("--json") + 1])
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps({
            "verdict": GP.PASS, "reason": "stubbed green",
            "steps": [{"step_id": s.step_id, "label": s.step_id,
                       "verdict": GP.PASS, "evidence": "stub"}
                      for s in GP.LADDER]}, indent=2))
        return 0, "", ""

    rep = TP.evaluate(proj, timeout=120.0, runner=all_green)
    operator = next(a for a in rep.arms if a.arm == "operator")

    assert operator.state == TP.NOT_DETERMINED, operator.reason
    assert "never fetched" in operator.reason
    assert rep.verdict != TP.PASS, (
        "measured 2026-08-21: a self tape-out on a shuttle-served PDK cannot "
        "reach PASS at 37.5ic under any input, because the arm it is refused "
        "for is one it declared it does not have")


def test_the_route_predicate_exists_and_the_operator_arm_does_not_consult_it():
    """The other half of the same measurement, stated where a reader will find
    it: the flow HAS the answer, and this arm asks a different question.

    `route_of` is the flow's own three-way router. If `tapeout_precheck` ever
    starts consulting it, this test goes red and the case above must be
    re-decided — which is exactly when somebody should look at it.
    """
    import tapeout_precheck as TP

    assert TD.route_of({"answers": {"deliverable": TD.DELIVERABLE_DIE}},
                       has_slots=False) == TD.ROUTE_SELF_TAPEOUT
    src = (PROGRAMS / "tapeout_precheck.py").read_text()
    body = src[src.index("def operator_arm_applicability"):]
    body = body[:body.index("\n\ndef ")]
    assert "route_of" not in body and "SELF_TAPEOUT" not in body, (
        "the operator arm now reads the route; re-decide "
        "test_a_self_tapeout_on_a_shuttle_pdk_is_refused_at_37_5ic")
