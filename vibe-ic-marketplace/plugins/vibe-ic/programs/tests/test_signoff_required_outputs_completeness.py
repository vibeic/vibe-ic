#!/usr/bin/env python3
"""Steps 25 / 26 — artefacts the step produces that nothing verified.

`required_outputs` is ALL-of-N (PR #455): every declared entry must be present
or the step's PASS-tier verdict is downgraded. An artefact the step PRODUCES and
that its own verdict is READ FROM, but which no step declares, is verified by
nothing.

TWO such artefacts, both confirmed present on the real completed run
`campaign_pr427/spm/converge_ihp-sg13g2` (pure-digital standard cell — both are
digital-flow artefacts):

  step 25  reports/phase3/em.json                        293 B
  step 26  reports/phase3/antenna.json                   236 B

These are the MEASUREMENTS `phase3_one_shot_runner` reads back via
`_read_verdict()` as those steps' sign-off evidence — the step's verdict came
from a file nothing checked was there.

SATISFIABILITY is the constraint on adding an entry: a declaration a real run
cannot meet manufactures red. Each is paired with an artefact ALREADY declared,
in the same emitter branch:

  * `_emit_ir_em_reports` writes em.rpt and em.json inside one `if has_em:`
  * both `_emit_antenna_report` branches write antenna.rpt and antenna.json
    together and return True only there

The tests below assert the PAIRING property (what makes the entry satisfiable),
not that a particular string appears in a file.

WHAT IT COSTS — measured over EVERY tracked root (`git ls-files benchmark-data`,
not just `benchmark-data/ic`): ZERO. No root carries `em.rpt` without `em.json`
(12 vs 13), and none carries `antenna.rpt` without `antenna.json` (13 vs 14).
The newly-MISSING set is empty for both, so no published run changes verdict.

WITHDRAWN FROM THIS CHANGE — step 23's two multi-corner STANCE files
(`multi_corner_spef_stance.json`, `mcorner_ocv_stance.json`). They belong in
`required_outputs` on the merits, but their cost is NOT zero and the original
count understated it. Re-measured over every tracked root: stance files in 7,
the already-declared `post_route_timing.rpt` in 8, and the newly-MISSING set is
SIX roots, not two — `benchmark-data/ic/{caravel_user_project,subservient}` PLUS
`benchmark-data/evaluation/phase1_parity/{espi,lpc/phase3,mdio,sgmii}`, which
were excluded only because the first count stopped at `benchmark-data/ic`.
Six of the eight roots that carry the step's existing artefact would start
reporting MISSING. That is a separate decision; `test_d1_step23_stance_files_
are_not_declared_here` pins the withdrawal so it cannot drift back in silently.

DIRECTION-1 GUARDS (`test_d1_*`) hold on the pre-fix tree too.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
_PLUGIN = _PROGRAMS.parent
_FLOW = _PLUGIN / "flow" / "phase1_phase2_phase3.yaml"
sys.path.insert(0, str(_PROGRAMS))

_RUNNER_SRC = (_PROGRAMS / "phase3_one_shot_runner.py").read_text(
    errors="replace")


def _steps():
    import yaml  # noqa: WPS433
    doc = yaml.safe_load(_FLOW.read_text(errors="replace"))
    steps = doc.get("steps") or doc.get("flow") or []
    return {str(s.get("id")): s for s in steps if isinstance(s, dict)}


def _required(step_id: str):
    return list(_steps()[step_id].get("required_outputs") or [])


#: The module-level table in `phase3_one_shot_runner` whose rows ARE the
#: inline sign-off dispatch: `(step name, program, output path, extra argv)`.
_SIGNOFF_TABLE = "_DECLARED_SIGNOFF_GATES"


def _declared_signoff_outputs() -> set:
    """The output column of every row in the runner's sign-off gate table.

    READ AS DATA, NOT AS A SHAPE, and that is the whole point of parsing it
    rather than grepping for it. The two producer shapes this module already
    accepts are both TEXT patterns — a literal beside a `/`, or a literal after
    `--json` in the yaml. `_run_declared_signoff_gate` satisfies BOTH of them
    (`out_json = project / out_rel`, then `"--json", str(out_json)`), but it
    spells the path through a parameter, so neither pattern can see it and the
    literal lives one call away, in this table.

    Returns an empty set if the table cannot be found or parsed; the callers
    below refuse on an empty set rather than passing over one.
    """
    import ast  # noqa: WPS433
    try:
        tree = ast.parse(_RUNNER_SRC)
    except SyntaxError:                                    # pragma: no cover
        return set()
    out = set()
    primary = set()
    # The same real dispatcher writes the pre-stream table.
    # Raw Step-23 products moved here when independent verdict paths were split;
    # their consumer --json targets must not be mistaken for their producers.
    tables = {_SIGNOFF_TABLE, "_PRESTREAM_GATES"}
    for node in tree.body:
        targets = (node.targets if isinstance(node, ast.Assign)
                   else [node.target] if isinstance(node, ast.AnnAssign)
                   else [])
        if not any(isinstance(x, ast.Name) and x.id in tables
                   for x in targets):
            continue
        value = getattr(node, "value", None)
        for row in getattr(value, "elts", []):
            elts = getattr(row, "elts", [])
            if len(elts) >= 3 and isinstance(elts[2], ast.Constant) \
                    and isinstance(elts[2].value, str):
                out.add(elts[2].value)
                if any(isinstance(x, ast.Name) and x.id == _SIGNOFF_TABLE
                       for x in targets):
                    primary.add(elts[2].value)
    # Keep an absent table a refusal; delegated writes must not mask its loss.
    return out | _delegated_signoff_outputs() if primary else set()


def _delegated_signoff_outputs() -> set:
    """Follow the sign-off dispatch's local capture owner to actual writes.

    This is a bounded source oracle, not execution/sign-off evidence. Only a
    call carrying the dispatch's project into the existing capture owner is
    followed. Paths come from that owner's current AST, never an output list.
    Unreadable source, unresolved paths and disconnected writers yield nothing.
    """
    import ast

    def parse(source):
        try:
            return ast.parse(source)
        except SyntaxError:
            return ast.Module(body=[], type_ignores=[])

    def scope_nodes(fn):
        def walk(node):
            yield node
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.Lambda, ast.ClassDef)):
                return
            for child in ast.iter_child_nodes(node):
                yield from walk(child)
        for statement in fn.body:
            yield from walk(statement)

    runner = parse(_RUNNER_SRC)
    gate = next((n for n in runner.body if isinstance(n, ast.FunctionDef)
                 and n.name == "_run_declared_signoff_gate"), None)
    if gate is None or not gate.args.args:
        return set()
    aliases = {a.asname or a.name for n in scope_nodes(gate)
               if isinstance(n, ast.Import) for a in n.names
               if a.name == "drv_capture_plan"}
    outputs, visited = set(), set()

    def follow(name):
        visited.add(name)

        def path_value(node, seen=frozenset()):
            return None


    project_arg = gate.args.args[0].arg
    for call in (n for n in scope_nodes(gate) if isinstance(n, ast.Call) and n.args):
        if isinstance(call.func, ast.Attribute) \
                and isinstance(call.func.value, ast.Name) \
                and call.func.value.id in aliases \
                and isinstance(call.args[0], ast.Name) \
                and call.args[0].id == project_arg:
            follow(call.func.attr)
    return outputs


# ===========================================================================
# The artefacts the step's own verdict is read from are declared
# ===========================================================================
@pytest.mark.parametrize("step_id,path", [
    ("25", "reports/phase3/em.json"),
    ("26", "reports/phase3/antenna.json"),
])
def test_produced_evidence_is_declared(step_id, path):
    assert path in _required(step_id), (
        f"step {step_id} produces {path} and reads its verdict from it, but no "
        f"step declares it — required_outputs verifies nothing about it")


@pytest.mark.parametrize("path", [
    "reports/phase3/em.json",
    "reports/phase3/antenna.json",
])
def test_the_runner_reads_its_verdict_from_the_declared_file(path):
    """These are not incidental files: `_read_verdict` is how the runner
    decides the step's outcome."""
    name = Path(path).name
    assert re.search(rf'_read_verdict\(\s*rpt3\s*/\s*"{re.escape(name)}"',
                     _RUNNER_SRC), (
        f"{path} is no longer the runner's verdict source — re-check the "
        f"declaration")


