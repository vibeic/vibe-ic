#!/usr/bin/env python3
"""test_ruling82_a_number_is_matched_by_typed_value.py

A NUMERIC expected token is matched by VALUE, against typed values only
(leader ruling #82(5), see also #82(3)).

WHAT WAS MEASURED
-----------------
On a live Phase-1 root the expectation `pad_edge_spacing` expected the token
`5.5`. `phrase_present` reduces `5.5` to the tokens `5 5`, which concatenate to
`55`, and the owning-layer answer then named four layers on the strength of a
citation LINE NUMBER 55 (`reset_strategy.evidence.line: 55`) and of a citation
string ending `….md:55`. None of them carries the value 5.5. The verdict
happened to be right; the evidence published for it was not, so any numeric
expectation could be satisfied by an unrelated line number or position.

THE RULE PINNED HERE
--------------------
  * a numeric token (a number, optionally with a unit) matches only a TYPED
    value: a JSON number, or a string that is wholly one number with an
    optional unit — never a key, prose, a citation, a source position, a
    digest, a version, or a different number (`5.5` is not `55`, `15.5`,
    `5.55` or `1.5.5`; `40` is not `-40`);
  * equal values match after unit normalisation (`5.5 um` == `5500 nm` ==
    `pad_edge_spacing_um: 5.5`); a unitless token compares with the number as
    written, in whatever unit the layer states it;
  * every other token is matched exactly as before.

Every fixture is synthesised from neutral parts; the layer stems are the
plugin's own L-doc taxonomy.

Run: python3 -m pytest programs/tests/test_ruling82_a_number_is_matched_by_typed_value.py -q
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
if str(_PROGRAMS) not in sys.path:
    sys.path.insert(0, str(_PROGRAMS))

import phase1_expert_parse_track as T  # noqa: E402


# The measured shape, neutralised. The addressed layer carries only the
# CONSEQUENCE of the spacing (a core box whose coordinates end in .5); every
# other layer carries a 55 that is a position, a citation, a digest, a version
# or a different number — and none carries the value 5.5.
_ADDRESSED = {"doc_id": "L19", "constraints": {"tapeout_geometry": {
    "core_area_um": [205.5, 205.5, 1094.5, 1094.5]}}}
_LINE_55_LAYERS = {
    "L19_CONSTRAINTS_PDK": _ADDRESSED,
    "L8_TIMING_WAVEFORM": {"doc_id": "L8", "reset_strategy": {
        "evidence": {"file": "input/docs/rulings.md", "line": 55}}},
    "L22_VERIFICATION_PLAN": {"doc_id": "L22", "fields": {
        "verification_plan": {"gaps": [
            {"evidence": "input/docs/rulings.md:55"}]}}},
    "L9_INTEGRATION_SPEC": {"doc_id": "L9", "fields": {"table": {
        "source": {"doc": "input/docs/spec.md", "header_line": 55},
        "document_sha256": "55", "plugin_version": "1.5.5",
        "values": [55, 15.5, "5.55", "15.5", "v1.5.5"],
        "notes": "pad spacing 5 5 per side, see rulings.md line 55"}}},
}
_SPACING = {"id": "spacing", "layer": "L19_CONSTRAINTS_PDK",
            "requirement": "the pad edge spacing is 5.5 um",
            "evidence": ["input/docs/rulings.md:13 — pad edge spacing 5.5 um"],
            "expected_tokens": ["5.5"]}


def _project(tmp_path, layers):
    p = tmp_path / "proj"
    d = p / "phase1" / "generated_docs"
    d.mkdir(parents=True)
    for stem, blob in layers.items():
        (d / f"{stem}.json").write_text(json.dumps(blob))
    return p


def _units(blob):
    return T._haystack_units(blob)


# ── 1. the counterexample: a line number 55 is not the value 5.5 ───────────

def test_the_measured_counterexample_no_longer_matches(tmp_path):
    c = T.converge_ai_expectation(_project(tmp_path, _LINE_55_LAYERS),
                                  dict(_SPACING))
    assert c["usable"] is True
    assert c["met"] is False and c["missing_tokens"] == ["5.5"]
    # The ownership answer is DECIDED and empty: no layer carries 5.5, and no
    # line number, citation, digest or other number is offered as evidence.
    assert c["owning_layers_status"] == "OK"
    assert c["owning_layers"] == []
    assert c["owning_layers_evidence"] == {}
    assert c["carriage"]["verdict"] == T.CARRIAGE_NOWHERE
    assert c["carriage"]["tokens_in_no_layer"] == ["5.5"]


def test_the_raw_text_matcher_is_unchanged_and_no_longer_decides_numbers():
    """`phrase_present` is the text matcher other callers use and it is not
    widened or narrowed here; it still equates `5.5` with `…:55`. That is
    exactly why the comparator no longer routes a NUMBER through it."""
    assert T.phrase_present("5.5", "input/docs/rulings.md:55") is True
    assert T.present_in_units(
        "5.5", _units({"cite": "input/docs/rulings.md:55"})) is False


# ── 2. a real typed 5.5 still matches, in every reading ────────────────────

def test_a_typed_5_5_still_matches(tmp_path):
    layers = dict(_LINE_55_LAYERS)
    layers["L19_CONSTRAINTS_PDK"] = {"doc_id": "L19", "constraints": {
        "tapeout_geometry": {"pad_edge_spacing_um": 5.5,
                             "core_area_um": [205.5, 205.5, 1094.5, 1094.5]}}}
    p = _project(tmp_path, layers)

    whole = T.converge_ai_expectation(p, dict(_SPACING))
    assert whole["met"] is True and whole["scope"] == "whole_layer"

    pointed = T.converge_ai_expectation(p, dict(
        _SPACING, field_path="/constraints/tapeout_geometry/pad_edge_spacing_um"))
    assert pointed["met"] is True and pointed["scope"] == "json_pointer"

    # ownership and carriage read the same value through the same predicate
    own = T.owning_layers_answer(p, ["5.5"])
    assert own["status"] == "OK"
    assert own["layers"] == ["L19_CONSTRAINTS_PDK"]
    assert own["evidence"] == {"L19_CONSTRAINTS_PDK": {"5.5": "5.5"}}
    assert T.token_paths(layers["L19_CONSTRAINTS_PDK"], "5.5") == [
        "constraints.tapeout_geometry.pad_edge_spacing_um"]


@pytest.mark.parametrize("blob", [
    {"x": 5.5}, {"x": "5.5"}, {"x": "5.50"}, {"x": " 5.5 "}, {"x": "5.5 um"},
    {"x": [1, 5.5]}, {"pad_edge_spacing_um": 5.5},
])
def test_a_typed_5_5_matches_in_each_spelling(blob):
    assert T.present_in_units("5.5", _units(blob)) is True


# ── 3. equal values match after unit normalisation ─────────────────────────

@pytest.mark.parametrize("token, blob", [
    ("5.5 um", {"pad_edge_spacing_um": 5.5}),          # unit in the field name
    ("5.5 um", {"spacing": "5500 nm"}),                # unit in the string
    ("5.5 um", {"spacing_nm": 5500}),                  # another scale
    ("5.5 um", {"spacing": {"value": 5.5, "unit": "\u00b5m"}}),  # record unit
    ("5.5um", {"spacing": "5.5 \u03bcm"}),             # glyph variants
    ("1 MHz", {"freq_hz": 1000000}),
    ("100 us", {"t": {"min_typ_max": {"min": 100}, "unit": "us"}}),
    ("-40", {"temperature_c": [-40, 27, 125]}),
    ("-40 C", {"temperature_c": [-40, 27, 125]}),
    ("\u221240 \u00b0C", {"t": "-40\u00b0C"}),         # U+2212 minus
    ("14", {"enob": {"min": 14.0, "unit": "bit"}}),    # 14 == 14.0
    ("16 bit", {"width": "16-bit"}),
])
def test_a_unit_normalised_value_matches(token, blob):
    assert T.present_in_units(token, _units(blob)) is True


@pytest.mark.parametrize("token, blob", [
    ("5.5 um", {"spacing_mm": 5.5}),        # 5.5 mm is not 5.5 um
    ("5.5 um", {"spacing": 5.5}),           # unit unknown: equality unproven
    ("5.5 um", {"spacing_um": 55}),
    ("5 um", {"a": "5 um2"}),               # a length is not an area
    ("40", {"temperature_c": [-40, 27, 125]}),   # the sign is the value
    ("1.0", {"x": 10}),
    ("10", {"x": "1.0"}),
    ("1", {"flag": True}),                  # a Boolean is not a number
])
def test_a_different_value_or_unit_does_not_match(token, blob):
    assert T.present_in_units(token, _units(blob)) is False


def test_a_scoped_leaf_keeps_the_unit_its_record_states(tmp_path):
    """A pointer straight at a number still sees the unit its own record (or
    field name) states — the context the whole-layer walk would give it."""
    p = _project(tmp_path, {"L5_ADI_SPEC": {"doc_id": "L5", "specs": [
        {"name": "vin", "target": 1.0, "unit": "V"}]}})
    c = T.converge_ai_expectation(p, {
        "id": "vin", "layer": "L5_ADI_SPEC", "field_path": "/specs/0/target",
        "requirement": "input range 1.0 V", "expected_tokens": ["1000 mV"]})
    assert c["scope"] == "json_pointer" and c["met"] is True


# ── 4. never a position, citation, digest, key, version or other number ────

@pytest.mark.parametrize("token, blob", [
    ("55", {"evidence": {"file": "a.md", "line": 55}}),
    ("55", {"source": {"doc": "a.md", "header_line": 55}}),
    ("55", {"intent": [{"clause_index": 55}]}),
    ("55", {"cite": "input/docs/a.md:55"}),
    ("55", {"x": "see line 55"}),
    ("55", {"55": "a label"}),
    ("91094619", {"document_sha256": "91094619"}),
    ("5.5", {"v": "1.5.5"}),
    ("5.5", {"v": "v1.5.5"}),
    ("5.5", {"x": 55}),
    ("5.5", {"x": 15.5}),
    ("5.5", {"x": "15.5"}),
    ("5.5", {"x": 5.55}),
    ("5.5", {"x": "5 5"}),
])
def test_a_number_never_matches_a_position_or_another_number(token, blob):
    assert T.present_in_units(token, _units(blob)) is False


@pytest.mark.parametrize("token, blob", [
    ("55", {"x": 55}),
    ("55", {"lines_of_code": "55"}),
    ("91094619", {"count": 91094619}),
    # design values whose field names look like positions or digests
    ("16", {"registers": [{"name": "CTRL", "offset": 16}]}),
    ("3", {"ball": {"row": "C", "column": 3}}),
    ("480", {"active_lines": 480}),
    ("256", {"digest_bits": "256"}),
])
def test_the_refusals_above_are_not_vacuous(token, blob):
    """The pair: the same numbers, typed as values, DO match — and the
    position/digest exclusions stay as narrow as the shapes measured."""
    assert T.present_in_units(token, _units(blob)) is True


# ── 5. every other token is matched exactly as before ──────────────────────

@pytest.mark.parametrize("token", [
    "REFHI", "TRIM_SEL", "power domain", "0xc", "2 clocks", "16-bit 4-to-1",
    "v1.5.5", "lib7x2", "false",
])
def test_a_token_that_is_not_a_number_is_matched_as_before(token):
    blob = {"pins": ["REFHI", "A_REFHI_B"], "trim sel": 1,
            "x": "the power domain here", "reg": "0xC", "setup": "2 clocks",
            "mux": "16-bit 4-to-1 multiplexer", "ver": "v1.5.5",
            "lib": "lib7x2", "flag": False}
    units = _units(blob)
    assert T.present_in_units(token, units) == any(
        T.phrase_present(token, str(u)) for u in units)
    assert T.present_in_units(token, units) is True
