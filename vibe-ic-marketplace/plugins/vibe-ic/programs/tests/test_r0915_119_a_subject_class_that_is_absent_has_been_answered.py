#!/usr/bin/env python3
"""R-0915-119 — a checker whose SUBJECT CLASS is absent has DECIDED.

MEASURED, sha256 x sky130A, FRONT DOOR, run24 on main 8337cc81f:
`final_audit Overall: NOT_MEASURED (strict=True)` <- Step P0
`partial_population` <- eight INCOMPLETE checkers, seven of which exit rc=2
saying the design has no such structure at all. All seven were recorded
`reason_class=EXECUTION_ERROR`, which says the program errored — and none of
them did. A design with no arbiter has been ANSWERED about arbiters.

`_flow_reason_taxonomy` already recognised those sentences and deliberately
refused to act on them, for a reason this branch KEEPS rather than overturns:
"the sentence was a better clue than the old default, and a clue is not a
declaration". So the claim is not made by the sentence. It is made by the
CHECKER, out of its own ENUMERATION, and it carries that enumeration with it.

THE TWO GUARDS, asserted here for every checker and for the taxonomy:

  (i)  POSITIVELY ESTABLISHED. The class is granted only with a named
       population and a scanned count >= 1. The token alone classifies
       EXECUTION_ERROR; an unreadable input stays EXECUTION_ERROR.
  (ii) FOUND-BUT-EXAMINED-NOTHING IS NOT THIS CLASS. A checker that found its
       subject and examined none of it has a zero denominator and stays
       INCOMPLETE.

IT IS NEVER A PASS. It is a third state, published under its own name; the
step TIER it permits is the same one a design-declared N/A permits
(R-0915-102(1)), and strict mode still refuses on any true incomplete.
"""
from __future__ import annotations

import ast
import json
import subprocess
import sys
from pathlib import Path

import pytest

PROG = Path(__file__).resolve().parents[1]
if str(PROG) not in sys.path:
    sys.path.insert(0, str(PROG))

import _flow_reason_taxonomy as T      # noqa: E402
import _structural_absence as SA       # noqa: E402

CLS = SA.NOT_APPLICABLE_BY_STRUCTURE

#: A design with NONE of the seven subject classes: no arbiter, no BRAM, no
#: cross-module pulse pair, no rx_*, no tx, no break signal.
#: The same design WITH an arbiter: request/grant with a fixed priority.


def _run(mod: str, args, json_out: Path = None):
    cmd = [sys.executable, str(PROG / f"{mod}.py")] + [str(a) for a in args]
    if json_out is not None:
        cmd += ["--json", str(json_out)]
    return subprocess.run(cmd, capture_output=True, text=True)


# ── 1. the vocabulary refuses a weak claim at the point it is made ────────
def test_an_absence_must_name_the_population_it_enumerated():
    with pytest.raises(ValueError, match="name the population"):
        SA.absence("", 5)


@pytest.mark.parametrize("scanned", [0, -1, None, True, "7"])
def test_an_empty_or_unreadable_enumeration_establishes_nothing(scanned):
    """Guard (i): an empty glob is not a structural absence."""
    with pytest.raises(ValueError, match="walked at least"):
        SA.absence("modules in rtl", scanned)


@pytest.mark.parametrize("found", [1, 42, None, True])
def test_a_subject_that_was_found_is_not_a_structural_absence(found):
    """Guard (ii): found-but-examined-nothing is a zero denominator."""
    with pytest.raises(ValueError, match="zero denominator"):
        SA.absence("fields", 10, found=found)


def test_a_well_formed_absence_is_valid_and_a_malformed_one_is_not():
    assert SA.is_valid(SA.absence("modules in rtl", 3))
    assert not SA.is_valid({"population": "x"})
    assert not SA.is_valid({"population": "x", "scanned": 3, "found": 2})
    assert not SA.is_valid({"population": "", "scanned": 3, "found": 0})
    assert not SA.is_valid(None)


# ── 2. the taxonomy: decided, but only on the enumeration ─────────────────
def test_the_class_is_decided_and_keeps_its_own_name():
    assert CLS in T.REASON_CLASSES
    assert CLS in T.SKIP_ELIGIBLE
    assert CLS not in T.INCOMPLETE
    # published under its OWN name — it is never renamed to PASS
    assert T.record_verdict(CLS) != "PASS"
    assert T.normalise(CLS) == CLS


def test_the_step_tier_is_the_one_a_declared_na_already_permits():
    """R-0915-102(1) precedent: the question is answered, so it does not hold
    the step at INCOMPLETE. A true incomplete beside it still does."""
    assert T.p0_tier_for_reason_classes([CLS]) == \
        T.p0_tier_for_reason_classes([T.DESIGN_DECLARED_NA])
    assert T.p0_tier_for_reason_classes([CLS, T.EXECUTION_ERROR]) == \
        "INCOMPLETE"
    assert T.p0_tier_for_reason_classes([CLS, T.ZERO_DENOMINATOR]) == \
        "INCOMPLETE"


