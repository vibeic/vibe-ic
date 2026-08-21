#!/usr/bin/env python3
"""The published schema and the code that enforces it must agree, or one of
them is decoration.

WHY THERE ARE TWO OF THEM AT ALL
================================
`schemas/ppa/metric_record.v1.schema.json` is the CONTRACT: a producer in
another language, or another repository, or a reviewer with no Python, reads
that file to learn what a record is. `_ppa/metrics.py::validate` is the
ENFORCER: it runs inside programs that must not acquire a `jsonschema`
dependency to check a record, and it catches two things JSON Schema cannot
express without enumerating the taxonomy (a unit suffix contradicting its own
`unit` field, and NaN/Infinity, which are not JSON but which `json.loads`
accepts by default).

Two artefacts describing one shape is exactly how a shape drifts. The fixture
corpus below is run through BOTH and the verdicts must match, so neither can
move without the other going red.

WHICH ENGINE APPLIES THE SCHEMA (R11)
=====================================
`_ppa/schema_validation.engine_or_skip` resolves it: the `jsonschema` library
when a usable one is present, otherwise the validator bundled with this plugin.
This file used to open with `pytest.importorskip("jsonschema")`, which asks the
wrong question twice over. On a host with `jsonschema` 3.2.0 -- a current
distribution's system package -- the import SUCCEEDS and
`Draft202012Validator` does not exist, so every test below died with an
AttributeError instead of skipping. And on a host with nothing installed it
skipped, which meant the schema this repository ships was checked only where
somebody happened to have the right library.

The skip arm is kept, and it is now unreachable for this schema. That is what
it should be: "I could not check it" and "I checked it and it was clean" must
never produce the same verdict, and a schema-agreement test that quietly passes
when it could not load a validator is that defect wearing a green tick.
"""
import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from _ppa import metrics as M  # noqa: E402

from _ppa import schema_validation as _SV  # noqa: E402

SCHEMA_PATH = (pathlib.Path(__file__).resolve().parents[2]
               / "schemas" / "ppa" / "metric_record.v1.schema.json")

SCOPE = {"stage": "post_route_extracted", "process": "ss"}
SRC = {"path": "sta.rpt", "tool": "opensta"}


def _schema():
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def test_the_schema_file_is_shipped_and_is_a_valid_schema():
    assert SCHEMA_PATH.exists(), f"{SCHEMA_PATH} missing"
    assert _SV.check_schema(_schema()) == []


def test_the_schema_declares_the_frozen_id():
    assert _schema()["properties"]["schema"]["const"] == M.SCHEMA_ID


def test_the_schema_status_enum_is_the_codes_status_enum():
    """§6.2 is one enum. Two copies that disagree means a record is valid to
    one half of the system and not the other."""
    assert set(_schema()["properties"]["status"]["enum"]) == set(M.STATUSES)


def test_the_schema_does_not_enumerate_metric_names():
    """The taxonomy is not this file's to close. An enum here would have to be
    edited by every domain lane, which makes the schema a contention point and
    guarantees it trails the tree."""
    assert "enum" not in _schema()["properties"]["metric"]
    assert "pattern" in _schema()["properties"]["metric"]


