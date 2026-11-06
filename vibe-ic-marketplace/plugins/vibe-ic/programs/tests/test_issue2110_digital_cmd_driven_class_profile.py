#!/usr/bin/env python3
"""Regression for #2110 — the class profile for `digital_cmd_driven`.

THIS CLASS WAS REFERRED UP, NOT SKIPPED, AND THE REFERRAL IS ANSWERED BY
MEASUREMENT. `test_issue2110_unprofiled_classes_are_decisions` records the six
other still-null classes as DECISIONS with measured reasons and this one as the
single open question, on two grounds. Both were re-measured on pristine main
before this landing and neither survives:

  (1) "no readable corpus design; seven classified doc-sets, zero with an input
      the retrieval can read". Measured over every `*/phase1/generated_docs`
      tree reachable on the measuring host (2974 doc-sets, 346 of them
      classified into this class): SIX distinct design inputs of this class are
      readable — `input_text_report(...)['status'] == 'READ'` — and the class's
      own protocol corpus alone holds fifteen designs. The premise is a fact
      about the corpus a lane could reach, not about the class.
  (2) "the features-alone condition is a judgement because the assigning
      condition is a conjunction one of whose conjuncts is a disjunction".
      The disjunct is `has_analog`, and it is CRAFT-INERT: the DB carries no
      entry for the analog half (already pinned, twice, in the decisions file),
      so the two assigning routes select the SAME entries. That is checked here
      by construction rather than asserted — see
      `test_the_two_assigning_routes_select_the_same_entries`. A condition whose
      two branches cannot disagree is a reading, not a judgement.

THE DEFECT, MEASURED ON THE CLASS'S OWN CORPUS (pristine main e2b3c08170b5).
On all SIX readable designs the unconfined top-5 was LED by an entry from
another design family — an AXI-stream image-frame processor on three of them, a
serial-parallel multiplier on two, a clock divider on one — and 28 of the 30
slots were out of class. Not one of the three dispatcher entries this profile
selects (`command-driven-memory-controller-fsm`, `fsm-controller`,
`fsm-register-interface`) reached any of the six packs: the craft for the one
thing the class is named for, executing a host-issued command, was unreachable
on every design of it. The two in-class slots that DID land were
`mmio-register-controlled-counter`, on two designs.

THE DERIVATION HAS A THIRD SHAPE, AND IT IS THE CLASSIFIER'S. The classes
profiled before this one are decided by a FEATURE TABLE (`_SERIAL_PROTO_
FEATURES`, `_BUS_PROTO_FEATURES`, …) or by a CONJUNCTION of profile flags. This
one is decided by a DISJUNCTION OF TWO CONJUNCTIONS, and it has exactly ONE
positive discriminator, `has_command_protocol`. One feature cannot by itself
justify four entries, so the selection is derived from what the shipped tree
says a design carrying that feature must DOCUMENT: `_CLASS_LAYER_REQUIREMENTS
['digital_cmd_driven']` makes L3, L4 and L6 mandatory, and
`_CONDITIONAL_LAYER_GUARDS` says L3 and L6 are mandatory BECAUSE of
`has_command_protocol` / `has_fsm`. Those three layers — the command set, the
register state it changes, the control logic that runs it — are the parts, and
`_PART_TO_DB_CLASSES` maps them to craft in both directions.

WHAT IS NOT IN IT, AND WHY (recorded so a later reader does not re-derive them):
`apb-master-fsm` is a two-phase bus initiator and the DB's own `related` names
three `bus_peripheral` entries — bus craft, not command-dispatch craft.
`priority-interrupt-controller` is the interrupt-controller family and its
`related` names `processor-cpu-core`. `mmio-timer-counter` is write-one-to-clear
status and undecoded-address read behaviour, which is verbatim the
`bus_peripheral` integration contract. `onehot-control-decode` matches the
decode part on its NAME and its one lesson is an area-optimisation rewrite; the
DB has an area-optimization family that owns it. `nvm-fuse-array` is the OTP
conjunct's ONLY entry and taking it would empty `mixed_signal_otp`'s half.

chip-AGNOSTIC: every fixture below is synthetic. The corpus facts quoted above
are counts and SENTENCE SHAPES; they name no chip, vendor, SKU or process node.
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import ic_expert_backup_pack as PACK          # noqa: E402
import ic_expert_db_query as Q                # noqa: E402
import ic_class_profile as ICP                # noqa: E402

_DB = _PROGRAMS.parent / "agents" / "ic_expert_db" / "ic_expert_db.json"

_CLASS = "digital_cmd_driven"

# A command-driven brief in the class's own vocabulary, SALTED with the three
# neighbouring families whose words its prose genuinely contains (a bus fabric,
# a stream and a serial-parallel product). The salt is the point: it is the
# literal-phrase collision #2094 was opened for.
_CMD_PROMPT = (
    "A command-driven digital controller. A host issues a one-byte opcode over "
    "the command interface; the dispatcher decodes the current command, drives "
    "every control output from that command's own truth table, and latches the "
    "command's parameters on the accept edge so a mid-command input change is "
    "ignored. Each command that writes takes effect on a memory-mapped control "
    "register, and a start write enables the datapath counter; a command that "
    "does not complete within the bounded timeout returns the sequencer to IDLE "
    "with every output deasserted. The status register is read back over the "
    "same interface, and the payload of one command is a serial-parallel "
    "product accumulated one bit per clock while the AXI-stream side of the "
    "fabric arbitrates between managers."
)

# TWO DESIGNS OF THE CLASS — one per transport member of it, because the class
# spans framed-serial and memory-mapped-parallel command interfaces and a proof
# on one member is a proof about half the class. Both state a top module, which
# is what lets the pack reach ASSEMBLED rather than ASSEMBLED_INCOMPLETE.
_DESIGN_SERIAL_FRAMED = (
    "A framed-serial command target. The top-level module is `cmd_target`. The "
    "host frames a one-byte opcode followed by an optional payload; the "
    "dispatcher decodes the accepted command, holds every control output for "
    "the whole command state, and raises a framing error output for an opcode "
    "the table does not contain. Command parameters are latched on the accept "
    "edge and the sequencer returns to IDLE when a command does not complete "
    "inside its bounded timeout."
)
_DESIGN_MMIO_PARALLEL = (
    "A memory-mapped parallel command interface. `cmd_block` is the top-level "
    "module. A write to the control register issues the command; the enable "
    "flop and the datapath counter share a clocked block, so the edge that "
    "produces the first count after a start write is part of the "
    "specification. Status is read back combinationally off the address, and a "
    "second command arriving while the first is running is rejected with a busy "
    "status bit that a write clears."
)

# The three layers `_CLASS_LAYER_REQUIREMENTS[_CLASS]` makes MANDATORY and that
# are the structural parts of "a host-issued command set a digital chip
# dispatches" -> the craft that answers each. Pinned in BOTH directions below.
_PART_TO_DB_CLASSES = {
    # L3 — the command set itself: every output decoded from the CURRENT
    # command's own truth table, with explicit inactive defaults outside it.
    "L3_command_set": ["command-driven-memory-controller-fsm"],
    # L6 — the sequencer that runs one command to completion: parameters
    # latched on the accept edge, Moore-decoded outputs, bounded timeout.
    "L6_control_logic": ["fsm-controller"],
    # L4 <-> L6 — the boundary between the command FSM and the software-visible
    # registers: side-effects keyed off the registered CURRENT state, read
    # arbitrated against write; and the memory-mapped control register whose
    # write IS the command for the parallel member of the class.
    "L4_software_visible_state": ["fsm-register-interface",
                                  "mmio-register-controlled-counter"],
}

# The conjuncts of the two assigning branches. `has_analog` is the DISJUNCT the
# referral was about; the negatives are written down as empty on purpose, so a
# reader can see they were considered rather than forgotten.
_ROUTE_A = {"has_analog": True, "has_command_protocol": True,
            "has_otp": False, "looks_like_processor_cpu": False}
_ROUTE_B = {"has_analog": False, "has_command_protocol": True,
            "looks_like_processor_cpu": False}


def _db() -> dict:
    return json.loads(_DB.read_text())


def _profile() -> dict:
    p = _db()["registered_class_profiles"].get(_CLASS)
    assert isinstance(p, dict), f"{_CLASS!r} is not profiled in the expert DB"
    return p


def _null_profile_db(tmp_path: Path) -> Path:
    db = _db()
    db["registered_class_profiles"][_CLASS] = None
    p = tmp_path / "db_null.json"
    p.write_text(json.dumps(db))
    return p


def _entry_text_matches(rx: str) -> list:
    pat = re.compile(rx, re.I)
    return [e["ic_class"] for e in _db()["entries"]
            if pat.search(e["ic_class"] + " " + " ".join(e.get("lessons", [])))]


def _mk_project(root: Path, l1: dict, l3: dict, l5=None) -> Path:
    gd = root / "phase1" / "generated_docs"
    gd.mkdir(parents=True)
    (gd / "L1_DATASHEET.json").write_text(json.dumps(l1))
    (gd / "L3_CMD_PROTOCOL.json").write_text(json.dumps(l3))
    if l5 is not None:
        (gd / "L5_ADI_SPEC.json").write_text(json.dumps(l5))
    return root


# ── 1. the referral, answered ──────────────────────────────────────────────

def test_the_two_assigning_routes_select_the_same_entries():
    """THE REFERRAL. The class is assigned by a disjunction of two conjunctions
    and the only thing that differs between them is `has_analog`. Build the
    selection each route can justify — the craft answering its positive
    conjuncts — and require them to be EQUAL. They are, because the analog
    disjunct has no craft to contribute in either direction, so "the features
    alone determine the selection" is a reading of the DB rather than a
    judgement about it.

    This is also the tripwire: the day the DB grows analog craft, the two
    selections stop being equal and this goes red, which is precisely when the
    decision has to be re-taken."""
    analog_craft = _entry_text_matches(
        r"\bLDO\b|bandgap|\bamplifier\b|\bop-?amp\b|charge\s+pump|"
        r"\bvoltage\s+regulator\b")
    assert analog_craft == [], (
        f"the DB now carries analog craft {analog_craft}; the disjunct is no "
        f"longer craft-inert and this profile's derivation must be re-taken")
    craft = {c for v in _PART_TO_DB_CLASSES.values() for c in v}
    route_a = craft | set(analog_craft)   # has_analog True
    route_b = craft                       # has_analog False
    assert route_a == route_b == set(_profile()["db_classes"])


def test_both_assigning_routes_really_do_reach_this_class(tmp_path):
    """The corpus exercises exactly ONE of the two routes: all 346 doc-sets
    classified into this class record `is_pure_digital + has_command_protocol`,
    and not one has `has_analog`. A route with no real-world instance is the
    one no real test reaches, so both are exercised here from synthetic L docs
    and each is checked by the branch it actually took, not by the class name
    alone."""
    cmds = {"opcodes": [{"name": "READ_STATUS", "hex": "0x11"},
                        {"name": "START", "hex": "0x12"}]}
    b = _mk_project(tmp_path / "pure_digital",
                    {"description": "A command-driven digital controller."},
                    cmds)
    pb = ICP.infer_ic_class_uncached(b)
    assert pb["ic_class"] == _CLASS
    assert pb["decisive_evidence"] == "is_pure_digital + has_command_protocol"
    assert pb["has_analog"] is False

    a = _mk_project(tmp_path / "mixed",
                    {"description": "A mixed-signal command-driven controller "
                                    "with an on-chip analog reference."},
                    cmds,
                    l5={"blocks": [{"name": "bandgap_reference",
                                    "type": "analog", "vout_v": 1.2,
                                    "iq_ua": 50}]})
    pa = ICP.infer_ic_class_uncached(a)
    assert pa["ic_class"] == _CLASS
    assert pa["decisive_evidence"] == ("is_mixed_signal (no otp) + "
                                       "has_command_protocol")
    assert pa["has_analog"] is True


def test_the_conjuncts_this_map_names_are_the_ones_the_classifier_computes():
    """The enumeration is DERIVED, so it is checked against the tree rather
    than against memory: every conjunct name maps to a predicate the classifier
    actually evaluates, and the positive discriminator is exercised on this
    class's own vocabulary so it is live code and not a name."""
    assert callable(ICP._l3_has_commands)
    assert callable(ICP._l5_has_analog)
    assert callable(ICP._looks_like_processor_cpu)
    assert callable(ICP._l4_has_otp)
    assert ICP._l3_has_commands({"opcodes": [{"name": "START", "hex": "0x1"}]})
    assert not ICP._l3_has_commands({"opcodes": []})
    # a fully scrubbed opcode list is NOT a command set (v0.1.62)
    assert not ICP._l3_has_commands(
        {"opcodes": [{"name": "X", "hex": "<HALLUCINATION_SCRUBBED>"}]})
    for conj in ("has_analog", "has_command_protocol",
                 "looks_like_processor_cpu"):
        assert conj in _ROUTE_A or conj in _ROUTE_B
    assert set(_ROUTE_B) < set(_ROUTE_A), (
        "route B must be route A's conjuncts minus the OTP guard the analog "
        "half needs; if that stops holding the derivation has changed shape")


