#!/usr/bin/env python3
"""`phase1_planned_consumer_starved_check` — the rule and its reverse.

WHAT THIS FILE HAS TO PROVE, AND WHY IN THIS ORDER
==================================================
A gate that only demonstrates its FAIL case proves nothing about what it
catches: a program that returns 1 unconditionally would pass such a suite.
Every fail case here is therefore paired with a reverse case that differs in
exactly ONE property and must still return 0. The pairs are:

    FAIL                                  REVERSE (must still PASS)
    silently empty + planned consumer     the same layer, emptiness DECLARED
    silently empty + planned consumer     the same layer, carrying CONTENT
    silently empty + planned consumer     silently empty, NO declared consumer
    silently empty + planned consumer     consumer not PLANNED (condition unmet)

The third pair is the one that matters most. 77 of the layers in this repo's
tracked corpus are empty; 72 of them say so. A rule that fired on emptiness
alone would score as a fix and would be a false-positive machine. The reverse
case pins that the trigger is the CONSUMER, not the emptiness.

THE PRE-FIX CONTROL IS NOT IN THIS FILE
=======================================
It cannot be: the pre-fix tree does not contain the program, so the control is
"run THIS file against a tree without the change". That is run as a tree-level
stash/restore, and its two numbers belong in the change's own record, not in an
assertion here.

REAL-DATA ANCHORS
=================
The last two tests judge PUBLISHED cells rather than fixtures the author wrote,
following `test_issue316_layergates_on_published_cells`. A gate justified only
by its own fixture has never seen a production artefact. If the corpus is not
checked out they skip; while it is there the justification is falsifiable.
chip-AGNOSTIC: the cells are named as published fixtures, never as detection
inputs — the gate keys on no name appearing here.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Optional

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
_PROG = _PROGRAMS / "phase1_planned_consumer_starved_check.py"
_REPO = _PROGRAMS.parents[3]

sys.path.insert(0, str(_PROGRAMS))

import phase1_planned_consumer_starved_check as P  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import _progress_run as _pr  # noqa: E402

#: The layer the shipped flow conditions three separate consumers on, and its
#: sibling under the same layer CODE. Spelled as flow artefacts, not as design
#: facts.
_LAYER = "L8_TIMING_WAVEFORM.json"
_SIBLING = "L8_RTL_CONSTANTS.json"

_EMPTY_SKELETON = {
    "schema_version": "1",
    "doc_class": "timing_waveform",
    "timing_windows": [],
    "timing_constants": [],
    "waveforms": [],
    "extraction_evidence": {},
}

_SIBLING_WITH_CONTENT = {
    "schema_version": "1",
    "doc_class": "rtl_constants",
    "parameters": [{"name": "WIDTH", "default": 8}],
}

#: The same layer as `_EMPTY_SKELETON`, one property changed: it carries
#: content, so the gate genuinely examines it.
_LAYER_WITH_CONTENT = {
    "schema_version": "1",
    "doc_class": "timing_waveform",
    "timing_windows": [{"name": "t_setup", "min_ns": 5}],
    "timing_constants": [],
    "waveforms": [],
    "extraction_evidence": {},
}


def _mkproject(tmp_path: Path, docs: dict) -> Path:
    proj = tmp_path / "proj"
    gd = proj / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    for name, body in docs.items():
        (gd / name).write_text(json.dumps(body, indent=1))
    return proj


def _run(project: Path, flow: Optional[Path] = None):
    argv = [sys.executable, str(_PROG), str(project)]
    if flow is not None:
        argv += ["--flow", str(flow)]
    return _pr.run(argv, capture_output=True, text=True)


# ---------------------------------------------------------------------------
# A CASE THAT ASSERTS A NEGATIVE OWNS ITS CONSUMER SET
#
# Four cases below assert something the shipped flow cannot promise:
# "this layer has no OTHER planned reader", "no OTHER planned read went
# unexamined". Those are statements about a GROWING artefact. MEASURED:
# d453eaca6 (`fix(flow): uhadc round-5 consumer captures`) added one
# `--spec phase1/generated_docs/L3_CMD_PROTOCOL.json` argument to a step-2
# clause whose `condition_files_exist` names only L8_TIMING_WAVEFORM.json.
# That is a legitimate flow edit -- the clause really does read L3 -- and it
# turned all four red at once, with the gate behaving exactly as designed.
# Restoring them by editing the fixtures would buy a green until the next
# consumer landed.
#
# So they run against a flow they OWN. Not a hand-written one: the clause
# shapes (`condition_files_exist`, the three command keys, stage/step
# conditions) are the thing under test, and a fixture flow that spelt them by
# hand would drift from the real ones silently. `_flow_keeping` PRUNES the
# shipped flow instead, so every surviving clause is a real shipped clause and
# only the POPULATION is the case's own. `_flow_keeping` refuses an empty
# result, so a flow change that removes the shapes these cases need fails
# loudly here instead of making them vacuous.
# ---------------------------------------------------------------------------
def _layers_named(clause: Any) -> set:
    """Layer CODES a gate clause reads — command and condition alike."""
    text = json.dumps(clause)
    return set(P._LAYER_REF_RE.findall(text))


def _is_clause(node: Any) -> bool:
    return isinstance(node, dict) and any(k in node for k in P._COMMAND_KEYS)


def _prune(node: Any, keep) -> Any:
    if isinstance(node, list):
        out = []
        for v in node:
            if _is_clause(v) and not keep(v):
                continue
            out.append(_prune(v, keep))
        return out
    if isinstance(node, dict):
        return {k: _prune(v, keep) for k, v in node.items()}
    return node


def _flow_keeping(tmp_path: Path, keep, why: str) -> Path:
    """The shipped flow with every gate clause `keep` rejects removed."""
    import yaml as _yaml
    path = P.resolve_flow_yaml(None)
    if not path.is_file():
        pytest.skip("shipped flow YAML not present")
    flow = _yaml.safe_load(path.read_text(encoding="utf-8"))
    pruned = _prune(flow, keep)
    kept = P.consumers_from_flow(pruned)
    assert kept, (
        "the pruned flow declares no layer consumer at all, so every case "
        "built on it would pass by having nothing to judge — which is the "
        f"vacuity these cases exist to disprove. Wanted: {why}")
    out = tmp_path / "flow_pruned.yaml"
    out.write_text(_yaml.safe_dump(pruned, sort_keys=False), encoding="utf-8")
    return out


def _condition_files(clause: Any) -> list:
    """Every `condition_files_exist` entry on a gate clause."""
    out = []
    for key in P._COMMAND_KEYS:
        val = clause.get(key)
        if isinstance(val, dict):
            out += [c for c in (val.get("condition_files_exist") or [])
                    if isinstance(c, str)]
    return out


def _reads_L3_behind_two_conditions(clause: Any) -> bool:
    """A clause that reads the command-protocol layer and cannot run until
    TWO layer files exist — the shape the plannedness case is about."""
    return "L3" in _layers_named(clause) and len(_condition_files(clause)) >= 2


def _only_the_L8_pair(clause: Any) -> bool:
    """Clauses that read the fixture's own layer pair and nothing else."""
    named = _layers_named(clause)
    return bool(named) and named <= {"L8"}