# --------------------------------------------------------------------------
# The corpus. `valid` is what BOTH must say.
# --------------------------------------------------------------------------
CORPUS = [
    ("measured", True, {
        "schema": M.SCHEMA_ID, "metric": "timing.setup.wns_ns",
        "status": "MEASURED", "value": -0.124, "unit": "ns",
        "scope": dict(SCOPE), "source": dict(SRC)}),
    ("not_measured with a reason", True, {
        "schema": M.SCHEMA_ID, "metric": "power.total_mw",
        "status": "NOT_MEASURED", "reason": "no VCD was produced",
        "scope": dict(SCOPE)}),
    ("not_applicable with a reason", True, {
        "schema": M.SCHEMA_ID, "metric": "power.total_mw",
        "status": "NOT_APPLICABLE", "reason": "no switching logic",
        "scope": dict(SCOPE)}),
    ("derived with a formula", True, {
        "schema": M.SCHEMA_ID, "metric": "power.density",
        "status": "DERIVED", "value": 3.0, "unit": "mW/mm^2",
        "formula": "total / area", "scope": dict(SCOPE)}),
    ("estimated with a basis", True, {
        "schema": M.SCHEMA_ID, "metric": "area.die_um2",
        "status": "ESTIMATED", "value": 12000.0, "unit": "um^2",
        "basis": "cell-count regression", "scope": dict(SCOPE)}),

    # THE FOURTH INVARIANT, three ways.
    ("not_measured carrying 0", False, {
        "schema": M.SCHEMA_ID, "metric": "power.total_mw",
        "status": "NOT_MEASURED", "reason": "no VCD", "value": 0,
        "scope": dict(SCOPE)}),
    ("not_measured carrying -1", False, {
        "schema": M.SCHEMA_ID, "metric": "power.total_mw",
        "status": "NOT_MEASURED", "reason": "no VCD", "value": -1,
        "scope": dict(SCOPE)}),
    ("not_measured with no reason", False, {
        "schema": M.SCHEMA_ID, "metric": "power.total_mw",
        "status": "NOT_MEASURED", "scope": dict(SCOPE)}),

    ("unknown status", False, {
        "schema": M.SCHEMA_ID, "metric": "power.total_mw",
        "status": "PROBABLY_FINE", "scope": dict(SCOPE)}),
    ("wrong schema id", False, {
        "schema": "vibeic.ppa.metric.v2", "metric": "power.total_mw",
        "status": "NOT_MEASURED", "reason": "x", "scope": dict(SCOPE)}),
    ("measured with no source", False, {
        "schema": M.SCHEMA_ID, "metric": "timing.setup.wns_ns",
        "status": "MEASURED", "value": -0.124, "unit": "ns",
        "scope": dict(SCOPE)}),
    ("measured with an empty unit", False, {
        "schema": M.SCHEMA_ID, "metric": "timing.setup.wns_ns",
        "status": "MEASURED", "value": -0.124, "unit": "",
        "scope": dict(SCOPE), "source": dict(SRC)}),
    ("no scope", False, {
        "schema": M.SCHEMA_ID, "metric": "timing.setup.wns_ns",
        "status": "MEASURED", "value": -0.124, "unit": "ns",
        "scope": {}, "source": dict(SRC)}),
    ("scope with no stage", False, {
        "schema": M.SCHEMA_ID, "metric": "timing.setup.wns_ns",
        "status": "MEASURED", "value": -0.124, "unit": "ns",
        "scope": {"process": "ss"}, "source": dict(SRC)}),
    ("scope field that is the empty string", False, {
        "schema": M.SCHEMA_ID, "metric": "timing.setup.wns_ns",
        "status": "MEASURED", "value": -0.124, "unit": "ns",
        "scope": {"stage": "post_route_extracted", "process": ""},
        "source": dict(SRC)}),
    ("derived with no formula", False, {
        "schema": M.SCHEMA_ID, "metric": "power.density",
        "status": "DERIVED", "value": 3.0, "unit": "mW/mm^2",
        "scope": dict(SCOPE)}),
    ("metric name that is not dotted", False, {
        "schema": M.SCHEMA_ID, "metric": "wns", "status": "NOT_MEASURED",
        "reason": "x", "scope": dict(SCOPE)}),
    ("metric name in caps", False, {
        "schema": M.SCHEMA_ID, "metric": "Timing.Setup", "status": "NOT_MEASURED",
        "reason": "x", "scope": dict(SCOPE)}),
]


@pytest.mark.parametrize("name,valid,rec",
                         CORPUS, ids=[c[0] for c in CORPUS])
def test_the_schema_and_the_enforcer_return_the_same_verdict(name, valid, rec):
    code_ok = (M.validate(rec) == [])
    schema_ok = _SV.engine_or_skip(_schema()).is_valid(rec)
    assert code_ok is valid, (
        f"_ppa.metrics.validate says {code_ok} for {name!r}; expected {valid}. "
        f"problems={M.validate(rec)}")
    assert schema_ok is valid, (
        f"the published schema says {schema_ok} for {name!r}; expected {valid}")
    assert code_ok == schema_ok


def test_the_enforcer_catches_two_things_the_schema_cannot():
    """Stated as a test so the asymmetry is deliberate and visible, rather than
    being discovered later as a schema bug.

    NaN survives `json.loads` by default and is not JSON; and a unit suffix
    contradicting its own `unit` field cannot be expressed in JSON Schema
    without enumerating every metric name here, which this schema deliberately
    does not do.
    """
    nan = {"schema": M.SCHEMA_ID, "metric": "timing.setup.wns_ns",
           "status": "MEASURED", "value": float("nan"), "unit": "ns",
           "scope": dict(SCOPE), "source": dict(SRC)}
    assert "VALUE_NOT_FINITE" in [c for c, _ in M.validate(nan)]
    assert _SV.engine_or_skip(_schema()).is_valid(nan)

    wrong_unit = {"schema": M.SCHEMA_ID, "metric": "area.die_um2",
                  "status": "MEASURED", "value": 12000.0, "unit": "mm^2",
                  "scope": dict(SCOPE), "source": dict(SRC)}
    assert "UNIT_CONTRADICTS_NAME" in [c for c, _ in M.validate(wrong_unit)]
    assert _SV.engine_or_skip(_schema()).is_valid(wrong_unit)