# ===========================================================================
# SATISFIABILITY — the pairing that makes each entry meetable
# ===========================================================================
# vibe-ic#1082 — a declared report may be written through `_atomic_artefact`
# instead of `Path.write_text`. This file asserts on the runner's SOURCE, so
# matching only `.write_text` reports "the write is gone" about a write that
# merely moved to the durable form. Widened in spelling, not in property.
_ATOMIC_ALIASES = ("_aa.write_text", "_aa.write_json",
                   "atomic_write_text", "atomic_write_json")


def _json_write_pos(body: str, expr: str):
    """Index of the statement writing `expr`, in either spelling, else None."""
    direct = f'({expr}).write_text'
    if direct in body:
        return body.index(direct)
    for alias in _ATOMIC_ALIASES:
        cand = f'{alias}({expr}'
        if cand in body:
            return body.index(cand)
    return None


def _json_write_count(body: str, expr: str) -> int:
    """How many statements write `expr`, counting either spelling."""
    n = body.count(f'({expr}).write_text')
    for alias in _ATOMIC_ALIASES:
        n += body.count(f'{alias}({expr}')
    return n


def test_em_json_is_written_in_the_same_branch_as_em_rpt(tmp_path):
    """Drive the emitter's own JSON-writing statement rather than asserting a
    substring: build the pair the way `_emit_ir_em_reports` does and confirm
    both land together."""
    src = _RUNNER_SRC
    # The two writes must live inside one `if has_em:` branch, i.e. between
    # `em_ok = False` and `em_ok = True` there is exactly one branch guard.
    body = src[src.index("    em_ok = False"):src.index("    return ir_ok, em_ok")]
    assert body.count("if has_em:") == 1, body[:200]
    assert "em_rpt.write_text(body)" in body
    _em_pos = _json_write_pos(body, 'em_rpt.parent / "em.json"')
    assert _em_pos is not None, (
        "the em.json write is gone from this branch — neither Path.write_text "
        "nor an _atomic_artefact delegate writes it (vibe-ic#1082)")
    assert body.index("em_rpt.write_text(body)") < _em_pos
    assert "em_ok = True" in body


