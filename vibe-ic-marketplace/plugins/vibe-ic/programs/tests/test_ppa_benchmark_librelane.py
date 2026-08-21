#!/usr/bin/env python3
"""The LibreLane backend: it parses, and it can tell "nothing there" from
"nothing to say". vibe-ic#1121.

LibreLane is the opponent in the head-to-head this repository wants to publish,
so its numbers have to be read out of its OWN artefacts by code with no opinion
about who should win. Three properties are worth a test each, and all three were
measured against the tool rather than remembered:

  (1) THE NAMES ARE THE TOOL'S.  LibreLane 3.1.0.dev1 writes `metrics.json` and
      `metrics.csv`; there is no `final_summary_report.csv` in it -- that is
      OpenLane 1's name. A parser written from the remembered name finds
      nothing, and the whole of `test_a_directory_with_the_OLD_name_only...` is
      that finding nothing must not read as finding it clean.

  (2) THE METRIC NAME IS A SCOPE.  `timing__setup__ws__corner:X` is a per-corner
      reading and the bare `timing__setup__ws` is a CROSS-CORNER AGGREGATE.
      They are different metrics, and if the modifier stays buried in the name
      the fairness check cannot see the corner at all.

  (3) POWER IS VECTORLESS BY CONSTRUCTION.  Not by campaign choice. So the
      activity basis of a LibreLane arm can be DERIVED from the tool instead of
      being trusted from the record -- which is the difference between a
      declaration and evidence.

Nothing here asserts that any number is good. A backend with a threshold in it
would mean that adding a tool could change a rule.
"""
import json
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent.parent
PROGRAMS = PLUGIN / "programs"
sys.path.insert(0, str(PROGRAMS))

from _ppa.backends import librelane as L    # noqa: E402


# ---------------------------------------------------------------------------
# (2) the metric name is a scope
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name,base,mods", [
    ("timing__setup__ws__corner:nom_tt_025C_1v80",
     "timing__setup__ws", {"corner": "nom_tt_025C_1v80"}),
    ("power__total__corner:min_ff_n40C_1v95",
     "power__total", {"corner": "min_ff_n40C_1v95"}),
    ("design__instance__area", "design__instance__area", {}),
    ("timing__hold_vio__count__corner:A__pin:B",
     "timing__hold_vio__count", {"corner": "A", "pin": "B"}),
])
def test_metrics21_modifiers_are_split_out_of_the_name(name, base, mods):
    assert L.split_modifiers(name) == (base, mods)


def test_an_aggregate_and_a_per_corner_reading_do_not_look_the_same(tmp_path):
    """The bare name is the aggregate LibreLane's own `MetricAggregator` built
    across corners; the modified name is one corner. Dropping the distinction
    would let a cross-corner aggregate compare EQUAL to a per-corner number,
    which is the "same corner" defect arriving through a name that looks
    identical."""
    metrics = {"timing__setup__ws": -0.4,
               "timing__setup__ws__corner:CORNER_A": -0.1}
    p = tmp_path / "metrics.json"
    p.write_text(json.dumps(metrics), encoding="utf-8")
    got, path, digest = L.read_metrics(tmp_path)
    recs = {r["metric"]: r for r in L.to_records(
        got, source_path=path, source_sha256=digest)}
    assert recs["timing__setup__ws"]["scope"]["corner"] == "__AGGREGATE__"
    assert recs["timing__setup__ws__corner:CORNER_A"]["scope"]["corner"] \
        == "CORNER_A"
    assert (recs["timing__setup__ws"]["scope"]
            != recs["timing__setup__ws__corner:CORNER_A"]["scope"])


# ---------------------------------------------------------------------------
# (1) the names are the tool's, and absent is not clean
# ---------------------------------------------------------------------------
def test_metrics_json_is_read(tmp_path):
    (tmp_path / "metrics.json").write_text(
        json.dumps({"design__instance__area": 1234.5}), encoding="utf-8")
    got, path, digest = L.read_metrics(tmp_path)
    assert got == {"design__instance__area": 1234.5}
    assert path.name == "metrics.json"
    assert digest.startswith("sha256:") and len(digest) == 71


def test_metrics_csv_is_read_with_the_tools_own_header(tmp_path):
    (tmp_path / "metrics.csv").write_text(
        "Metric,Value\ndesign__instance__count,42\npower__total,0.0031\n",
        encoding="utf-8")
    got, path, _ = L.read_metrics(tmp_path)
    assert got == {"design__instance__count": 42, "power__total": 0.0031}
    assert path.name == "metrics.csv"


def test_a_csv_with_a_foreign_header_is_NOT_READABLE_not_empty(tmp_path):
    (tmp_path / "metrics.csv").write_text("metric;value\na;1\n", encoding="utf-8")
    with pytest.raises(L.NotReadable) as e:
        L.read_metrics(tmp_path)
    assert "Metric" in str(e.value)