# ── 2. the derivation, both directions ─────────────────────────────────────

def test_every_selected_db_class_answers_a_part_the_classifier_makes_mandatory():
    selected = set(_profile()["db_classes"])
    mapped = {c for v in _PART_TO_DB_CLASSES.values() for c in v}
    assert mapped == selected, (
        f"selected-but-unmapped {sorted(selected - mapped)} / "
        f"mapped-but-unselected {sorted(mapped - selected)}")
    for part, craft in _PART_TO_DB_CLASSES.items():
        assert craft, f"structural part {part!r} has no craft in the profile"


def test_the_parts_are_the_layers_the_shipped_requirement_table_makes_mandatory():
    """The parts are not a vocabulary this file invented: each names a layer
    `_CLASS_LAYER_REQUIREMENTS[_CLASS]` lists as MANDATORY, and L3 and L6 are
    mandatory BECAUSE of the two flags the assigning branches read. Read from
    the shipped tables, so a quotation cannot drift from its source."""
    req = ICP._CLASS_LAYER_REQUIREMENTS[_CLASS]
    for part in _PART_TO_DB_CLASSES:
        layer = part.split("_")[0]
        assert layer in req["mandatory"], (
            f"{part!r} names {layer}, which this class does not make mandatory")
    guards = ICP._CONDITIONAL_LAYER_GUARDS
    assert "has_command_protocol" in guards["L3"]
    assert set(guards["L6"]) == {"has_fsm", "has_command_protocol"}
    # L5 — the analog layer — is CONDITIONAL for this class, which is the same
    # fact about the disjunct, said by the requirement table instead of by the DB.
    assert "L5" in req["conditional"] and "L5" not in req["mandatory"]


