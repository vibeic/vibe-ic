#!/usr/bin/env python3
"""`schemas/ppa/readme_hint.v1.schema.json` -- the file the contract required
and the lane that emits the document could not create.

WHY THIS EXISTS
===============
`docs/PPA_INTERFACES.md` section 5 requires every instance document to carry
`"schema": "vibeic.ppa.<name>.v1"` as its first key AND requires the schema
file to live in `schemas/ppa/`. `programs/readme_ppa_extractor.py` has stamped
`vibeic.ppa.readme_hint.v1` into every document it writes since v1.11.31, and
the schema file did not exist -- `schemas/` was outside that lane's ownership.
A schema id that resolves to nothing is a contract nobody can check.

The schema was DERIVED FROM THE EMISSIONS, not from a reading of the code:
this file runs the program and validates what came out. Every constraint the
schema states is a fact about a document that was produced here, which is why
the corpus below is generated rather than hand-written.

WHAT THE SCHEMA IS FOR, BEYOND SHAPE
====================================
Four of its rules are the ones that matter, and each has a negative fixture:

  * `authority: HINT` and `authoritative: false` are CONSTANTS. The guarantee
    that a README number never outranks an L-doc is structural, so a document
    that promotes itself is invalid rather than merely unusual.
  * `span_status` and the span must agree. A hint claiming RECORDED with no
    span is the provenance gap the status exists to expose.
  * `verdict` and the body must agree, in BOTH directions: CONFLICT with no
    conflicts, and OK carrying one, are each a document arguing with itself.
  * CANNOT_CHECK carries a reason, read=false and no hints. "I could not read
    it" and "I read it and found nothing" must never serialize the same.

VALIDATOR HONESTY
=================
`jsonschema` older than 4.0 has no Draft 2020-12 validator. Rather than fail
or -- much worse -- skip quietly, this file falls back to Draft 7 AND pins that
the schema uses no keyword the two drafts read differently, so the fallback
verdict means what the 2020-12 verdict would have meant. If `jsonschema` is
absent altogether this SKIPS with a named reason: "I could not check it" and
"I checked it and it was clean" must never produce the same verdict.

Chip-AGNOSTIC: the fixture README names no IC, vendor, SKU, node or codename.
"""
from __future__ import annotations

import copy
import json
import subprocess
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parents[1]
_PROG = _PROGRAMS / "readme_ppa_extractor.py"
SCHEMA_PATH = (Path(__file__).resolve().parents[2]
               / "schemas" / "ppa" / "readme_hint.v1.schema.json")

jsonschema = pytest.importorskip(
    "jsonschema",
    reason="jsonschema is not installed, so the published readme_hint schema "
           "was NOT checked against a real emitted document in this session. "
           "This is a SKIP and not a pass: nothing here looked.")

#: Prefer the draft the schema declares; fall back only when the installed
#: library predates it. Never silently -- see the keyword pin below.
_VALIDATOR = getattr(jsonschema, "Draft202012Validator", None)
_FELL_BACK = _VALIDATOR is None
if _FELL_BACK:
    _VALIDATOR = jsonschema.Draft7Validator

#: Keywords whose meaning differs between draft-07 and 2020-12, or which one
#: of the two does not have at all. The schema must contain none of them for
#: the fallback above to be an honest substitute.
_DRAFT_DIVERGENT_KEYWORDS = frozenset({
    "prefixItems", "dependentRequired", "dependentSchemas",
    "unevaluatedProperties", "unevaluatedItems", "$recursiveRef",
    "$recursiveAnchor", "$dynamicRef", "$dynamicAnchor", "contentSchema",
    "additionalItems", "definitions", "exclusiveMinimum_bool",
})

