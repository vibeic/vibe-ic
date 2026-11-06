#!/usr/bin/env python3
"""Regression for #2094 — the expert pack a REGISTERED class gets.

THE DEFECT, MEASURED. The Phase-1 expert track assembled a hand-off pack for a
design whose registered `ic_class` was a crypto accelerator, and the pack
carried `target_module: null`, `interface_contract: null` and five db_classes
none of which was crypto. Three of the five were pure retrieval artifacts: the
input sentence "the multipliers are implemented in a serial-parallel fashion"
(describing two internal field multipliers) scored the `serial-parallel-
multiplier` entry — craft about authoring a golden for a serial-parallel
multiplier DESIGN — into a crypto pack. A LITERAL PHRASE COLLISION is not a
design-family match. The pack was handed on anyway, so a 46-expectation review
was recorded as having had an expert pack in hand when the pack held nothing
about the design's class.

THREE THINGS ARE FIXED, AND EACH IS PINNED HERE BOTH WAYS:

  1. CLASS-FIRST — the registered ic_class SELECTS the candidate entries; the
     lexical phrase score only RANKS within them. Positive: a profiled class
     gets only in-class entries. Negative (the MUTATION): with the class-first
     rule removed — the same call with `ic_class=None` — the collision comes
     straight back. A confinement that cannot be seen to bite is not one.

  2. REFUSAL — a pack for a PROFILED class with no target module and no
     interface contract is stamped `NOT_ASSEMBLED` and says why. Negative: give
     it a contract and the same code stamps `ASSEMBLED`, so the status is
     computed rather than constant.

  3. THE UNPROFILED CLASS IS UNTOUCHED — a registered class the DB does not
     profile retrieves exactly what it retrieved before (byte-identical hit
     list) and its pack is not refused. Refusing on an unprofiled class would
     score the absence of a profile as the design's deficiency, and the
     registry says of the classifier's terminal catch-all, in its own words,
     that designs landing there "are UNCLASSIFIED, not classified".

Plus the DECLARED-GAP invariant: every name in `ic_class_registry.json` appears
in `registered_class_profiles`, profiled or explicitly null. A registered class
that is simply absent is how "not yet profiled" goes silent.

chip-AGNOSTIC: the fixtures below are synthetic; the one real-corpus fact used
is the collision SENTENCE SHAPE, which names no chip, vendor, SKU or node.
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

_DB = _PROGRAMS.parent / "agents" / "ic_expert_db" / "ic_expert_db.json"
_REGISTRY = _PROGRAMS / "ic_class_registry.json"

# The collision, reduced to its shape: a crypto brief whose datapath prose uses
# the words another design family owns.
_CRYPTO_PROMPT = (
    "Implement a block cipher accelerator with a software-visible register "
    "interface: key registers, an initialisation vector, a data input and a "
    "data output, a control register selecting the operation mode, and a "
    "status register carrying an idle bit. The multipliers inside the "
    "authentication stage are implemented in a serial-parallel fashion to "
    "trade off area against performance. A second clock input carries the "
    "entropy interface into the block. The module `cipherblk` has the "
    "following hardware interfaces defined."
)


def _db() -> dict:
    return json.loads(_DB.read_text())


# THE SUBJECT OF THIS FILE, NAMED (#2110). This helper used to return "the
# first profiled class in the map", which was an unambiguous way of saying
# `crypto_accelerator` for exactly as long as that was the only profiled class.
# The moment a SECOND class was profiled the helper started returning the other
# one, and every assertion below — the collision, the contract, the refusal —
# went on passing while measuring a design family this file was never written
# about. Measured, not imagined: with `processor_cpu` profiled, this file ran
# 19/19 green against `processor_cpu`. A file that keeps passing after its
# subject is swapped out from under it is not testing what it says it is, so
# the subject is now spelled, and its being profiled is asserted rather than
# assumed.
_SUBJECT_CLASS = "crypto_accelerator"


def _profiled_class() -> str:
    prof = _db()["registered_class_profiles"]
    assert prof.get(_SUBJECT_CLASS), (
        f"{_SUBJECT_CLASS!r} is the class this regression is about and the DB "
        f"no longer profiles it")
    return _SUBJECT_CLASS


# ── 1. class-first, both directions ────────────────────────────────────────

def test_class_first_confines_retrieval_to_the_registered_class():
    cls = _profiled_class()
    allowed = set(_db()["registered_class_profiles"][cls]["db_classes"])
    hits = Q.query(_CRYPTO_PROMPT, k=5, ic_class=cls)
    assert hits, "class-first retrieval returned nothing at all"
    got = {h["ic_class"] for h in hits}
    assert got <= allowed, f"out-of-class entries leaked in: {sorted(got - allowed)}"


def test_the_phrase_collision_no_longer_reaches_a_profiled_pack():
    cls = _profiled_class()
    hits = Q.query(_CRYPTO_PROMPT, k=5, ic_class=cls)
    assert "serial-parallel-multiplier" not in {h["ic_class"] for h in hits}


def test_mutation_removing_class_first_brings_the_collision_back():
    """THE NEGATIVE CONTROL. The identical prompt with the class-first rule out
    of the way retrieves the colliding entry — which is what the shipped
    behaviour did on the real design. Without this, a test that the collision is
    absent could be passing because the entry is unreachable for some unrelated
    reason."""
    hits = Q.query(_CRYPTO_PROMPT, k=5, ic_class=None)
    assert "serial-parallel-multiplier" in {h["ic_class"] for h in hits}, (
        "the mutation did not reproduce the defect, so the positive assertion "
        "above proves nothing about class-first")


def test_class_first_keeps_an_in_class_entry_the_phrase_never_mentions():
    """Membership is the CLASS's decision, not the phrase's: an in-class entry
    the prompt does not happen to use the words of is still offered. Dropping it
    would let the phrase decide membership again through the back door."""
    cls = _profiled_class()
    allowed = _db()["registered_class_profiles"][cls]["db_classes"]
    hits = Q.query("a design.", k=99, ic_class=cls)
    assert {h["ic_class"] for h in hits} == set(allowed)


def test_expand_related_cannot_reopen_the_class_boundary():
    """The related[] concept graph is the one other door out of the candidate
    set. It follows the TOP hit's links, and an in-class entry may well link to
    an out-of-class sibling — the crypto entries do. Under class-first the graph
    is walked over the CONFINED entries, so an out-of-class target resolves to
    nothing and is skipped rather than appended. Pinned because it holds by
    construction, which is exactly the kind of property a later edit breaks
    without noticing."""
    cls = _profiled_class()
    allowed = set(_db()["registered_class_profiles"][cls]["db_classes"])
    hits = Q.query(_CRYPTO_PROMPT, k=5, ic_class=cls, expand_related=True)
    assert {h["ic_class"] for h in hits} <= allowed
    # and the control: unconfined, the same call DOES leave the crypto classes
    assert not {h["ic_class"] for h in
                Q.query(_CRYPTO_PROMPT, k=5, expand_related=True)} <= allowed


def test_class_first_degrades_loudly_when_a_profile_names_a_missing_entry(tmp_path):
    db = _db()
    cls = _profiled_class()
    db["registered_class_profiles"][cls]["db_classes"] = ["no-such-entry"]
    p = tmp_path / "db.json"
    p.write_text(json.dumps(db))
    with pytest.raises(KeyError):
        Q.query(_CRYPTO_PROMPT, k=5, db_path=p, ic_class=cls)


def test_the_loud_failure_is_not_swallowed_into_an_empty_pack(tmp_path):
    """The pack's retrieval wrapper answers "found nothing" with an empty list.
    That is right for a miss and WRONG for a broken class-first configuration —
    swallowing it turns a mis-declared profile into a silently empty pack, which
    is the whole failure mode. The KeyError must reach the caller."""
    db = _db()
    cls = _profiled_class()
    db["registered_class_profiles"][cls]["db_classes"] = ["no-such-entry"]
    p = tmp_path / "db.json"
    p.write_text(json.dumps(db))
    import ic_expert_db_query as _q
    orig = _q._DEFAULT_DB
    try:
        _q._DEFAULT_DB = p
        with pytest.raises(KeyError):
            PACK.assemble(_CRYPTO_PROMPT, None, None, [], ["gate"],
                          tmp_path / "pack",
                          output_target="l_doc_expectations.json", ic_class=cls)
    finally:
        _q._DEFAULT_DB = orig


def test_a_supplied_interface_still_yields_a_module_header_contract(tmp_path):
    """Ordering control. The target is resolved BEFORE the contract is chosen,
    so a caller that hands over an interface but no target gets `contract.v`
    (the module header) and not the class document — the class contract is the
    fallback for a hand-off with no ports, never a replacement for ports."""
    cls = _profiled_class()
    iface = [{"name": "clk", "dir": "input", "width": 1},
             {"name": "q", "dir": "output", "width": 8}]
    h = PACK.assemble(_CRYPTO_PROMPT, iface, None, [], ["gate"], tmp_path,
                      output_target="l_doc_expectations.json", ic_class=cls)
    assert h["target_module"] == "cipherblk"
    assert h["interface_contract"] == "contract.v"
    assert h["class_first"]["contract_kind"] == "module_header_v"
    assert "module cipherblk (" in (tmp_path / "contract.v").read_text()


# ── 2. the refusal, both directions ────────────────────────────────────────

def test_pack_for_a_profiled_class_is_assembled_and_carries_a_contract(tmp_path):
    cls = _profiled_class()
    h = PACK.assemble(_CRYPTO_PROMPT, None, None, [], ["gate"], tmp_path,
                      output_target="l_doc_expectations.json", ic_class=cls)
    cf = h["class_first"]
    assert cf["assembly_status"] == "ASSEMBLED", cf.get("not_assembled_reason")
    assert h["interface_contract"] == "contract.md"
    assert (tmp_path / "contract.md").is_file()
    # the top module the design INPUT states, recovered — not invented
    assert h["target_module"] == "cipherblk"
    assert cf["db_class_selection"] == "CLASS_CONFINED"


def test_pack_with_no_target_and_no_contract_for_a_profiled_class_is_refused(tmp_path):
    """THE REFUSAL, forced. A profile with an empty integration_contract and a
    prompt naming no module leaves the pack with nothing class-specific — and it
    must SAY so rather than be handed on as an assembled pack."""
    db = _db()
    cls = _profiled_class()
    db["registered_class_profiles"][cls]["integration_contract"] = []
    p = tmp_path / "db.json"
    p.write_text(json.dumps(db))
    import ic_expert_db_query as _q
    orig = _q._DEFAULT_DB
    try:
        _q._DEFAULT_DB = p
        h = PACK.assemble("a design with no module name in it.", None, None,
                          [], ["gate"], tmp_path / "pack",
                          output_target="l_doc_expectations.json", ic_class=cls)
    finally:
        _q._DEFAULT_DB = orig
    cf = h["class_first"]
    assert cf["assembly_status"] == "NOT_ASSEMBLED"
    assert h["target_module"] is None and h["interface_contract"] is None
    assert "target_module" in cf["not_assembled_reason"]
    assert "interface_contract" in cf["not_assembled_reason"]


def test_the_digest_the_agent_reads_agrees_with_the_declared_db_classes(tmp_path):
    """THE ARTEFACT, NOT THE NOTE ABOUT IT. `ic_expert_db.md` is the file the
    author actually reads; `db_classes` in the descriptor is only a note. They
    are produced by two separate calls, and confining one without the other
    leaves the pack DESCRIBING the confined selection while DELIVERING the
    unconfined one — the colliding lesson still in front of the author, and no
    reader of the descriptor able to see it. Measured: that is exactly what the
    first cut of this fix did."""
    cls = _profiled_class()
    allowed = set(_db()["registered_class_profiles"][cls]["db_classes"])
    h = PACK.assemble(_CRYPTO_PROMPT, None, None, [], ["gate"], tmp_path,
                      output_target="l_doc_expectations.json", ic_class=cls)
    digest = (tmp_path / "ic_expert_db.md").read_text()
    named = set(re.findall(r"^- \*\*\[([^\]]+)\]\*\*", digest, re.M))
    assert named, "the rendered digest names no ic_class at all"
    assert named <= allowed, f"out-of-class entries in the digest: {sorted(named - allowed)}"
    assert "serial-parallel-multiplier" not in named
    assert named == {h_["ic_class"] for h_ in h["db_classes"]}


def test_a_pack_that_has_the_class_contract_but_no_module_is_not_called_empty(tmp_path):
    """THE MIDDLE STATE. A profiled class whose design input names no module
    still gets the class integration contract and the class's lessons — that
    pack is INCOMPLETE, not empty, and refusing it as NOT_ASSEMBLED would make
    the refusal's own words ("contributed no class knowledge") false. A refusal
    that overstates its grounds is the same defect as a pack that overstates its
    contents, pointed the other way."""
    cls = _profiled_class()
    h = PACK.assemble("a block cipher accelerator with key registers and an "
                      "idle status bit.", None, None, [], ["gate"], tmp_path,
                      output_target="l_doc_expectations.json", ic_class=cls)
    cf = h["class_first"]
    assert h["target_module"] is None
    assert h["interface_contract"] == "contract.md"
    assert cf["assembly_status"] == "ASSEMBLED_INCOMPLETE"
    assert cf["missing_fields"] == ["target_module"]
    assert "not_assembled_reason" not in cf
    assert cf["db_classes_in_pack"], "the pack really does carry class knowledge"


def test_target_recovery_is_polarity_aware():
    """A sentence that DENIES a module name must not publish it (#712's one
    vocabulary). Both directions: the denied candidate is skipped AND the
    declared one is still taken."""
    assert PACK.recover_target_module("The module `core` has interfaces.") == "core"
    assert PACK.recover_target_module(
        "The module `core` is not the top level here.\n"
        "The top-level module is `core_wrap`.") == "core_wrap"


# ── 3. an unprofiled registered class is untouched ─────────────────────────

def _unprofiled_class() -> str:
    prof = _db()["registered_class_profiles"]
    named = [k for k, v in prof.items() if not k.startswith("_") and v is None]
    assert named, "every registered class is profiled; this control is empty"
    return named[0]


def test_unprofiled_registered_class_retrieval_is_byte_identical():
    cls = _unprofiled_class()
    a = Q.query(_CRYPTO_PROMPT, k=5)
    b = Q.query(_CRYPTO_PROMPT, k=5, ic_class=cls)
    assert a == b


def test_unprofiled_registered_class_pack_is_byte_identical(tmp_path):
    cls = _unprofiled_class()
    one = PACK.assemble(_CRYPTO_PROMPT, None, None, [], ["gate"], tmp_path / "a",
                        output_target="l_doc_expectations.json")
    two = PACK.assemble(_CRYPTO_PROMPT, None, None, [], ["gate"], tmp_path / "b",
                        output_target="l_doc_expectations.json", ic_class=cls)
    assert one == two
    assert "class_first" not in two
    assert ((tmp_path / "a" / "ic_expert_agent_handoff.json").read_bytes()
            == (tmp_path / "b" / "ic_expert_agent_handoff.json").read_bytes())
    assert sorted(q.name for q in (tmp_path / "a").iterdir()) == \
           sorted(q.name for q in (tmp_path / "b").iterdir())


def test_the_unprofiled_case_is_still_STATED_to_a_consumer():
    """The pack file gains no key, so the fact has to live somewhere a reader
    looks: the disposition a consumer writes into its own record. "We did not
    confine" and "there was nothing to confine to" must stay different."""
    reg = PACK.class_first_disposition(_unprofiled_class())
    assert reg["profile"] == "NOT_PROFILED" and reg["registered"] is True
    assert reg["db_class_selection"] == "LEXICAL_UNCONFINED"
    absent = PACK.class_first_disposition("not-a-registered-class")
    assert absent["profile"] == "NOT_A_REGISTERED_CLASS"
    assert absent["registered"] is False
    assert PACK.class_first_disposition(_profiled_class())["profile"] == "PROFILED"