def test_the_excluded_neighbours_are_still_someone_elses_or_nobodys():
    """The four entries this derivation rejected, pinned by the REASON each was
    rejected for, so a later landing that wants one has to come past the reason
    rather than past a list."""
    db = _db()
    by = {e["ic_class"]: e for e in db["entries"]}
    selected = set(_profile()["db_classes"])
    for name in ("apb-master-fsm", "priority-interrupt-controller",
                 "mmio-timer-counter", "onehot-control-decode",
                 "nvm-fuse-array"):
        assert name in by, f"{name} left the DB; re-take its exclusion"
        assert name not in selected
    # the DB's own concept graph is what puts the first two elsewhere
    assert set(by["apb-master-fsm"]["related"] or []) <= {
        e["ic_class"] for e in db["entries"]}
    assert any(r.startswith("apb-")
               for r in (by["apb-master-fsm"]["related"] or []))
    assert "processor-cpu-core" in (
        by["priority-interrupt-controller"]["related"] or [])
    # nvm-fuse-array is the OTP conjunct's ONLY entry; taking it would empty
    # the half of `mixed_signal_otp` that has craft at all.
    assert _entry_text_matches(r"\bOTP\b|\bfuse\b|antifuse") == ["nvm-fuse-array"]


def test_the_profile_names_only_entries_the_db_carries():
    present = {e["ic_class"] for e in _db()["entries"]}
    for c in _profile()["db_classes"]:
        assert c in present, f"profile names {c!r}, entries[] does not carry it"


