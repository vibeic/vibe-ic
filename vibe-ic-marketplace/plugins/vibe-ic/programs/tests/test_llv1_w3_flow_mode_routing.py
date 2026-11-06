"""llv1 W3: the flow-mode layer above the switch file and the class defaults.

Contracts:
  1. With no implementation-flow record the layer does not exist: every step
     any shipped call site asks `selected_mode` about gets today's answer,
     and asking writes nothing.
  2. Under a `librelane` record every such step gets the layer's answer,
     with no switch file, on a plain project and on a chip-path project
     alike (the layer outranks the class defaults).
  3. The call sites are DERIVED from the tree (AST over programs/), and every
     step they ask about has a defined answer under the flag: in the layer,
     or in the named out-of-layer set (the analog arms, refused at the front
     door in v1).
  4. The owner's kept checks: 13 and 25 stay vibe-ic; 8, 24, 26 and 31 are
     `dual`, because their `librelane` mode replaces vibe-ic's judgement.
  5. A switch file naming a step the flag decides refuses the run with
     IMPL_SWITCH_CONFLICT (decision 18), even when both say the same thing;
     a switch naming only out-of-layer steps is honoured.
  6. A damaged record refuses by its own reason class; `orfs` has no layer.
  7. `class_defaults_in_force` is empty under the flag.
  8. Step 9's LibreLane arm runs with no switch file (it used to crash).
"""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path

import pytest

import _plugin_tree  # noqa: F401 — puts programs/ on sys.path
import librelane_contract as LC
import _owner_declared as _OD  # noqa: E402 — tests/, the one attestation fixture

PROGRAMS = Path(LC.__file__).resolve().parent
FLOW_OUTPUT_CONDITIONS_PATH = PROGRAMS.parent / "flow" / "phase1_phase2_phase3.yaml"
#: The ruling, restated as the contract: under `--librelane` LibreLane
#: produces the step except where the owner keeps vibe-ic's check.
LAYER = {
    "2": "direct", "3": "direct", "4": "direct", "5": "direct",
    "7": "librelane", "8": "dual", "9": "librelane", "10": "librelane",
    "13": "direct",
    "15": "librelane", "15.5ic": "librelane", "17": "librelane",
    "18": "librelane", "19": "librelane", "20": "librelane",
    "21": "librelane", "22": "librelane", "23": "librelane",
    "24": "dual", "25": "direct", "26": "dual", "26.5ic": "librelane",
    "29": "librelane", "30": "direct",
    "31": "dual", "32": "librelane", "33": "librelane", "34": "librelane",
    "37": "librelane", "DT2": "librelane", "DT3": "librelane",
}
#: Steps a call site asks about that the flag deliberately does not decide.
OUT_OF_LAYER = {"A6", "A7", "A8"}
#: Call sites whose step is a runtime value no literal names, keyed by the
#: SITE: (file, enclosing function, argument variable). Each entry says where
#: its population comes from. Every entry must be used by exactly one site in
#: the census, and an unresolvable call no entry names is unresolved -- so a
#: new dynamic call anywhere, even beside a listed one, fails the census.
DYNAMIC_SITES = {
    ("librelane_pv_signoff.py", "state_metric", "step"): "STATE_KEYS",
    # obligation/finished_layout and precheck/state_metric callers use these steps.
    ("librelane_signoff_evidence.py", "tool_selected", "step"): ("26", "31", "34", "37"),
    ("phase3_one_shot_runner.py", "atpg_librelane_views", "step"): ("DT2", "DT3"),
    ("flow_compliance_check.py", "_output_not_owed", "selection"): "OUTPUT_CONDITIONS",
}


def _output_condition_steps():
    """The finite selection population owed by canonical output_conditions.

    Missing or unknown context is unresolved, never an empty covered set.
    """
    import _flow_yaml
    import yaml

    try:
        rows = _flow_yaml.load(FLOW_OUTPUT_CONDITIONS_PATH, encoding="utf-8")["steps"]
        if not isinstance(rows, list) or any(not isinstance(r, dict) for r in rows):
            return None
        declared = {str(row["id"]) for row in rows}
        steps = set()
        for row in rows:
            conditions = row.get("output_conditions", {})
            if not isinstance(conditions, dict):
                return None
            for condition in conditions.values():
                if not isinstance(condition, dict):
                    return None
                if "librelane_step_mode" not in condition:
                    continue
                selection = condition["librelane_step_mode"]
                if not isinstance(selection, dict):
                    return None
                step = selection.get("step")
                if type(step) not in (str, int) or str(step) not in declared:
                    return None
                steps.add(str(step))
        return tuple(sorted(steps)) or None
    except (OSError, ValueError, TypeError, KeyError, yaml.YAMLError):
        return None