def test_a_directory_with_the_OLD_openlane1_name_only_is_NOT_READABLE(tmp_path):
    """The defect this exists for, in its exact shape: a parser written from
    `final_summary_report.csv` finds no LibreLane metrics and, if it returned an
    empty mapping, every downstream check would report clean over a run it never
    read. Hard rule: "I could not read it" and "I read it and it was empty" must
    never produce the same verdict."""
    (tmp_path / "final_summary_report.csv").write_text(
        "design,area\nx,1\n", encoding="utf-8")
    with pytest.raises(L.NotReadable) as e:
        L.read_metrics(tmp_path)
    msg = str(e.value)
    assert "[CANNOT CHECK]" in msg
    for name in L.METRICS_FILENAMES:
        assert name in msg, "the refusal must NAME the population it searched"


def test_an_EMPTY_metrics_file_is_read_and_reports_zero_metrics(tmp_path):
    """The other half of the rule. This directory HAS a metrics file and it
    contains no metrics; that is a different fact from the test above and a
    caller is entitled to tell them apart."""
    (tmp_path / "metrics.json").write_text("{}", encoding="utf-8")
    got, path, _ = L.read_metrics(tmp_path)
    assert got == {}
    assert path.name == "metrics.json"
    assert L.to_records(got, source_path=path, source_sha256="sha256:" + "0" * 64) == []


def test_an_absent_directory_is_NOT_READABLE(tmp_path):
    with pytest.raises(L.NotReadable):
        L.read_metrics(tmp_path / "no_such_run")


def test_unparseable_json_is_NOT_READABLE_not_empty(tmp_path):
    (tmp_path / "metrics.json").write_text("{not json", encoding="utf-8")
    with pytest.raises(L.NotReadable) as e:
        L.read_metrics(tmp_path)
    assert "not JSON" in str(e.value)


# ---------------------------------------------------------------------------
# (3) power is vectorless by construction
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("metric", L.POWER_METRICS)
def test_every_power_record_carries_the_activity_basis_from_the_TOOL(
        tmp_path, metric):
    """The record does not get to declare this. LibreLane 3.1.0.dev1 contains
    zero occurrences of read_vcd / set_power_activity / SAIF and its only power
    producer is `report_power -corner <c>` with no activity file, so the basis
    is a property of the tool. Deriving it is the difference between evidence
    and a claim."""
    p = tmp_path / "metrics.json"
    p.write_text(json.dumps({metric + "__corner:C": 0.001}), encoding="utf-8")
    got, path, digest = L.read_metrics(tmp_path)
    rec = L.to_records(got, source_path=path, source_sha256=digest)[0]
    assert rec["scope"]["activity_basis"] == "vectorless"
    assert L.POWER_ACTIVITY_BASIS == "vectorless"


def test_a_non_power_metric_does_not_acquire_an_activity_basis(tmp_path):
    """The differential half: the key appears where it means something and
    nowhere else. A scope key on every record would make scope equality
    meaningless."""
    p = tmp_path / "metrics.json"
    p.write_text(json.dumps({"design__instance__area": 1.0}), encoding="utf-8")
    got, path, digest = L.read_metrics(tmp_path)
    rec = L.to_records(got, source_path=path, source_sha256=digest)[0]
    assert "activity_basis" not in rec["scope"]


# ---------------------------------------------------------------------------
# What was MEASURED, what was DERIVED, and what was neither
# ---------------------------------------------------------------------------
def test_a_bbox_is_not_an_area_and_the_derived_area_says_so(tmp_path):
    """`design__die__area` does not exist in this LibreLane; the die geometry is
    a bbox STRING. Emitting an area as MEASURED would state that the tool
    measured something it never reported."""
    p = tmp_path / "metrics.json"
    p.write_text(json.dumps({"design__die__bbox": "0 0 100 50"}),
                 encoding="utf-8")
    got, path, digest = L.read_metrics(tmp_path)
    recs = {r["metric"]: r for r in L.to_records(
        got, source_path=path, source_sha256=digest)}
    raw = recs["design__die__bbox"]
    assert raw["status"] == "INVALID"          # a string is not a number
    assert "value" not in raw
    derived = recs["design__die__area__DERIVED"]
    assert derived["status"] == "DERIVED"
    assert derived["value"] == 5000.0
    assert "urx - llx" in derived["formula"]
    assert derived["derived_from"] == {"design__die__bbox": "0 0 100 50"}


def test_no_record_ever_claims_the_metric_name_the_tool_does_not_emit(tmp_path):
    """A reader cross-checking us against LibreLane must find our metric names
    in LibreLane. A derived quantity is suffixed so it cannot be mistaken for
    one the tool wrote."""
    p = tmp_path / "metrics.json"
    p.write_text(json.dumps({"design__die__bbox": "0 0 10 10"}),
                 encoding="utf-8")
    got, path, digest = L.read_metrics(tmp_path)
    names = {r["metric"] for r in L.to_records(
        got, source_path=path, source_sha256=digest)}
    assert "design__die__area" not in names
    assert "design__die__area__DERIVED" in names


