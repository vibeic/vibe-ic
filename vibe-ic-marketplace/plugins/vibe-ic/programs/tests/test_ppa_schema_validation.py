#!/usr/bin/env python3
"""R11 — `jsonschema` was used and declared nowhere, and the guard that was
supposed to cover its absence asked the wrong question.

THE TWO FAILURES, BOTH REPRODUCED BEFORE ANYTHING WAS FIXED
===========================================================
  jsonschema ABSENT   `ppa_contract_check.py` reported PPA-C-010 UNDETERMINED
                      and exited 2. Honest -- and the contract's shape is never
                      checked on a fresh install, so the flow does not
                      complete, which is the whole standard this work is held
                      to.
  jsonschema 3.2.0    what a current distribution's system package installs.
                      `import jsonschema` SUCCEEDS. The shipped schemas declare
                      draft 2020-12 and `Draft202012Validator` arrived in 4.0,
                      and the guard caught ImportError only -- so the program
                      died with an uncaught AttributeError and returned rc=1.
                      In this contract rc=1 is a finding about a DESIGN. A
                      crash was publishing itself as one, and 33 tests of this
                      repository were red on that host because of it.

THE HARD PART OF SHIPPING A HAND-WRITTEN VALIDATOR
==================================================
A re-implementation that quietly ignores a keyword reports clean over a rule it
never applied. So the bundled engine REFUSES what it cannot apply, and this
file spends most of its assertions on that: on the shipped schemas it must
support everything, on a schema using an unimplemented keyword it must produce
a REASON and no verdict, and the refusal must survive being buried in a nested
subschema where lazy discovery would never reach it.

THE DIFFERENTIAL ARM is the other half. Wherever a reference `jsonschema` on
this host can apply a schema, the two engines are run over the same corpus and
required to AGREE case by case. That is what stops "it passes my own fixtures"
from being the whole evidence.

chip-AGNOSTIC: JSON Schema semantics and this plugin's own schema files.
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

_PROGRAMS = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(_PROGRAMS))

from _ppa import jsonschema_bundled as B          # noqa: E402
from _ppa import schema_validation as SV          # noqa: E402

SCHEMA_DIR = _PROGRAMS.parent / "schemas" / "ppa"
SHIPPED = sorted(p.name for p in SCHEMA_DIR.glob("*.json"))


def _schema(name):
    return json.loads((SCHEMA_DIR / name).read_text(encoding="utf-8"))


# ---------------------------------------------------------------------------
# the declaration
# ---------------------------------------------------------------------------
def test_the_preferred_library_is_declared_in_exactly_one_place():
    """R11 was "used and not declared". The declaration is machine-readable and
    every install message is built from it, so advice cannot drift from need."""
    for key in ("distribution", "minimum_version", "why", "install"):
        assert SV.PREFERRED[key], key
    assert SV.PREFERRED["distribution"] in SV.PREFERRED["install"]
    assert SV.PREFERRED["minimum_version"] in SV.PREFERRED["install"]
    assert SV.PREFERRED["required"] is False, (
        "it is declared as OPTIONAL because the engine is bundled; if that "
        "ever stops being true this flag is the thing that must change first")


def test_an_old_library_names_the_version_and_the_remedy():
    """The 3.2.0 case, told to the user rather than crashed at them."""
    class _Old:
        __version__ = "3.2.0"
    sys.modules["jsonschema"], real = _Old(), sys.modules.get("jsonschema")
    try:
        engine, why = SV._library_engine(_schema("contract.v1.schema.json"))
    finally:
        if real is None:
            sys.modules.pop("jsonschema", None)
        else:
            sys.modules["jsonschema"] = real
    assert engine is None
    assert "3.2.0" in why and "Draft202012Validator" in why
    assert SV.PREFERRED["install"] in why


# ---------------------------------------------------------------------------
# the bundled engine covers what this plugin actually ships
# ---------------------------------------------------------------------------
def test_there_are_schemas_to_check():
    """The denominator, stated. A parametrised sweep over an empty glob is a
    green tick over nothing."""
    assert len(SHIPPED) >= 5, SHIPPED


@pytest.mark.parametrize("name", SHIPPED)
def test_the_bundled_engine_can_apply_every_shipped_schema(name):
    """If this ever goes red, a schema grew a construct the bundled engine does
    not implement -- and the right fix is to implement it, not to weaken the
    refusal that caught it."""
    assert B.unsupported(_schema(name)) == []


@pytest.mark.parametrize("name", SHIPPED)
def test_every_shipped_schema_resolves_to_some_engine(name):
    engine, notes = SV.resolve(_schema(name))
    assert engine is not None, notes
    assert notes and "validated by" in notes[-1]


# ---------------------------------------------------------------------------
# THE RULE THAT MAKES IT SAFE: it refuses rather than ignores
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("schema,fragment", [
    ({"type": "object", "contains": {"type": "string"}}, "contains"),
    ({"type": "array", "prefixItems": [{"type": "string"}]}, "prefixItems"),
    ({"dependentSchemas": {"a": {"required": ["b"]}}}, "dependentSchemas"),
    ({"$ref": "https://example.invalid/other.json"}, "LOCAL pointer"),
    ({"type": "number", "exclusiveMinimum": True}, "draft-04"),
    ({"type": "array", "items": [{"type": "string"}]}, "tuple"),
    ({"type": "string", "pattern": "([unclosed"}, "regular expression"),
])
def test_an_unimplemented_construct_is_named_not_ignored(schema, fragment):
    gaps = B.unsupported(schema)
    assert gaps, schema
    assert any(fragment in g for g in gaps), gaps


def test_an_unimplemented_construct_NESTED_DEEP_is_still_caught():
    """The one that matters. Lazy discovery during validation would never reach
    a keyword on a branch a passing instance does not take, and the engine
    would report clean over a rule it could not apply. The walk is EAGER."""
    schema = {"type": "object", "properties": {"a": {"type": "object",
              "properties": {"b": {"allOf": [{"type": "object",
                             "properties": {"c": {"contains": {}}}}]}}}}}
    gaps = B.unsupported(schema)
    assert gaps and "contains" in gaps[0]
    assert "/properties/a/properties/b/allOf[0]/properties/c" in gaps[0]


def test_an_unsupported_schema_resolves_to_NO_ENGINE_with_a_reason():
    """rc=2 territory, not rc=0. `resolve` must hand back None, and the reason
    must say plainly that this is not the schema passing."""
    class _Blocked:
        def find_spec(self, name, path=None, target=None):
            if name.split(".")[0] == "jsonschema":
                raise ImportError("blocked for this test")
            return None
    sys.meta_path.insert(0, _Blocked())
    sys.modules.pop("jsonschema", None)
    try:
        engine, notes = SV.resolve({"type": "array", "contains": {}})
        assert engine is None
        assert any("NOT validated" in n for n in notes)
        assert any("not the schema passing" in n for n in notes)
        assert any(SV.PREFERRED["install"] in n for n in notes)
        assert SV.check_schema({"type": "array", "contains": {}})
    finally:
        sys.meta_path.pop(0)


def test_with_no_library_at_all_a_shipped_schema_still_validates():
    """THE R11 FIX, stated directly: a fresh install with nothing installed
    must still be able to check a contract's shape."""
    class _Blocked:
        def find_spec(self, name, path=None, target=None):
            if name.split(".")[0] == "jsonschema":
                raise ImportError("blocked for this test")
            return None
    sys.meta_path.insert(0, _Blocked())
    real = sys.modules.pop("jsonschema", None)
    try:
        schema = _schema("contract.v1.schema.json")
        engine, notes = SV.resolve(schema)
        assert engine is not None, notes
        assert engine.name == SV.ENGINE_BUNDLED
        # and it DISCRIMINATES, which is the part a fallback usually does not
        assert engine.errors({"schema": "not-the-const"}), \
            "the fallback accepted a document the schema forbids"
    finally:
        sys.meta_path.pop(0)
        if real is not None:
            sys.modules["jsonschema"] = real