def _tree(project: Path) -> dict:
    return {str(p.relative_to(project)): (hashlib.sha256(p.read_bytes()).hexdigest()
                                          if p.is_file() else "dir")
            for p in sorted(project.rglob("*"))}






def _switch(project: Path, steps: dict) -> None:
    p = project / "phase3" / "librelane_switch.json"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"steps": steps}))


def _chip(project: Path) -> Path:
    st = project / "input" / "submission_template"
    st.mkdir(parents=True, exist_ok=True)
    (st / "SELF_TAPEOUT.txt").write_text("# self tape-out\n")
    (st / "tapeout_declaration.json").write_text(json.dumps(_OD.attest(
        {"schema": "vibe-ic/tapeout_declaration/1",
         "answers": {"deliverable": "DIE"}})))
    return project


def _constants(module: ast.Module) -> dict:
    out = {}
    for node in module.body:
        if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                and isinstance(node.targets[0], ast.Name):
            try:
                out[node.targets[0].id] = ast.literal_eval(node.value)
            except ValueError:
                pass
    return out


def _loop_values(parents: list, name: str, consts: dict):
    """The literal population a loop or comprehension binds `name` to."""
    for node in reversed(parents):
        gens = []
        if isinstance(node, (ast.ListComp, ast.SetComp, ast.DictComp, ast.GeneratorExp)):
            gens = node.generators
        elif isinstance(node, ast.For):
            gens = [node]
        for gen in gens:
            if isinstance(gen.target, ast.Name) and gen.target.id == name:
                if isinstance(gen.iter, ast.Name) and gen.iter.id in consts:
                    return tuple(consts[gen.iter.id])
                try:
                    return tuple(ast.literal_eval(gen.iter))
                except ValueError:
                    return None
    return None


CONTRACT_MODULE = "librelane_contract"
FUNCTION = "selected_mode"


class UnaccountedReference(AssertionError):
    """A reference to the function the census can neither call nor alias."""


def _aliases(module: ast.Module) -> tuple[set, set]:
    """(function aliases, module aliases) the file binds, read from its own
    import and assignment statements, anywhere in the file."""
    funcs, mods = set(), set()
    for node in ast.walk(module):
        if isinstance(node, ast.ImportFrom):
            for a in node.names:
                if a.name == FUNCTION:
                    funcs.add(a.asname or a.name)
        elif isinstance(node, ast.Import):
            for a in node.names:
                if a.name == CONTRACT_MODULE:
                    mods.add(a.asname or a.name)
    changed = True
    while changed:                       # `f = _ll.selected_mode`, `g = f`
        changed = False
        for node in ast.walk(module):
            if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                    and isinstance(node.targets[0], ast.Name):
                v, name = node.value, node.targets[0].id
                if ((isinstance(v, ast.Attribute) and v.attr == FUNCTION)
                        or (isinstance(v, ast.Name) and v.id in funcs)) and name not in funcs:
                    funcs.add(name)
                    changed = True
    return funcs, mods