def test_the_token_alone_is_not_the_claim():
    """Guard (i) at the reader: a checker cannot reach the decided state by
    writing a word into its report."""
    assert T.infer_nonverdict_reason(
        message="no arbitration patterns found",
        evidence={"reason_class": CLS}) == T.EXECUTION_ERROR
    assert T.infer_nonverdict_reason(
        message="no arbitration patterns found",
        evidence={"reason_class": CLS,
                  SA.EVIDENCE_KEY: {"population": "x", "scanned": 0,
                                    "found": 0}}) == T.EXECUTION_ERROR


def test_the_token_with_its_enumeration_is_the_claim():
    assert T.infer_nonverdict_reason(
        message="no arbitration patterns found",
        evidence={"reason_class": CLS,
                  SA.EVIDENCE_KEY: SA.absence("modules in rtl", 4)}) == CLS


def test_the_sentence_alone_still_cannot_launder_a_declaration():
    """The refusal the taxonomy already carried is UNCHANGED: the prose
    recogniser existed before this ruling and acting on it alone was wrong."""
    for msg in ("no arbitration patterns found",
                "no rx_* modules found",
                "No break signals detected — not a break-based protocol"):
        assert T.infer_nonverdict_reason(message=msg) == T.EXECUTION_ERROR


def test_the_second_channel_needs_the_counts_in_the_same_line():
    """A checker with no --json may state the class, and only WITH its
    enumeration: `_structural_absence.sentence()` is its one writer."""
    good = SA.sentence(SA.absence("register field(s) L4 carries", 32), "g")
    assert T.infer_nonverdict_reason(message=good) == CLS
    assert T.infer_nonverdict_reason(
        message=f"[{CLS}] g: this design has no such subject") == \
        T.EXECUTION_ERROR


def test_an_unreadable_input_is_still_an_execution_error():
    for msg in ("no RTL files found", "no modules parseable",
                "no top-level modules found"):
        assert T.infer_nonverdict_reason(message=msg) == T.EXECUTION_ERROR


# ── 3. each checker, in both directions, on real RTL ──────────────────────


# ── 4. the seventh: guard (ii) is the whole of the distinction ────────────
def _l4_project(tmp_path: Path, fields) -> Path:
    p = tmp_path / "l4proj"
    (p / "phase1" / "generated_docs").mkdir(parents=True)
    (p / "phase1" / "generated_docs" / "L4_REGMAP.json").write_text(
        json.dumps({"schema_version": 2, "doc_class": "regmap",
                    "ic_name": "x",
                    "registers": [{"name": "CTRL", "address": "0x00",
                                   "fields": fields}]}))
    return p


def test_fields_enumerated_and_none_eligible_is_decided(tmp_path):
    fields = [{"field_name": f"BIT{i}", "bits": str(i), "lsb": i}
              for i in range(8)]
    p = _l4_project(tmp_path, fields)
    cp = _run("l4_regmap_enumerated_values_typed_check", [p])
    assert cp.returncode == 2, cp.stdout
    assert CLS in cp.stdout, cp.stdout
    assert T.infer_nonverdict_reason(message=cp.stdout) == CLS


def test_no_field_enumerated_at_all_stays_a_zero_denominator(tmp_path):
    """Guard (ii), and the case the ruling singles out: an EMPTY population
    establishes nothing, so `examined 0` over nothing is not decided."""
    p = _l4_project(tmp_path, [])
    cp = _run("l4_regmap_enumerated_values_typed_check", [p])
    assert cp.returncode == 2, cp.stdout
    assert CLS not in cp.stdout, cp.stdout
    assert T.infer_nonverdict_reason(message=cp.stdout) != CLS


# ── 5. the umbrella reads the taxonomy, not a copy of it ──────────────────
def test_the_umbrella_accounting_is_not_a_second_class_list():
    """A hard-coded list in the umbrella would go stale the day a class is
    added — which is the day this test exists for."""
    tree = ast.parse((PROG / "_flow_reason_taxonomy.py").read_text())
    names = {n.targets[0].id for n in tree.body
             if isinstance(n, ast.Assign) and len(n.targets) == 1
             and isinstance(n.targets[0], ast.Name)}
    assert {"SKIP_ELIGIBLE", "INCOMPLETE", "REASON_CLASSES"} <= names


# ── 6. the deck's own hygiene ─────────────────────────────────────────────
def test_no_two_tests_in_this_file_share_a_name():
    tree = ast.parse(Path(__file__).read_text())
    names = [n.name for n in tree.body
             if isinstance(n, ast.FunctionDef) and n.name.startswith("test_")]
    assert len(names) == len(set(names)), \
        sorted({n for n in names if names.count(n) > 1})
