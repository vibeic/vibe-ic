#!/usr/bin/env python3
"""Regression for #2110 — the FIRST of the twelve null class profiles:
`processor_cpu`.

THE DEFECT, MEASURED ON THE TWO CORPUS DESIGNS OF THE CLASS. #2094 made
expert-pack retrieval class-first and named every registered ic_class in the
DB's `registered_class_profiles`, twelve of them as `null` — a DECLARED gap, so
those classes kept the unconfined phrase ranking. For `processor_cpu` that gap
was not cosmetic. On pristine main the two corpus designs the shipped
classifier puts in this class got these packs (k=5, host 8hd-3, base
94617408759e):

  a bit-serial RISC-V SoC   integer-clock-divider, serial-parallel-multiplier,
                            mmio-register-controlled-counter,
                            integer-clock-divider, mmio-timer-counter
  a two-stage RISC-V core   axi-stream, integer-clock-divider,
                            mmio-register-controlled-counter,
                            axi-mmio-cdc-datapath, axi-stream-width-downsizer

Ten of ten out-of-class, and not one of `processor-cpu-core`,
`load-store-unit`, `alu-datapath` or `microcoded-datapath-sequencer` in either.
The same literal-phrase mechanism as #2094: "bit-serial", "clock", "counter",
"stream" are words a processor spec uses about its own datapath, and they
scored entries whose craft is about designing a clock divider or an AXI stream
resizer. A pack of five entries with no referent in the design is what the
class-first rule exists to stop.

WHAT THIS LANDING ADDS, AND WHY EACH PIECE IS PINNED BOTH WAYS:

  1. THE PROFILE. `processor_cpu` selects four db_classes and carries a
     six-requirement integration contract. Positive: a core brief's whole pack
     is in-class. Negative (THE MUTATION): the same brief with the profile back
     at `null` returns the out-of-class list — and returns it as the DECLARED
     GAP state (no `class_first` key, no contract, no recovered target), not as
     some third thing.

  2. THE SELECTION IS DERIVED, NOT ASSERTED. Each of the four db_classes is
     tied to one of the six structural features the shipped classifier itself
     uses to put a design in this class, so the candidate set is derived from
     the code that assigns the class rather than from an author's taste.

  3. THE THIRD TARGET-MODULE CONVENTION. One of the two designs states its top
     module with the NAME BEFORE THE PHRASE, which the two shipped conventions
     do not read, so its pack was ASSEMBLED_INCOMPLETE. The convention is
     APPENDED, so it can only answer where both earlier ones answered nothing:
     pinned by an input that both earlier ones DO answer, whose answer must not
     move.

chip-AGNOSTIC: every fixture below is synthetic. The one real-corpus fact used
is the SENTENCE SHAPE, which names no chip, vendor, SKU or process node.
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
_REGISTRY = _PROGRAMS / "ic_class_registry.json"

_CLASS = "processor_cpu"

# A core brief reduced to its shape: the datapath prose of a processor uses the
# words three other design families own ("bit-serial", "clock divider",
# "counter", "memory-mapped"). Synthetic; no design, vendor or node named.
_CPU_PROMPT = (
    "Implement a small processor core with a bit-serial datapath: the ALU "
    "processes one bit per clock, so a 32-bit operation takes 32 cycles. The "
    "core fetches instructions over a memory bus shared with the data side and "
    "with the architectural register file, and a memory-mapped output register "
    "drives a single status pin. A program counter register holds the reset "
    "vector, and the instruction decoder selects the load/store unit for "
    "memory instructions. The multiplier in the optional extension is built in "
    "a serial-parallel fashion. An internal clock divider produces the slow "
    "timer tick the counter peripheral needs. `corecpu` provides the "
    "top-level module for the build."
)


def _db() -> dict:
    return json.loads(_DB.read_text())


def _profile() -> dict:
    p = _db()["registered_class_profiles"].get(_CLASS)
    assert isinstance(p, dict), f"{_CLASS!r} is not profiled in the expert DB"
    return p


def _null_profile_db(tmp_path: Path) -> Path:
    """The DB with this class back at its declared-gap `null` — the MUTATION
    arm. Reverting the profile, not deleting the name, is the right mutation:
    deleting it would also break the declared-gap invariant and the two effects
    would be impossible to tell apart."""
    db = _db()
    db["registered_class_profiles"][_CLASS] = None
    p = tmp_path / "db_null.json"
    p.write_text(json.dumps(db))
    return p


# ── 1. the profile, both directions ────────────────────────────────────────

def test_a_core_brief_gets_an_all_in_class_pack():
    allowed = set(_profile()["db_classes"])
    hits = Q.query(_CPU_PROMPT, k=5, ic_class=_CLASS)
    assert hits, "class-first retrieval returned nothing at all"
    got = {h["ic_class"] for h in hits}
    assert got <= allowed, f"out-of-class entries leaked in: {sorted(got - allowed)}"
    assert "processor-cpu-core" in got, (
        "the class's own craft entry is not even in the pack")


def test_mutation_reverting_the_profile_brings_the_out_of_class_pack_back(tmp_path):
    """THE NEGATIVE CONTROL, and it has to be run against the SAME prompt: with
    this class back at `null` the identical brief retrieves entries whose craft
    is about a clock divider and a serial-parallel multiplier. Without this, the
    positive assertion above could be passing because the colliding entries are
    unreachable for some unrelated reason."""
    allowed = set(_profile()["db_classes"])
    got = {h["ic_class"] for h in
           Q.query(_CPU_PROMPT, k=5, db_path=_null_profile_db(tmp_path),
                   ic_class=_CLASS)}
    assert got, "the mutation arm retrieved nothing at all"
    assert not (got & allowed), (
        f"the mutation did not reproduce the defect — it still returned "
        f"in-class entries {sorted(got & allowed)}, so the positive assertion "
        f"above proves nothing about the profile")


def test_the_class_decides_membership_not_the_phrase():
    """Every in-class entry is offered even when the brief never uses its
    words — membership is the CLASS's decision.

    The second assertion USED to be `"load-store-unit" not in` the k=5 pack,
    and it was true: under the old allocator the ranking deduped per LESSON, so
    `processor-cpu-core`'s two lessons and `alu-datapath`'s two took four of the
    five slots and the load/store entry fell off. That was a fact about the
    BUDGET, not about membership, and #2164 changed the budget — the k slots
    are ENTRY slots now, so this class's four selected entries all fit. The
    assertion is re-taken as what is now true, which is also the stronger
    statement: the pack the author reads IS the class's whole selection."""
    allowed = set(_profile()["db_classes"])
    assert {h["ic_class"] for h in Q.query("a design.", k=99, ic_class=_CLASS)} == allowed
    assert {h["ic_class"] for h in
            Q.query(_CPU_PROMPT, k=5, ic_class=_CLASS)} == allowed