def test_a_profile_naming_an_absent_entry_is_REFUSED_not_quietly_shrunk(tmp_path):
    """The map's own refusal, for THIS class. A profile that names an entry the
    DB does not carry must raise rather than fall back towards the unconfined
    behaviour the profile exists to stop — a silently shrunk candidate set is
    the failure mode that looks exactly like success."""
    db = _db()
    db["registered_class_profiles"][_CLASS]["db_classes"] = [
        "fsm-controller", "no-such-entry"]
    p = tmp_path / "db_bad.json"
    p.write_text(json.dumps(db))
    with pytest.raises(KeyError) as e:
        Q.query(_CMD_PROMPT, k=5, db_path=p, ic_class=_CLASS)
    assert "no-such-entry" in str(e.value)


def test_the_profiled_classes_select_disjoint_knowledge():
    prof = _db()["registered_class_profiles"]
    named = {k: set(v["db_classes"]) for k, v in prof.items()
             if not k.startswith("_") and isinstance(v, dict)}
    assert len(named) >= 2, "only one class is profiled; this control is empty"
    items = sorted(named.items())
    for i, (a, sa) in enumerate(items):
        for b, sb in items[i + 1:]:
            assert not (sa & sb), (
                f"profiles {a} and {b} share db_classes {sorted(sa & sb)}")