#: A README exercising every emission branch the program has: a markdown
#: table, an inline key/value block, the number-first bullet form, the area
#: key/value form, per-sub-block counts, and the vendor/bold-family/device
#: triplet. Generic labels on purpose.
README = (
    "# Example Core\n"
    "\n"
    "## Implementation results\n"
    "\n"
    "| Platform  | LUTs | Regs | Fmax    |\n"
    "|-----------|------|------|---------|\n"
    "| Fabric A  | 1234 | 567  | 250 MHz |\n"
    "| Fabric B  | 2345 | 678  | 300 MHz |\n"
    "\n"
    "## Fabric A\n"
    "LUTs: 1234\n"
    "Regs: 567\n"
    "Fmax: 250 MHz\n"
    "\n"
    "## Standard cell flow\n"
    "- Area: 520 x 520 um\n"
    "- 8 kCells\n"
    "- 96 MHz\n"
    "- block_one: 512 LUTs\n"
    "- block_two: 128 LUTs\n"
    "\n"
    "### Vendor One\n"
    "**Family Alpha**\n"
    "- DevcodeOne\n"
    "LUTs: 900\n"
    "Fmax: 120 MHz\n"
)


def _run(args, cwd):
    return subprocess.run(
        [sys.executable, str(_PROG)] + [str(a) for a in args],
        capture_output=True, text=True, cwd=str(cwd))


@pytest.fixture(scope="module")
def emitted(tmp_path_factory):
    """The real documents, produced by running the shipped CLI.

    Three of them, because the program has three verdicts and the schema
    constrains each differently. Returns {verdict: document}.
    """
    d = tmp_path_factory.mktemp("readme_hint")
    (d / "README.md").write_text(README)
    # An L-doc that DISAGREES with the README's Fabric A fmax -> CONFLICT.
    (d / "l1_conflict.json").write_text(json.dumps(
        {"platform": "Fabric A", "clock": {"target_fmax_mhz": 200}}))
    (d / "design.sdc").write_text(
        "create_clock -name clk -period 10.0 [get_ports clk]\n")
    (d / "rtl").mkdir()

    out = {}

    # OK -- the declared skills/ppa-predict preflight invocation, verbatim.
    p_ok = d / "hints_ok.json"
    r = _run(["--rtl-dir", d / "rtl", "--readme", d / "README.md",
              "--json", p_ok], d)
    assert r.returncode == 0, r.stderr
    out["OK"] = json.loads(p_ok.read_text())

    # CONFLICT -- a README number contradicts an L-doc at a matched scope.
    p_c = d / "hints_conflict.json"
    r = _run(["--rtl-dir", d / "rtl", "--readme", d / "README.md",
              "--l-doc", d / "l1_conflict.json", "--sdc", d / "design.sdc",
              "--json", p_c], d)
    assert r.returncode == 1, (r.returncode, r.stderr)
    out["CONFLICT"] = json.loads(p_c.read_text())

    # CANNOT_CHECK -- the input could not be read.
    p_x = d / "hints_cannot_check.json"
    r = _run(["--readme", d / "no_such_README.md", "--json", p_x], d)
    assert r.returncode == 2, (r.returncode, r.stderr)
    out["CANNOT_CHECK"] = json.loads(p_x.read_text())
    return out


@pytest.fixture(scope="module")
def schema():
    assert SCHEMA_PATH.is_file(), (
        "%s is missing. PPA_INTERFACES.md section 5 requires the schema a "
        "document names to exist in schemas/ppa/." % SCHEMA_PATH)
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def _errors(schema, doc):
    return sorted(_VALIDATOR(schema).iter_errors(doc),
                  key=lambda e: list(e.absolute_path))


# ======================================================================
# The file itself
# ======================================================================
def test_the_schema_file_is_shipped_and_is_a_valid_schema(schema):
    _VALIDATOR.check_schema(schema)


def test_the_schema_declares_the_id_the_program_stamps(schema):
    """One id, in the schema and in every document. Two spellings would make
    the document valid to one half of the system and unknown to the other."""
    import importlib.util
    spec = importlib.util.spec_from_file_location("rpe_for_id", _PROG)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert schema["$id"] == mod.SCHEMA
    assert schema["properties"]["schema"]["const"] == mod.SCHEMA


