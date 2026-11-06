#!/usr/bin/env python3
"""Regression for #2110 — the class profile for `bus_peripheral`.

THE DEFECT, MEASURED ON THE CLASS'S OWN CORPUS. `bus_peripheral` was one of the
twelve classes #2094 left `null`. The shipped classifier puts three corpus
doc-sets in it; two carry a design INPUT the retrieval can read, and on pristine
main BOTH got a pack that was five-for-five out of class:

    a memory-mapped user project   mmio-register-controlled-counter,
                                   priority-interrupt-controller x3,
                                   cdc-mux-synchronizer
    a bus-interface doc-set        axi-stream-width-downsizer, axi-stream,
                                   axi-mmio-cdc-datapath, integer-clock-divider,
                                   cdc-mux-synchronizer

Ten of ten out of class, and the DB carries six entries of genuine
bus-peripheral craft — the register map with its CSR band, the subordinate
channel FSMs, the bus-phase response discipline, the reserved-bit and
read-only-write semantics, and what a named bus interface implies when the input
is silent. None of the six reached either design.

DERIVED, NOT CHOSEN. Every db_class answers at least one of the five structural
features `ic_class_profile._BUS_PERIPHERAL_FEATURES` uses to ASSIGN this class,
and every one of those features has craft in the profile; the map is pinned in
both directions.

THE LINE THIS PROFILE DRAWS, and it is pinned so it stays a decision: the class
is the BUS INTERFACE, not the function behind it. `mmio-register-controlled-
counter`, `mmio-timer-counter` and `apb-register-peripheral-pwm` are craft about
a counter, a timer and a PWM — a bus peripheral is not necessarily any of those,
and a pack that hands a register-bank design a counter's off-by-one lesson has
imported a function it does not have. `apb-master-fsm` is the INITIATOR's craft
while the class's own feature is `bus_subordinate`. `bus-protocol-bridge` is an
interconnect element. `fsm-register-interface` is named for this class and its
five lessons are dominated by priority-interrupt-controller lifecycle craft.

chip-AGNOSTIC: every fixture is synthetic; the one real-corpus fact used is the
SHAPE of the collision, which names no chip, vendor, SKU or node.
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

_CLASS = "bus_peripheral"

# A bus-peripheral brief reduced to its shape: the class's own structural
# vocabulary plus the two families a register bank's prose unavoidably borrows —
# a counter behind the map and a divided clock driving it. Synthetic.
_PERIPHERAL_PROMPT = (
    "Implement a memory-mapped peripheral that attaches to the system bus as a "
    "subordinate. The address map reserves the low offsets for a control "
    "register, a status register and a threshold register; the control register "
    "has a read/write enable bit and a write-one-to-clear error bit, and the "
    "reserved bits read back as zero. An access to an offset the peripheral does "
    "not decode raises the bus error response. Behind the register bank a free-"
    "running counter increments once per divided clock tick and raises a level "
    "interrupt to the host when it reaches the threshold; the interrupt is "
    "cleared by writing the status register."
)

# The five features `_BUS_PERIPHERAL_FEATURES` tests for -> the entries whose
# craft answers each. List-valued: this class has no bijection either, and two
# of its features are answered by two entries apiece.
_FEATURE_TO_DB_CLASSES = {
    "register_map": ["apb-mmio-register-file"],
    "bus_subordinate": ["axi4lite-register-slave"],
    "bus_interface": ["apb-peripheral-mmio", "bus-interface-defaults"],
    "register_fields": ["apb-csr-shift-register",
                        "apb-mmio-register-file-peripheral"],
    "address_decode": ["apb-mmio-register-file", "apb-peripheral-mmio"],
}

# Craft that is about the FUNCTION behind the bus, the INITIATOR side, an
# interconnect element, or another class entirely. Excluded on purpose.
_EXCLUDED = {"mmio-register-controlled-counter", "mmio-timer-counter",
             "apb-register-peripheral-pwm", "apb-master-fsm",
             "bus-protocol-bridge", "fsm-register-interface"}


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


# ── 1. the profile, both directions ────────────────────────────────────────

def test_a_bus_peripheral_brief_gets_an_all_in_class_pack():
    allowed = set(_profile()["db_classes"])
    hits = Q.query(_PERIPHERAL_PROMPT, k=5, ic_class=_CLASS)
    assert hits, "class-first retrieval returned nothing at all"
    got = {h["ic_class"] for h in hits}
    assert got <= allowed, f"out-of-class entries leaked in: {sorted(got - allowed)}"


def test_mutation_reverting_the_profile_brings_the_out_of_class_pack_back(tmp_path):
    """THE NEGATIVE CONTROL, on the SAME prompt: with the class back at `null`
    the identical brief retrieves a clock divider and a counter — the function
    behind the map, not the map. Asserted DISJOINT, not merely different: two
    arms that overlap prove nothing about the confinement."""
    allowed = set(_profile()["db_classes"])
    got = {h["ic_class"] for h in
           Q.query(_PERIPHERAL_PROMPT, k=5, db_path=_null_profile_db(tmp_path),
                   ic_class=_CLASS)}
    assert got, "the mutation arm retrieved nothing at all"
    assert not (got & allowed), (
        f"the mutation did not reproduce the defect — still in-class: "
        f"{sorted(got & allowed)}")
    # The measured HARM, stated positively. This assertion used to enumerate
    # the whole mutation-arm pack and require it to be a subset — which pinned
    # the CONTENTS of an unconfined ranking rather than anything about the
    # profile, and #2164's entry-slot allocator legitimately changed those
    # contents (repeats replaced by two further out-of-class entries). What the
    # arm is actually FOR is that the function-behind-the-bus family the
    # profile deliberately excludes is what a bus-peripheral design gets
    # instead of its own craft, so that is what is asserted.
    assert got & _EXCLUDED, (
        f"the mutation arm returned no entry from the family this profile "
        f"exists to displace: {sorted(got)}")


def test_the_class_decides_membership_not_the_phrase():
    allowed = set(_profile()["db_classes"])
    assert {h["ic_class"] for h in
            Q.query("a design.", k=99, ic_class=_CLASS)} == allowed


def test_related_graph_cannot_reopen_this_class_boundary():
    """Three of this class's entries carry `related` links, and two of those
    links point OUT of the class (`apb-master-fsm`, `apb-register-peripheral-
    pwm`). A concept link is not a membership claim: the expansion walks the
    CONFINED entries, so those targets resolve to nothing."""
    allowed = set(_profile()["db_classes"])
    seed = next(e for e in _db()["entries"]
                if e["ic_class"] == "apb-csr-shift-register")
    assert set(seed.get("related") or []) - allowed, (
        "the out-of-class links this test exists to contain are gone; re-pick")
    got = {h["ic_class"] for h in
           Q.query(_PERIPHERAL_PROMPT, k=5, ic_class=_CLASS, expand_related=True)}
    assert got <= allowed, f"the related graph leaked {sorted(got - allowed)}"


def test_the_profiled_classes_select_disjoint_knowledge():
    prof = _db()["registered_class_profiles"]
    named = {k: set(v["db_classes"]) for k, v in prof.items()
             if not k.startswith("_") and isinstance(v, dict)}
    assert len(named) >= 2, "only one class is profiled; this control is empty"
    items = sorted(named.items())
    for i, (a, sa) in enumerate(items):
        for b, sb in items[i + 1:]:
            assert not (sa & sb), f"profiles {a} and {b} share db_classes {sorted(sa & sb)}"


# ── 2. the selection is DERIVED from the classifier ────────────────────────

def test_every_selected_db_class_answers_a_feature_the_classifier_uses():
    selected = set(_profile()["db_classes"])
    features = {name for name, _ in ICP._BUS_PERIPHERAL_FEATURES}
    assert features == set(_FEATURE_TO_DB_CLASSES), (
        f"the classifier's feature set moved to {sorted(features)}; the "
        f"profile's derivation has to be re-taken against it")
    for feat, entries in _FEATURE_TO_DB_CLASSES.items():
        assert entries, f"feature {feat!r} has no craft in the profile"
    mapped = {c for v in _FEATURE_TO_DB_CLASSES.values() for c in v}
    assert mapped == selected, (
        f"selected-but-unmapped {sorted(selected - mapped)} / "
        f"mapped-but-unselected {sorted(mapped - selected)}")


def test_the_mandatory_feature_of_this_class_has_craft():
    """`register_map` is the classifier's DENY-GUARD for this class: without it
    the design is not a bus peripheral at all. The one feature that must be
    present to be in the class is the one that must not be uncovered."""
    assert _FEATURE_TO_DB_CLASSES["register_map"]
    assert set(_FEATURE_TO_DB_CLASSES["register_map"]) <= set(_profile()["db_classes"])


def test_the_profile_names_only_entries_the_db_carries():
    present = {e["ic_class"] for e in _db()["entries"]}
    for c in _profile()["db_classes"]:
        assert c in present, f"profile names {c!r}, entries[] does not carry it"


def test_the_function_and_initiator_families_are_excluded_on_purpose():
    """The exclusion is a DECISION and is pinned as one. These six are real
    craft; each is about the function behind the bus, the initiator side, an
    interconnect element, or another class. A later landing that wants one must
    say which feature it answers, not quietly widen the list."""
    present = {e["ic_class"] for e in _db()["entries"]}
    assert _EXCLUDED <= present, "one of the deliberately-excluded entries is gone"
    assert not (_EXCLUDED & set(_profile()["db_classes"]))


# ── 3. the pack, both directions ───────────────────────────────────────────

def test_the_pack_carries_the_class_contract(tmp_path):
    h = PACK.assemble(_PERIPHERAL_PROMPT, None, None, [], ["gate"], tmp_path,
                      output_target="l_doc_expectations.json", ic_class=_CLASS)
    cf = h["class_first"]
    assert h["interface_contract"] == "contract.md"
    assert cf["contract_kind"] == "class_integration_contract_md"
    assert cf["db_class_selection"] == "CLASS_CONFINED"
    body = (tmp_path / "contract.md").read_text()
    for req in _profile()["integration_contract"]:
        assert req in body, f"the contract document drops a requirement: {req[:60]}…"


def test_the_assembly_status_is_computed_both_ways(tmp_path):
    """A brief that names no module is INCOMPLETE (it carries the class
    contract and the class's craft); the same brief with a module name is
    ASSEMBLED. Both, so the status is computed rather than constant here."""
    a = PACK.assemble(_PERIPHERAL_PROMPT, None, None, [], ["gate"],
                      tmp_path / "a", output_target="l_doc_expectations.json",
                      ic_class=_CLASS)
    assert a["target_module"] is None
    assert a["class_first"]["assembly_status"] == "ASSEMBLED_INCOMPLETE"
    assert a["class_first"]["missing_fields"] == ["target_module"]
    assert "not_assembled_reason" not in a["class_first"]
    b = PACK.assemble(_PERIPHERAL_PROMPT + " The module `regblk` has the "
                      "following hardware interfaces defined.", None, None, [],
                      ["gate"], tmp_path / "b",
                      output_target="l_doc_expectations.json", ic_class=_CLASS)
    assert b["target_module"] == "regblk"
    assert b["class_first"]["assembly_status"] == "ASSEMBLED"


def test_the_digest_the_agent_reads_agrees_with_the_declared_selection(tmp_path):
    allowed = set(_profile()["db_classes"])
    h = PACK.assemble(_PERIPHERAL_PROMPT, None, None, [], ["gate"], tmp_path,
                      output_target="l_doc_expectations.json", ic_class=_CLASS)
    named = set(re.findall(r"^- \*\*\[([^\]]+)\]\*\*",
                           (tmp_path / "ic_expert_db.md").read_text(), re.M))
    assert named, "the rendered digest names no ic_class at all"
    assert named <= allowed, f"out-of-class entries in the digest: {sorted(named - allowed)}"
    assert named == {x["ic_class"] for x in h["db_classes"]}


def test_mutation_the_unprofiled_pack_is_the_DECLARED_GAP_state(tmp_path, monkeypatch):
    monkeypatch.setattr(Q, "_DEFAULT_DB", _null_profile_db(tmp_path))
    h = PACK.assemble(_PERIPHERAL_PROMPT, None, None, [], ["gate"],
                      tmp_path / "pack",
                      output_target="l_doc_expectations.json", ic_class=_CLASS)
    assert "class_first" not in h
    assert h["target_module"] is None and h["interface_contract"] is None
    assert not (tmp_path / "pack" / "contract.md").exists()
    d = PACK.class_first_disposition(_CLASS)
    assert d["profile"] == "NOT_PROFILED" and d["registered"] is True
    assert d["db_class_selection"] == "LEXICAL_UNCONFINED"


def test_a_design_of_another_class_is_byte_identical(tmp_path):
    other = next(k for k, v in _db()["registered_class_profiles"].items()
                 if not k.startswith("_") and v is None)
    prompt = ("A serial-parallel multiplier: the multiplicand is applied in "
              "parallel and the multiplier one bit per clock, with a "
              "clock-divided strobe advancing the accumulation.")
    one = PACK.assemble(prompt, None, None, [], ["gate"], tmp_path / "a",
                        output_target="l_doc_expectations.json")
    two = PACK.assemble(prompt, None, None, [], ["gate"], tmp_path / "b",
                        output_target="l_doc_expectations.json", ic_class=other)
    assert one == two and "class_first" not in two
    names = sorted(q.name for q in (tmp_path / "a").iterdir())
    assert names == sorted(q.name for q in (tmp_path / "b").iterdir())
    for n in names:
        assert (tmp_path / "a" / n).read_bytes() == (tmp_path / "b" / n).read_bytes()