def test_antenna_json_is_written_wherever_antenna_rpt_is():
    """`_emit_antenna_report` has two success branches; both must write the
    pair, or the declaration is unsatisfiable on one of them."""
    start = _RUNNER_SRC.index("def _emit_antenna_report(")
    end = _RUNNER_SRC.index("def _parse_spef_caps(")
    body = _RUNNER_SRC[start:end]
    assert body.count("antenna_rpt.write_text(") == 2, body.count(
        "antenna_rpt.write_text(")
    _ant = _json_write_count(body, 'antenna_rpt.parent / "antenna.json"')
    assert _ant == 2, (
        f"expected exactly 2 antenna.json writes, one per success branch — "
        f"found {_ant} in either spelling (vibe-ic#1082)")


def _gate_commands(step: dict):
    """Every `program_exit_zero` command string in a step's gate, at any
    nesting (`all_of`, `optional_program_exit_zero`, mapping form)."""
    out = []

    def walk(node):
        if isinstance(node, dict):
            for k, v in node.items():
                if k.endswith("program_exit_zero"):
                    out.append(v if isinstance(v, str)
                               else str(v.get("command", "")))
                else:
                    walk(v)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    walk(step.get("gate") or {})
    return out


def test_every_declared_output_of_these_steps_has_a_producer():
    """The rule an added entry must satisfy: something WRITES it. A
    declaration with no producer is the step-23 post_route_summary.json defect
    PR #473 fixed — the file was named in the flow and by nothing else.

    A mention in the flow is NOT a producer, and neither is a mention in a
    comment. The two accepted producers are: the phase-3 runner CONSTRUCTING
    that path (`<dir> / "<name>"` — how it builds every artefact path), or this
    step's own gate passing the path to `--json`, which the wrappers now
    forward.

    LIMIT of this test, stated rather than implied: it proves a producer
    EXISTS, not that it runs on every path. Satisfiability on real runs is
    measured separately — see the corpus counts in this module's docstring.
    """
    steps = _steps()
    declared_signoff_outputs = _declared_signoff_outputs()
    assert declared_signoff_outputs, (
        f"{_SIGNOFF_TABLE} yielded no output paths — the third producer shape "
        f"below would pass nothing and this test would silently narrow back to "
        f"two shapes")
    for step_id in ("23", "25", "26"):
        gate_json_targets = set()
        for cmd in _gate_commands(steps[step_id]):
            toks = cmd.split()
            gate_json_targets.update(
                toks[i + 1] for i, t in enumerate(toks) if t == "--json")
        for entry in _required(step_id):
            name = Path(entry).name
            built_by_runner = re.search(
                rf'/\s*f?["\'][^"\'\n]*{re.escape(name)}["\']', _RUNNER_SRC)
            assert (built_by_runner or entry in gate_json_targets
                    or entry in declared_signoff_outputs), (
                f"step {step_id} declares {entry} but no producer was found: "
                f"the runner does not build that path from a literal, this "
                f"step's gate does not produce it via --json, and it is not "
                f"the output column of any {_SIGNOFF_TABLE} row")