def test_a_null_value_is_NOT_MEASURED_and_carries_a_reason_not_a_zero(tmp_path):
    """No numeric sentinels. 0, -1 and "" never mean "not measured", and the
    record prints the literal status rather than omitting the row."""
    (tmp_path / "metrics.csv").write_text(
        "Metric,Value\ntiming__setup__ws,\n", encoding="utf-8")
    got, path, digest = L.read_metrics(tmp_path)
    rec = L.to_records(got, source_path=path, source_sha256=digest)[0]
    assert rec["status"] == "NOT_MEASURED"
    assert "value" not in rec
    assert rec["reason"]


def test_a_non_numeric_value_is_INVALID_and_is_not_coerced(tmp_path):
    (tmp_path / "metrics.csv").write_text(
        "Metric,Value\ndesign__instance__area,n/a\n", encoding="utf-8")
    got, _, _ = L.read_metrics(tmp_path)
    assert got == {"design__instance__area": "n/a"}


@pytest.mark.parametrize("raw", ["nan", "NaN", "inf", "-inf", "Infinity"])
def test_the_three_floats_that_are_not_JSON_do_not_become_numbers(tmp_path, raw):
    """`canonical_json` forbids NaN and Infinity because they are not JSON and
    they do not round-trip identically in two parsers. A CSV reader that
    coerced them would smuggle one into a document whose hash is taken."""
    (tmp_path / "metrics.csv").write_text(
        f"Metric,Value\npower__total,{raw}\n", encoding="utf-8")
    got, _, _ = L.read_metrics(tmp_path)
    assert isinstance(got["power__total"], str)


def test_every_record_names_the_tool_version_it_was_parsed_against(tmp_path):
    """All three facts in this module's docstring are facts about a VERSION, and
    a later LibreLane may differ. A record that did not say which version it
    read would make that undetectable."""
    (tmp_path / "metrics.json").write_text(
        json.dumps({"power__total": 1.0}), encoding="utf-8")
    got, path, digest = L.read_metrics(tmp_path)
    rec = L.to_records(got, source_path=path, source_sha256=digest)[0]
    assert rec["source"]["tool"] == "librelane"
    assert rec["source"]["tool_version"] == L.MEASURED_AGAINST_VERSION
    assert rec["source"]["sha256"] == digest
    assert rec["source"]["path"] == str(path)


def test_the_records_are_canonically_serializable(tmp_path):
    """Everything this module emits must survive the one serializer, because
    anything a document hashes goes through it. A float that is not JSON, or a
    non-string key, would raise here rather than in a campaign."""
    from _ppa import canonical_json as cj
    (tmp_path / "metrics.json").write_text(json.dumps({
        "power__total__corner:C": 0.0031,
        "design__die__bbox": "0 0 10 10",
        "design__instance__count": 42,
    }), encoding="utf-8")
    got, path, digest = L.read_metrics(tmp_path)
    recs = L.to_records(got, source_path=path, source_sha256=digest)
    assert cj.digest_of(recs).startswith("sha256:")


# ---------------------------------------------------------------------------
# A backend carries no policy
# ---------------------------------------------------------------------------
def _executable_source(path):
    """The module's source with every comment and every string literal removed.

    A prose check that reads comments is a check on prose. This module's
    docstring legitimately says the words "verdict" and "threshold" -- it is
    explaining that it has none -- so a substring search over the raw file
    measures the explanation instead of the code. Tokenising and dropping
    COMMENT and STRING leaves only what actually executes.
    """
    import io
    import tokenize
    out = []
    with open(path, "rb") as fh:
        for tok in tokenize.tokenize(fh.readline):
            if tok.type in (tokenize.COMMENT, tokenize.STRING):
                continue
            out.append(tok.string)
    return " ".join(out)


def test_the_backend_carries_no_threshold_and_no_verdict():
    """A backend that decided anything would mean that adding a tool changes a
    rule, and changing a rule would touch every tool."""
    body = _executable_source(PROGRAMS / "_ppa" / "backends" / "librelane.py")
    for word in ("PASS", "FAIL", "threshold", "limit", "is_clean", "verdict",
                 "refuse", "Refusal"):
        assert word not in body, (
            f"{word!r} appears in the backend's executable code; a backend "
            "parses and decides nothing")


def test_that_prose_check_would_have_missed_a_real_threshold():
    """The negative control for the test above. A check that only ever passes
    is a certificate, so this proves the tokeniser sees code the raw docstring
    scan would have been fooled by -- and that a REAL threshold would be
    caught."""
    body = _executable_source(PROGRAMS / "_ppa" / "backends" / "librelane.py")
    assert "POWER_ACTIVITY_BASIS" in body, "the tokeniser must see identifiers"
    assert "vectorless" not in body, "and must NOT see string literals"
    import io
    import tokenize
    planted = "def check(x):\n    threshold = 5\n    return x < threshold\n"
    toks = tokenize.generate_tokens(io.StringIO(planted).readline)
    seen = " ".join(t.string for t in toks
                    if t.type not in (tokenize.COMMENT, tokenize.STRING))
    assert "threshold" in seen
