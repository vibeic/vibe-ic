#!/usr/bin/env python3
"""`ppa_report_gen.py` — the four fixtures, and the one row it may never drop.

PPA_INTERFACES.md §7: positive, negative, vacuous, mutation. The mutation cases
here are run IN PROCESS, by removing the rule under test and asserting the fixture
stops being caught: a red that survives the removal of its own rule was not
produced by that rule, and a gate credited with a finding it did not make is
worse than no gate.
"""
from __future__ import annotations

import json
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
import ppa_report_gen as gen  # noqa: E402

SHA = "sha256:" + "a" * 64


def _measured(metric="timing.setup.wns_ns", value=-0.124, **over):
    rec = {
        "schema": gen.METRIC_SCHEMA,
        "metric": metric,
        "status": "MEASURED",
        "value": value,
        "unit": "ns",
        "scope": {"stage": "post_route_extracted", "check": "setup"},
        "source": {"path": "phase3/stage3/sta/sta.rpt", "sha256": SHA,
                   "tool": "opensta", "parser": "ppa_metric_extract.py"},
    }
    rec.update(over)
    return rec


def _not_measured(metric="power.total_mw", reason="no activity basis recorded"):
    return {"schema": gen.METRIC_SCHEMA, "metric": metric,
            "status": "NOT_MEASURED", "reason": reason,
            "scope": {"stage": "post_route_extracted"}}


def _corpus(tmp_path, *records):
    root = tmp_path / "metrics"
    root.mkdir(parents=True, exist_ok=True)
    for i, rec in enumerate(records):
        (root / f"m{i}.json").write_text(json.dumps(rec), encoding="utf-8")
    return root


# ---------------------------------------------------------------- positive

def test_positive_a_well_formed_corpus_generates(tmp_path):
    rc, result = gen.generate(_corpus(tmp_path, _measured(), _not_measured()))
    assert rc == gen.RC_OK, result
    assert result["coverage"] == {"total": 2,
                                  "by_status": {"MEASURED": 1,
                                                "NOT_MEASURED": 1}}


def test_the_not_measured_row_is_printed_not_omitted(tmp_path):
    """The row that must never be omitted (spec §18).

    A report that silently drops what it could not measure reads as complete,
    and it reads that way to the author first. Both the reason and the literal
    status have to appear.
    """
    reason = "no activity basis: neither a VCD nor a vectorless default existed"
    rc, result = gen.generate(_corpus(tmp_path, _measured(),
                                      _not_measured(reason=reason)))
    assert rc == gen.RC_OK
    md = result["report_md"]
    assert "NOT_MEASURED" in md
    assert reason in md
    assert "power.total_mw" in md
    assert "## Not measured" in md


def test_an_axis_with_no_record_still_gets_a_printed_row(tmp_path):
    """An axis missing from a report reads as an axis with nothing to report."""
    rc, result = gen.generate(_corpus(tmp_path, _measured()))
    assert rc == gen.RC_OK
    md = result["report_md"]
    for axis in ("## Timing", "## Power", "## Area"):
        assert axis in md, f"{axis} heading dropped"
    area = md.split("## Area", 1)[1].split("##", 1)[0]
    assert "NOT_MEASURED" in area


def test_no_numeric_sentinel_stands_in_for_a_missing_measurement(tmp_path):
    """PPA_INTERFACES.md §2: 0, -1 and "" never mean `not measured`."""
    rc, result = gen.generate(_corpus(tmp_path, _not_measured()))
    assert rc == gen.RC_OK
    claim = [c for c in result["claims_doc"]["claims"]
             if c.get("metric") == "power.total_mw"][0]
    assert "value" not in claim
    assert claim["reason"]


def test_every_status_appears_in_the_coverage_table_including_the_zeros(tmp_path):
    """A status absent from the table is indistinguishable from one nobody
    thought to look for."""
    rc, result = gen.generate(_corpus(tmp_path, _measured()))
    assert rc == gen.RC_OK
    for status in gen.STATUS_MAY_CARRY_VALUE:
        assert f"| {status} |" in result["report_md"], status