# ---------------------------------------------------------------------------
# THE RULE
# ---------------------------------------------------------------------------
def test_silent_skeleton_with_a_planned_consumer_fails(tmp_path):
    proj = _mkproject(tmp_path, {_LAYER: _EMPTY_SKELETON,
                                 _SIBLING: _SIBLING_WITH_CONTENT})
    r = _run(proj)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "EMPTY SKELETON" in r.stdout


def test_the_failure_names_the_starved_consumer(tmp_path):
    """'names the consumer' is half the rule — an unnamed FAIL leaves the
    reader to go find who cared, which is the work the gate exists to do."""
    proj = _mkproject(tmp_path, {_LAYER: _EMPTY_SKELETON,
                                 _SIBLING: _SIBLING_WITH_CONTENT})
    r = _run(proj)
    assert r.returncode == 1
    report = json.loads(
        (proj / "reports" / "phase1"
         / "phase1_planned_consumer_starved_check.json").read_text())
    findings = report["findings"]
    assert findings, report
    for f in findings:
        assert f["consumer_step"] is not None
        assert f["consumer_command"]
        assert f["consumer_step_name"]
        # the admission rule is part of the accusation: the layer's mere
        # presence is what lets the consumer run.
        assert f["admitted_by"]
    steps = {f["consumer_step"] for f in findings}
    assert len(steps) >= 2, (
        f"the shipped flow conditions consumers on this layer in more than "
        f"one step; only {steps} were named")