def test_related_graph_cannot_reopen_this_class_boundary():
    """`processor-cpu-core` links to `serial-parallel-multiplier` in the DB's
    concept graph — an OUT-of-class link, and the colliding entry of #2094. A
    `related[]` link is a concept cross-reference, never a membership claim, so
    the expansion must resolve it to nothing under class-first."""
    allowed = set(_profile()["db_classes"])
    seed = next(e for e in _db()["entries"] if e["ic_class"] == "processor-cpu-core")
    assert "serial-parallel-multiplier" in (seed.get("related") or []), (
        "the out-of-class link this test exists to contain is gone; re-pick it")
    got = {h["ic_class"] for h in
           Q.query(_CPU_PROMPT, k=5, ic_class=_CLASS, expand_related=True)}
    assert got <= allowed, f"the related graph leaked {sorted(got - allowed)}"


def test_the_profiles_two_classes_select_disjoint_knowledge():
    """The point of a per-class profile is that two classes do not hand their
    designs the same pack. Pinned as MEMBERSHIP: an overlap would mean one of
    the two selections is not about its own class."""
    prof = _db()["registered_class_profiles"]
    named = {k: set(v["db_classes"]) for k, v in prof.items()
             if not k.startswith("_") and isinstance(v, dict)}
    assert len(named) >= 2, "only one class is profiled; this control is empty"
    items = sorted(named.items())
    for i, (a, sa) in enumerate(items):
        for b, sb in items[i + 1:]:
            assert not (sa & sb), f"profiles {a} and {b} share db_classes {sorted(sa & sb)}"


