"""A macro somebody else places has no die edge, so it owes no die steps.

vibe-ic#2277, flow steps 15.5ic / 26.5ic / 37.5ic and step 31. MEASURED on live
main 79506306d (lane icspm4, run1).

DIE STEPS (class a, ABSENT SUBJECT). All three rows condition on ROUTER FILES --
`input/submission_template/slots/*.yaml` OR `SELF_TAPEOUT.txt` -- and the only
N/A a hardmacro was offered is `NO_TEMPLATE.txt`. Since 0.5ic's fetch was wired,
a PDK with a LIVE shuttle in the registry has the operator's whole CATALOGUE
ingested as `slots/*.yaml` whether or not the design bought a slot, and no
`NO_TEMPLATE.txt` is written. So a delivery whose own input declares
`deliverable=HARDMACRO` with `operator_template.path/.slot` null matched the
`any_of`, all three rows were judged APPLICABLE, every output was owed, the
producers correctly wrote nothing (`tapeout_precheck` step_applies=false,
`tapeout_docs_gen` NOT_APPLICABLE, `die_finishing_gen._hardmacro_skip`), and the
rows read MISSING -- failing stage3 and stage4 compliance. RULINGS R12
(2026-09-07): a hardmacro exposes pins, gets no pad ring and no die ring.

STEP 31 (class c, PRODUCER GAP). `reports/phase3/perc_sweep.json` is a step-31
`required_output` and `perc_corpus_sweep` is named under its `programs:`, but no
clause invoked it -- the reach clause only READS the document. 8 of 9 outputs
were produced and the ninth was owed by nobody. `flow_declared_producer_run`
could not adopt it either: it matched only `--json`, and this producer writes
through `--report` because its own `--json` is a boolean.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PROGRAMS = HERE.parent
PLUGIN = PROGRAMS.parent
sys.path.insert(0, str(PROGRAMS))
sys.path.insert(0, str(HERE))

import pytest                                            # noqa: E402

import _tapeout_declaration as TD                        # noqa: E402
import _owner_declared as _OD                              # noqa: E402
import flow_compliance_check as F                        # noqa: E402
import flow_declared_producer_run as P                   # noqa: E402

yaml = pytest.importorskip("yaml")

_FLOW = PLUGIN / "flow" / "phase1_phase2_phase3.yaml"
_DIE_STEPS = ("15.5ic", "26.5ic", "37.5ic")


def _steps():
    doc = yaml.safe_load(_FLOW.read_text(encoding="utf-8"))
    return {str(s["id"]): s for s in doc["steps"]}


def _project(tmp_path, *, deliverable="HARDMACRO", operator=None,
             declaration=True, self_tapeout=False):
    """A run whose 0.5ic left the operator's CATALOGUE on disk."""
    p = tmp_path / "run"
    tmpl = p / "input" / "submission_template"
    (tmpl / "slots").mkdir(parents=True)
    if self_tapeout:
        (tmpl / "SELF_TAPEOUT.txt").write_text("own tape-out\n")
    else:
        (tmpl / "slots" / "slot_1x1.yaml").write_text("slot: slot_1x1\n")
    if declaration:
        doc, _ = TD.merge_answers(TD.blank_declaration(),
                                  {"deliverable": deliverable,
                                   "top_cell": "top"})
        _OD.attest(doc)
        assert not TD.validate(doc)
        (tmpl / "tapeout_declaration.json").write_text(json.dumps(doc))
    else:
        (tmpl / "tapeout_declaration.json").write_text("{ not json")
    (p / "input" / "step_0_5ic_answers.json").write_text(json.dumps(_OD.attest({
        "schema": "vibe-ic/step_0_5ic_answers/1",
        "operator_template": operator or {"path": None, "slot": None,
                                          "absent_reason": "no operator"},
        "answers": {"deliverable": deliverable, "top_cell": "top"}})))
    return p


def _runs(project, sid):
    return F._check_condition(project, _steps()[sid].get("condition") or {})


# --------------------------------------------------------------------------- #
# the die steps stand down BY DECLARATION
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("sid", _DIE_STEPS)
def test_a_declared_hardmacro_owes_no_die_step(tmp_path, sid):
    assert _runs(_project(tmp_path), sid) is False


@pytest.mark.parametrize("sid", _DIE_STEPS)
def test_the_skip_CITES_the_designs_own_declaration(tmp_path, sid):
    """A reviewer must be able to tell a design that declared the subject
    absent from a trigger file somebody forgot to author."""
    cited = F._delivery_declares_absence(
        _project(tmp_path),
        (_steps()[sid]["condition"] or {}).get("delivery_declares"))
    assert cited is not None
    rel, detail, _evidence = cited   # R-0915-64: third element, None here
    assert rel == "input/submission_template/tapeout_declaration.json"
    assert "HARDMACRO" in detail and "no operator slot is bound" in detail


