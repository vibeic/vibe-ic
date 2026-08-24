#!/usr/bin/env python3
"""Re-encoding a published measurement must be provable, not asserted.

`_ppa/records_migrate` rewrites records that shipped -- the campaign's own
evidence. The only thing that makes that acceptable is that it CANNOT change a
number and cannot make one disappear, and that the program refuses itself when
it would. Every test here drives that refusal.
"""
from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest

_PROGRAMS = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_PROGRAMS))
from _ppa import contract as C            # noqa: E402
from _ppa import records_migrate as M     # noqa: E402
from _ppa import timing as T              # noqa: E402


def _rec(metric="timing.setup.worst_slack_ns", value=1.98, path="x.rpt",
         sha="sha256:aa", line=1, scope=None, parser="_ppa/backends/opensta.py"):
    return {"schema": "vibeic.ppa.metric.v1", "metric": metric,
            "status": "MEASURED", "value": value, "unit": "ns",
            "scope": dict(scope if scope is not None
                          else {"stage": "post_route_extracted",
                                "rc_corner": None, "check": "setup"}),
            "source": {"path": path, "sha256": sha, "line": line,
                       "parser": parser}}


# ── the sentinel rule (v1.11.69), applied to records that predate it ────────

def test_a_null_scope_key_becomes_an_absence_with_a_stated_reason():
    rows, _notes = M.migrate([_rec()])
    assert "rc_corner" not in rows[0]["scope"], "the null survived"
    assert rows[0]["scope_gaps"]["rc_corner"] == \
        T._SCOPE_OMISSION_REASON["rc_corner"]


def test_the_number_is_not_touched():
    rows, _ = M.migrate([_rec(value=1.98)])
    assert rows[0]["value"] == 1.98 and rows[0]["unit"] == "ns"


# ── the declared ruling, and its BOUNDARY ──────────────────────────────────

def test_a_declared_analysis_is_separated():
    rows, _ = M.migrate([_rec(path="phase3/stage3/sta/sta_mcorner_ocv.rpt")])
    assert rows[0]["scope"]["sta_analysis"] == "sta_mcorner_ocv"
    assert rows[0]["source"]["sta_analysis_declared_in"].endswith(
        "LEGACY_DISTINCT_STA_ANALYSES")


def test_an_undeclared_report_name_gets_NOTHING():
    """The boundary that stops this being 'a name tells you what a report is'.

    Two artefacts of one analysis must still be able to disagree, and a stem
    nobody declared must not quietly acquire an axis.
    """
    rows, _ = M.migrate([_rec(path="phase3/stage3/sta/sta_something_else.rpt")])
    assert "sta_analysis" not in rows[0]["scope"]
    assert "sta_mcorner_ocv" in C.LEGACY_DISTINCT_STA_ANALYSES   # anti-vacuity


def test_a_row_from_another_backend_is_not_touched_by_the_ruling():
    rows, _ = M.migrate([_rec(path="phase3/stage3/sta/sta_mcorner_ocv.rpt",
                              parser="_ppa/backends/openroad.py")])
    assert "sta_analysis" not in rows[0]["scope"]


# ── one reported path per row (v1.11.69 `_path_scope`) ─────────────────────

def test_colliding_worst_path_rows_are_ordered_by_the_line_they_came_from():
    base = {"stage": "post_route_extracted", "check": "hold", "clock": "clk"}
    rows, _ = M.migrate([
        _rec("timing.hold.worst_path_slack_ns", 0.34, line=190, scope=base),
        _rec("timing.hold.worst_path_slack_ns", 0.31, line=134, scope=base),
        _rec("timing.hold.worst_path_slack_ns", 0.33, line=162, scope=base)])
    by_line = {r["source"]["line"]: r["scope"]["path_ordinal"] for r in rows}
    assert by_line == {134: 0, 162: 1, 190: 2}


def test_a_lone_worst_path_row_gets_no_ordinal():
    """An ordinal on a row that collides with nothing is a scope key that
    means nothing, and it would make the row incomparable to a later one."""
    rows, _ = M.migrate([_rec("timing.hold.worst_path_slack_ns", 0.31)])
    assert "path_ordinal" not in rows[0]["scope"]


# ── declared authority: nothing is deleted ─────────────────────────────────

def test_the_overridden_reading_is_kept_beside_the_winner():
    scope = {"stage": "detailed_route", "tool": "openroad"}
    rows, notes = M.migrate([
        _rec("route.wirelength.um", 16511.0, path="a/openroad.log",
             sha="sha256:l", scope=scope, parser="_ppa/backends/openroad.py"),
        _rec("route.wirelength.um", 16522.0, path="a/openroad.metrics.json",
             sha="sha256:j", scope=scope, parser="_ppa/backends/openroad.py")])
    assert len(rows) == 1 and rows[0]["value"] == 16522.0
    lost = rows[0]["source"]["overridden_by_authority"]
    assert [x["value"] for x in lost] == [16511.0]
    assert rows[0]["source"]["authority"]["reason"] == \
        C.METRIC_AUTHORITY_REASON["route.wirelength.um"]
    assert any("METRIC_AUTHORITY_RESOLVED" in n for n in notes)


def test_an_unranked_artefact_leaves_the_conflict_standing():
    scope = {"stage": "detailed_route", "tool": "openroad"}
    rows, _ = M.migrate([
        _rec("route.wirelength.um", 16511.0, path="a/openroad.rpt",
             sha="sha256:r", scope=scope, parser="_ppa/backends/openroad.py"),
        _rec("route.wirelength.um", 16522.0, path="a/openroad.metrics.json",
             sha="sha256:j", scope=scope, parser="_ppa/backends/openroad.py")])
    assert len(rows) == 2, "an unrankable kind was settled anyway"


# ── the refusal that makes the whole thing acceptable ──────────────────────

def test_verify_refuses_a_changed_number():
    before = [_rec(value=1.98)]
    after = copy.deepcopy(before)
    after[0]["value"] = 2.98
    with pytest.raises(AssertionError):
        M.verify(before, after)


def test_verify_refuses_an_invented_record():
    before = [_rec(value=1.98)]
    with pytest.raises(AssertionError):
        M.verify(before, before + [_rec(value=9.99, sha="sha256:zz")])


def test_verify_refuses_a_vanished_record():
    before = [_rec(value=1.98), _rec(value=3.58, sha="sha256:bb")]
    with pytest.raises(AssertionError):
        M.verify(before, before[:1])


# ── the three container shapes one trial writes the same records into ──────

def test_every_container_shape_is_migrated_and_its_digests_follow():
    flat, _, b, a = M.migrate_document([_rec()])
    assert b == a == 1 and "rc_corner" not in flat[0]["scope"]

    doc, _, b, a = M.migrate_document(
        {"rows": [_rec()], "row_count": 1, "row_digests": ["sha256:stale"]})
    assert doc["row_digests"] == [T.row_digest(doc["rows"][0])]
    assert doc["row_digests"] != ["sha256:stale"]

    doc, _, b, a = M.migrate_document(
        {"candidates": [{"candidate_id": "b000", "metrics": [_rec()]}]})
    assert "rc_corner" not in doc["candidates"][0]["metrics"][0]["scope"]

    with pytest.raises(SystemExit):
        M.migrate_document({"nothing": "recognisable"})