def test_the_schema_lives_where_section_5_says():
    assert SCHEMA_PATH.parent.name == "ppa"
    assert SCHEMA_PATH.name == "readme_hint.v1.schema.json"


def test_the_fallback_validator_is_an_honest_substitute(schema):
    """The Draft 7 fallback only means what 2020-12 would mean if the schema
    stays inside the two drafts' shared vocabulary."""
    seen = set()

    def walk(node):
        if isinstance(node, dict):
            seen.update(node)
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(schema)
    bad = seen & _DRAFT_DIVERGENT_KEYWORDS
    assert not bad, (
        "the schema uses %s, which draft-07 and 2020-12 do not read the same "
        "way; the fallback validator in this file would then report a verdict "
        "the declared draft does not share" % sorted(bad))


def test_every_ref_is_a_local_pointer(schema):
    """`$id` here is a bare name and not a resolvable URL, which is the
    convention the other 2020-12 schemas in this directory use. That is only
    safe while every `$ref` is a pointer INTO this document -- a remote ref
    would send a validator to a host that does not exist."""
    refs = []

    def walk(node):
        if isinstance(node, dict):
            if isinstance(node.get("$ref"), str):
                refs.append(node["$ref"])
            for v in node.values():
                walk(v)
        elif isinstance(node, list):
            for v in node:
                walk(v)

    walk(schema)
    assert refs, "the schema declares no $ref at all; this pin checks nothing"
    assert all(r.startswith("#/") for r in refs), [r for r in refs
                                                   if not r.startswith("#/")]


# ======================================================================
# POSITIVE -- every document the program actually emits validates
# ======================================================================
@pytest.mark.parametrize("verdict", ["OK", "CONFLICT", "CANNOT_CHECK"])
def test_a_real_emitted_document_validates(schema, emitted, verdict):
    doc = emitted[verdict]
    assert doc["verdict"] == verdict
    errs = _errors(schema, doc)
    assert not errs, "\n".join(
        "%s: %s" % (list(e.absolute_path), e.message) for e in errs)


def test_the_positive_corpus_is_not_vacuous(emitted):
    """A schema validated only against near-empty documents constrains
    nothing. These are the branches the negatives below mutate."""
    ok = emitted["OK"]
    assert len(ok["hints"]) >= 10
    conflict = emitted["CONFLICT"]
    assert conflict["conflicts"], "no CONFLICT branch was exercised"
    assert conflict["undetermined"], "no UNDETERMINED branch was exercised"
    assert conflict["authority_records"], "no authority was harvested"
    assert any(h.get("sub_block") for h in ok["hints"])
    assert any(h.get("vendor") for h in ok["hints"])
    assert any(isinstance(h["value"], str) for h in ok["hints"])
    assert any(h["value"] is None for h in ok["hints"])
    assert any(h["source_form"] == "markdown_table" for h in ok["hints"])


# ======================================================================
# NEGATIVE -- one mutation each, applied to a document that validates
# ======================================================================
def _first_hint_index(doc, pred):
    for i, h in enumerate(doc["hints"]):
        if pred(h):
            return i
    raise AssertionError("no hint matched; the fixture corpus changed shape")


def _promote_itself(d):
    d["authoritative"] = True


def _claim_authority(d):
    d["authority"] = "L_DOC"


def _wrong_schema_id(d):
    d["schema"] = "vibeic.ppa.readme_hint.v2"


def _span_status_lies(d):
    i = _first_hint_index(d, lambda h: h["span_status"] == "RECORDED")
    d["hints"][i]["span"] = None


def _span_digest_lies(d):
    i = _first_hint_index(d, lambda h: h["span_status"] == "RECORDED")
    d["hints"][i]["span_sha256"] = "not-a-digest"


def _span_that_cannot_be_sliced(d):
    i = _first_hint_index(d, lambda h: h["span_status"] == "RECORDED")
    d["hints"][i]["span"]["line"] = 0


def _unknown_top_level_key(d):
    d["confidence"] = 0.9