def test_two_documents_under_one_layer_code_are_judged_separately(tmp_path):
    """The sibling with content must not absolve the empty one.

    Resolving a consumer's layer by `L<n>_` PREFIX would pick whichever file
    sorts first and report a clean verdict about a document no consumer named
    — the same prefix-matching hole the flow's own comment records for the
    presence gate.
    """
    proj = _mkproject(tmp_path, {_LAYER: _EMPTY_SKELETON,
                                 _SIBLING: _SIBLING_WITH_CONTENT})
    r = _run(proj)
    assert r.returncode == 1
    assert _LAYER in r.stdout
    report = json.loads(
        (proj / "reports" / "phase1"
         / "phase1_planned_consumer_starved_check.json").read_text())
    by_path = {s["declared_path"]: s["state"] for s in report["layer_states"]}
    assert by_path[f"phase1/generated_docs/{_LAYER}"] == "SILENT_EMPTY"
    assert by_path[f"phase1/generated_docs/{_SIBLING}"] == "HAS_CONTENT"


# ---------------------------------------------------------------------------
# THE REVERSE CASES — each differs from the FAIL fixture in ONE property
# ---------------------------------------------------------------------------
def test_declared_emptiness_still_passes(tmp_path):
    """The design says the input carried none of this. 72 of the 77 empty
    layers in the tracked corpus do exactly this; firing on them would make
    the gate unreadable."""
    declared = dict(_EMPTY_SKELETON, no_timing_windows_in_input=True)
    proj = _mkproject(tmp_path, {_LAYER: declared,
                                 _SIBLING: _SIBLING_WITH_CONTENT})
    r = _run(proj)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "PASS" in r.stdout


def test_applicability_na_still_passes(tmp_path):
    declared = dict(_EMPTY_SKELETON, applicability="N/A")
    proj = _mkproject(tmp_path, {_LAYER: declared,
                                 _SIBLING: _SIBLING_WITH_CONTENT})
    assert _run(proj).returncode == 0


def test_a_layer_with_content_still_passes(tmp_path):
    filled = dict(_EMPTY_SKELETON,
                  timing_constants=[{"name": "t_setup", "value_ns": 5}])
    proj = _mkproject(tmp_path, {_LAYER: filled,
                                 _SIBLING: _SIBLING_WITH_CONTENT})
    assert _run(proj).returncode == 0


def test_silent_skeleton_with_no_declared_consumer_still_passes(tmp_path):
    """The trigger is the CONSUMER, not the emptiness.

    This layer is as silently empty as the failing fixture. The shipped flow
    declares no step that reads it, so the gate must not speak — and must not
    even list it, because a gate that reports every empty layer is the
    false-positive machine this one was written to avoid.
    """
    proj = _mkproject(tmp_path, {
        "L5_ADI_SPEC.json": {"schema_version": "1", "doc_class": "adi_spec",
                             "analog_blocks": [], "supplies": []},
        _LAYER: dict(_EMPTY_SKELETON, no_timing_windows_in_input=True),
        _SIBLING: _SIBLING_WITH_CONTENT,
    })
    r = _run(proj)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "L5_ADI_SPEC" not in r.stdout


def test_consumer_whose_condition_is_unmet_is_not_planned(tmp_path):
    """Plannedness, not mere declaration.

    The case is a SHIPPED clause conditioned on TWO layer files. With the
    second absent the predicate can never run, so nothing is starved and the
    gate must stay quiet even though the first layer is a silent skeleton.

    The flow is pruned to the multi-condition clauses so that the OTHER
    shipped readers of the same layer — which the flow is free to grow, and
    did — cannot decide this case. The property under test is plannedness,
    not the census of the shipped flow.
    """
    flow = _flow_keeping(
        tmp_path, _reads_L3_behind_two_conditions,
        "a shipped clause that reads L3 and is conditioned on two layer files")
    proj = _mkproject(tmp_path, {
        "L3_CMD_PROTOCOL.json": {"schema_version": "1",
                                 "doc_class": "cmd_protocol",
                                 "opcodes": [], "responses": []},
        _LAYER: dict(_EMPTY_SKELETON, no_timing_windows_in_input=True),
        _SIBLING: _SIBLING_WITH_CONTENT,
    })
    r = _run(proj, flow)
    assert r.returncode == 0, r.stdout + r.stderr
    report = json.loads(
        (proj / "reports" / "phase1"
         / "phase1_planned_consumer_starved_check.json").read_text())
    l3 = [e for e in report["examined"] if e["layer"] == "L3"]
    assert l3, "the L3 consumer should still be listed as examined"
    assert all(not e["planned"] for e in l3), l3
    assert all(e["layer_state"] == "SILENT_EMPTY" for e in l3), l3