def test_the_claims_document_carries_the_schema_key_first(tmp_path):
    rc, result = gen.generate(_corpus(tmp_path, _measured()))
    assert rc == gen.RC_OK
    doc = result["claims_doc"]
    assert doc["schema"] == gen.CLAIMS_SCHEMA
    assert doc["generated_by"] == "ppa_report_gen.py"


def test_claim_id_is_stable_across_dict_build_order(tmp_path):
    """Scope is part of the id, via the canonical serializer, so the id cannot
    depend on the order somebody happened to assemble the scope in."""
    a = {"stage": "post_route", "check": "setup"}
    b = {"check": "setup", "stage": "post_route"}
    assert gen.claim_id_for("timing.setup.wns_ns", a) == \
        gen.claim_id_for("timing.setup.wns_ns", b)


def test_a_different_scope_is_a_different_claim():
    """Two numbers are comparable only if their scope matches (§2), so they
    must not share a citation id."""
    assert gen.claim_id_for("m", {"process": "ss"}) != \
        gen.claim_id_for("m", {"process": "ff"})


# ---------------------------------------------------------------- negative

@pytest.mark.parametrize("record,code", [
    (_measured(status="NOT_MEASURED", reason="x"), "VALUE_WITHOUT_MEASUREMENT"),
    ({"schema": gen.METRIC_SCHEMA, "metric": "area.total_um2",
      "status": "MEASURED"}, "MEASURED_WITHOUT_VALUE"),
    ({"schema": gen.METRIC_SCHEMA, "metric": "power.total_mw",
      "status": "NOT_MEASURED"}, "REASON_MISSING"),
    ({"schema": gen.METRIC_SCHEMA, "metric": "x", "status": "PROBABLY"},
     "STATUS_UNKNOWN"),
    ({"schema": gen.METRIC_SCHEMA, "status": "MEASURED", "value": 1},
     "METRIC_UNNAMED"),
    ({"schema": gen.METRIC_SCHEMA, "metric": "x", "status": "ESTIMATED",
      "value": 1}, "ESTIMATED_IN_FINAL"),
    ({"schema": gen.METRIC_SCHEMA, "metric": "x", "status": "DERIVED",
      "value": 1}, "DERIVED_WITHOUT_FORMULA"),
    (_measured(source={"path": "a.rpt"}, **{}), None),  # digest absent is legal
])
def test_negative_a_record_that_cannot_support_its_sentence_is_refused(
        tmp_path, record, code):
    rc, result = gen.generate(_corpus(tmp_path, record))
    if code is None:
        assert rc == gen.RC_OK, result
        return
    assert rc == gen.RC_REFUSED, result
    assert result["code"] == code, result
    assert result["marker"] == "[REFUSE]"


def test_negative_a_measured_record_with_no_source_is_refused(tmp_path):
    rec = _measured()
    del rec["source"]
    rc, result = gen.generate(_corpus(tmp_path, rec))
    assert (rc, result["code"]) == (gen.RC_REFUSED, "MEASURED_WITHOUT_SOURCE")


def test_negative_a_malformed_source_digest_is_refused(tmp_path):
    """A digest that cannot be compared reads as one that was checked."""
    rec = _measured()
    rec["source"]["sha256"] = "deadbeef"
    rc, result = gen.generate(_corpus(tmp_path, rec))
    assert (rc, result["code"]) == (gen.RC_REFUSED, "SOURCE_DIGEST_MALFORMED")


@pytest.mark.parametrize("field", gen.COLLAPSED_SCALAR_FIELDS)
def test_negative_a_collapsed_scalar_is_refused_for_existing(tmp_path, field):
    """One combined figure is a proxy for the property and not the property —
    and it is the figure that gets quoted."""
    rc, result = gen.generate(_corpus(tmp_path, _measured(**{field: 0.9})))
    assert (rc, result["code"]) == (gen.RC_REFUSED, "COLLAPSED_SCALAR")