def call_sites(root: Path = PROGRAMS, used: dict | None = None):
    """[(file, line, steps)] for every shipped call of the contract's
    `selected_mode`, under whatever name the file imported it as. Any other
    reference to it (passed, stored, wrapped) raises UnaccountedReference: a
    site the census cannot see must fail it, never shrink it. `used`, when
    given, counts the sites each DYNAMIC_SITES entry resolved."""
    sites = []
    for path in sorted(root.rglob("*.py")):
        rel = path.relative_to(root)
        if rel.parts[0] == "tests" or path.name == f"{CONTRACT_MODULE}.py":
            continue
        text = path.read_text(encoding="utf-8")
        if FUNCTION not in text:
            continue
        module = ast.parse(text)
        consts = _constants(module)
        funcs, _mods = _aliases(module)
        accounted: set = set()

        def is_ref(node) -> bool:
            return ((isinstance(node, ast.Attribute) and node.attr == FUNCTION)
                    or (isinstance(node, ast.Name) and node.id in funcs))

        def walk(node, parents):
            # Only this assignment form is followed by _aliases.  Every
            # other storage shape must remain loose so the census refuses a
            # call it cannot trace, rather than silently losing that site.
            if isinstance(node, ast.Assign) and len(node.targets) == 1 \
                    and isinstance(node.targets[0], ast.Name) and is_ref(node.value):
                accounted.add(id(node.value))
            if isinstance(node, ast.Call) and is_ref(node.func):
                accounted.add(id(node.func))
                steps = None
                if len(node.args) >= 2:
                    arg = node.args[1]
                    if isinstance(arg, ast.Constant):
                        steps = (arg.value,)
                    elif isinstance(arg, ast.Name):
                        steps = _loop_values(parents, arg.id, consts)
                        if steps is None and arg.id in consts:
                            steps = (consts[arg.id],)
                        if steps is None:
                            enclosing = next(
                                (p.name for p in reversed(parents)
                                 if isinstance(p, (ast.FunctionDef, ast.AsyncFunctionDef))),
                                None)
                            key = (path.name, enclosing, arg.id)
                            source = DYNAMIC_SITES.get(key)
                            if source is not None and used is not None:
                                used[key] = used.get(key, 0) + 1
                            if isinstance(source, str):
                                table = getattr(__import__(path.stem), source)
                                steps = tuple(sorted({v[0] for v in table.values()}))
                            else:
                                steps = source
                    elif (isinstance(arg, ast.Call) and isinstance(arg.func, ast.Name)
                          and arg.func.id == "str" and len(arg.args) == 1
                          and not arg.keywords):
                        selection = arg.args[0]
                        if (isinstance(selection, ast.Call)
                                and isinstance(selection.func, ast.Attribute)
                                and isinstance(selection.func.value, ast.Name)
                                and selection.func.attr == "get"
                                and len(selection.args) == 1 and not selection.keywords
                                and isinstance(selection.args[0], ast.Constant)
                                and selection.args[0].value == "step"):
                            enclosing = next(
                                (p.name for p in reversed(parents)
                                 if isinstance(p, (ast.FunctionDef, ast.AsyncFunctionDef))),
                                None)
                            key = (path.name, enclosing, selection.func.value.id)
                            if DYNAMIC_SITES.get(key) == "OUTPUT_CONDITIONS":
                                if used is not None:
                                    used[key] = used.get(key, 0) + 1
                                steps = _output_condition_steps()
                sites.append((str(rel), node.lineno, steps))
            for child in ast.iter_child_nodes(node):
                walk(child, parents + [node])

        walk(module, [])
        loose = [getattr(n, "lineno", "?") for n in ast.walk(module)
                 if is_ref(n) and id(n) not in accounted
                 and not (isinstance(n, ast.Name) and isinstance(n.ctx, ast.Store))]
        if loose:
            raise UnaccountedReference(f"{rel}: references to {FUNCTION} at lines "
                                       f"{loose} are neither a call nor an alias")
    return sites


def test_every_call_site_is_enumerated_and_resolved():
    sites = call_sites()
    assert sites, "the instrument found no call site; it cannot see"
    unresolved = [s for s in sites if not s[2]]
    assert not unresolved, unresolved
    # Positive control on the instrument: sites known to exist are found.
    files = {s[0] for s in sites}
    for known in ("phase3_one_shot_runner.py", "design_one_shot_runner.py",
                  "librelane_route.py", "librelane_pv_signoff.py"):
        assert known in files
    # Every DYNAMIC_SITES entry resolved exactly one site: none is stale and
    # none silently covers a second call.
    used: dict = {}
    call_sites(used=used)
    assert used == {key: 1 for key in DYNAMIC_SITES}, used


def test_the_contract_carries_the_ruled_layer():
    assert getattr(LC, "IMPL_STEP_MODES", {}).get("librelane") == LAYER