def test_the_IP_terminal_step_stays_LIVE(tmp_path):
    """37.5ip is what this delivery DOES owe. The fix must not stand it down
    too, or the hardmacro would ship with no kit at all."""
    assert _runs(_project(tmp_path), "37.5ip") is True


# --------------------------------------------------------------------------- #
# negative controls: a design WITH a die keeps every row live
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("sid", _DIE_STEPS)
def test_a_DIE_against_the_same_catalogue_keeps_the_row_live(tmp_path, sid):
    assert _runs(_project(tmp_path, deliverable="DIE"), sid) is True


@pytest.mark.parametrize("sid", _DIE_STEPS)
def test_a_self_tapeout_keeps_the_row_live(tmp_path, sid):
    assert _runs(_project(tmp_path, deliverable="DIE", self_tapeout=True),
                 sid) is True


@pytest.mark.parametrize("sid", _DIE_STEPS)
def test_a_hardmacro_that_BOUGHT_a_slot_is_refused(tmp_path, sid):
    """The owner's IP and IC route declarations cannot both be accepted."""
    with pytest.raises(ValueError,
                       match="HARDMACRO.*bought shuttle slot"):
        _runs(_project(tmp_path, operator={"path": "t.yaml",
                                          "slot": "slot_1x1"}), sid)


@pytest.mark.parametrize("sid", _DIE_STEPS)
def test_an_unreadable_declaration_RUNS_the_step(tmp_path, sid):
    """Absence of a declaration is not a declaration of absence."""
    assert _runs(_project(tmp_path, declaration=False), sid) is True


def test_a_deliverable_the_clause_does_not_list_runs_the_step(tmp_path):
    assert F._delivery_declares_absence(
        _project(tmp_path, deliverable="NOT_DETERMINED"),
        {"declaration": "input/submission_template/tapeout_declaration.json",
         "field": "answers.deliverable", "absent_when": ["HARDMACRO"]}) is None


def test_a_malformed_predicate_declares_nothing(tmp_path):
    p = _project(tmp_path)
    for spec in (None, {}, "HARDMACRO",
                 {"declaration": "/etc/passwd", "field": "answers.deliverable",
                  "absent_when": ["HARDMACRO"]},
                 {"declaration": "input/submission_template/"
                                 "tapeout_declaration.json",
                  "field": "answers.deliverable", "absent_when": []},
                 {"declaration": "input/submission_template/"
                                 "tapeout_declaration.json",
                  "field": "answers.no_such_field",
                  "absent_when": ["HARDMACRO"]}):
        assert F._delivery_declares_absence(p, spec) is None, spec


# --------------------------------------------------------------------------- #
# step 31: the producer gap
# --------------------------------------------------------------------------- #
def _clauses():
    return P.declared_producer_clauses(_FLOW)


def test_the_perc_sweep_document_now_has_a_declared_producer():
    rows = [c for c in _clauses()
            if c["target"] == "reports/phase3/perc_sweep.json"]
    assert len(rows) == 1, rows
    assert rows[0]["program"] == "perc_corpus_sweep"
    assert rows[0]["step"] == "31"


def test_the_producer_is_declared_OFF_the_gate():
    """#1980 is the contract and it is not negotiable here: step 31's PERC and
    via findings are ADVISORY EVIDENCE that stays OUT of gate coverage, so the
    producer may be named under `programs:` and `program_outputs:` and must NOT
    appear in the `gate:`. A gate clause naming it is what
    `test_issue1980_advisory_evidence_tiers` refuses by name, and it is what the
    first attempt at this wiring did."""
    step31 = _steps()["31"]
    assert "perc_corpus_sweep" in step31["programs"]
    assert "perc_corpus_sweep" not in str(step31["gate"])
    entry = [e for e in step31["program_outputs"]
             if e.get("program") == "perc_corpus_sweep"]
    assert len(entry) == 1
    assert entry[0]["path"] == "reports/phase3/perc_sweep.json"
    assert entry[0]["producer_command"].split()[0] == "perc_corpus_sweep"




def test_the_reader_still_owns_the_refusal():
    """#1980 gave the refusal predicate to `sweep_reach_check`, and it still has
    it: the producer writes the document, that gate judges it."""
    gate = json.dumps(_steps()["31"]["gate"])
    assert "sweep_reach_check --report reports/phase3/perc_sweep.json" in gate