# ── 2. the selection is DERIVED from the classifier, not asserted ──────────

_FEATURE_TO_DB_CLASS = {
    # the six features `ic_class_profile._PROCESSOR_CPU_FEATURES` uses to put a
    # design in this class -> the db entry whose craft is about that feature.
    "isa_family": "processor-cpu-core",
    "instruction_semantics": "processor-cpu-core",
    "architectural_state": "microcoded-datapath-sequencer",
    "core_noun": "processor-cpu-core",
    "memory_bus": "load-store-unit",
    "execution_units": "alu-datapath",
}


def test_every_selected_db_class_answers_a_feature_the_classifier_uses():
    """Both directions of the derivation. Every db_class in the profile is the
    craft for at least one feature the classifier tests for, AND every feature
    the classifier tests for has craft in the profile. A selection that fails
    the first half carries knowledge with no referent in the class; one that
    fails the second half leaves a defining feature of the class with no craft
    at all, and the second is the failure nobody notices."""
    selected = set(_profile()["db_classes"])
    features = {name for name, _ in ICP._PROCESSOR_CPU_FEATURES}
    assert features == set(_FEATURE_TO_DB_CLASS), (
        f"the classifier's feature set moved to {sorted(features)}; the "
        f"profile's derivation has to be re-taken against it")
    mapped = set(_FEATURE_TO_DB_CLASS.values())
    assert mapped <= selected, f"a feature maps to an unselected entry: {sorted(mapped - selected)}"
    assert selected <= mapped, (
        f"selected entries answering no classifier feature: {sorted(selected - mapped)}")


def test_the_profile_names_only_entries_the_db_carries():
    present = {e["ic_class"] for e in _db()["entries"]}
    for c in _profile()["db_classes"]:
        assert c in present, f"profile names {c!r}, entries[] does not carry it"


# ── 3. the pack, both directions ───────────────────────────────────────────

def test_the_pack_for_a_core_brief_is_assembled_and_carries_the_contract(tmp_path):
    h = PACK.assemble(_CPU_PROMPT, None, None, [], ["gate"], tmp_path,
                      output_target="l_doc_expectations.json", ic_class=_CLASS)
    cf = h["class_first"]
    assert cf["assembly_status"] == "ASSEMBLED", cf.get("not_assembled_reason")
    assert h["interface_contract"] == "contract.md"
    assert cf["contract_kind"] == "class_integration_contract_md"
    assert h["target_module"] == "corecpu"
    assert cf["db_class_selection"] == "CLASS_CONFINED"
    body = (tmp_path / "contract.md").read_text()
    for req in _profile()["integration_contract"]:
        assert req in body, f"the contract document drops a requirement: {req[:60]}…"


def test_the_digest_the_agent_reads_agrees_with_the_declared_selection(tmp_path):
    """THE ARTEFACT, NOT THE NOTE ABOUT IT — `ic_expert_db.md` is what the
    author actually reads."""
    allowed = set(_profile()["db_classes"])
    h = PACK.assemble(_CPU_PROMPT, None, None, [], ["gate"], tmp_path,
                      output_target="l_doc_expectations.json", ic_class=_CLASS)
    named = set(re.findall(r"^- \*\*\[([^\]]+)\]\*\*",
                           (tmp_path / "ic_expert_db.md").read_text(), re.M))
    assert named, "the rendered digest names no ic_class at all"
    assert named <= allowed, f"out-of-class entries in the digest: {sorted(named - allowed)}"
    assert named == {x["ic_class"] for x in h["db_classes"]}