# ---------------------------------------------------------------------------
# the differential arm -- agreement with the reference implementation
# ---------------------------------------------------------------------------
def _reference(schema):
    """A reference validator for `schema` on THIS host, or None.

    This is the ONE place outside `_ppa/schema_validation.py` that imports
    `jsonschema` directly, and it must be: a differential that obtained its
    reference through the module under test would be comparing that module
    with itself. `test_jsonschema_is_imported_in_exactly_one_place` exempts
    this file by exact path and nothing else.
    """
    try:
        import jsonschema                               # noqa: WPS433
    except ImportError:                                 # pragma: no cover
        return None
    declared = str(schema.get("$schema", ""))
    want = SV._DRAFTS.get(declared, SV._FALLBACK_CLASS)
    cls = getattr(jsonschema, want, None)
    if cls is None:
        return None
    return cls(schema)


CORPUS = [
    ("empty object", {}),
    ("null", None),
    ("a bare string", "x"),
    ("a number", 3),
    ("a boolean where an integer belongs", True),
    ("a list", [1, 2, 3]),
    ("a nested object", {"a": {"b": [1, {"c": None}]}}),
    ("a plausible metric record", {
        "schema": "vibeic.ppa.metric.v1", "metric": "area.core_um2",
        "status": "MEASURED", "value": 1.0, "unit": "um^2",
        "scope": {"stage": "post_route_extracted"},
        "source": {"path": "x.rpt", "sha256": "sha256:" + "a" * 64}}),
    ("the same record with the sentinel defect", {
        "schema": "vibeic.ppa.metric.v1", "metric": "area.core_um2",
        "status": "NOT_MEASURED", "value": 0, "unit": "um^2",
        "scope": {"stage": "post_route_extracted"},
        "source": {"path": "x.rpt", "sha256": "sha256:" + "a" * 64}}),
    ("a record with a bad digest", {
        "schema": "vibeic.ppa.metric.v1", "metric": "area.core_um2",
        "status": "MEASURED", "value": 1.0, "unit": "um^2",
        "scope": {"stage": "post_route_extracted"},
        "source": {"path": "x.rpt", "sha256": "nope"}}),
]