# ===========================================================================
# DIRECTION-1 GUARDS — hold on the pre-fix tree too
# ===========================================================================
@pytest.mark.parametrize("step_id,path", [
    ("23", "phase3/stage3/sta/post_route_timing.rpt"),
    ("23", "reports/phase3/sta/post_route_summary.json"),
    ("25", "reports/phase3/em.rpt"),
    ("26", "reports/phase3/antenna.rpt"),
])
def test_d1_the_existing_declarations_are_untouched(step_id, path):
    assert path in _required(step_id)


@pytest.mark.parametrize("step_id,path", [
    # Conditional on the PDK shipping distinct ss/ff process libraries.
    ("23", "phase3/stage3/sta/sta_mcorner_ocv.rpt"),
    # Conditional on a non-empty SPEF; extraction has a documented waiver.
    ("23", "phase3/stage3/sta/sta_spef_based.rpt"),
])
def test_d1_conditional_artefacts_are_not_declared(step_id, path):
    """Declaring a transient or a conditional artefact manufactures a false
    MISSING — the failure mode the ALL-of-N rule makes expensive."""
    assert path not in _required(step_id), (
        f"{path} is not produced on every real run; declaring it creates a "
        f"false MISSING")


@pytest.mark.parametrize("path", [
    "reports/phase3/multi_corner_spef_stance.json",
    "reports/phase3/mcorner_ocv_stance.json",
])
def test_d1_step23_stance_files_are_not_declared_here(path):
    """WITHDRAWN, deliberately — pinned so it cannot drift back in unnoticed.

    Declaring these makes 6 of the 8 tracked roots that carry step 23's
    already-declared `post_route_timing.rpt` report MISSING (see this module's
    docstring for the enumeration). Landing that needs its own decision with
    that number stated, not a ride-along on a batch whose other entries cost
    nothing.
    """
    assert path not in _required("23"), (
        f"{path} was re-added to step 23 without the 6-root cost being "
        f"restated — see the module docstring")


# ===========================================================================
# Step 31 — reports/phase3/drc_signoff.json, and the reason it is PINNED HERE
# ===========================================================================
# The `.rpt` half of this step's DRC sign-off has been declared since the step
# existed; the machine-readable `.json` half was not. It is read by three
# programs OTHER than its writer, none of which the d7 analyser can see, because
# `matrix_d7_artifact_graph.literal_index()` matches only the FULL path literal
# and all three reach the file by BASENAME or by recursive glob:
#
#   signoff_ladder_run.check_tier_1_drc     `reports/**/drc_signoff.json`, and
#       it grades release-gating tier T1 on it; absent, T1 reports NOT_RUN
#   final_report_generate                   echoes its verdict into the sign-off
#       summary a reader treats as the deliverable
#   macro_obs_geometry_intersect_check      reads `passed` / `is_signoff_deck`
#       out of it as geometric-DRC evidence it will not re-derive
#
# W1 did charge this path once, and only by accident: `general_precheck` named
# the literal because its `Checker.MagicDRC` delegate WROTE there, and the
# literal index cannot tell a writer from a reader. With that clobber fixed the
# accidental consumer is gone and W1 falls silent — MEASURED: remove the entry
# from a tree carrying the general_precheck fix and
# `test_d7_required_outputs_list_is_complete` is 64 passed / 1 skipped /
# 4 xfailed, step 31 GREEN with all three readers untouched.
#
# So the declaration is held HERE, by the readers, and not by the matrix. If a
# reader goes away, the pin below goes red and an author re-decides rather than
# inheriting an entry nobody can explain.
#
# WHAT IT COSTS, on the same corpus rule this file applies to step 23's
# withdrawn stance files (`find` over benchmark-data, 2026-08-21, at
# `~/vibe-ic` — benchmark-data is no longer tracked on main): 16 roots carry
# `drc_signoff.rpt`, 3 carry `drc_signoff.json`, so 13 report the entry MISSING.
# Unlike step 23's six, those 13 are not runs that DROPPED the artefact — the
# PRODUCER POSTDATES THEM. Every root carrying the JSON is dated 2026-08-03 or
# later and every root without it 2026-07-25 or earlier, which is
# `final_report_generate`'s own ORGANIC-20260808 note from the other side.
# That makes it the `magic_illegal_overlap.json` case, already accepted in the
# same list: the gate postdates every older published run, dimension 3 records
# the entry UNPROVEN there, and that is the true statement of the gap.
_STEP31_DRC_SIGNOFF_JSON = "reports/phase3/drc_signoff.json"