def test_every_step_a_call_site_asks_about_is_decided_under_the_flag():
    asked = {step for _, _, steps in call_sites() for step in steps}
    undecided = sorted(asked - set(LAYER) - OUT_OF_LAYER)
    assert not undecided, f"call sites ask about steps the flag leaves open: {undecided}"
    assert all(m in ("direct", "librelane", "dual") for m in LAYER.values())


@pytest.mark.parametrize("chip", [False, True])
def test_no_record_gives_todays_answer_at_every_site_and_writes_nothing(tmp_path, chip):
    project = _chip(tmp_path) if chip else tmp_path
    before = _tree(project)
    for _, _, steps in call_sites():
        for step in steps:
            assert getattr(LC, "impl_step_modes", lambda p: None)(project) is None
            # selected_mode's documented order with no switch: a step-wide
            # production default (R-0929-TOOL-DEFAULT: step 3), then the
            # design class's, then `direct`.
            expected = (LC.PRODUCTION_DEFAULTS.get(step)
                        or LC._class_default(project, step, {}) or "direct")
            assert LC.selected_mode(project, step) == expected, step
    assert _tree(project) == before


@pytest.mark.parametrize("chip", [False, True])
def test_under_librelane_every_site_gets_the_layers_answer(tmp_path, chip):
    project = _chip(tmp_path) if chip else tmp_path
    for _, _, steps in call_sites():
        for step in steps:
            if step in LAYER:
                assert LC.selected_mode(project, step) == LAYER[step], step
    # The chain the chip class defaults run is LibreLane's under the flag
    # too, but because the flag decides it, not the class.
    assert LC.class_defaults_in_force(project) == {}


def test_the_owners_kept_checks_are_not_replaced_by_the_tool(tmp_path):
    kept = {"13": "direct", "25": "direct", "2": "direct",
            "8": "dual", "24": "dual", "26": "dual", "31": "dual",
            "23": "librelane", "32": "librelane"}
    assert {s: LC.selected_mode(tmp_path, s) for s in kept} == kept


@pytest.mark.parametrize("mode", ["librelane", "direct", "dual"])
def test_a_switch_naming_a_step_the_flag_decides_refuses(tmp_path, mode):
    _switch(tmp_path, {"21": mode})
    for step in ("21", "9", "30"):       # every step the flag decides refuses
        with pytest.raises(LC.Refusal) as exc:
            LC.selected_mode(tmp_path, step)
        assert exc.value.code == "IMPL_SWITCH_CONFLICT"
        assert "'21'" in str(exc.value)
    # Analog A6 is outside the digital implementation layer, but its own
    # production default now selects the native LibreLane arm.
    assert LC.selected_mode(tmp_path, "A6") == "librelane"


def test_a_switch_naming_only_out_of_layer_steps_is_honoured(tmp_path):
    _switch(tmp_path, {"A6": "librelane"})
    assert LC.selected_mode(tmp_path, "A6") == "librelane"
    assert LC.selected_mode(tmp_path, "21") == "librelane"
    assert LC.selected_mode(tmp_path, "13") == "direct"


def test_without_a_record_the_switch_file_still_rules(tmp_path):
    _switch(tmp_path, {"21": "dual", "13": "librelane"})
    assert LC.selected_mode(tmp_path, "21") == "dual"
    assert LC.selected_mode(tmp_path, "13") == "librelane"


def test_a_damaged_record_refuses_never_the_default(tmp_path):
    with pytest.raises(LC.Refusal) as exc:
        LC.selected_mode(tmp_path, "21")


def test_a_mode_with_no_layer_refuses_by_name(tmp_path):
    with pytest.raises(LC.Refusal) as exc:
        LC.selected_mode(tmp_path, "21")


def test_step9_librelane_arm_runs_without_a_switch_file(tmp_path):
    import phase3_one_shot_runner as P3
    assert LC.selected_mode(tmp_path, "9") == "librelane"
    assert not (tmp_path / "phase3/librelane_switch.json").exists()
    res = P3._step_synth_librelane(tmp_path, "top", None, "no-container")
    assert res.status == "FAIL"
    assert "LL_SYNTH_INPUT_MISSING" in res.detail