def test_the_new_channel_adopted_exactly_one_entry():
    """The blast radius, asserted rather than assumed: `producer_command` is read
    from `program_outputs` only, and these are the entries in the whole flow
    that have one.

    RE-MEASURED 2026-09-26 (T90). v1.24.73 (#2635, fd809a4c9 "declare report
    producers") put the step-17 and step-22 pre-stream receipts on THIS channel
    -- the producer declared off the gate, the gate re-measuring to its own
    `*_verdict.json` -- which is the #1980 shape this channel exists for. It
    did not move this pin, so the test was red on main from v1.24.73. Measured
    on the live yaml: arrived [('17', 'placement_legality_check'),
    ('22', 'spef_extraction_check')], departed []. Each carries a
    `producer_command` whose program is the entry's own program and whose path
    is a `required_output` of its step (asserted below, not assumed)."""
    doc = yaml.safe_load(_FLOW.read_text(encoding="utf-8"))
    carrying = [(str(st["id"]), e["program"])
                for st in doc["steps"]
                for e in (st.get("program_outputs") or [])
                if isinstance(e, dict) and e.get("producer_command")]
    # Existing FS1, Step14/23 and Step35 writers use this declared producer
    # channel. Pin every identity; each gate keeps its own verdict path.
    assert carrying == [("FS1", "fmeda_fault_injection_coverage"),
                        ("FS1", "fmeda_coverage_check"),
                        ("14", "yosys_hilomap_required_check"),
                        ("14", "yosys_script_template_check"),
                        ("14", "yosys_tiecell_recipe_order_check"),
                        ("17", "placement_legality_check"),
                        ("22", "spef_extraction_check"),
                        ("23", "hold_corner_coverage_check"),
                        ("23", "sta_assumed_clock_disclosure_check"),
                        ("23", "clock_target_record_agreement_check"),
                        ("35", "dfm_screen_check"),
                        ("31", "perc_corpus_sweep")]
    for st in doc["steps"]:
        for e in (st.get("program_outputs") or []):
            if isinstance(e, dict) and e.get("producer_command"):
                assert e["producer_command"].split()[0] == e["program"], e
                assert e["path"] in (st.get("required_outputs") or []), e
                assert e["program"] not in str(st.get("gate")) or (
                    f"--json {e['path']}" not in str(st.get("gate"))), (
                    f"step {st['id']}: the gate writes the producer's own "
                    f"document {e['path']} (R-0915-141)")


def _explicit_gate_commands_for_entry(step, entry):
    """Match the existing gate channel to this entry's own program and output.

    Use the collector's command parser, without consulting its adopted rows.
    A command for another program or target does not speak for this entry.
    """
    program, target = entry.get("program"), entry.get("path")
    if (program not in (step.get("programs") or [])
            or target not in (step.get("required_outputs") or [])):
        return []
    matching = []
    for command, _tier in P._iter_command_specs(step.get("gate") or {}):
        parts = command.split()
        output = P._JSON_RE.search(command)
        if parts and parts[0] == program and output and output.group(1) == target:
            matching.append(command)
    return matching


def _silent_entries(doc):
    """An entry is silent only when both declaration channels are absent."""
    return [(str(st["id"]), e["program"], e.get("path"))
            for st in doc["steps"]
            for e in (st.get("program_outputs") or [])
            if isinstance(e, dict) and not e.get("producer_command")
            and not _explicit_gate_commands_for_entry(st, e)]


def _neutral_output_step():
    return {"id": "NEUTRAL", "programs": ["fixture_producer"],
            "required_outputs": ["reports/neutral.json", "reports/sibling.json"],
            "program_outputs": [{"program": "fixture_producer",
                                 "path": "reports/neutral.json"}]}


def test_an_entry_without_a_producer_command_is_NOT_adopted(tmp_path):
    """Silence in BOTH channels is not a dispatch instruction. Guessing a
    producer's argv writes an output nobody asked for. FS1 is not silent:
    its explicit gate command already names its program and required output.
    """
    doc = yaml.safe_load(_FLOW.read_text(encoding="utf-8"))
    doc["steps"].append(_neutral_output_step())
    flow = tmp_path / "with_silent_entry.yaml"
    flow.write_text(yaml.safe_dump(doc), encoding="utf-8")
    silent = _silent_entries(doc)
    assert silent, "the control needs at least one silent entry to be real"
    adopted = {(c["step"], c["program"], c["target"])
               for c in P.declared_producer_clauses(flow)}
    for row in silent:
        assert row not in adopted, row


def test_the_current_FS1_gate_channel_binds_its_own_output():
    """The typed producer owns the raw report; the gate reads it separately."""
    step = _steps()["FS1"]
    entries = [e for e in step["program_outputs"]
               if e["program"] == "fmeda_fault_injection_coverage"]
    assert len(entries) == 1, entries
    entry = entries[0]
    assert entry.get("producer_command")
    assert entry["path"] == "reports/phase2/safety/fmeda_coverage.json"
    commands = _explicit_gate_commands_for_entry(step, entry)
    assert commands == [], "the gate must not write the producer-owned raw report"
    rows = [c for c in _clauses()
            if (c["step"], c["program"], c["target"])
            == ("FS1", entry["program"], entry["path"])]
    assert len(rows) == 1, rows
    assert rows[0]["command"] == entry["producer_command"]
    assert _silent_entries({"steps": [step]}) == []


