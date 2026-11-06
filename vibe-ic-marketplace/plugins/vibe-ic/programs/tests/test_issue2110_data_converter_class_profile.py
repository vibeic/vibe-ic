#!/usr/bin/env python3
"""Regression for #2110 — the class profile for `data_converter`.

THE DEFECT, MEASURED ON THE CLASS'S ONE CORPUS DESIGN. `data_converter` was
split out of `pure_analog` by #613 precisely because such a design HAS a digital
datapath — the decimation / serial-readout chain that has to reach synth, PnR
and GDS through `spec-to-rtl`. Its expert pack was still phrase-selected. On
pristine main the class's one corpus design got:

    serial-parallel-multiplier, serial-parallel-multiplier,
    sigma-delta-modulator, mac-accumulator, spi-serializer-fsm

Four of five out of class; the single in-class entry ranked third, and the
class's own READOUT craft — the decimation chain, which is the half of the
design the class exists to name — did not appear at all.

THE DERIVATION IS SHAPED BY THE CLASSIFIER, AND THIS CLASSIFIER IS A
CONJUNCTION, NOT A FEATURE TABLE. `ic_class_profile` assigns this class when
`has_analog AND NOT has_command_protocol AND NOT has_fsm AND
_v1_6_613_has_digital_serial_readout`. Only the POSITIVE conjuncts can have
craft: a negative conjunct states what the design is NOT, and there is no craft
for an absence. So the map below has two entries and two explicit empties, and
the empties are written down rather than omitted — an omitted key and a key
mapped to nothing are the same dict and very different claims.

chip-AGNOSTIC: every fixture is synthetic.
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

_CLASS = "data_converter"

_CONVERTER_PROMPT = (
    "Implement a second-order sigma-delta analog-to-digital converter. The "
    "analog modulator produces a one-bit serial output stream at the "
    "oversampled modulator clock; the digital readout decimates that bitstream "
    "into 16-bit signed output words at one sixty-fourth of the modulator rate. "
    "Each output word is presented on a memory-mapped data port with a "
    "data-ready strobe, and the accumulator that forms the running sum "
    "multiplies each sample by the filter coefficient in a serial-parallel "
    "fashion."
)

# The four conjuncts of this class's decision -> the craft that answers each.
# The two NEGATIVE conjuncts map to nothing, on purpose and in writing.
_CONJUNCT_TO_DB_CLASSES = {
    "has_analog": ["sigma-delta-modulator"],
    "digital_serial_readout": ["decimator-peak-detect"],
    "not_has_command_protocol": [],
    "not_has_fsm": [],
}
_POSITIVE = ("has_analog", "digital_serial_readout")


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

def test_a_converter_brief_gets_an_all_in_class_pack():
    allowed = set(_profile()["db_classes"])
    hits = Q.query(_CONVERTER_PROMPT, k=5, ic_class=_CLASS)
    assert hits, "class-first retrieval returned nothing at all"
    got = {h["ic_class"] for h in hits}
    assert got <= allowed, f"out-of-class entries leaked in: {sorted(got - allowed)}"


def test_mutation_reverting_the_profile_loses_the_readout_craft(tmp_path):
    """THE NEGATIVE CONTROL, and it is stated as the MEASURED HARM rather than
    as "the arms differ". Unconfined, this brief retrieves a multiplier twice
    over and the class's own decimation craft — the digital readout, which is
    the half of the design this class was split out to name — does not appear at
    all. The modulator entry DOES survive unconfined (it ranks third), so an
    assertion that the two arms are disjoint would be false here; asserting the
    thing that is actually true is what makes this control mean something."""
    got = {h["ic_class"] for h in
           Q.query(_CONVERTER_PROMPT, k=5, db_path=_null_profile_db(tmp_path),
                   ic_class=_CLASS)}
    assert got, "the mutation arm retrieved nothing at all"
    assert "decimator-peak-detect" not in got, (
        "the mutation did not reproduce the defect — the readout craft is "
        "already there unconfined, so the positive assertion proves nothing")
    assert got - set(_profile()["db_classes"]), (
        "the mutation arm returned no out-of-class entry at all")
    assert "serial-parallel-multiplier" in got


def test_the_class_decides_membership_not_the_phrase():
    allowed = set(_profile()["db_classes"])
    assert {h["ic_class"] for h in
            Q.query("a design.", k=99, ic_class=_CLASS)} == allowed


def test_the_profiled_classes_select_disjoint_knowledge():
    prof = _db()["registered_class_profiles"]
    named = {k: set(v["db_classes"]) for k, v in prof.items()
             if not k.startswith("_") and isinstance(v, dict)}
    assert len(named) >= 2, "only one class is profiled; this control is empty"
    items = sorted(named.items())
    for i, (a, sa) in enumerate(items):
        for b, sb in items[i + 1:]:
            assert not (sa & sb), f"profiles {a} and {b} share db_classes {sorted(sa & sb)}"


# ── 2. the derivation, for a CONJUNCTION-decided class ─────────────────────

def test_every_positive_conjunct_has_craft_and_nothing_else_is_selected():
    selected = set(_profile()["db_classes"])
    for c in _POSITIVE:
        assert _CONJUNCT_TO_DB_CLASSES[c], f"positive conjunct {c!r} has no craft"
    mapped = {x for v in _CONJUNCT_TO_DB_CLASSES.values() for x in v}
    assert mapped == selected, (
        f"selected-but-unmapped {sorted(selected - mapped)} / "
        f"mapped-but-unselected {sorted(mapped - selected)}")


def test_the_negative_conjuncts_are_written_down_as_empty():
    """An omitted key and a key mapped to nothing are the same dict and very
    different claims. The two negatives are here, empty, so a later reader can
    see they were considered rather than forgotten."""
    for c in ("not_has_command_protocol", "not_has_fsm"):
        assert c in _CONJUNCT_TO_DB_CLASSES
        assert _CONJUNCT_TO_DB_CLASSES[c] == []


def test_the_conjuncts_this_map_names_are_the_ones_the_classifier_computes():
    """The enumeration is DERIVED, so it has to be checked against the tree
    rather than against memory. Each conjunct names a predicate the classifier
    actually evaluates, and the positive discriminator is exercised on this
    class's own vocabulary so the mapped conjunct is live code, not a name."""
    assert callable(ICP._v1_6_613_has_digital_serial_readout)
    assert callable(ICP._l6_has_fsm)
    assert callable(ICP._l3_has_commands)
    # the vocabulary the discriminator's own regex names, not a paraphrase of
    # it: a first draft of this case said "one-bit serial" and the discriminator
    # answered False, which is a fact about my fixture and not about the class.
    l1 = {"description": "the modulator emits a 1-bit serial output stream"}
    assert ICP._v1_6_613_has_digital_serial_readout(l1, None) is True
    assert ICP._v1_6_613_has_digital_serial_readout(
        {"description": "a low-dropout regulator with a trimmed reference"},
        None) is False