# ── review fixes (review_wave3 W3) ───────────────────────────────────────────





@pytest.mark.parametrize("record", ["damaged", "orfs", "conflict", "librelane"])
@pytest.mark.parametrize("step", sorted(OUT_OF_LAYER))
def test_out_of_layer_steps_never_read_the_record(tmp_path, record, step):
    _switch(tmp_path, {step: "dual"})
    expected = LC.selected_mode(tmp_path, step)
    assert expected == "dual"
    assert LC.selected_mode(tmp_path, step) == expected


def test_the_admission_identity_carries_the_layer(tmp_path, monkeypatch):
    import phase3_one_shot_runner as P3
    assert P3._librelane_admission_facts(tmp_path) == {}
    facts = P3._librelane_admission_facts(tmp_path)
    assert facts["librelane_impl_layer"] == LAYER
    assert facts["librelane_contract_sha256"] == LC.digest(Path(LC.__file__))
    # A different layer is a different identity.
    moved = dict(LC.IMPL_STEP_MODES["librelane"], **{"8": "librelane"})
    monkeypatch.setitem(LC.IMPL_STEP_MODES, "librelane", moved)
    assert P3._librelane_admission_facts(tmp_path) != facts


def test_a_damaged_record_is_part_of_the_identity_not_dropped(tmp_path):
    import phase3_one_shot_runner as P3
    facts = P3._librelane_admission_facts(tmp_path)
    assert "IMPL_RECORD_UNREADABLE" in json.dumps(facts["librelane_impl_layer"])


def test_a_chip_project_under_the_flag_keeps_a_contract_bound_identity(tmp_path):
    import phase3_one_shot_runner as P3
    project = _chip(tmp_path)
    before = P3._librelane_admission_facts(project)
    assert before.get("librelane_class_defaults")
    after = P3._librelane_admission_facts(project)
    assert after["librelane_impl_layer"] == LAYER and "librelane_contract_sha256" in after
    assert after != before


def _scratch(tmp_path, body: str) -> Path:
    root = tmp_path / "programs"
    root.mkdir()
    (root / "aliased_site.py").write_text(body)
    return root


def test_the_census_sees_an_aliased_import(tmp_path):
    root = _scratch(tmp_path, (
        "def f(project):\n"
        "    from librelane_contract import selected_mode as _renamed\n"
        "    return _renamed(project, 'Z9')\n"))
    sites = call_sites(root)
    assert [(Path(f).name, s) for f, _, s in sites] == [("aliased_site.py", ("Z9",))]
    # ... and the census goes red on it: Z9 is decided by no layer.
    asked = {s for _, _, steps in sites for s in steps}
    assert sorted(asked - set(LAYER) - OUT_OF_LAYER) == ["Z9"]


def test_the_census_sees_an_assigned_alias(tmp_path):
    root = _scratch(tmp_path, (
        "import librelane_contract as _c\n"
        "pick = _c.selected_mode\n"
        "again = pick\n"
        "def f(project):\n"
        "    return again(project, 'Z8')\n"))
    assert [s for _, _, s in call_sites(root)] == [("Z8",)]


def test_a_reference_the_census_cannot_follow_fails_it(tmp_path):
    root = _scratch(tmp_path, (
        "from librelane_contract import selected_mode\n"
        "TABLE = {'m': selected_mode}\n"))
    with pytest.raises(UnaccountedReference):
        call_sites(root)


@pytest.mark.parametrize("body", [
    (
        "import librelane_contract as _ll\n"
        "class Holder:\n"
        "    def f(self, project):\n"
        "        self.mode = _ll.selected_mode\n"
        "        return self.mode(project, '40')\n"
    ),
    (
        "from librelane_contract import selected_mode\n"
        "TABLE = {}\n"
        "TABLE['mode'] = selected_mode\n"
        "def f(project):\n"
        "    return TABLE['mode'](project, '40')\n"
    ),
    (
        "import librelane_contract as _ll\n"
        "pick = other = _ll.selected_mode\n"
        "def f(project):\n"
        "    return other(project, '40')\n"
    ),
])
def test_assignment_shapes_the_census_cannot_follow_refuse(tmp_path, body):
    with pytest.raises(UnaccountedReference):
        call_sites(_scratch(tmp_path, body))