def test_waiver_suppresses_but_is_recorded(tmp_path):
    proj = _mkproject(tmp_path, {_LAYER: _EMPTY_SKELETON,
                                 _SIBLING: _SIBLING_WITH_CONTENT})
    (proj / "waivers.json").write_text(json.dumps({
        P.WAIVER_KEY: ("the timing layer is intentionally empty for this "
                       "run and the downstream consumers are known to be "
                       "no-ops here"),
    }))
    r = _run(proj)
    assert r.returncode == 0, r.stdout + r.stderr
    report = json.loads(
        (proj / "reports" / "phase1"
         / "phase1_planned_consumer_starved_check.json").read_text())
    assert report["verdict"] == "WAIVED"
    assert report["findings"], "a waiver must suppress the exit code, not the "\
                               "finding"


def test_no_generated_docs_is_a_skip_not_a_pass(tmp_path):
    proj = tmp_path / "bare"
    proj.mkdir()
    r = _run(proj)
    assert r.returncode == 0
    assert "SKIP" in r.stdout


# ---------------------------------------------------------------------------
# DERIVATION INVARIANTS
# ---------------------------------------------------------------------------
def _flow():
    import yaml
    path = P.resolve_flow_yaml(None)
    if not path.is_file():
        pytest.skip("shipped flow YAML not present")
    return yaml.safe_load(path.read_text())


def test_the_producing_step_is_never_counted_as_a_consumer():
    """The step that emits the layers lists every one of them in its
    `required_outputs`. Counting that as consumption would make the producer
    starve itself and fire on every project."""
    consumers = P.consumers_from_flow(_flow())
    assert consumers, "the shipped flow declares no layer consumer at all"
    producing = {s.get("id") for s in _flow()["steps"]
                 if any("phase1/generated_docs/" in str(o)
                        for o in (s.get("required_outputs") or []))}
    assert producing, "no step declares a layer as a required output"
    assert not (producing & {c["step"] for c in consumers})


def test_consumers_are_read_out_of_the_flow_not_hardcoded():
    """No layer name is spelled in the program's own source; the set comes
    from the flow definition, so wiring a new consumer extends the gate."""
    src = _PROG.read_text()
    consumers = P.consumers_from_flow(_flow())
    layers = {c["layer"] for c in consumers}
    assert len(layers) >= 4, layers
    for lay in layers:
        assert f'"{lay}_' not in src and f"'{lay}_" not in src


def test_condition_only_references_count_as_consumption():
    """A predicate whose argv does not spell the layer out but whose
    `condition_files_exist` names it is still a consumer — that is the purest
    form of the defect, and reading only commands would miss it."""
    consumers = P.consumers_from_flow(_flow())
    cond_only = [c for c in consumers if not c["named_in_command"]]
    assert cond_only, ("the shipped flow has at least one consumer admitted "
                       "purely by a layer's existence; none was found")


# ---------------------------------------------------------------------------
# UNEXAMINED IS NOT CLEAN
#
# Three layer states — LAYER_ABSENT, UNPARSEABLE, NO_CONTENT_SCHEMA — are
# states in which this gate reads NOTHING about emptiness. Before the
# disclosure they printed the same unqualified `[PASS]` as a layer that was
# read and found healthy, and the summary counted them among the clean reads.
# The pair below differs in exactly ONE property: whether the planned layer
# parses. Both return 0 — the point is not the exit code, it is that the two
# verdicts must not read the same.
# ---------------------------------------------------------------------------
def test_an_unexaminable_planned_layer_is_disclosed_not_counted_as_clean(
        tmp_path):
    # Pruned to the clauses that read only this fixture's layer pair: the
    # assertion below is `{UNPARSEABLE}` EXACTLY, so any shipped consumer of a
    # layer this project does not carry would add a LAYER_ABSENT and make the
    # case about the flow's consumer census instead of about the disclosure.
    flow = _flow_keeping(tmp_path, _only_the_L8_pair,
                         "a shipped clause reading only the L8 pair")
    proj = _mkproject(tmp_path, {_SIBLING: _SIBLING_WITH_CONTENT})
    (proj / "phase1" / "generated_docs" / _LAYER).write_text("not json {")
    r = _run(proj, flow)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "NOT EXAMINED" in r.stdout, (
        "an unparseable planned layer was never read for emptiness; a verdict "
        "that does not say so passes an unexamined layer off as a clean one\n"
        + r.stdout)
    assert "DID examine" in r.stdout, (
        "the [PASS] line must be qualified, not merely footnoted\n" + r.stdout)
    report = json.loads(
        (proj / "reports" / "phase1"
         / "phase1_planned_consumer_starved_check.json").read_text())
    blind = P.unexamined_planned(report)
    assert blind, report["examined"]
    assert {e["layer_state"] for e in blind} == {"UNPARSEABLE"}
    # the count is SUBTRACTED from the clean ones, not added alongside them
    planned = [e for e in report["examined"] if e["planned"]]
    line = P.summary_line(report)
    assert f"{len(planned) - len(blind)} examined" in line, line
    assert f"{len(blind)} NOT EXAMINED" in line, line


