#!/usr/bin/env python3
"""The registry is an AUTHORISATION, so every one of its refusals is a test.

"OpenROAD is allowed" authorises nothing. `timing.hold` with `margin_ps` in
[0, 500] and `max_buffer_percent` in (0, 5] authorises one bounded action. The
difference between those two sentences is entirely made of the checks below, and
each one is here because its opposite is a plausible entry somebody could add
next week without noticing what it opened.

The registry is also the only place that says which of the flow's 21 declared
`closed_loop` edges can actually be executed. `test_registry_enumerates_exactly
_the_flow_declarations` is the drift guard for that: add a `closed_loop` block to
the flow and this file goes red until the registry says what does or does not
execute it. An edge that were merely absent here would be invisible rather than
honest, which is the failure one level up from an unexecuted declaration.
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest
import yaml

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from _ppa import closure  # noqa: E402

PLUGIN = pathlib.Path(__file__).resolve().parents[2]
REGISTRY = PLUGIN / "config" / "ppa_actuator_registry.yaml"
SCHEMA = PLUGIN / "schemas" / "ppa" / "actuator_registry.v1.schema.json"
FLOW = PLUGIN / "flow" / "phase1_phase2_phase3.yaml"


def _write(tmp_path, doc) -> pathlib.Path:
    p = tmp_path / "reg.yaml"
    p.write_text(yaml.safe_dump(doc, sort_keys=False), encoding="utf-8")
    return p


def _minimal() -> dict:
    """The smallest registry that LOADS. Every negative test below mutates one
    field of this and asserts the load refuses, so the positive control and the
    negative controls differ by exactly the thing under test."""
    return {
        "schema": closure.SCHEMA_REGISTRY,
        "domains": {
            "d.one": {
                "metric": "d.one.count", "unit": "count", "direction": "minimize",
                "binding": "DECLARED_ONLY",
                "satisfied_when": {"op": "<=", "value": 0},
            },
        },
        "actuators": {
            "a.one": {
                "summary": "s", "binding": "DECLARED_ONLY", "wrapper": {},
                "blast_radius": "DECK",
                "resource_ceilings": {"wall_seconds": 1, "max_invocations_per_run": 1},
                "rollback": "SNAPSHOT_RESTORE",
                "remeasure_domains": ["d.one"],
            },
        },
        "controllers": {},
        "edges": {"20": {"controller": None}},
    }


# --------------------------------------------------------------------------
# The shipped file
# --------------------------------------------------------------------------

def test_shipped_registry_and_schema_are_present():
    assert REGISTRY.is_file(), f"{REGISTRY} missing"
    assert SCHEMA.is_file(), f"{SCHEMA} missing"
    doc = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert doc["$id"] == closure.SCHEMA_REGISTRY


def test_shipped_registry_loads_and_every_executable_claim_resolves():
    """An unverified claim of executability is the same defect one level up as
    an unexecuted `closed_loop`: a promise nothing checks."""
    reg = closure.load_registry(REGISTRY)
    problems = reg.verify_bindings()
    assert problems == [], "\n".join(problems)


def test_registry_enumerates_exactly_the_flow_declarations():
    """The drift guard. 21 declared, 21 listed, no more and no fewer.

    RAW ids: the flow declares `A7` and `A9` as strings and `20` as an int.
    Normalising them is how `blocks_on` lost edges before (D5-EDGE-UNRESOLVED),
    so the comparison is on `str(id)` and nothing else is coerced.
    """
    flow = yaml.safe_load(FLOW.read_text(encoding="utf-8"))
    declared = {str(s["id"]): s["closed_loop"]
                for s in flow["steps"] if s.get("closed_loop")}
    assert declared, "the flow declares no closed_loop at all -- a zero " \
                     "denominator is a refusal, not a pass"
    reg = closure.load_registry(REGISTRY)
    assert set(reg.edges) == set(declared), (
        f"registry/flow drift.\n"
        f"  in flow, not in registry: {sorted(set(declared) - set(reg.edges))}\n"
        f"  in registry, not in flow: {sorted(set(reg.edges) - set(declared))}")


def test_registry_repeats_the_flows_fallback_target_for_every_edge():
    """A copied field that nobody compares is a field that rots."""
    flow = yaml.safe_load(FLOW.read_text(encoding="utf-8"))
    declared = {str(s["id"]): s["closed_loop"]
                for s in flow["steps"] if s.get("closed_loop")}
    raw = yaml.safe_load(REGISTRY.read_text(encoding="utf-8"))
    for edge_id, spec in raw["edges"].items():
        want = str(declared[str(edge_id)]["fallback_to"])
        assert str(spec["fallback_to"]) == want, (
            f"edge {edge_id}: registry says fallback_to={spec['fallback_to']!r}, "
            f"flow says {want!r}")


def test_an_unbound_edge_is_declared_only_and_is_not_a_success():
    """The honesty requirement, asserted on the shipped file as it stands."""
    reg = closure.load_registry(REGISTRY)
    status = reg.edge_status()
    for edge_id, cid in reg.edges.items():
        if cid is None:
            assert status[edge_id] == "DECLARED_ONLY"
    assert not closure.Outcome.DECLARED_ONLY.is_success()
    assert closure.Outcome.DECLARED_ONLY.exit_code() == 2, (
        "a DECLARED_ONLY edge must be NOT CHECKED (2). 0 would let a flow gate "
        "read an unexecuted declaration as green; 1 would claim a finding about "
        "silicon from a loop that never ran.")


# --------------------------------------------------------------------------
# The prohibitions. Each is a NEGATIVE fixture: the load must REFUSE.
# --------------------------------------------------------------------------

def test_positive_control_the_minimal_registry_loads(tmp_path):
    """Without this, every refusal below could be passing for the wrong reason."""
    reg = closure.load_registry(_write(tmp_path, _minimal()))
    assert set(reg.edges) == {"20"}


@pytest.mark.parametrize("key", ["shell", "shell_command", "command_line"])
def test_a_wrapper_may_not_carry_a_shell_line(tmp_path, key):
    """There is no shell in the executor for it to reach, and a registry that
    accepted the key would let an author believe otherwise."""
    doc = _minimal()
    doc["actuators"]["a.one"]["binding"] = "EXECUTABLE"
    doc["actuators"]["a.one"]["wrapper"] = {"program": "true_prog", key: "rm -rf /"}
    with pytest.raises(closure.RegistryError, match="argv, never a shell line"):
        closure.load_registry(_write(tmp_path, doc))


@pytest.mark.parametrize("program", [
    "../../etc/passwd", "/bin/sh", "sub/dir/prog", "prog.py", "pro-gram", "",
])
def test_a_wrapper_program_must_be_a_bare_name(tmp_path, program):
    """Refused BEFORE resolution. Resolving first and checking afterwards is how
    a `..` gets to be a real path for one instant."""
    doc = _minimal()
    doc["actuators"]["a.one"]["binding"] = "EXECUTABLE"
    doc["actuators"]["a.one"]["wrapper"] = {"program": program, "argv_template": []}
    with pytest.raises(closure.RegistryError, match="bare program name"):
        closure.load_registry(_write(tmp_path, doc))


@pytest.mark.parametrize("name", sorted(closure.FORBIDDEN_PARAM_NAMES))
def test_no_parameter_may_smuggle_a_command(tmp_path, name):
    """The check is on the NAME because the value is caller-shaped and the name
    is author-shaped: a typed field called `script` is an unbounded action with
    a schema drawn round it."""
    doc = _minimal()
    doc["actuators"]["a.one"]["parameters"] = {name: {"type": "string"}}
    with pytest.raises(closure.RegistryError, match="forbidden"):
        closure.load_registry(_write(tmp_path, doc))


def test_a_numeric_parameter_must_declare_a_unit(tmp_path):
    doc = _minimal()
    doc["actuators"]["a.one"]["parameters"] = {"m": {"type": "number", "maximum": 5}}
    with pytest.raises(closure.RegistryError, match="declares no unit"):
        closure.load_registry(_write(tmp_path, doc))


def test_an_actuator_must_declare_resource_ceilings(tmp_path):
    doc = _minimal()
    del doc["actuators"]["a.one"]["resource_ceilings"]
    with pytest.raises(closure.RegistryError, match="not authorised"):
        closure.load_registry(_write(tmp_path, doc))


def test_an_actuator_must_name_something_to_re_measure(tmp_path):
    """An action whose effect nobody re-measures is an action with no evidence."""
    doc = _minimal()
    doc["actuators"]["a.one"]["remeasure_domains"] = []
    with pytest.raises(closure.RegistryError, match="no evidence"):
        closure.load_registry(_write(tmp_path, doc))


def test_rollback_none_is_admissible_only_at_the_smallest_blast_radius(tmp_path):
    doc = _minimal()
    doc["actuators"]["a.one"]["rollback"] = "NONE"
    doc["actuators"]["a.one"]["blast_radius"] = "FULL_IMPLEMENTATION"
    with pytest.raises(closure.RegistryError, match="cannot be undone"):
        closure.load_registry(_write(tmp_path, doc))
    doc["actuators"]["a.one"]["blast_radius"] = "NET"
    closure.load_registry(_write(tmp_path, doc))          # NET is fine


def test_an_argv_placeholder_must_be_a_declared_parameter(tmp_path):
    doc = _minimal()
    doc["actuators"]["a.one"]["binding"] = "EXECUTABLE"
    doc["actuators"]["a.one"]["wrapper"] = {
        "program": "ppa_closure_run", "argv_template": ["--x", "{undeclared}"]}
    with pytest.raises(closure.RegistryError, match="not a declared parameter"):
        closure.load_registry(_write(tmp_path, doc))


def test_a_declared_only_entry_may_not_name_a_program(tmp_path):
    """So that the label and the tree cannot disagree."""
    doc = _minimal()
    doc["actuators"]["a.one"]["wrapper"] = {"program": "ppa_closure_run"}
    with pytest.raises(closure.RegistryError, match="name no program"):
        closure.load_registry(_write(tmp_path, doc))


def test_an_executable_domain_must_say_how_its_number_is_read(tmp_path):
    doc = _minimal()
    doc["domains"]["d.one"]["binding"] = "EXECUTABLE"
    doc["domains"]["d.one"]["measure"] = {
        "program": "ppa_closure_run", "argv_template": []}
    with pytest.raises(closure.RegistryError, match="not a measurement"):
        closure.load_registry(_write(tmp_path, doc))


def test_a_controller_must_optimise_something_it_re_measures(tmp_path):
    doc = _minimal()
    doc["domains"]["d.two"] = dict(doc["domains"]["d.one"], metric="d.two.count")
    doc["controllers"]["c.one"] = {
        "summary": "s", "objective_domain": "d.two", "actuator": "a.one",
        "plan": [{}],
        "stop": {"max_iterations": 1, "plateau_patience": 1, "wall_seconds": 1},
    }
    with pytest.raises(closure.RegistryError, match="must be the thing being re-measured"):
        closure.load_registry(_write(tmp_path, doc))


def test_a_controller_must_declare_a_stop_condition(tmp_path):
    """A loop with no declared stop condition is a loop."""
    doc = _minimal()
    doc["controllers"]["c.one"] = {
        "summary": "s", "objective_domain": "d.one", "actuator": "a.one",
        "plan": [{}], "stop": {"max_iterations": 1, "plateau_patience": 1},
    }
    with pytest.raises(closure.RegistryError, match="stop.wall_seconds is required"):
        closure.load_registry(_write(tmp_path, doc))


def test_a_controller_must_declare_a_non_empty_plan(tmp_path):
    doc = _minimal()
    doc["controllers"]["c.one"] = {
        "summary": "s", "objective_domain": "d.one", "actuator": "a.one",
        "plan": [],
        "stop": {"max_iterations": 1, "plateau_patience": 1, "wall_seconds": 1},
    }
    with pytest.raises(closure.RegistryError, match="declared ladder"):
        closure.load_registry(_write(tmp_path, doc))


def test_a_registry_with_no_edges_is_a_refusal_not_a_clean_report(tmp_path):
    """A ZERO DENOMINATOR IS A REFUSAL. "0 unbound edges" over a document that
    describes nothing is the empty-corpus green three systems here have shipped."""
    doc = _minimal()
    doc["edges"] = {}
    with pytest.raises(closure.RegistryError, match="declares no edges"):
        closure.load_registry(_write(tmp_path, doc))


def test_an_unreadable_registry_is_a_refusal_not_an_empty_one(tmp_path):
    """"I could not read it" and "I read it and it was empty" must never produce
    the same verdict."""
    missing = tmp_path / "not_here.yaml"
    with pytest.raises(closure.RegistryError, match="not found"):
        closure.load_registry(missing)
    bad = tmp_path / "bad.yaml"
    bad.write_text("{{{ not yaml", encoding="utf-8")
    with pytest.raises(closure.RegistryError):
        closure.load_registry(bad)
    wrong = tmp_path / "wrong.yaml"
    wrong.write_text(yaml.safe_dump({"schema": "something.else"}), encoding="utf-8")
    with pytest.raises(closure.RegistryError, match="declares schema"):
        closure.load_registry(wrong)


# --------------------------------------------------------------------------
# Parameter binding: the ceiling IS the authorisation.
# --------------------------------------------------------------------------

def test_a_request_above_the_ceiling_is_refused_and_never_clamped():
    """Silently clamping would let a caller ask for a runaway budget and be told
    it got what it asked for."""
    reg = closure.load_registry(REGISTRY)
    act = reg.actuators["pnr.deck.emit_hold_repair_block"]
    with pytest.raises(closure.ParameterError, match="above declared maximum"):
        act.bind_params({"margin_ps": 0, "max_buffer_percent": 9,
                         "out_path": "pnr.tcl"})
    with pytest.raises(closure.ParameterError, match="not above declared"):
        act.bind_params({"margin_ps": 0, "max_buffer_percent": 0,
                         "out_path": "pnr.tcl"})
    ok = act.bind_params({"margin_ps": 0, "max_buffer_percent": 5,
                          "out_path": "pnr.tcl"})
    assert ok["max_buffer_percent"] == 5


def test_an_undeclared_parameter_is_refused_not_ignored():
    """An unknown key is how a caller believes it configured something it did not."""
    reg = closure.load_registry(REGISTRY)
    act = reg.actuators["pnr.deck.emit_hold_repair_block"]
    with pytest.raises(closure.ParameterError, match="undeclared parameter"):
        act.bind_params({"margin_ps": 0, "max_buffer_percent": 5,
                         "out_path": "pnr.tcl", "allow_setup_violations": True})


@pytest.mark.parametrize("escape", [
    "../outside.tcl", "../../etc/passwd", "/etc/passwd", "a/../../b.tcl",
])
def test_a_path_parameter_may_not_escape_the_implementation_root(tmp_path, escape):
    """The blast radius the registry declares is the blast radius the action gets."""
    reg = closure.load_registry(REGISTRY)
    act = reg.actuators["pnr.deck.emit_hold_repair_block"]
    impl = tmp_path / "impl"
    impl.mkdir()
    params = {"margin_ps": 0, "max_buffer_percent": 5, "out_path": escape}
    with pytest.raises(closure.ParameterError):
        act.build_argv(impl, act.bind_params(params))


def test_a_symlink_out_of_the_root_does_not_widen_the_blast_radius(tmp_path):
    """A plain `..` check misses this one, which is why the check is on the
    RESOLVED path with the root resolved too."""
    reg = closure.load_registry(REGISTRY)
    act = reg.actuators["pnr.deck.emit_hold_repair_block"]
    impl = tmp_path / "impl"
    impl.mkdir()
    (tmp_path / "outside").mkdir()
    (impl / "escape").symlink_to(tmp_path / "outside", target_is_directory=True)
    params = act.bind_params({"margin_ps": 0, "max_buffer_percent": 5,
                              "out_path": "escape/evil.tcl"})
    with pytest.raises(closure.ParameterError, match="outside the implementation root"):
        act.build_argv(impl, params)


def test_the_built_argv_is_a_list_and_names_the_interpreter_and_the_program(tmp_path):
    """No shell, and nothing that a shell would have to be asked to split."""
    reg = closure.load_registry(REGISTRY)
    act = reg.actuators["pnr.deck.emit_hold_repair_block"]
    impl = tmp_path / "impl"
    impl.mkdir()
    argv = act.build_argv(impl, act.bind_params(
        {"margin_ps": 20, "max_buffer_percent": 3, "out_path": "pnr.tcl"}))
    assert isinstance(argv, list) and all(isinstance(a, str) for a in argv)
    assert argv[0] == sys.executable
    assert argv[1].endswith("openroad_hold_repair_tcl_gen.py")
    assert "--margin-ps" in argv and "20" in argv
    assert str((impl / "pnr.tcl").resolve()) in argv


@pytest.mark.parametrize("rel", [
    "programs/_ppa/closure.py", "programs/ppa_closure_run.py"])
def test_the_executor_never_uses_a_shell(rel):
    """Asserted on the PARSED SOURCE, so the prohibition survives a refactor
    that the behavioural tests above would not notice.

    Parsed, not grepped: both files DISCUSS `shell=True` in their prose, and a
    substring check that a comment can trip is a check whose green means
    "nobody wrote that word", not "nobody does that thing".
    """
    import ast
    tree = ast.parse((PLUGIN / rel).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            for kw in node.keywords:
                assert kw.arg != "shell", (
                    f"{rel}:{node.lineno} passes a `shell` keyword to a call")
            name = ast.unparse(node.func) if hasattr(ast, "unparse") else ""
            assert name not in ("os.system", "os.popen"), (
                f"{rel}:{node.lineno} calls {name}")
    assert "subprocess.run(" in (PLUGIN / rel).read_text(encoding="utf-8") \
        or rel.endswith("ppa_closure_run.py")


def test_the_registry_digest_is_canonical_and_stable():
    """The identity of the authorisation a run acted under. Two loads of the
    same bytes are the same authorisation."""
    a = closure.load_registry(REGISTRY).digest()
    b = closure.load_registry(REGISTRY).digest()
    assert a == b and a.startswith("sha256:")


def test_a_template_slot_that_cannot_always_be_filled_is_refused(tmp_path):
    """MEASURED while writing the round-trip tests: an optional parameter with
    no default, referenced from argv_template, builds an argv that cannot be
    rendered — and the failure surfaced mid-run as HANDOFF_REQUIRED, which is an
    authorisation defect wearing the costume of a design finding. It is decided
    at load now, not on the third iteration."""
    doc = _minimal()
    doc["actuators"]["a.one"]["binding"] = "EXECUTABLE"
    doc["actuators"]["a.one"]["wrapper"] = {
        "program": "ppa_closure_run", "argv_template": ["--x", "{maybe}"]}
    doc["actuators"]["a.one"]["parameters"] = {
        "maybe": {"type": "string", "required": False}}
    with pytest.raises(closure.RegistryError, match="cannot always be filled"):
        closure.load_registry(_write(tmp_path, doc))
    # A default makes the same slot fillable, so it loads.
    doc["actuators"]["a.one"]["parameters"]["maybe"]["default"] = "x"
    closure.load_registry(_write(tmp_path, doc))