# ── 3. the pack, on TWO designs of the class ───────────────────────────────

@pytest.mark.parametrize("prompt,top", [
    (_DESIGN_SERIAL_FRAMED, "cmd_target"),
    (_DESIGN_MMIO_PARALLEL, "cmd_block"),
])
def test_a_design_of_this_class_gets_an_assembled_collision_free_pack(
        prompt, top, tmp_path):
    allowed = set(_profile()["db_classes"])
    h = PACK.assemble(prompt, None, None, [], ["gate"], tmp_path,
                      output_target="l_doc_expectations.json", ic_class=_CLASS)
    cf = h["class_first"]
    assert h["target_module"] == top
    assert h["interface_contract"] == "contract.md"
    assert cf["contract_kind"] == "class_integration_contract_md"
    assert cf["assembly_status"] == "ASSEMBLED" and cf["missing_fields"] == []
    assert cf["db_class_selection"] == "CLASS_CONFINED"
    got = {x["ic_class"] for x in h["db_classes"]}
    assert got == allowed, f"out of class: {sorted(got - allowed)}"
    body = (tmp_path / "contract.md").read_text()
    for req in _profile()["integration_contract"]:
        assert req in body, f"the contract document drops: {req[:60]}…"


def test_the_digest_the_agent_reads_agrees_with_the_declared_selection(tmp_path):
    allowed = set(_profile()["db_classes"])
    h = PACK.assemble(_CMD_PROMPT, None, None, [], ["gate"], tmp_path,
                      output_target="l_doc_expectations.json", ic_class=_CLASS)
    named = set(re.findall(r"^- \*\*\[([^\]]+)\]\*\*",
                           (tmp_path / "ic_expert_db.md").read_text(), re.M))
    assert named, "the rendered digest names no ic_class at all"
    assert named <= allowed
    assert named == {x["ic_class"] for x in h["db_classes"]}


def test_the_class_decides_membership_not_the_phrase():
    allowed = set(_profile()["db_classes"])
    assert {h["ic_class"] for h in
            Q.query("a design.", k=99, ic_class=_CLASS)} == allowed


# ── 4. the negative control, stated as the MEASURED HARM ───────────────────

def test_mutation_reverting_the_profile_loses_the_dispatcher_craft(tmp_path):
    """Unconfined, this brief is led by a stream processor and returns four
    out-of-class entries; the three DISPATCHER entries — the craft for
    executing a host-issued command, which is the one thing this class is named
    for — do not appear at all. `mmio-register-controlled-counter` DOES survive
    unconfined, so an assertion that the two arms are disjoint would be false;
    asserting what is actually true is what makes the control mean anything."""
    got = {h["ic_class"] for h in
           Q.query(_CMD_PROMPT, k=5, db_path=_null_profile_db(tmp_path),
                   ic_class=_CLASS)}
    assert got, "the mutation arm retrieved nothing at all"
    dispatcher = {"command-driven-memory-controller-fsm", "fsm-controller",
                  "fsm-register-interface"}
    assert not (got & dispatcher), (
        "the mutation did not reproduce the defect — the dispatcher craft is "
        "already reachable unconfined, so the positive assertion proves nothing")
    assert got - set(_profile()["db_classes"]), (
        "the mutation arm returned no out-of-class entry at all")


