#!/usr/bin/env python3
"""vibe-ic#2150 — the layer-contract ruling, as a measurement.

A fact can be in the Phase-1 root and still be undeclared: it sits in a
comparison-table row, a discovered identifier, an evidence literal. `met` and
`owning_layers` cannot tell that apart from a fact sitting in a field named
for it, because both answers are a layer NAME.

THE RULING (#2150): a generic bucket does not satisfy a layer obligation
unless a consumer reads it by that path, and the repair is NOT to promote the
fact to a field — #2132 stands, nothing is promoted without a measured
consumer. So the row stays a DISAGREEMENT and the REASON is recorded.

Everything here is ADVISORY and ADDITIVE. The last two tests are the ones that
say so: `met` and `scope` are byte-identical with the carriage reading present
and with it removed.
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

import pytest

PROGRAMS = Path(__file__).resolve().parent.parent
if str(PROGRAMS) not in sys.path:
    sys.path.insert(0, str(PROGRAMS))

_spec = importlib.util.spec_from_file_location(
    "phase1_expert_parse_track", PROGRAMS / "phase1_expert_parse_track.py")
T = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(T)


def _root(tmp_path: Path, docs: dict) -> Path:
    d = tmp_path / "phase1" / "generated_docs"
    d.mkdir(parents=True)
    for stem, blob in docs.items():
        (d / f"{stem}.json").write_text(json.dumps(blob))
    return tmp_path


# ── the vocabulary ──────────────────────────────────────────────────────────

def test_generic_segment_vocabulary_is_non_empty_and_lower_case():
    assert T.GENERIC_CARRIAGE_SEGMENTS
    assert all(s == s.lower() and s.strip() == s
               for s in T.GENERIC_CARRIAGE_SEGMENTS)


def test_a_generic_segment_at_any_depth_makes_the_path_generic():
    assert T.is_generic_carriage_path("comparison_tables.rows.Description")
    assert T.is_generic_carriage_path("fields.a.b.extraction_evidence.literal")
    assert not T.is_generic_carriage_path("registers.reset_value")
    assert not T.is_generic_carriage_path("clock_domains.name")


def test_a_named_record_field_is_not_generic_because_of_its_leaf():
    # `description` is a field OF a named record: the path says what it is.
    assert not T.is_generic_carriage_path(
        "registers.fields.encoding.description")


# ── token_paths ─────────────────────────────────────────────────────────────

def test_token_paths_elides_list_indices_so_one_field_is_one_path():
    blob = {"registers": [{"reset_value": "0x1"}, {"reset_value": "0x1"}]}
    assert T.token_paths(blob, "0x1") == ["registers.reset_value"]


def test_token_paths_is_empty_when_the_token_is_absent():
    assert T.token_paths({"a": "b"}, "zzz") == []


# ── the three row verdicts ──────────────────────────────────────────────────

def test_generic_only_when_the_fact_is_a_comparison_table_row(tmp_path):
    proj = _root(tmp_path, {"L1_DATASHEET": {
        "comparison_tables": {"rows": {"Description": "fields are FACTTOKEN"}}}})
    c = T.token_carriage(proj, ["FACTTOKEN"])
    assert c["verdict"] == T.CARRIAGE_GENERIC_ONLY
    assert c["per_token"]["FACTTOKEN"]["generic"] == {
        "L1_DATASHEET": ["comparison_tables.rows.Description"]}
    assert c["per_token"]["FACTTOKEN"]["named"] == {}


def test_named_field_elsewhere_when_a_field_is_named_for_the_fact(tmp_path):
    proj = _root(tmp_path, {"L8_RTL_CONSTANTS": {
        "clock_domains": [{"name": "FACTTOKEN"}]}})
    c = T.token_carriage(proj, ["FACTTOKEN"])
    assert c["verdict"] == T.CARRIAGE_NAMED_FIELD
    assert c["per_token"]["FACTTOKEN"]["named"] == {
        "L8_RTL_CONSTANTS": ["clock_domains.name"]}


def test_nowhere_when_no_layer_carries_the_token(tmp_path):
    proj = _root(tmp_path, {"L1_DATASHEET": {"a": "something else"}})
    assert T.token_carriage(proj, ["FACTTOKEN"])["verdict"] \
        == T.CARRIAGE_NOWHERE


def test_named_wins_over_generic_when_the_token_is_in_both(tmp_path):
    proj = _root(tmp_path, {
        "L1_DATASHEET": {"comparison_tables": {"rows": "FACTTOKEN"}},
        "L8_RTL_CONSTANTS": {"clock_domains": [{"name": "FACTTOKEN"}]}})
    c = T.token_carriage(proj, ["FACTTOKEN"])
    assert c["verdict"] == T.CARRIAGE_NAMED_FIELD
    # and BOTH are still recorded: the reader is told the generic copy exists.
    assert c["per_token"]["FACTTOKEN"]["generic"]
    assert c["per_token"]["FACTTOKEN"]["named"]


def test_the_addressed_layer_is_not_counted_as_somewhere_else(tmp_path):
    proj = _root(tmp_path, {"L9_INTEGRATION_SPEC": {
        "clock_domains": [{"name": "FACTTOKEN"}]}})
    me = proj / "phase1" / "generated_docs" / "L9_INTEGRATION_SPEC.json"
    assert T.token_carriage(proj, ["FACTTOKEN"], exclude=me)["verdict"] \
        == T.CARRIAGE_NOWHERE
    assert T.token_carriage(proj, ["FACTTOKEN"])["verdict"] \
        == T.CARRIAGE_NAMED_FIELD


def test_no_tokens_is_nowhere_and_never_an_agreement(tmp_path):
    proj = _root(tmp_path, {"L1_DATASHEET": {"a": "b"}})
    assert T.token_carriage(proj, [])["verdict"] == T.CARRIAGE_NOWHERE


# ── the sentence ────────────────────────────────────────────────────────────

@pytest.mark.parametrize("verdict,needle", [
    (T.CARRIAGE_NOWHERE, "content gap"),
    (T.CARRIAGE_GENERIC_ONLY, "generic"),
    (T.CARRIAGE_NAMED_FIELD, "layer-contract"),
])
def test_every_verdict_has_its_own_sentence(tmp_path, verdict, needle):
    docs = {
        T.CARRIAGE_NOWHERE: {"L1_DATASHEET": {"a": "b"}},
        T.CARRIAGE_GENERIC_ONLY: {
            "L1_DATASHEET": {"comparison_tables": {"rows": "FACTTOKEN"}}},
        T.CARRIAGE_NAMED_FIELD: {
            "L8_RTL_CONSTANTS": {"clock_domains": [{"name": "FACTTOKEN"}]}},
    }[verdict]
    c = T.token_carriage(_root(tmp_path, docs), ["FACTTOKEN"])
    assert c["verdict"] == verdict
    assert needle in T.carriage_sentence(c)


def test_the_generic_sentence_states_the_ruling_and_names_the_bucket(tmp_path):
    proj = _root(tmp_path, {
        "L1_DATASHEET": {"comparison_tables": {"rows": "FACTTOKEN"}}})
    s = T.carriage_sentence(T.token_carriage(proj, ["FACTTOKEN"]))
    assert "L1_DATASHEET.comparison_tables.rows" in s
    assert "not promoted" in s


# ── additive: `met` is decided where it always was ──────────────────────────

def _exp(**kw):
    base = {"id": "row", "layer": "L9_INTEGRATION_SPEC", "field_path": "ports",
            "requirement": "r", "evidence": [],
            "expected_tokens": ["FACTTOKEN"]}
    base.update(kw)
    return base


def test_carriage_is_attached_only_when_the_row_disagrees(tmp_path):
    proj = _root(tmp_path, {"L9_INTEGRATION_SPEC": {"ports": "FACTTOKEN"}})
    met = T.converge_ai_expectation(proj, _exp())
    assert met["met"] is True
    assert "carriage" not in met, \
        "a satisfied row has no carriage question to answer"

    proj2 = _root(tmp_path / "b", {
        "L9_INTEGRATION_SPEC": {"ports": "nothing"},
        "L1_DATASHEET": {"comparison_tables": {"rows": "FACTTOKEN"}}})
    unmet = T.converge_ai_expectation(proj2, _exp())
    assert unmet["met"] is False
    assert unmet["carriage"]["verdict"] == T.CARRIAGE_GENERIC_ONLY


def test_carriage_does_not_move_met_or_scope(tmp_path, monkeypatch):
    """THE ADDITIVITY PROOF, taken by removing the reading entirely.

    With `token_carriage` neutered the row must decide identically. If this
    ever fails, the carriage reading has become a comparator change and the
    whole point of keeping it separate is gone.
    """
    proj = _root(tmp_path, {
        "L9_INTEGRATION_SPEC": {"ports": "nothing"},
        "L1_DATASHEET": {"comparison_tables": {"rows": "FACTTOKEN"}}})
    with_reading = T.converge_ai_expectation(proj, _exp())
    monkeypatch.setattr(T, "token_carriage",
                        lambda *a, **k: {"verdict": "X", "per_token": {}})
    without = T.converge_ai_expectation(proj, _exp())
    for key in ("met", "scope", "missing_tokens", "observed",
                "field_path_status", "owning_layers"):
        assert with_reading[key] == without[key], key
    # AND the comparator's own invariant, stated here because the comparison
    # above has one blind spot: a mutation that writes `met` from the carriage
    # verdict fires in BOTH arms, so the two agree and the equality proves
    # nothing. `met` is `not missing_tokens` and nothing else decides it.
    assert with_reading["met"] is (not with_reading["missing_tokens"])
    assert without["met"] is (not without["missing_tokens"])


def test_missing_tokens_alone_are_asked_about(tmp_path):
    """A token the addressed layer already carries must not supply a named
    field for a fact the layer does NOT carry."""
    proj = _root(tmp_path, {
        "L9_INTEGRATION_SPEC": {"ports": "PRESENTTOKEN"},
        "L8_RTL_CONSTANTS": {"clock_domains": [{"name": "PRESENTTOKEN"}]},
        "L1_DATASHEET": {"comparison_tables": {"rows": "MISSINGTOKEN"}}})
    r = T.converge_ai_expectation(
        proj, _exp(expected_tokens=["PRESENTTOKEN", "MISSINGTOKEN"]))
    assert r["missing_tokens"] == ["MISSINGTOKEN"]
    assert r["carriage"]["verdict"] == T.CARRIAGE_GENERIC_ONLY, \
        "PRESENTTOKEN's named field must not answer for MISSINGTOKEN"


def test_the_verdict_is_an_or_over_tokens_and_says_so(tmp_path):
    """One token in a named field makes the ROW `NAMED_FIELD_ELSEWHERE`. A
    reader who cannot see which tokens that was would read the verdict as a
    statement about the whole fact, so the split is published."""
    proj = _root(tmp_path, {
        "L8_RTL_CONSTANTS": {"clock_domains": [{"name": "HERE"}]}})
    c = T.token_carriage(proj, ["HERE", "GONE"])
    assert c["verdict"] == T.CARRIAGE_NAMED_FIELD
    assert c["tokens_carried_elsewhere"] == ["HERE"]
    assert c["tokens_in_no_layer"] == ["GONE"]


def test_a_raw_table_row_is_generic_wherever_it_is_nested(tmp_path):
    """`fields.tables.rows` is the same undifferentiated unit as
    `comparison_tables.rows`; MEASURED on a real root, it was the container
    holding nine of the tokens the first vocabulary scored as named fields."""
    proj = _root(tmp_path, {"L15_ENCODING_TABLES": {
        "fields": {"tables": [{"name": "T", "rows": ["0x1 | X | FACTTOKEN"]}]}}})
    c = T.token_carriage(proj, ["FACTTOKEN"])
    assert c["verdict"] == T.CARRIAGE_GENERIC_ONLY
    # and the table's own NAME is still a named field
    assert T.token_carriage(proj, ["T"])["verdict"] == T.CARRIAGE_NAMED_FIELD
