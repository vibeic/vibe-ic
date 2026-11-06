#!/usr/bin/env python3
"""Regression for #2110 — the class profile for `bus_interconnect_protocol`.

THE CORPUS ARM FOR THIS CLASS IS EMPTY, AND THAT IS SAID FIRST. The shipped
classifier puts three corpus doc-sets in this class and NOT ONE of them carries
a design input the retrieval can read — they have no `input/` tree at all. So
unlike the classes profiled beside it, this profile has no "here is what the
pack used to be on a real design of the class" measurement behind it, and no
amount of test structure creates one. The evidence it does have is stated
below, and the ruling that authorises a profile on that evidence is the one
that says a class with no corpus design may be profiled only where its FEATURES
ALONE determine the selection.

THEY DO, HERE. `ic_class_profile._BUS_PROTO_FEATURES` is an explicit six-entry
structural table, every one of whose features has craft in the DB, and the map
is pinned in both directions. Two properties stand in for the corpus arm, and
neither is a restatement of the map:

  * CONFINEMENT — a brief written from the class's own vocabulary retrieves a
    pack that is five-for-five OUT of class unconfined (a shift collector, a
    register slave, a multiplier, a register file with BIST, a ping-pong
    buffer) and five-for-five IN class confined, with the two arms disjoint.
  * REACHABILITY — every entry the profile selects actually surfaces in a
    top-5 pack for at least one brief written from a feature's own vocabulary.
    An entry that no realistic brief can rank into the pack is dead weight the
    membership assertion cannot see, and one candidate (`skid-buffer`) was
    dropped from this profile BECAUSE it failed this check: it is genuine
    interconnect craft, it answers none of the six features, and it never
    reached a top-5. Both reasons are recorded; either alone would have been
    enough.

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

_CLASS = "bus_interconnect_protocol"

_FABRIC_PROMPT = (
    "Specify a memory-mapped interconnect protocol with five independent "
    "channels: write address, write data, write response, read address and "
    "read data. Each channel uses a valid/ready handshake, and a transfer "
    "happens on the cycle both are high. A manager issues burst transactions "
    "of up to sixteen beats to a subordinate through a crossbar fabric that "
    "arbitrates between managers; the fabric may insert width conversion and "
    "buffering on a path. A watchdog raises an error response when a "
    "transaction does not complete. The address decoder holds its control "
    "registers in a memory-mapped register bank and the parity checksum is "
    "accumulated in a serial-parallel fashion."
)

_FEATURE_TO_DB_CLASSES = {
    "valid_ready_handshake": ["handshake-valid-ready"],
    "multiple_channels": ["axi-stream"],
    "master_slave_roles": ["bus-arbiter"],
    "burst_transfers": ["axi-stream-width-downsizer",
                        "axi-stream-datawidth-upsizer"],
    "interconnect_topology": ["bus-arbiter", "axi-interconnect-timeout",
                              "bus-protocol-bridge"],
    "handshake_concept": ["handshake-valid-ready"],
}

# One brief per feature, in that feature's own vocabulary. Used for the
# reachability property, not for a ranking claim: the ranking is per-LESSON and
# is NOT a per-feature retriever, and a test that asserted each feature's brief
# ranks its own entry first would be false for three of the six (measured).
_FEATURE_PROBES = {
    "valid_ready_handshake":
        "a transfer happens on the cycle valid and ready are both high; the "
        "source must hold the payload stable while ready is low",
    "multiple_channels":
        "the protocol partitions into five independent channels, each carrying "
        "its own payload between the two ends",
    "master_slave_roles":
        "several managers issue transactions to one subordinate and the fabric "
        "arbitrates between them with a stated tie-break",
    "burst_transfers":
        "a burst transaction carries up to sixteen beats of data, and a width "
        "converter splits each wide beat into narrower ones",
    "interconnect_topology":
        "the interconnect fabric routes each request through a bridge stage "
        "and a watchdog raises an error response when a transaction never "
        "completes",
    "handshake_concept":
        "the handshake concept is named for every channel of this protocol",
}


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


# ── 1. confinement, both directions ────────────────────────────────────────

def test_a_fabric_brief_gets_an_all_in_class_pack():
    allowed = set(_profile()["db_classes"])
    hits = Q.query(_FABRIC_PROMPT, k=5, ic_class=_CLASS)
    assert hits
    got = {h["ic_class"] for h in hits}
    assert got <= allowed, f"out-of-class entries leaked in: {sorted(got - allowed)}"


def test_mutation_reverting_the_profile_brings_the_out_of_class_pack_back(tmp_path):
    allowed = set(_profile()["db_classes"])
    got = {h["ic_class"] for h in
           Q.query(_FABRIC_PROMPT, k=5, db_path=_null_profile_db(tmp_path),
                   ic_class=_CLASS)}
    assert got, "the mutation arm retrieved nothing at all"
    assert not (got & allowed), (
        f"the mutation did not reproduce the defect — still in-class: "
        f"{sorted(got & allowed)}")


def test_the_class_decides_membership_not_the_phrase():
    allowed = set(_profile()["db_classes"])
    assert {h["ic_class"] for h in
            Q.query("a design.", k=99, ic_class=_CLASS)} == allowed


def test_the_profiled_classes_select_disjoint_knowledge():
    prof = _db()["registered_class_profiles"]
    named = {k: set(v["db_classes"]) for k, v in prof.items()
             if not k.startswith("_") and isinstance(v, dict)}
    assert len(named) >= 2
    items = sorted(named.items())
    for i, (a, sa) in enumerate(items):
        for b, sb in items[i + 1:]:
            assert not (sa & sb), f"profiles {a} and {b} share db_classes {sorted(sa & sb)}"


# ── 2. the derivation ─────────────────────────────────────────────────────

def test_every_selected_db_class_answers_a_feature_the_classifier_uses():
    selected = set(_profile()["db_classes"])
    features = {name for name, _ in ICP._BUS_PROTO_FEATURES}
    assert features == set(_FEATURE_TO_DB_CLASSES), (
        f"the classifier's feature set moved to {sorted(features)}; the "
        f"profile's derivation has to be re-taken against it")
    for feat, entries in _FEATURE_TO_DB_CLASSES.items():
        assert entries, f"feature {feat!r} has no craft in the profile"
    mapped = {c for v in _FEATURE_TO_DB_CLASSES.values() for c in v}
    assert mapped == selected, (
        f"selected-but-unmapped {sorted(selected - mapped)} / "
        f"mapped-but-unselected {sorted(mapped - selected)}")


def test_the_profile_names_only_entries_the_db_carries():
    present = {e["ic_class"] for e in _db()["entries"]}
    for c in _profile()["db_classes"]:
        assert c in present, f"profile names {c!r}, entries[] does not carry it"


# ── 3. reachability — the property that stands in for the missing corpus ──

def test_every_selected_entry_can_actually_reach_a_pack():
    """MEMBERSHIP IS NOT ENOUGH. An entry the profile selects that no realistic
    brief can rank into a top-5 is dead weight, and the membership assertion
    above cannot see it. Six briefs, one per feature, in that feature's own
    words; the union of their top-5 packs must be the WHOLE selection."""
    selected = set(_profile()["db_classes"])
    assert set(_FEATURE_PROBES) == set(_FEATURE_TO_DB_CLASSES)
    reached = set()
    for feat, text in _FEATURE_PROBES.items():
        got = {h["ic_class"] for h in Q.query(text, k=5, ic_class=_CLASS)}
        assert got <= selected, f"{feat}: out of class {sorted(got - selected)}"
        reached |= got
    assert reached == selected, f"never reached by any feature brief: {sorted(selected - reached)}"


def test_the_dropped_candidate_is_still_in_the_db_and_still_out_of_the_profile():
    """`skid-buffer` is genuine interconnect craft that was measured OUT of this
    profile on two independent grounds: it answers none of the six features, and
    it never reached a top-5 for any of them. Pinned so the drop stays a
    decision — and so a landing that wants it has to name the feature it answers
    and show it can surface."""
    present = {e["ic_class"] for e in _db()["entries"]}
    assert "skid-buffer" in present
    assert "skid-buffer" not in set(_profile()["db_classes"])
    assert "skid-buffer" not in {c for v in _FEATURE_TO_DB_CLASSES.values() for c in v}


# ── 4. the pack, both directions ──────────────────────────────────────────

def test_the_pack_carries_the_class_contract(tmp_path):
    h = PACK.assemble(_FABRIC_PROMPT, None, None, [], ["gate"], tmp_path,
                      output_target="l_doc_expectations.json", ic_class=_CLASS)
    cf = h["class_first"]
    assert h["interface_contract"] == "contract.md"
    assert cf["contract_kind"] == "class_integration_contract_md"
    assert cf["db_class_selection"] == "CLASS_CONFINED"
    body = (tmp_path / "contract.md").read_text()
    for req in _profile()["integration_contract"]:
        assert req in body, f"the contract document drops a requirement: {req[:60]}…"


def test_the_assembly_status_is_computed_both_ways(tmp_path):
    a = PACK.assemble(_FABRIC_PROMPT, None, None, [], ["gate"], tmp_path / "a",
                      output_target="l_doc_expectations.json", ic_class=_CLASS)
    assert a["target_module"] is None
    assert a["class_first"]["assembly_status"] == "ASSEMBLED_INCOMPLETE"
    b = PACK.assemble(_FABRIC_PROMPT + " The module `fabric_top` has the "
                      "following hardware interfaces defined.", None, None, [],
                      ["gate"], tmp_path / "b",
                      output_target="l_doc_expectations.json", ic_class=_CLASS)
    assert b["target_module"] == "fabric_top"
    assert b["class_first"]["assembly_status"] == "ASSEMBLED"


def test_the_digest_the_agent_reads_agrees_with_the_declared_selection(tmp_path):
    allowed = set(_profile()["db_classes"])
    h = PACK.assemble(_FABRIC_PROMPT, None, None, [], ["gate"], tmp_path,
                      output_target="l_doc_expectations.json", ic_class=_CLASS)
    named = set(re.findall(r"^- \*\*\[([^\]]+)\]\*\*",
                           (tmp_path / "ic_expert_db.md").read_text(), re.M))
    assert named and named <= allowed
    assert named == {x["ic_class"] for x in h["db_classes"]}


def test_mutation_the_unprofiled_pack_is_the_DECLARED_GAP_state(tmp_path, monkeypatch):
    monkeypatch.setattr(Q, "_DEFAULT_DB", _null_profile_db(tmp_path))
    h = PACK.assemble(_FABRIC_PROMPT, None, None, [], ["gate"],
                      tmp_path / "pack",
                      output_target="l_doc_expectations.json", ic_class=_CLASS)
    assert "class_first" not in h
    assert h["interface_contract"] is None
    d = PACK.class_first_disposition(_CLASS)
    assert d["profile"] == "NOT_PROFILED" and d["registered"] is True


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