def test_mutation_the_unprofiled_pack_is_the_DECLARED_GAP_state(tmp_path, monkeypatch):
    """The mutation arm has to land on a NAMED state, not merely "different".
    With the profile back at `null` the pack must be exactly what a registered
    but unprofiled class gets: no `class_first` key, no contract, no recovered
    target — and the disposition a consumer records must say NOT_PROFILED, not
    NOT_A_REGISTERED_CLASS. "We did not confine" and "there is no such class"
    are different facts and the mutation must land on the first."""
    monkeypatch.setattr(Q, "_DEFAULT_DB", _null_profile_db(tmp_path))
    h = PACK.assemble(_CPU_PROMPT, None, None, [], ["gate"], tmp_path / "pack",
                      output_target="l_doc_expectations.json", ic_class=_CLASS)
    assert "class_first" not in h
    assert h["target_module"] is None and h["interface_contract"] is None
    assert not (tmp_path / "pack" / "contract.md").exists()
    d = PACK.class_first_disposition(_CLASS)
    assert d["profile"] == "NOT_PROFILED" and d["registered"] is True
    assert d["db_class_selection"] == "LEXICAL_UNCONFINED"


def test_a_design_of_another_class_is_byte_identical(tmp_path):
    """THE CONTROL. A design of a class this landing did not touch gets the
    same pack it got before — same descriptor bytes, same file set, same file
    contents. Without it, "the core packs changed" cannot be told apart from
    "every pack changed"."""
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


# ── 4. the third target-module convention, both directions ─────────────────

def test_the_name_before_phrase_convention_recovers_a_top_module():
    assert PACK.recover_target_module(
        "`corecpu` provides the top-level module for the build.") == "corecpu"
    assert PACK.recover_target_module(
        "The design `soc_wrap` is the top module taped out here.") == "soc_wrap"


def test_mutation_without_the_third_convention_that_input_recovers_nothing(monkeypatch):
    """THE NEGATIVE CONTROL for the convention: the shipped pair reads the
    name-before-phrase form as nothing at all, which is why the pack for such a
    design was ASSEMBLED_INCOMPLETE."""
    monkeypatch.setattr(PACK, "_TARGET_RES", PACK._TARGET_RES[:2])
    assert PACK.recover_target_module(
        "`corecpu` provides the top-level module for the build.") is None


def test_the_convention_is_APPENDED_so_an_earlier_answer_never_moves():
    """ORDER IS THE CONTRACT. An input that BOTH forms match must still get the
    earlier form's answer — prepending the new one would silently re-answer
    every design that was already right."""
    both = "The top-level module is `outer`. `inner` is the top module of the core."
    assert PACK.recover_target_module(both) == "outer"
    assert PACK._TARGET_RES[-1].search(both).group(1) == "inner"


def test_the_convention_does_not_bind_across_a_table_cell():
    """A markdown table puts a backticked name and the words "top module" on
    one line in DIFFERENT cells. Binding them would invent a statement nobody
    wrote, so the gap stops at the pipe.

    The row below is deliberately TIGHT: the two cells are seven characters
    apart, well inside the 24-character window, so the only thing that can stop
    the match is the pipe itself. A first draft of this case used a realistic
    wide row and passed under a mutant that allowed the pipe — it was the
    DISTANCE, not the exclusion, doing the work, and the guard was vacuous."""
    assert PACK.recover_target_module("| `mem_ctrl` | the top module |") is None
    # and the control: the same shape without the cell boundary DOES bind
    assert PACK.recover_target_module("  `mem_ctrl`   the top module ") == "mem_ctrl"


def test_the_convention_is_polarity_aware():
    """A sentence that DENIES the name must not publish it (#712's one
    vocabulary), in the new direction as well as the old."""
    assert PACK.recover_target_module(
        "`inner_core` is not the top-level module here.\n"
        "`outer_wrap` is the top-level module.") == "outer_wrap"