@pytest.mark.parametrize("schema_name", SHIPPED)
@pytest.mark.parametrize("label,doc", CORPUS, ids=[c[0] for c in CORPUS])
def test_the_two_engines_agree_case_by_case(schema_name, label, doc):
    """Run BOTH engines over the same document and require the same verdict.

    Skipped per schema where this host's library cannot apply that draft --
    which on a 3.2.0 host is every 2020-12 schema, and is exactly how R11 was
    found. The draft-07 schemas still cross-check here, so the arm is never
    entirely vacuous on such a host; `test_at_least_one_pair_was_compared`
    asserts that rather than leaving it to be assumed.
    """
    schema = _schema(schema_name)
    ref = _reference(schema)
    if ref is None:
        pytest.skip(f"no reference validator for {schema_name} on this host")
    assert B.unsupported(schema) == []
    theirs = bool(list(ref.iter_errors(doc)))
    ours = bool(list(B.iter_errors(schema, doc)))
    assert ours == theirs, (
        f"{schema_name} / {label}: bundled says "
        f"{'INVALID' if ours else 'valid'}, reference says "
        f"{'INVALID' if theirs else 'valid'}")


def test_at_least_one_pair_was_compared():
    """The denominator of the differential arm. If every case skipped, the arm
    above is a row of green ticks over nothing."""
    compared = [n for n in SHIPPED if _reference(_schema(n)) is not None]
    assert compared, (
        "no shipped schema could be cross-checked against a reference engine "
        "on this host; the differential arm measured nothing")


