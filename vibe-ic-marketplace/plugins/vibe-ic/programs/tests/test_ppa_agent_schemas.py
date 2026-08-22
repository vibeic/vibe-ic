#!/usr/bin/env python3
"""The schemas and the code state the same closed sets, so they can disagree.

Two hand-maintained copies of one fact drift, and the drift is silent: a schema
that still lists eight handoff reasons after a ninth was added to the code
validates every document anyone will ever produce, so nothing goes red and the
schema quietly stops being a contract.

THE STRUCTURAL CHECKS BELOW DELIBERATELY DO NOT NEED `jsonschema`.
They are plain dict comparisons against the code's own constants, so they run
wherever pytest runs. Only the instance-validation tests need the library, and
those `importorskip` with a stated reason -- a skip that says why is honest,
where a structural check that silently vanished on a machine without the
library would be a gate that never runs while looking green.
"""
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from _ppa import agent_context as ac  # noqa: E402
from _ppa import agent_policy as ap  # noqa: E402
from _ppa import agent_router as ar  # noqa: E402

PLUGIN_ROOT = pathlib.Path(__file__).resolve().parents[2]
SCHEMA_DIR = PLUGIN_ROOT / "schemas" / "ppa"
NAMES = ("agent_policy", "agent_handoff", "agent_proposal")


def load(name):
    path = SCHEMA_DIR / f"{name}.v1.schema.json"
    assert path.exists(), f"schema {path} is missing"
    return json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("name", NAMES)
def test_the_schema_file_exists_and_is_valid_json(name):
    load(name)


@pytest.mark.parametrize("name", NAMES)
def test_the_schema_id_matches_its_filename(name):
    """`v1` is versioned by filename, so an `$id` that disagrees means a
    document hashed against one identity and validated against another."""
    assert load(name)["$id"] == f"vibeic.ppa.{name}.v1"


@pytest.mark.parametrize("name", NAMES)
def test_every_instance_declares_its_schema_as_a_const(name):
    """PPA_INTERFACES.md 5: an instance carries `schema` as its first key. A
    schema that does not pin it would validate a document of another type."""
    assert load(name)["properties"]["schema"]["const"] == \
        f"vibeic.ppa.{name}.v1"
    assert "schema" in load(name)["required"]


# --------------------------------------------------------------------------
# Drift guards: schema enum == code constant.
# --------------------------------------------------------------------------

def test_the_handoff_reason_enum_is_exactly_the_code_closed_set():
    enum = set(load("agent_handoff")["properties"]["reason"]["enum"])
    assert enum == set(ap.HANDOFF_REASONS)


def test_the_autonomy_enum_is_exactly_the_code_level_list():
    for name, key in (("agent_policy", "autonomy_level"),
                      ("agent_handoff", "autonomy_level")):
        enum = load(name)["properties"][key]["enum"]
        assert enum == list(ap.AUTONOMY_LEVELS)


def test_the_policy_schema_names_every_level_not_only_the_activated_one():
    """Deliberate. If the schema allowed only A0, raising autonomy would be an
    edit to a schema file -- a smaller, quieter act than editing the gate. The
    schema says what is well-formed; the program says what is permitted."""
    enum = load("agent_policy")["properties"]["autonomy_level"]["enum"]
    assert "A3" in enum
    assert not ap.is_activated("A3")


def test_the_proposal_schema_refuses_unknown_keys():
    """An explain-only boundary enforced by a schema that IGNORES unknown keys
    is not enforced: an action only has to be named something new."""
    assert load("agent_proposal")["additionalProperties"] is False


def test_the_proposal_schema_allows_exactly_the_keys_the_code_allows():
    schema_keys = set(load("agent_proposal")["properties"])
    assert schema_keys == set(ap._PROPOSAL_ALLOWED_KEYS)


def test_the_proposal_schema_requires_what_the_code_requires():
    assert set(load("agent_proposal")["required"]) == \
        set(ap._PROPOSAL_REQUIRED_KEYS)


def test_the_handoff_schema_pins_the_handling_rule():
    assert load("agent_handoff")["properties"]["handling"]["const"] == \
        "DATA_ONLY_NEVER_INSTRUCTION"
    assert ac.build_context.__doc__ is not None


def test_every_digest_field_is_pinned_to_the_prefixed_form():
    """A bare hex string does not say what produced it."""
    props = load("agent_handoff")["properties"]
    for key in ("policy_sha256", "situation_sha256", "handoff_sha256"):
        assert props[key]["pattern"] == "^sha256:[0-9a-f]{64}$"
    assert load("agent_proposal")["properties"]["handoff_sha256"]["pattern"] \
        == "^sha256:[0-9a-f]{64}$"


# --------------------------------------------------------------------------
# Instance validation. Needs the library; skips loudly without it.
# --------------------------------------------------------------------------

def _validator():
    jsonschema = pytest.importorskip(
        "jsonschema",
        reason="instance validation needs jsonschema; the structural drift "
               "guards in this file run without it and are the load-bearing "
               "half")
    return jsonschema


def test_a_real_handoff_validates_against_the_schema():
    jsonschema = _validator()
    diag = ar.diagnose({
        "schema": "vibeic.ppa.situation.v1", "question": "root_cause",
        "domains_in_scope": ["timing_setup", "area"],
        "gates": [{"domain": "timing_setup", "verdict": "FAIL"},
                  {"domain": "area", "verdict": "FAIL"}]})
    jsonschema.validate(diag.handoff, load("agent_handoff"))


def test_a_real_default_policy_validates_against_the_schema():
    jsonschema = _validator()
    jsonschema.validate(ap.default_policy(), load("agent_policy"))


def test_an_a0_proposal_validates_and_an_acting_one_does_not():
    jsonschema = _validator()
    good = {"schema": "vibeic.ppa.agent_proposal.v1",
            "handoff_sha256": "sha256:" + "b" * 64,
            "explanation": "the hold path crosses two clock domains",
            "hypotheses": ["skew"], "confidence": 0.5}
    jsonschema.validate(good, load("agent_proposal"))

    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(dict(good, actions=["apply"]),
                            load("agent_proposal"))


def test_a_handoff_reason_outside_the_closed_set_fails_validation():
    jsonschema = _validator()
    diag = ar.diagnose({
        "schema": "vibeic.ppa.situation.v1", "question": "root_cause",
        "domains_in_scope": ["timing_setup", "area"],
        "gates": [{"domain": "timing_setup", "verdict": "FAIL"},
                  {"domain": "area", "verdict": "FAIL"}]})
    bad = dict(diag.handoff, reason="BECAUSE_I_SAID_SO")
    with pytest.raises(jsonschema.ValidationError):
        jsonschema.validate(bad, load("agent_handoff"))
