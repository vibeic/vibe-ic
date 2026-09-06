#!/usr/bin/env python3
"""#2070 O1/O2 — the DESIGN's declaration decides the route, and a mount is
resolved before it is spelled.

O1 — WHAT WAS MEASURED. Once step 0.5ic learned the run's PDK, the fetch
resolved the registry's live gf180mcu shuttle and fetched its four slots for
`spm` and `subservient` — two designs that declare `deliverable=HARDMACRO` and
name no slot. Step 0.5ic's first gate clause then refused them with
SLOT_NOT_DECLARED plus the shape rules (PAD_LIST_UNREAD,
SLOT_GEOMETRY_INCOMPLETE) of slots they never bought. A hardmacro failed the
step because an operator happened to exist on a process it targets.

THE OWNER RULING (2026-09-07): a live shuttle in the registry, on the PDK the
design names, is INFORMATION, not a requirement. When the design declares
HARDMACRO and names no slot the fetch REPORTS the shuttle and the route, and
the clause does not refuse. The slot contract — which slot was bought, and the
shape of that slot — is owed ONLY by a design that declares DIE: a shuttle die
must name its slot.

NOTHING A DIE OWES IS WIDENED, and that is asserted here in the direction that
would hide a defect: with the SAME tree and the SAME operator template, a
declaration of DIE brings all three refusals straight back.

O2 — a relative project path made the wafer.space adapter build the volume
spec `input:input`, which docker refuses (rc=125), reported as "the operator's
image did not yield its template" — an operator refusal for our own argument.
It never bit through the runner, which resolves the project first.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import _submission_template as ST                             # noqa: E402
import _tapeout_declaration as TD                             # noqa: E402
import submission_template_check as STC                       # noqa: E402
import submission_template_fetch as STF                       # noqa: E402

SLOT_RULES = {"SLOT_NOT_DECLARED", "PAD_LIST_UNREAD",
              "SLOT_GEOMETRY_INCOMPLETE", "SLOT_GEOMETRY_DEGENERATE"}


def _declared(tmp_path: Path, deliverable) -> Path:
    """A project carrying only a declaration answering `deliverable`."""
    proj = tmp_path / "p"
    doc = TD.blank_declaration()
    if deliverable is not None:
        doc["answers"]["deliverable"] = deliverable
    path = proj / TD.DECLARATION_REL
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(doc), encoding="utf-8")
    return proj


# ── who owes the slot contract ────────────────────────────────────────
def test_a_hardmacro_that_names_no_slot_does_not_owe_it(tmp_path):
    owed, why = STC.slot_rules_are_owed(_declared(tmp_path, "HARDMACRO"), None)
    assert owed is False
    assert TD.DELIVERABLE_HARDMACRO in why and "INFORMATION" in why


def test_a_die_that_names_no_slot_still_owes_it(tmp_path):
    """THE NEGATIVE CONTROL. A shuttle die must name its slot; nothing here
    relaxes that, and this assertion is what stops the clause above from
    quietly becoming "nobody owes it"."""
    owed, why = STC.slot_rules_are_owed(_declared(tmp_path, "DIE"), None)
    assert owed is True and why is None


def test_a_design_that_names_a_slot_owes_it_whatever_it_calls_itself(tmp_path):
    owed, _ = STC.slot_rules_are_owed(_declared(tmp_path, "HARDMACRO"), "1x1")
    assert owed is True


@pytest.mark.parametrize("deliverable", [None, TD.NOT_DETERMINED, ""])
def test_an_unstated_route_owes_it_never_buys_a_pass(tmp_path, deliverable):
    """DEGRADE TOWARDS OWING IT. An unstated, absent or unreadable declaration
    is not a declaration of HARDMACRO, and a route nobody chose must never buy
    the slot contract away — that is the whole weight of this clause."""
    owed, _ = STC.slot_rules_are_owed(_declared(tmp_path, deliverable), None)
    assert owed is True


def test_an_absent_declaration_owes_it(tmp_path):
    owed, _ = STC.slot_rules_are_owed(tmp_path / "nothing-here", None)
    assert owed is True


# ── the same record, judged both ways ─────────────────────────────────
def _ingested_project(tmp_path: Path, deliverable: str) -> Path:
    """One project, one ingested operator template of one under-specified
    slot, and a declaration answering `deliverable`. The ONLY thing that
    differs between the two arms below is that word."""
    proj = _declared(tmp_path, deliverable)
    slots = proj / ST.SLOTS_DIR_REL
    slots.mkdir(parents=True)
    src = proj / "input" / "submission_template_source" / "1x1.json"
    src.parent.mkdir(parents=True, exist_ok=True)
    src.write_text(json.dumps({"SLOT": "1x1", "DIE_AREA": "0 0 100 100",
                               "FORBIDDEN_LAYERS": ["x"]}), encoding="utf-8")
    slot = {"slot": "1x1", "source_file": str(src),
            "source_sha256": ST.sha256_file(src),
            "die_area": {"rect": [0, 0, 100, 100], "raw": "0 0 100 100"},
            "core_area": None,                       # -> SLOT_GEOMETRY_INCOMPLETE
            "pads": {"lists": {}, "unmatched_list_keys": ["FORBIDDEN_LAYERS"],
                     "pattern": "^PAD$"}}
    (slots / "1x1.yaml").write_text(json.dumps(slot), encoding="utf-8")
    doc = {"program": "submission_template_ingest",
           "ingest": {"status": ST.STATUS_INGESTED, "slots": [slot],
                      "slots_shipped": ["1x1"], "declared_slot": None,
                      "fixtures": [],
                      "lookup": {"attempted": True, "searched": [str(src.parent)],
                                 "template_root": str(src.parent)}}}
    rep = proj / ST.REPORT_REL
    rep.parent.mkdir(parents=True, exist_ok=True)
    rep.write_text(json.dumps(doc), encoding="utf-8")
    return proj


def _rules(proj: Path):
    doc = json.loads((proj / ST.REPORT_REL).read_text())
    check = STC.evaluate(proj, doc, None)
    return check, {r["rule"] for r in check["refusals"]}


def test_the_hardmacro_arm_does_not_refuse_and_says_why(tmp_path):
    proj = _ingested_project(tmp_path, TD.DELIVERABLE_HARDMACRO)
    check, rules = _rules(proj)
    assert rules & SLOT_RULES == set()
    assert check["verdict"] == ST.VERDICT_NOT_APPLICABLE
    # NOT SILENT: the shuttle that exists and is not being used is reported.
    ex = check["examined"]
    assert ex[STC.NOT_OWED_KEY]
    assert ex["operator_shuttle_available_not_used"]["slots_shipped"] == ["1x1"]


def test_the_die_arm_refuses_exactly_as_before(tmp_path):
    """SAME tree, SAME operator template, ONE word different."""
    proj = _ingested_project(tmp_path, TD.DELIVERABLE_DIE)
    check, rules = _rules(proj)
    assert "SLOT_NOT_DECLARED" in rules
    assert "SLOT_GEOMETRY_INCOMPLETE" in rules
    assert "PAD_LIST_UNREAD" in rules
    assert check["verdict"] == ST.VERDICT_FAIL
    assert STC.NOT_OWED_KEY not in check["examined"]


def test_the_records_own_integrity_is_owed_by_every_design(tmp_path):
    """The line the ruling does NOT move. Whether the file the record was
    built from is still there, and still hashes to what was ingested, is about
    whether this report can be believed at all — a hardmacro owes that as much
    as a die, and a clause that dropped it would make the whole record
    unfalsifiable."""
    proj = _ingested_project(tmp_path, TD.DELIVERABLE_HARDMACRO)
    src = proj / "input" / "submission_template_source" / "1x1.json"
    src.write_text(src.read_text() + "\n", encoding="utf-8")   # edited after
    _check, rules = _rules(proj)
    assert "TEMPLATE_CHANGED_SINCE_INGEST" in rules


# ── the fetch reports the route ───────────────────────────────────────
def _design_answers(tmp_path: Path, deliverable, slot=None) -> Path:
    proj = tmp_path / "d"
    (proj / "input").mkdir(parents=True)
    (proj / ST.DESIGN_ANSWERS_REL).write_text(json.dumps({
        "answers": {"deliverable": deliverable},
        "operator_template": {"slot": slot}}), encoding="utf-8")
    return proj


def test_the_design_route_is_read_from_the_designs_own_answers(tmp_path):
    """From its ANSWERS, not from the declaration: the fetch runs FIRST in the
    step's chain, so the declaration on disk is the PREVIOUS run's."""
    rec = STF.design_route(_design_answers(tmp_path, "HARDMACRO"))
    assert rec["deliverable"] == "HARDMACRO" and rec["slot"] is None
    assert rec["source"] == ST.DESIGN_ANSWERS_REL


@pytest.mark.parametrize("staged", [None, "NOT_DETERMINED"])
def test_a_design_that_states_no_deliverable_gets_no_route_claim(tmp_path,
                                                                 staged):
    rec = STF.design_route(_design_answers(tmp_path, staged))
    assert rec["deliverable"] is None


def test_a_design_with_no_answers_file_is_not_given_a_route(tmp_path):
    rec = STF.design_route(tmp_path / "empty")
    assert rec["deliverable"] is None and rec["source"] is None


def test_the_fetch_consults_the_route_and_reports_it(tmp_path):
    """BY AST. `design_route` existing proves nothing: the fact the ruling
    asks for — an operator exists on this process and this design is not
    using it — is only carried if `fetch` actually calls it and writes the
    note. The PASS branch itself starts a container, so the WIRE is what is
    asserted here and the sentence is measured on real silicon in the lane."""
    import ast
    fn = next(n for n in ast.walk(ast.parse(
        (_PROGRAMS / "submission_template_fetch.py").read_text(
            errors="replace")))
        if isinstance(n, ast.FunctionDef) and n.name == "fetch")
    called = {n.func.id for n in ast.walk(fn)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "design_route" in called
    keys = {n.slice.value for n in ast.walk(fn)
            if isinstance(n, ast.Subscript)
            and isinstance(n.slice, ast.Constant)
            and isinstance(n.slice.value, str)}
    assert "route_note" in keys and "design_route" in keys


# ── O2: the mount is absolute before it is spelled ────────────────────
def test_the_container_mount_is_resolved_before_the_volume_spec(tmp_path,
                                                                monkeypatch):
    """BOTH DIRECTIONS, without a container: the spec docker is handed is
    captured. A relative `mount` produced `input:input`, which docker refuses
    outright with rc=125 — reported by this program as an OPERATOR refusal."""
    seen = {}

    def _fake(argv, timeout=900.0):
        seen["argv"] = list(argv)
        return 0, "", ""

    monkeypatch.setattr(STF, "_run", _fake)
    monkeypatch.chdir(tmp_path)
    (tmp_path / "input").mkdir()
    STF._in_image("sha256:deadbeef", "pass", Path("input"), "python")
    spec = seen["argv"][seen["argv"].index("-v") + 1]
    host, _, guest = spec.partition(":")
    assert Path(host).is_absolute(), f"docker refuses {spec!r} outright"
    assert Path(guest).is_absolute()
    assert host == guest == str((tmp_path / "input").resolve())