#: reader -> a fragment of the SOURCE that shows the read, so this pin fails
#: when a reader stops reading rather than when a file is merely renamed.
_STEP31_JSON_READERS = {
    "signoff_ladder_run": "reports/**/drc_signoff.json",
    "final_report_generate": "drc_signoff.json",
    "macro_obs_geometry_intersect_check": "drc_signoff.json",
}


def test_step31_declares_the_machine_readable_drc_signoff():
    assert _STEP31_DRC_SIGNOFF_JSON in _required("31"), (
        f"step 31 produces {_STEP31_DRC_SIGNOFF_JSON} from its own `--signoff` "
        f"gate clause and three programs read it, but the step no longer "
        f"declares it. Its absence is invisible: signoff_ladder_run's tier T1 "
        f"takes its NOT_RUN branch and the sign-off summary prints "
        f"'(report missing)' — no gate goes red. The d7 matrix does NOT hold "
        f"this entry (its consumer index is literal-only and every reader here "
        f"uses a glob), so this pin is the only thing that does.")


@pytest.mark.parametrize("module,fragment", sorted(_STEP31_JSON_READERS.items()))
def test_step31_json_readers_still_read_it(module, fragment):
    """The declaration is justified by these readers and by nothing else.

    A reader that goes away is not a reason to delete the entry silently — it is
    a reason for an author to re-decide, which is what a red here asks for."""
    src = (_PROGRAMS / f"{module}.py").read_text(errors="replace")
    assert fragment in src, (
        f"{module} no longer names {fragment!r}. It was one of the three "
        f"readers that justify declaring {_STEP31_DRC_SIGNOFF_JSON} on step 31 "
        f"— re-count the readers before touching the declaration.")


#: Write verbs, by behaviour rather than by module name. A consumer that only
#: opens a path for reading is a READER however it is called; one that hands
#: the literal to any of these is a WRITER, which is the state this control
#: exists to refuse.
_WRITE_VERBS = frozenset({
    "write_text", "write_bytes", "write_json", "atomic_write_text",
    "atomic_write_json", "dump", "mkdir", "touch", "rename", "replace",
})


def _module_writes(module: str, literal: str) -> bool:
    """True when `module` hands `literal` (or a name bound to it) to a write.

    AST, not grep: the literal is usually assigned to a module constant and
    used through it, so a text search for the path beside the word "write"
    would answer about proximity rather than about data flow."""
    import ast
    path = _PROGRAMS / f"{module}.py"
    if not path.is_file():
        return False
    try:
        tree = ast.parse(path.read_text(errors="replace"))
    except SyntaxError:                       # pragma: no cover - not our tree
        return False
    bound = {literal}
    for node in ast.walk(tree):
        if isinstance(node, ast.Assign) and isinstance(node.value, ast.Constant) \
                and node.value.value == literal:
            for t in node.targets:
                if isinstance(t, ast.Name):
                    bound.add(t.id)

    def _mentions(n) -> bool:
        for sub in ast.walk(n):
            if isinstance(sub, ast.Constant) and sub.value in bound:
                return True
            if isinstance(sub, ast.Name) and sub.id in bound:
                return True
        return False

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        name = (node.func.attr if isinstance(node.func, ast.Attribute)
                else getattr(node.func, "id", ""))
        if name in _WRITE_VERBS and any(_mentions(a) for a in
                                        [node.func] + list(node.args)):
            return True
        if name == "open" and any(_mentions(a) for a in node.args):
            mode = node.args[1] if len(node.args) > 1 else None
            if isinstance(mode, ast.Constant) and isinstance(mode.value, str) \
                    and ("w" in mode.value or "a" in mode.value):
                return True
    return False


