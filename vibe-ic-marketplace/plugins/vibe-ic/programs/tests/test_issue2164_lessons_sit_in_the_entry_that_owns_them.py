#!/usr/bin/env python3
"""Regression for #2164 (3 of 3) — three mis-filed lessons moved, and the guard
that would have caught them.

WHAT WAS MEASURED. `integer-clock-divider` carried a lesson about making an
AXI-Lite register read mux combinational. `decimator-peak-detect` carried a
lesson about a learning-rate formula overriding a worked example, and another
about running `verilator --lint-only -Wall` as a self-gate. None of the three is
craft about the entry it sat in, and each was DELIVERED to every design of a
profiled class — because class-first retrieval selects by ENTRY, so a lesson
filed in the wrong entry inherits that entry's whole audience.

WHERE THEY WENT, and each has an owner already in the DB rather than a new one
invented for it: the register-read lesson to `axi4lite-register-slave`, the
learning-rate one to `iterative-training-datapath` (whose own first lesson is
about weight-update trainers and their DELTAS), the lint self-gate to
`lint-code-review`. Nothing was deleted; the DB's total lesson count is
unchanged.

THE GUARD IS EXACT, AND THAT IS PAID FOR IN COVERAGE. Three lexical detectors
were built and measured against the three known instances BEFORE this one:

  class-name stem intersection      flags  44 of 206 lessons
  best-other-class stem margin      ZERO power over two of the three at any
                                    threshold that was not itself noise
  self-consistency retrieval        catches 3 of 3 and flags 138 of 206

None is a gate. So an entry DECLARES `craft_subjects` and a lesson naming none
of them is refused BY NAME — which judges only the entries that declare, and
reports how many those are instead of implying it judged the rest.

AND THE DECLARATION HAD TO BE HONEST BEFORE THE GUARD WORKED. The first cut gave
the divider entry the subject "counter"; the AXI-Lite lesson mentions a
"live-counter read-back" in passing and slipped through. "counter" was too
generic a subject for an entry whose craft is clock division — the declaration
was wrong, not the guard — and every one of that entry's own lessons still names
a tightened subject.

chip-AGNOSTIC: reads the shipped DB and synthetic variants of it.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import ic_expert_db_query as Q              # noqa: E402

_DB = _PROGRAMS.parent / "agents" / "ic_expert_db" / "ic_expert_db.json"

#: (a phrase unique to the lesson, the entry it was WRONGLY in, its true owner)
_MOVED = [
    ("make the read-data mux COMBINATIONAL",
     "integer-clock-divider", "axi4lite-register-slave"),
    ("Normative equations override worked-example numbers",
     "decimator-peak-detect", "iterative-training-datapath"),
    ("verilator --lint-only -Wall",
     "decimator-peak-detect", "lint-code-review"),
]


def _db() -> dict:
    return json.loads(_DB.read_text())


def _entry(db: dict, cls: str) -> dict:
    return next(e for e in db["entries"] if e["ic_class"] == cls)


def _write(tmp_path: Path, db: dict) -> Path:
    p = tmp_path / "db.json"
    p.write_text(json.dumps(db, ensure_ascii=False))
    return p


# ── 1. the three lessons are where they belong now ────────────────────────

@pytest.mark.parametrize("phrase,wrong,owner", _MOVED)
def test_each_lesson_is_in_its_owner_and_out_of_the_entry_it_was_in(
        phrase, wrong, owner):
    db = _db()
    assert any(phrase in l for l in _entry(db, owner)["lessons"]), (
        f"{owner} does not carry the lesson it owns")
    assert not any(phrase in l for l in _entry(db, wrong)["lessons"]), (
        f"{wrong} still carries a lesson that is not its craft")


def test_nothing_was_deleted_only_moved():
    """MEMBERSHIP over the whole DB, not a count of the entries touched: a move
    that dropped a lesson on the way and a move that landed it look the same
    from either end alone."""
    db = _db()
    assert db["total_lessons"] == sum(len(e["lessons"]) for e in db["entries"])
    for e in db["entries"]:
        assert e["lesson_count"] == len(e["lessons"]), e["ic_class"]
    for phrase, _wrong, _owner in _MOVED:
        hits = [e["ic_class"] for e in db["entries"]
                if any(phrase in l for l in e["lessons"])]
        assert len(hits) == 1, f"{phrase!r} is in {hits}"


def test_the_moved_lesson_is_retrievable_from_its_new_entry():
    """END TO END. Moving craft only helps if retrieval now reaches it through
    the entry that owns it — which is the entry a class profile selects."""
    hits = Q.query("a lint clean-up task: make the RTL lint-clean under "
                   "verilator with no unused signals", k=5)
    assert "lint-code-review" in {h["ic_class"] for h in hits}


# ── 2. the guard, both directions ─────────────────────────────────────────











# ── 3. the coverage is a number a reader sees ─────────────────────────────

def test_the_census_reports_how_far_the_guard_reaches(capsys):
    """A verdict that did not say how many entries declare would read as though
    it had checked all 103. Both figures are in the report AND in the line the
    operator sees."""
    out = capsys.readouterr().out
    assert "craft_declared=" in out and "lessons_craft_checked=" in out


def test_every_entry_this_landing_touched_declares_its_craft():
    """The five entries the three lessons left or arrived at all declare, so
    the guard covers both ends of every move it was built from. Pinned as
    MEMBERSHIP so a later edit cannot drop one silently."""
    db = _db()
    touched = {w for _p, w, _o in _MOVED} | {o for _p, _w, o in _MOVED}
    for cls in sorted(touched):
        assert _entry(db, cls).get("craft_subjects"), cls


def test_the_divider_declaration_does_not_use_a_subject_too_generic_to_bite():
    """THE FIX THAT MADE THE GUARD WORK, pinned. The first cut declared
    "counter" for the divider entry, and the AXI-Lite lesson — which mentions a
    "live-counter read-back" in passing — slipped straight through. The
    declaration was wrong, not the guard. Every divider lesson must still name
    a subject after the tightening, or the fix traded one silence for another."""
    e = _entry(_db(), "integer-clock-divider")
    subs = e["craft_subjects"]
    assert "counter" not in subs
    for i, les in enumerate(e["lessons"]):
        assert any(t.lower() in les.lower() for t in subs), (
            f"divider lesson {i} names none of {subs} — the tightening went "
            f"too far and the entry now fails its own declaration")