def _unknown_hint_key(d):
    d["hints"][0]["estimated"] = True


def _source_digest_not_a_digest(d):
    d["source"]["sha256"] = "deadbeef"


def _hint_not_ignored(d):
    d["conflicts"][0]["hint_ignored"] = False


def _conflict_resolved_as_agreement(d):
    d["conflicts"][0]["resolution"] = "AGREE"


def _undetermined_called_a_mismatch(d):
    d["undetermined"][0]["reason"] = "VALUE_MISMATCH"


def _rtl_claimed_read(d):
    d["inputs"]["rtl_read"] = True


def _identity_dropped(d):
    del d["document_sha256"]


def _authority_dropped(d):
    del d["authority_records"]


def _verdict_conflict_with_no_conflicts(d):
    d["conflicts"] = []


def _verdict_ok_carrying_a_conflict(d):
    d["verdict"] = "OK"


def _unknown_source_form(d):
    d["hints"][0]["source_form"] = "guessed"


#: (id, base document, mutation). Every one is a document the program cannot
#: emit; the schema exists to say so.
NEGATIVES = [
    ("a document that promotes itself to authoritative",
     "CONFLICT", _promote_itself),
    ("a document claiming to be an L_DOC", "CONFLICT", _claim_authority),
    ("a document stamped with another schema version",
     "CONFLICT", _wrong_schema_id),
    ("span_status RECORDED with no span", "CONFLICT", _span_status_lies),
    ("span_status RECORDED with an unusable digest",
     "CONFLICT", _span_digest_lies),
    ("a span whose line number is not a line",
     "CONFLICT", _span_that_cannot_be_sliced),
    ("an unknown top-level key", "CONFLICT", _unknown_top_level_key),
    ("an unknown key on a hint", "CONFLICT", _unknown_hint_key),
    ("a source digest that is not a sha256",
     "CONFLICT", _source_digest_not_a_digest),
    ("a conflict where the hint was NOT ignored",
     "CONFLICT", _hint_not_ignored),
    ("a conflict resolved as an agreement",
     "CONFLICT", _conflict_resolved_as_agreement),
    ("an undetermined comparison reported as a mismatch",
     "CONFLICT", _undetermined_called_a_mismatch),
    ("a run claiming it read the RTL", "CONFLICT", _rtl_claimed_read),
    ("a verdict with no document identity", "CONFLICT", _identity_dropped),
    ("a verdict with no authority it compared against",
     "CONFLICT", _authority_dropped),
    ("CONFLICT with an empty conflicts list",
     "CONFLICT", _verdict_conflict_with_no_conflicts),
    ("OK while carrying a conflict", "CONFLICT",
     _verdict_ok_carrying_a_conflict),
    ("a hint from a form the parser does not have",
     "OK", _unknown_source_form),
    ("CANNOT_CHECK with no reason", "CANNOT_CHECK",
     lambda d: d.pop("reason")),
    ("CANNOT_CHECK carrying hints", "CANNOT_CHECK",
     lambda d: d.__setitem__("hints", [{
         "metric": "luts", "value": 1, "platform": None,
         "platform_key": None, "authority": "HINT", "authoritative": False,
         "source_form": "inline_kv", "span": None, "span_sha256": None,
         "span_status": "NO_SPAN_RECORDED"}])),
    ("CANNOT_CHECK claiming it read the file", "CANNOT_CHECK",
     lambda d: d.__setitem__("read", True)),
]


@pytest.mark.parametrize("label,base,mutate",
                         NEGATIVES, ids=[n[0] for n in NEGATIVES])
def test_the_schema_rejects(schema, emitted, label, base, mutate):
    doc = copy.deepcopy(emitted[base])
    assert not _errors(schema, doc), (
        "the UNMUTATED base document does not validate, so this negative "
        "would go red for the wrong reason")
    mutate(doc)
    assert _errors(schema, doc), (
        "the schema ACCEPTS %r. A document the program cannot emit is a "
        "document the contract must not permit." % label)