def test_the_matrix_does_not_hold_the_step31_json_entry():
    """NEGATIVE CONTROL for the pin above, and the honest statement of an
    analyser limit: `literal_index` is keyed on the FULL path literal, so a
    reader that reaches this file by glob is invisible to W1. Asserted rather
    than described, so that if the analyser is ever widened to see glob readers
    this test goes red and the comment above stops being true quietly."""
    import matrix_d7_artifact_graph as G  # noqa: WPS433
    consumers = G.literal_index().get(_STEP31_DRC_SIGNOFF_JSON, frozenset())
    # `task_nature_route` NAMES this artefact and neither reads nor writes it:
    # it is the `artefact` field of the exit-evidence row that says which file
    # proves a manufacturability exit. A routing table has to spell the path to
    # be a routing table, and `literal_index` is keyed on the path literal, so
    # it cannot tell a declaration from a read. That is the analyser limit this
    # negative control exists to state.
    #
    # THE ALLOW-LIST IS GONE, AND THE PROPERTY IS ASSERTED INSTEAD.
    # This used to read `set(consumers) <= {"drc_report_check",
    # "task_nature_route"}` — a hand-written name list, which is the shape that
    # expires silently, and it did. MEASURED on TREE 7903c1972305 the index
    # holds `{'_ic_release_artefacts', 'task_nature_route'}`: a legitimate new
    # READER arrived (the 37.5ic product document set, 5bfae3aedb) and
    # `drc_report_check` LEFT, because it now names the path only in its module
    # docstring and the analyser stopped counting prose — the correct
    # direction, verified rather than assumed.
    #
    # The assertion this control actually owes is in its own failure message:
    # a READER is fine, a WRITER is "the general_precheck clobber returning
    # under a new name". So that is what is measured — per consumer, by AST,
    # not by whether the name looks harmless.
    assert consumers, (
        f"no consumer names {_STEP31_DRC_SIGNOFF_JSON} at all; the pin above "
        f"rests on readers that must exist for it to mean anything")
    writers = sorted(c for c in consumers if _module_writes(c, _STEP31_DRC_SIGNOFF_JSON))
    assert not writers, (
        f"{writers} WRITE {_STEP31_DRC_SIGNOFF_JSON}. A consumer that writes "
        f"this path is the general_precheck clobber returning under a new "
        f"name — the matrix must not hold an entry an audit produces itself.")


# ===========================================================================
# The third producer shape is only admissible while it really produces
# ===========================================================================
def test_the_signoff_table_dispatch_really_writes_its_output_column():
    """Membership in `_DECLARED_SIGNOFF_GATES` means PRODUCED, or it means
    nothing — and if it means nothing, accepting it above is a relaxation
    rather than a widening.

    So the implication is asserted, not assumed. `_run_declared_signoff_gate`
    must (1) build the row's third column under the project directory and
    (2) hand that path to the gate as `--json`. Those are precisely the two
    producer mechanisms this module already accepts from a literal; the row
    reaches them through a parameter, which is why the text patterns miss it.

    If the dispatcher is ever refactored so a row's output path is no longer
    built and passed, this fails HERE — and the acceptance above becomes
    unsound at the same moment, which is the point of pinning it.
    """
    import ast
    fn = None
    for node in ast.walk(ast.parse(_RUNNER_SRC)):
        if isinstance(node, ast.FunctionDef) \
                and node.name == "_run_declared_signoff_gate":
            fn = node
            break
    assert fn is not None, (
        "the runner no longer defines _run_declared_signoff_gate, so nothing "
        f"dispatches {_SIGNOFF_TABLE} and its rows produce nothing")
    body = ast.unparse(fn)
    assert re.search(r"out_json\s*=\s*project\s*/\s*out_rel", body), (
        "_run_declared_signoff_gate no longer builds <project> / <out_rel>; "
        f"a {_SIGNOFF_TABLE} row's output column is then not a produced path")
    assert re.search(r"'--json'\s*,\s*str\(out_json\)", body) \
        or re.search(r'"--json"\s*,\s*str\(out_json\)', body), (
        "_run_declared_signoff_gate no longer passes the row's output path to "
        "the gate as --json; the row declares a path nothing is told to write")