# ── the declared-gap invariant ─────────────────────────────────────────────

def test_every_registered_class_is_named_in_registered_class_profiles():
    registered = {c["name"] for c in json.loads(_REGISTRY.read_text())["classes"]}
    profiled = {k for k in _db()["registered_class_profiles"] if not k.startswith("_")}
    assert registered - profiled == set(), (
        f"registered but absent from registered_class_profiles: "
        f"{sorted(registered - profiled)} — null is a DECLARED gap, absence is a "
        f"silent one")
    assert profiled - registered == set(), (
        f"profiled but not a registered ic_class: {sorted(profiled - registered)}")


# ── the crypto entries themselves ──────────────────────────────────────────

def test_the_profiled_class_entries_exist_and_the_db_gate_is_clean():
    db = _db()
    present = {e["ic_class"] for e in db["entries"]}
    for c in db["registered_class_profiles"][_profiled_class()]["db_classes"]:
        assert c in present, f"profile names {c!r}, entries[] does not carry it"


def test_the_new_entries_state_a_source_sentence_class_and_name_no_design():
    """Each added lesson has to be usable on a design nobody has seen, so it
    carries the SHAPE of the input sentence it came from, never the design it
    was measured on."""
    entry = next(e for e in _db()["entries"]
                 if e["ic_class"] == "block-cipher-accelerator")
    assert entry["lesson_count"] == len(entry["lessons"]) >= 3
    joined = " ".join(entry["lessons"]).lower()
    assert joined.count("source-sentence class") >= 3
    for banned in ("opentitan", "lowrisc", "benchmark ic", "opentitan_aes"):
        assert banned not in joined, f"design-identifying literal {banned!r} in a lesson"