def test_the_census_counts_a_reexported_function_import(tmp_path):
    root = tmp_path / "programs"
    root.mkdir()
    (root / "some_helper.py").write_text(
        "from librelane_contract import selected_mode\n")
    (root / "reexport_site.py").write_text(
        "from some_helper import selected_mode\n"
        "def f(project):\n"
        "    return selected_mode(project, 'Z7')\n")
    assert [(Path(f).name, steps) for f, _, steps in call_sites(root)] == [
        ("reexport_site.py", ("Z7",))]


# ── review fix 2 (review_wave4c W3): a dynamic site is keyed by its call ────

_DYNAMIC_BODY = (
    "import librelane_contract as _ll\n"
    "def atpg_librelane_views(project, step):\n"
    "    return _ll.selected_mode(project, step)\n")


def _scratch_named(tmp_path, name: str, body: str) -> Path:
    root = tmp_path / "programs"
    root.mkdir()
    (root / name).write_text(body)
    return root


def test_the_listed_dynamic_site_resolves_in_a_scratch_tree(tmp_path):
    root = _scratch_named(tmp_path, "phase3_one_shot_runner.py", _DYNAMIC_BODY)
    used: dict = {}
    assert [s for _, _, s in call_sites(root, used)] == [("DT2", "DT3")]
    assert used == {("phase3_one_shot_runner.py", "atpg_librelane_views", "step"): 1}


def test_a_new_dynamic_call_beside_a_listed_one_is_unresolved(tmp_path):
    root = _scratch_named(tmp_path, "phase3_one_shot_runner.py", _DYNAMIC_BODY + (
        "def some_new_step(project, step):\n"
        "    return _ll.selected_mode(project, step)\n"))
    sites = call_sites(root)
    unresolved = [(f, line) for f, line, s in sites if not s]
    assert unresolved == [("phase3_one_shot_runner.py", 5)]


def test_a_second_call_inside_the_listed_function_is_counted_twice(tmp_path):
    root = _scratch_named(tmp_path, "phase3_one_shot_runner.py", (
        "import librelane_contract as _ll\n"
        "def atpg_librelane_views(project, step):\n"
        "    a = _ll.selected_mode(project, step)\n"
        "    return a, _ll.selected_mode(project, step)\n"))
    used: dict = {}
    call_sites(root, used)
    assert used != {key: 1 for key in DYNAMIC_SITES}
    assert used[("phase3_one_shot_runner.py", "atpg_librelane_views", "step")] == 2


# A wrapped dynamic argument must still name one finite, registered source.
_OUTPUT_CONDITION_BODY = (
    "from librelane_contract import selected_mode\n"
    "def _output_not_owed(project, selection):\n"
    "    return selected_mode(project, str(selection.get('step')))\n")


def test_an_unlisted_output_condition_site_remains_unresolved(tmp_path):
    root = _scratch_named(tmp_path, "flow_compliance_check.py", (
        _OUTPUT_CONDITION_BODY.replace("_output_not_owed", "a_new_output_condition")))
    used: dict = {}
    assert call_sites(root, used) == [("flow_compliance_check.py", 3, None)]
    assert used == {}


def test_output_condition_context_cannot_resolve_a_missing_or_unknown_step(
        tmp_path, monkeypatch):
    root = _scratch_named(tmp_path, "flow_compliance_check.py", _OUTPUT_CONDITION_BODY)
    flow = tmp_path / "flow.yaml"
    monkeypatch.setitem(globals(), "FLOW_OUTPUT_CONDITIONS_PATH", flow)
    contexts = (
        None,                        # absent canonical context
        "[malformed",               # unreadable canonical context
        "steps: []\n",               # no finite population
        "steps:\n- id: '23'\n  output_conditions:\n    record:\n"
        "      librelane_step_mode: {}\n",  # missing selection step
        "steps:\n- id: '23'\n  output_conditions:\n    record:\n"
        "      librelane_step_mode: {step: UNKNOWN}\n",
    )
    for context in contexts:
        if context is not None:
            flow.write_text(context)
        assert call_sites(root) == [("flow_compliance_check.py", 3, None)], context