def test_the_profile_names_only_entries_the_db_carries():
    present = {e["ic_class"] for e in _db()["entries"]}
    for c in _profile()["db_classes"]:
        assert c in present, f"profile names {c!r}, entries[] does not carry it"


# ── 3. the pack, both directions ───────────────────────────────────────────

def test_the_pack_carries_the_class_contract(tmp_path):
    h = PACK.assemble(_CONVERTER_PROMPT, None, None, [], ["gate"], tmp_path,
                      output_target="l_doc_expectations.json", ic_class=_CLASS)
    cf = h["class_first"]
    assert h["interface_contract"] == "contract.md"
    assert cf["contract_kind"] == "class_integration_contract_md"
    assert cf["db_class_selection"] == "CLASS_CONFINED"
    body = (tmp_path / "contract.md").read_text()
    for req in _profile()["integration_contract"]:
        assert req in body, f"the contract document drops a requirement: {req[:60]}…"


def test_the_assembly_status_is_computed_both_ways(tmp_path):
    a = PACK.assemble(_CONVERTER_PROMPT, None, None, [], ["gate"], tmp_path / "a",
                      output_target="l_doc_expectations.json", ic_class=_CLASS)
    assert a["target_module"] is None
    assert a["class_first"]["assembly_status"] == "ASSEMBLED_INCOMPLETE"
    assert a["class_first"]["missing_fields"] == ["target_module"]
    b = PACK.assemble(_CONVERTER_PROMPT + " The module `adcblk` has the "
                      "following hardware interfaces defined.", None, None, [],
                      ["gate"], tmp_path / "b",
                      output_target="l_doc_expectations.json", ic_class=_CLASS)
    assert b["target_module"] == "adcblk"
    assert b["class_first"]["assembly_status"] == "ASSEMBLED"


def test_the_digest_the_agent_reads_agrees_with_the_declared_selection(tmp_path):
    allowed = set(_profile()["db_classes"])
    h = PACK.assemble(_CONVERTER_PROMPT, None, None, [], ["gate"], tmp_path,
                      output_target="l_doc_expectations.json", ic_class=_CLASS)
    named = set(re.findall(r"^- \*\*\[([^\]]+)\]\*\*",
                           (tmp_path / "ic_expert_db.md").read_text(), re.M))
    assert named, "the rendered digest names no ic_class at all"
    assert named <= allowed
    assert named == {x["ic_class"] for x in h["db_classes"]}


def test_mutation_the_unprofiled_pack_is_the_DECLARED_GAP_state(tmp_path, monkeypatch):
    monkeypatch.setattr(Q, "_DEFAULT_DB", _null_profile_db(tmp_path))
    h = PACK.assemble(_CONVERTER_PROMPT, None, None, [], ["gate"],
                      tmp_path / "pack",
                      output_target="l_doc_expectations.json", ic_class=_CLASS)
    assert "class_first" not in h
    assert h["target_module"] is None and h["interface_contract"] is None
    d = PACK.class_first_disposition(_CLASS)
    assert d["profile"] == "NOT_PROFILED" and d["registered"] is True


def test_the_sibling_analog_class_is_still_UNPROFILED(tmp_path):
    """`pure_analog` sits directly above this class in the classifier's ladder
    and is deliberately NOT profiled: the expert DB carries no craft for a
    design with no digital datapath, and its two analog-adjacent entries are
    THIS class's craft, not that one's. Pinned so the omission stays a decision
    — and so a later landing that profiles it has to come past this test."""
    assert _db()["registered_class_profiles"]["pure_analog"] is None
    d = PACK.class_first_disposition("pure_analog")
    assert d["registered"] is True and d["profile"] == "NOT_PROFILED"


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