def test_mutation_the_unprofiled_pack_is_the_DECLARED_GAP_state(tmp_path,
                                                               monkeypatch):
    """Remove the profile and the pack must fall back to the DECLARED GAP — the
    unconfined lexical ranking with no class_first block at all — and NOT to a
    phrase-selected confined pack. Byte-equality with the no-class arm is the
    one summary a substitution cannot disturb."""
    monkeypatch.setattr(Q, "_DEFAULT_DB", _null_profile_db(tmp_path))
    h = PACK.assemble(_CMD_PROMPT, None, None, [], ["gate"], tmp_path / "pack",
                      output_target="l_doc_expectations.json", ic_class=_CLASS)
    assert "class_first" not in h
    assert h["target_module"] is None and h["interface_contract"] is None
    d = PACK.class_first_disposition(_CLASS)
    assert d["registered"] is True and d["profile"] == "NOT_PROFILED"
    assert d["db_class_selection"] == "LEXICAL_UNCONFINED"
    assert (Q.query(_CMD_PROMPT, k=5, db_path=Q._DEFAULT_DB)
            == Q.query(_CMD_PROMPT, k=5, db_path=Q._DEFAULT_DB, ic_class=_CLASS))


# ── 5. a design of ANOTHER class does not move ─────────────────────────────

def test_a_design_of_another_class_is_byte_identical(tmp_path):
    """Both arms of "another class": one still-null (the unconfined path) and
    one PROFILED (the confined path). A profile for this class may not move
    either, and byte-identity of the whole emitted directory — not just of the
    descriptor — is what says so."""
    prof = _db()["registered_class_profiles"]
    still_null = next(k for k, v in prof.items()
                      if not k.startswith("_") and v is None)
    other_profiled = next(k for k, v in prof.items()
                          if not k.startswith("_") and isinstance(v, dict)
                          and k != _CLASS)
    prompt = ("A serial-parallel multiplier: the multiplicand is applied in "
              "parallel and the multiplier one bit per clock, with a "
              "clock-divided strobe advancing the accumulation.")
    a = PACK.assemble(prompt, None, None, [], ["gate"], tmp_path / "a",
                      output_target="l_doc_expectations.json")
    b = PACK.assemble(prompt, None, None, [], ["gate"], tmp_path / "b",
                      output_target="l_doc_expectations.json",
                      ic_class=still_null)
    assert a == b and "class_first" not in b
    for n in sorted(q.name for q in (tmp_path / "a").iterdir()):
        assert (tmp_path / "a" / n).read_bytes() == (tmp_path / "b" / n).read_bytes()
    # the other PROFILED class keeps its own selection, untouched by this one
    c = PACK.assemble(prompt, None, None, [], ["gate"], tmp_path / "c",
                      output_target="l_doc_expectations.json",
                      ic_class=other_profiled)
    got = {x["ic_class"] for x in c["db_classes"]}
    assert got <= set(prof[other_profiled]["db_classes"])
    assert not (got & set(_profile()["db_classes"]))


@pytest.mark.consistency
def test_the_six_remaining_null_classes_are_still_null():
    """This landing takes ONE class. The other six stay null — each a recorded
    DECISION in `test_issue2110_unprofiled_classes_are_decisions` — and pinning
    that here is what keeps "one class per landing" a property rather than a
    habit."""
    prof = _db()["registered_class_profiles"]
    nulls = {k for k, v in prof.items()
             if not k.startswith("_") and v is None}
    assert nulls == {"aid_class_half_duplex_single_wire", "bare_fpga",
                     "digital_arithmetic_primitive", "mixed_signal_otp",
                     "pure_analog", "unknown_protocol_class"}
    assert _CLASS not in nulls