def test_a_fully_examined_project_says_nothing_about_unexamined_layers(
        tmp_path):
    """REVERSE of the above, one property changed: the same layer PARSES.

    Without this the disclosure could be an unconditional string and the file
    would still be green."""
    flow = _flow_keeping(tmp_path, _only_the_L8_pair,
                         "a shipped clause reading only the L8 pair")
    proj = _mkproject(tmp_path, {_LAYER: _LAYER_WITH_CONTENT,
                                 _SIBLING: _SIBLING_WITH_CONTENT})
    r = _run(proj, flow)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "NOT EXAMINED" not in r.stdout, (
        "every planned read WAS examined; inventing a disclosure here would "
        "make the clause noise the reader learns to skip\n" + r.stdout)
    assert "DID examine" not in r.stdout, r.stdout
    report = json.loads(
        (proj / "reports" / "phase1"
         / "phase1_planned_consumer_starved_check.json").read_text())
    assert P.unexamined_planned(report) == []
    planned = [e for e in report["examined"] if e["planned"]]
    assert f"{len(planned)} examined and 0 starved" in P.summary_line(report)


def test_a_layer_with_no_recognisable_collection_is_unexamined_too(tmp_path):
    """NO_CONTENT_SCHEMA is the state the corpus actually carries: the doc
    parses, but nothing in it is a collection this gate can size, so 'not
    empty' was never established. Same disclosure, different state."""
    flow = _flow_keeping(tmp_path, _only_the_L8_pair,
                         "a shipped clause reading only the L8 pair")
    proj = _mkproject(tmp_path, {_LAYER: {"schema_version": "1",
                                          "doc_class": "timing_waveform",
                                          "note": "a scalar-only payload"},
                                 _SIBLING: _SIBLING_WITH_CONTENT})
    r = _run(proj, flow)
    assert r.returncode == 0, r.stdout + r.stderr
    # stdout FIRST, deliberately: on a tree without the change `P` carries no
    # `unexamined_planned` at all, and a test that dies of AttributeError
    # proves only that a symbol is new. This assertion fails on the OUTPUT.
    assert "NOT EXAMINED" in r.stdout, r.stdout
    report = json.loads(
        (proj / "reports" / "phase1"
         / "phase1_planned_consumer_starved_check.json").read_text())
    blind = P.unexamined_planned(report)
    assert {e["layer_state"] for e in blind} == {"NO_CONTENT_SCHEMA"}, report


# ---------------------------------------------------------------------------
# REAL-DATA ANCHORS (published cells, not author-written fixtures)
# ---------------------------------------------------------------------------
def _published(*parts) -> Path:
    p = _REPO.joinpath("benchmark-data", *parts)
    if not (p / "phase1" / "generated_docs").is_dir():
        pytest.skip(f"published cell not checked out: {'/'.join(parts)}")
    return p


def test_published_cell_with_the_defect_fails(tmp_path):
    """Copied, not judged in place: the gate writes a report next to the
    project and the tracked corpus must stay clean."""
    import shutil
    src = _published("ic", "opentitan_aes")
    dst = tmp_path / "cell"
    shutil.copytree(src / "phase1", dst / "phase1")
    r = _run(dst)
    assert r.returncode == 1, r.stdout + r.stderr
    assert "SDC" in r.stdout or "sdc" in r.stdout, (
        "the SDC-generating step is the consumer this cell starves")


def test_published_cell_without_the_defect_passes(tmp_path):
    import shutil
    src = _published("evaluation", "phase1_parity", "i2c")
    dst = tmp_path / "cell"
    shutil.copytree(src / "phase1", dst / "phase1")
    r = _run(dst)
    assert r.returncode == 0, r.stdout + r.stderr