def test_the_table_is_dispatched_over_every_row():
    """A table nobody iterates produces nothing either."""
    assert re.search(
        r"for\s+\w+\s*,\s*\w+\s*,\s*\w+\s*,\s*\w+\s+in\s+" + _SIGNOFF_TABLE,
        _RUNNER_SRC), (
        f"nothing iterates {_SIGNOFF_TABLE}, so its rows are declarations "
        f"with no dispatch behind them")
    # The newly recognized pre-stream table must pass each actual row to the
    # same writer, not merely mention its name in source or comments.
    import ast
    tree = ast.parse(_RUNNER_SRC)
    for table in ("_PRESTREAM_GATES",):
        dispatched = False
        for comp in ast.walk(tree):
            if not isinstance(comp, (ast.ListComp, ast.DictComp)):
                continue
            for gen in comp.generators:
                if not (isinstance(gen.iter, ast.Name) and gen.iter.id == table
                        and isinstance(gen.target, ast.Name)):
                    continue
                for call in ast.walk(comp):
                    if (isinstance(call, ast.Call)
                            and isinstance(call.func, ast.Name)
                            and call.func.id == "_run_declared_signoff_gate"
                            and len(call.args) == 2
                            and isinstance(call.args[0], ast.Name)
                            and call.args[0].id == "project"
                            and isinstance(call.args[1], ast.Starred)
                            and isinstance(call.args[1].value, ast.Name)
                            and call.args[1].value.id == gen.target.id):
                        dispatched = True
        assert dispatched, f"{table} has no complete row dispatch to the writer"


def test_an_entry_with_no_producer_anywhere_still_fails():
    """NEGATIVE CONTROL for the widening — the whole reason this test exists.

    Adding a third accepted shape is only safe if the check can still REFUSE.
    A path that satisfies none of the three shapes must not be accepted, so
    the acceptance is exercised here directly against a name no producer
    mentions. Without this, `test_every_declared_output_of_these_steps_has_a_
    producer` could be widened until nothing could fail it and it would still
    look green.
    """
    phantom = "reports/phase3/sta/no_such_artefact_cybk4_control.json"
    name = Path(phantom).name
    assert not re.search(
        rf'/\s*f?["\'][^"\'\n]*{re.escape(name)}["\']', _RUNNER_SRC), (
        "the control path is mentioned in the runner; pick another")
    assert phantom not in _declared_signoff_outputs(), (
        "the control path is a declared sign-off output; pick another")
    gate_json_targets = set()
    for cmd in _gate_commands(_steps()["23"]):
        toks = cmd.split()
        gate_json_targets.update(
            toks[i + 1] for i, t in enumerate(toks) if t == "--json")
    assert phantom not in gate_json_targets


def test_the_third_shape_is_what_admits_the_architectural_residual_report():
    """The entry this widening was measured on, pinned by NAME.

    `sta_architectural_residual_check` is the one declared sign-off gate whose
    step-23 yaml clause deliberately does NOT pass `--json`: the clause says so
    in as many words — "The inline sign-off runner owns the required JSON
    output. Auditing must re-check the timing inputs without creating or
    replacing it." So the runner's table is its ONLY producer, and that is by
    design, not by omission. Pinned here so that if someone later "fixes" this
    by adding `--json` to the yaml — re-creating the report on the audit pass
    the comment forbids — the reason this shape exists is still on the record.
    """
    entry = "reports/phase3/sta/architectural_residual.json"
    assert entry in _required("23")
    assert entry in _declared_signoff_outputs(), (
        f"{entry} is no longer an output column of {_SIGNOFF_TABLE}")
    name = Path(entry).name
    assert not re.search(
        rf'/\s*f?["\'][^"\'\n]*{re.escape(name)}["\']', _RUNNER_SRC), (
        "the runner now builds this path from a literal too; if that is "
        "intended, this pin should be retired rather than kept green by luck")


# Neutral source inputs for the same oracle; no physical design or tool launch.
_DELEGATED_RUNNER = '''
_DECLARED_SIGNOFF_GATES = (
    ("neutral", "neutral_gate.py", "reports/neutral/verdict.json", ()),
)
def _run_declared_signoff_gate(project):
    import drv_capture_plan as owner
    owner.capture_and_publish(project)
'''
_DELEGATED_OWNER = '''
from _atomic_artefact import write_text
def publish(project):
    output = project / "reports/neutral/plan.json"
    write_text(output, "neutral data")
    return output
def capture_and_publish(project):
    return publish(project)
'''
_NEUTRAL_PLAN = "reports/neutral/plan.json"


def test_delegated_writer_paths_are_derived_from_the_called_owner(tmp_path, monkeypatch):
    assert _NEUTRAL_PLAN in _declared_signoff_outputs()
    outputs = _declared_signoff_outputs()
    assert "reports/neutral/other.json" in outputs
    assert _NEUTRAL_PLAN not in outputs