def test_negative_a_metric_may_not_squat_the_reports_own_claim_namespace(tmp_path):
    rc, result = gen.generate(_corpus(
        tmp_path, _measured(metric="report.coverage.total")))
    assert (rc, result["code"]) == (gen.RC_REFUSED, "RESERVED_CLAIM_ID")


def test_negative_two_different_facts_under_one_citation_are_refused(tmp_path):
    """A citation that resolves to two numbers binds a sentence to neither."""
    one = _measured(value=-0.1)
    two = _measured(value=-0.2)
    rc, result = gen.generate(_corpus(tmp_path, one, two))
    assert (rc, result["code"]) == (gen.RC_REFUSED, "CLAIM_ID_COLLISION")


def test_an_identical_duplicate_record_is_not_a_collision(tmp_path):
    """The same fact recorded twice is still one fact. Refusing it would make
    the gate depend on how a corpus was assembled."""
    rc, result = gen.generate(_corpus(tmp_path, _measured(), _measured()))
    assert rc == gen.RC_OK
    assert result["coverage"]["total"] == 1


# ---------------------------------------------------------------- vacuous

def test_vacuous_absent_input_is_rc2_with_a_marker(tmp_path):
    """A gate whose declared invocation exits 2 on absent input can never fail;
    this repository shipped that twice. rc=2 AND a printed marker, never rc=0
    and never rc=1."""
    rc, result = gen.generate(tmp_path / "does-not-exist")
    assert rc == gen.RC_UNDETERMINED
    assert result["code"] == "NO_INPUT"
    assert result["marker"] == "[CANNOT CHECK]"


def test_vacuous_an_empty_corpus_is_a_DIFFERENT_answer_from_absent(tmp_path):
    """Hard rule: "I could not read it" and "I read it and it was empty" must
    never produce the same verdict."""
    empty = tmp_path / "empty"
    empty.mkdir()
    rc, result = gen.generate(empty)
    assert rc == gen.RC_UNDETERMINED
    assert result["code"] == "EMPTY_CORPUS"
    assert result["code"] != "NO_INPUT"
    assert str(empty) in result["detail"]


def test_vacuous_a_corpus_of_only_unparseable_files_is_not_reported_clean(tmp_path):
    root = tmp_path / "metrics"
    root.mkdir()
    (root / "broken.json").write_text("{not json", encoding="utf-8")
    rc, result = gen.generate(root)
    assert rc == gen.RC_UNDETERMINED
    assert result["code"] == "EMPTY_CORPUS"
    assert result["unreadable"], "the unreadable file was dropped silently"


def test_a_partly_unreadable_corpus_says_so_in_the_report(tmp_path):
    """A corpus that half-parsed must not be read as a corpus that measured
    half."""
    root = _corpus(tmp_path, _measured())
    (root / "broken.json").write_text("{not json", encoding="utf-8")
    rc, result = gen.generate(root)
    assert rc == gen.RC_OK
    assert "could not be read" in result["report_md"]
    assert "broken.json" in result["report_md"]


def test_vacuous_cli_writes_no_artefact_when_it_could_not_look(tmp_path):
    out = tmp_path / "report.md"
    rc = gen.main([str(tmp_path / "nowhere"), "--out", str(out)])
    assert rc == gen.RC_UNDETERMINED
    assert not out.exists(), "a report was written for a run that read nothing"


# ---------------------------------------------------------------- exit codes