def test_a_neutral_entry_without_either_command_channel_is_refused(tmp_path):
    step = _neutral_output_step()
    flow = tmp_path / "silent.yaml"
    flow.write_text(yaml.safe_dump({"steps": [step]}), encoding="utf-8")
    assert _silent_entries({"steps": [step]}) == [
        ("NEUTRAL", "fixture_producer", "reports/neutral.json")]
    assert P.declared_producer_clauses(flow) == []


@pytest.mark.parametrize("command", [
    "other_producer . --json reports/neutral.json",
    "fixture_producer . --json reports/undeclared.json",
    "fixture_producer . --json reports/sibling.json",
    "fixture_producer .",
])
def test_a_gate_command_for_another_binding_does_not_unsilence_the_entry(command):
    step = _neutral_output_step()
    step["gate"] = {"all_of": [{"program_exit_zero": command}]}
    assert _explicit_gate_commands_for_entry(step, step["program_outputs"][0]) == []
    assert _silent_entries({"steps": [step]}) == [
        ("NEUTRAL", "fixture_producer", "reports/neutral.json")]


def test_the_declared_command_must_BE_the_program_the_entry_names(tmp_path):
    """A row that declares one producer and runs another is a mis-declaration,
    not a dispatch. Driven through the real reader on a synthetic flow."""
    flow = tmp_path / "f.yaml"
    flow.write_text(yaml.safe_dump({"steps": [{
        "id": "T", "programs": ["perc_corpus_sweep"],
        "required_outputs": ["reports/x.json"],
        "program_outputs": [{"program": "perc_corpus_sweep",
                             "path": "reports/x.json",
                             "producer_command": "rm -rf reports/x.json"}]}]}))
    assert P.declared_producer_clauses(flow) == []


def test_a_clause_naming_an_undeclared_path_is_still_not_a_producer():
    """The third condition is what keeps the widening honest."""
    for c in _clauses():
        step = _steps()[c["step"]]
        assert c["target"] in set(step.get("required_outputs") or [])


# --------------------------------------------------------------------------- #
# the consumer the new condition key reaches: _ppa.delivery_path
# --------------------------------------------------------------------------- #
# MEASURED after the condition landed on the branch: `_ppa/delivery_path.py`
# refuses LOUDLY (by design) any key on a terminal's condition it has not been
# taught -- `_ROUTE_CONDITION_KEYS` -- and every route it resolved came back
# UNREADABLE, reddening 13 tests across two modules. That guard is right and
# stays; `delivery_declares` is now IN the set because it answers this module's
# OWN question from a better source, and the same predicate `resolve` already
# runs evaluates it.
import _ppa.delivery_path as DP                           # noqa: E402


def test_the_route_reader_was_TAUGHT_the_key_not_widened(tmp_path):
    """The loud refusal survives: a key nothing has been taught still makes
    the route UNREADABLE rather than being ignored."""
    assert "delivery_declares" in DP._ROUTE_CONDITION_KEYS
    conds, why = DP._route_conditions()
    assert conds is not None, why


def test_a_declared_hardmacro_resolves_to_the_IP_ROUTE(tmp_path):
    """Neither terminal's `files_exist` is met on this tree -- the chip
    terminal stands down BY DECLARATION and `NO_TEMPLATE.txt` was never
    written because a live shuttle existed on the target PDK. Reporting
    NOT_DETERMINED here would say "this tree carries no router artefact"
    about a tree that carries one, which is the one thing this module
    promises never to do."""
    r = DP.resolve(_project(tmp_path))
    assert r["path"] == DP.PATH_IP
    assert r["evidence"]["declaration"]["file"] == (
        "input/submission_template/tapeout_declaration.json")


def test_a_DIE_on_the_same_tree_still_resolves_to_the_CHIP_ROUTE(tmp_path):
    r = DP.resolve(_project(tmp_path, deliverable="DIE"))
    assert r["path"] == DP.PATH_CHIP


def test_a_tree_with_no_router_and_no_declaration_stays_NOT_DETERMINED(tmp_path):
    """The honest unknown is preserved: nothing to read is not an IP finding."""
    bare = tmp_path / "bare"
    (bare / "input" / "submission_template").mkdir(parents=True)
    assert DP.resolve(bare)["path"] == DP.PATH_NOT_DETERMINED