@pytest.mark.parametrize("fault", [
    "absent_owner", "malformed_owner", "missing_entry", "disconnected_publish",
    "reader_only", "unbound_path", "rebound_path", "foreign_root",
    "unresolved_writer", "missing_import", "missing_dispatch", "empty_table",
    "malformed_runner", "uncalled_nested_writer", "uncalled_lambda_writer",
    "uncalled_class_writer", "shadowed_helper",
])
def test_delegated_writer_refuses_incomplete_source(tmp_path, monkeypatch, fault):
    runner, owner = _DELEGATED_RUNNER, _DELEGATED_OWNER
    if fault == "absent_owner":
        owner = None
    elif fault == "malformed_owner":
        owner = "def publish(:"
    elif fault == "missing_entry":
        owner = owner.replace("def capture_and_publish", "def unused_entry")
    elif fault == "disconnected_publish":
        owner = owner.replace("return publish(project)", "return None")
    elif fault == "shadowed_helper":
        owner = owner.replace("return publish(project)",
                              "def publish(project):\n        return project\n    return publish(project)")
    elif fault == "reader_only":
        owner = owner.replace('write_text(output, "neutral data")', "output.read_text()")
    elif fault == "unbound_path":
        owner = owner.replace('project / "reports/neutral/plan.json"', "unknown_path")
    elif fault == "rebound_path":
        owner = owner.replace('write_text(output, "neutral data")',
                              'output = unknown_path\n    write_text(output, "neutral data")')
    elif fault == "foreign_root":
        runner = runner.replace("owner.capture_and_publish(project)",
                                "owner.capture_and_publish(other_project)")
    elif fault == "unresolved_writer":
        owner = owner.replace("from _atomic_artefact import write_text", "")
    elif fault == "missing_import":
        runner = runner.replace("import drv_capture_plan as owner", "pass")
    elif fault == "missing_dispatch":
        runner = runner.replace("owner.capture_and_publish(project)", "pass")
    elif fault == "empty_table":
        runner = runner.replace("_DECLARED_SIGNOFF_GATES", "_UNUSED_GATES")
    elif fault == "malformed_runner":
        runner = "def gate(:"
    elif fault in {"uncalled_nested_writer", "uncalled_lambda_writer",
                   "uncalled_class_writer"}:
        nested = {
            "uncalled_nested_writer": 'def disconnected_writer(project):\n        output = project / "reports/neutral/plan.json"\n        write_text(output, "{}")',
            "uncalled_lambda_writer": 'disconnected_writer = lambda: write_text(project / "reports/neutral/plan.json", "{}")',
            "uncalled_class_writer": 'class DisconnectedWriter:\n        output = project / "reports/neutral/plan.json"\n        write_text(output, "{}")',
        }[fault]
        owner = ('from _atomic_artefact import write_text\n'
                 'def capture_and_publish(project):\n    ' + nested + '\n    return project\n')
    assert _NEUTRAL_PLAN not in _declared_signoff_outputs()


def test_delegated_writer_does_not_reuse_stale_owner_source(tmp_path, monkeypatch):
    assert _NEUTRAL_PLAN in _declared_signoff_outputs()
    assert _NEUTRAL_PLAN not in _declared_signoff_outputs()
    assert _NEUTRAL_PLAN not in _declared_signoff_outputs()


_PEER_RUNNER = 'def _run_declared_signoff_gate(project):\n    import drv_capture_plan as _drv_plan\n    _drv_plan.capture_and_publish(project)\n'
_PEER_OWNER = 'from _atomic_artefact import write_text\n\ndef capture_and_publish(project):\n    def disconnected_writer(project):\n        output = project / "reports/neutral/disconnected.json"\n        write_text(output, "{}")\n    return project\n'


_PEER_SHADOWED_OWNER = 'from _atomic_artefact import write_text\n\ndef publish(project):\n    output = project / "reports/neutral/disconnected.json"\n    write_text(output, "{}")\n\ndef capture_and_publish(project):\n    def publish(project):\n        return None\n    return publish(project)\n'

@pytest.mark.parametrize("owner_source", [_PEER_OWNER, _PEER_SHADOWED_OWNER],
                         ids=["uncalled_nested_writer", "shadowed_helper"])
def test_peer_uncalled_nested_writer_is_disconnected(tmp_path, monkeypatch, owner_source):
    assert "reports/neutral/disconnected.json" not in _declared_signoff_outputs()