def test_bad_invocation_is_not_a_design_finding():
    """rc=1 is a claim about silicon (§1). Arg errors must not borrow it."""
    # PPA_INTERFACES §1: 3 is BAD INVOCATION; 2 is UNDETERMINED ("I could not
    # look") and must never be mapped to PASS by a flow gate -- which is how a
    # caller that treats 2 as "nothing to check here" swallows a typo'd flag
    # and carries on green. This test previously asserted argparse's own 2,
    # which satisfied its stated intent (never 1) but pinned the wrong one of
    # the two remaining codes.
    rc = gen.main([])
    assert rc == 3, (
        f"a bad invocation must be rc=3, got {rc}. 2 there is UNDETERMINED "
        f"and a caller cannot tell it from an artefact that was not present.")


def test_cli_exit_codes_are_the_contract(tmp_path):
    good = _corpus(tmp_path, _measured())
    assert gen.main([str(good), "--out", str(tmp_path / "r.md"),
                     "--claims", str(tmp_path / "c.json")]) == gen.RC_OK
    bad = _corpus(tmp_path / "bad", _measured(**{"score": 1.0}))
    assert gen.main([str(bad)]) == gen.RC_REFUSED
    assert gen.main([str(tmp_path / "gone")]) == gen.RC_UNDETERMINED


# ---------------------------------------------------------------- mutation

def test_mutation_without_the_collapsed_scalar_list_the_fixture_passes(
        tmp_path, monkeypatch):
    """Revert the rule, and the negative fixture stops being caught.

    Run both ways in one test so the pair cannot drift apart: the assertion is
    not "the fixture is red" but "the fixture is red BECAUSE of this rule".
    """
    corpus = _corpus(tmp_path, _measured(**{"score": 0.9}))
    rc_with, result = gen.generate(corpus)
    assert (rc_with, result["code"]) == (gen.RC_REFUSED, "COLLAPSED_SCALAR")

    monkeypatch.setattr(gen, "COLLAPSED_SCALAR_FIELDS", ())
    rc_without, _ = gen.generate(corpus)
    assert rc_without == gen.RC_OK, (
        "the fixture is refused by something other than the rule under test")


def test_mutation_without_the_reason_requirement_a_hole_ships(
        tmp_path, monkeypatch):
    corpus = _corpus(tmp_path, {"schema": gen.METRIC_SCHEMA,
                                "metric": "power.total_mw",
                                "status": "NOT_MEASURED"})
    assert gen.generate(corpus)[1]["code"] == "REASON_MISSING"

    monkeypatch.setattr(gen, "STATUS_REQUIRES_REASON", ())
    rc, result = gen.generate(corpus)
    assert rc == gen.RC_OK
    # and this is exactly what the rule buys: a report with a labelled hole.
    assert "no reason recorded" in result["report_md"]


def test_mutation_treating_empty_as_readable_would_report_nothing_as_clean(
        tmp_path, monkeypatch):
    """The vacuous rule, mutated. With the empty-corpus arm removed the run
    would produce a report over zero records and exit 0 — the shape
    PPA_INTERFACES.md §7 says this repository has shipped twice."""
    empty = tmp_path / "empty"
    empty.mkdir()
    assert gen.generate(empty)[0] == gen.RC_UNDETERMINED

    monkeypatch.setattr(gen, "load_metrics",
                        lambda root: ([_measured()], []))
    assert gen.generate(empty)[0] == gen.RC_OK


# ---------------------------------------------------------------- schema

def test_the_generated_claims_document_validates_against_the_shipped_schema(
        tmp_path):
    jsonschema = pytest.importorskip(
        "jsonschema", reason="validated here when available; the program itself "
                             "never imports it, so a shipped gate does not "
                             "depend on it")
    schema_path = (pathlib.Path(__file__).resolve().parents[2]
                   / "schemas" / "ppa" / "claims.v1.schema.json")
    assert schema_path.exists(), f"{schema_path} is not shipped"
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    rc, result = gen.generate(_corpus(tmp_path, _measured(), _not_measured()))
    assert rc == gen.RC_OK
    jsonschema.validate(result["claims_doc"], schema)