# ---------------------------------------------------------------------------
# the bundled engine's own semantics, on the cases that are easy to get wrong
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("schema,doc,valid", [
    ({"type": "integer"}, True, False),          # bool is not an integer
    ({"type": "integer"}, 1, True),
    ({"type": "integer"}, 1.0, True),            # 1.0 is an integer value
    ({"type": "integer"}, 1.5, False),
    ({"type": "boolean"}, 1, False),
    ({"type": "number"}, True, False),
    ({"enum": [1, 2]}, True, False),             # True is not 1
    ({"enum": [1, 2]}, 1.0, True),               # 1.0 is 1
    ({"const": "a"}, "a", True),
    ({"const": 0}, False, False),
    ({"type": "object", "additionalProperties": False,
      "properties": {"a": {}}}, {"b": 1}, False),
    ({"type": "object", "additionalProperties": {"type": "string"},
      "properties": {"a": {}}}, {"b": 1}, False),
    ({"type": "object", "additionalProperties": {"type": "string"},
      "properties": {"a": {}}}, {"b": "x"}, True),
    ({"type": "object", "required": ["a"]}, {}, False),
    ({"type": "object", "propertyNames": {"pattern": "^[a-z]+$"}},
     {"A": 1}, False),
    ({"type": "array", "uniqueItems": True}, [1, 1], False),
    ({"type": "array", "uniqueItems": True}, [1, True], True),
    ({"type": "number", "exclusiveMinimum": 0}, 0, False),
    ({"type": "number", "exclusiveMinimum": 0}, 0.1, True),
    ({"type": "number", "minimum": 0}, 0, True),
    ({"type": "string", "minLength": 1}, "", False),
    ({"type": "string", "pattern": "^x"}, "yx", False),
    ({"not": {"type": "string"}}, "x", False),
    ({"oneOf": [{"type": "integer"}, {"type": "number"}]}, 1, False),
    ({"anyOf": [{"type": "integer"}, {"type": "string"}]}, "x", True),
    ({"if": {"const": "a"}, "then": {"type": "integer"}}, "a", False),
    ({"if": {"const": "a"}, "then": {"type": "integer"}}, "b", True),
    ({"$defs": {"s": {"type": "string"}}, "$ref": "#/$defs/s"}, 1, False),
    ({"$defs": {"s": {"type": "string"}}, "$ref": "#/$defs/s"}, "x", True),
])
def test_the_bundled_semantics(schema, doc, valid):
    errors = list(B.iter_errors(schema, doc))
    assert (not errors) == valid, (schema, doc, [e.message for e in errors])


def test_an_unresolvable_ref_is_a_defect_in_the_schema_not_a_pass():
    errors = list(B.iter_errors({"$ref": "#/$defs/missing"}, "anything"))
    assert errors and "defect in the SCHEMA" in errors[0].message


def test_errors_carry_the_path_a_reader_needs():
    schema = {"type": "object", "properties": {
        "a": {"type": "object", "properties": {"b": {"type": "string"}}}}}
    errors = list(B.iter_errors(schema, {"a": {"b": 1}}))
    assert [e.path for e in errors] == [["a", "b"]]


# ---------------------------------------------------------------------------
# the guard that stops R11 happening again
# ---------------------------------------------------------------------------
def test_jsonschema_is_imported_in_exactly_one_place():
    """R11's shape was "a third-party library reached for wherever it was
    convenient, declared nowhere". Six test modules and one program each said
    `import jsonschema` and each had to get the version question right; none
    of them did.

    One import site is what makes the declaration above load-bearing: a new
    caller either goes through `resolve()` -- and inherits the version probe,
    the bundled fallback and the refusal -- or reddens here.
    """
    import ast
    #: The differential arm in THIS file is the one deliberate exception: a
    #: cross-check that obtained its reference through the module under test
    #: would be comparing that module with itself. It is exempt by exact path,
    #: never by pattern, so a second exception cannot appear by accident.
    exempt = {pathlib.Path(SV.__file__).resolve(),
              pathlib.Path(__file__).resolve()}
    offenders = []
    for path in sorted(_PROGRAMS.rglob("*.py")):
        if path.resolve() in exempt:
            continue
        if "fixtures" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:                             # pragma: no cover
            continue
        for node in ast.walk(tree):
            names = []
            if isinstance(node, ast.Import):
                names = [a.name for a in node.names]
            elif isinstance(node, ast.ImportFrom) and node.module:
                names = [node.module]
            if any(n.split(".")[0] == "jsonschema" for n in names):
                offenders.append(
                    f"{path.relative_to(_PROGRAMS)}:{node.lineno}")
    assert offenders == [], (
        "these import `jsonschema` directly instead of going through "
        f"_ppa/schema_validation.py, so they do not inherit the version probe, "
        f"the bundled fallback or the refusal: {offenders}")


def test_the_engine_note_is_always_printed_so_a_reader_knows_which_ran():
    """A silent fallback would hide the fact that a host is running the bundled
    engine, which is precisely what a reader of a verdict needs to know."""
    for name in SHIPPED:
        _, notes = SV.resolve(_schema(name))
        assert notes, name
        assert any("validated by" in n or "NOT validated" in n for n in notes)
