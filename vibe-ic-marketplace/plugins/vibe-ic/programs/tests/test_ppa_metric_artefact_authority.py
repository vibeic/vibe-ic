#!/usr/bin/env python3
"""CLASS 1: two artefacts of one tool, one identity, two numbers.

`PPA measurement coverage`, pointed at a real corpus for the first time in
v1.11.69, refused `route.wirelength.um` (16511.0 from `openroad.log`, 16522
from `openroad.metrics.json`) and `route.via.count` (4151 vs 4159) as
CONFLICTING_RECORD. Its refusal said settling it "is a declared authority
decision (`_ppa/contract.py`), never an index's" -- and `_ppa/contract.py`
carried no such declaration, so nothing settled it and the conflict was
permanent. MEASURED over 12 real run trees on this host with the shipped
producers: 17 records refused, on exactly three metrics, always these two
artefacts.

WHICH ARTEFACT IS AUTHORITATIVE IS A MEASUREMENT, NOT A PREFERENCE
=================================================================
`routed.def` is the database that ships. Counting via placements in it:

    openroad.metrics.json (last)  ==  routed.def   10 of 10 uncontaminated runs
    openroad.log          (last)  ==  routed.def    6 of 10, and 0 of the 4
                                                   runs where the two disagree

The mechanism is printed in the log: `PNR_STAGE: postroute_antenna_repair`
inserts a diode and calls detailed_route AGAIN, and that re-route appends to
the metrics JSON while printing no `Total wire length` summary to the log. On
`_tim_priv/run_base`, `routed_preantenna.def` carries 1944 via placements --
the log's number -- and `routed.def` carries 1951, the JSON's.

The direction is NOT uniform, which is why the rule cannot be "take the larger":
one run moves 824556 -> 821064 and another 16511 -> 16522.

WHAT THESE TESTS PROTECT
========================
1. The declaration exists, is opt-in BY NAME, and states its reason.
2. A metric OUTSIDE it is still emitted twice and still refused -- the fix must
   not become a blanket "last artefact wins".
3. The overridden reading is NOT DELETED. Its value, artefact and hash survive
   on the winner, because a resolution that made the loser vanish would destroy
   the evidence that there was ever a question.
"""
import pathlib
import sys

import pytest

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from _ppa import contract as C                    # noqa: E402
from _ppa import metrics as M                     # noqa: E402
from _ppa.backends import openroad as oro         # noqa: E402

#: The two figures the router prints, and the shape around them. Values chosen
#: to be the corpus's own: the log's last total is 16511/4151 and the JSON's
#: last entry is 16522/4159.
LOG = """\
OpenROAD 26Q3-1535-g543c33894f
PNR_STAGE: detailed_route
[INFO DRT-0195] Start 3rd optimization iteration.
Total wire length = 16700 um.
Total number of vias = 4200.
[INFO DRT-0195] Start 4th optimization iteration.
Total wire length = 16511 um.
Total number of vias = 4151.
[INFO DRT-0267] cpu time = 00:02:08, elapsed time = 00:00:19
[WARNING DRT-0701] Post-route verification found 1 violation(s) that the routing loop did not report (0 in-loop). The published result is the verified one.
PNR_STAGE: postroute_antenna_repair
[INFO GRT-0015] Inserted 1 diodes.
[INFO DRT-0178] Init guide query.
[INFO DRT-0501] Runtime: 3.07s
"""

#: An APPEND LOG with duplicate keys, exactly as `openroad -metrics` writes it:
#: the first block is the router's own pass, the second is the re-route that
#: the antenna repair triggered. The last entry is the database that ships.
METRICS_JSON = """\
{
 "detailedroute__route__drc_errors": 0,
 "detailedroute__route__wirelength": 16511,
 "detailedroute__route__vias": 4151,
 "detailedroute__route__drc_errors": 1,
 "detailedroute__route__wirelength": 16522,
 "detailedroute__route__vias": 4159
}
"""

_SETTLED = ("route.wirelength.um", "route.via.count",
            "route.drc.violation.count")


def _run(tmp_path):
    d = tmp_path / "pnr"
    d.mkdir()
    (d / "openroad.log").write_text(LOG)
    (d / "openroad.metrics.json").write_text(METRICS_JSON)
    return d


def _by(records, metric):
    return [r for r in records
            if r["metric"] == metric and r["status"] == "MEASURED"
            and (r["scope"] or {}).get("stage") == "detailed_route"]


# ── NEGATIVE: what must come out RED if the producer change is reverted ─────

def test_the_settled_metrics_no_longer_refuse(tmp_path):
    """The whole point, at the seam that did the refusing.

    Before the change these three reached `MetricIndex` twice each with
    different values and it refused the second every time.
    """
    out = oro.parse_run(_run(tmp_path))
    index = M.MetricIndex()
    refused = []
    for rec in out.records:
        try:
            index.add(rec)
        except M.MetricError as exc:
            refused.append((exc.code, rec["metric"]))
    assert refused == [], refused
    # NOT VACUOUS: the three really are present and really are the JSON's
    # numbers, so this cannot pass by the records having disappeared.
    assert [_by(out.records, m)[0]["value"] for m in _SETTLED] \
        == [16522.0, 4159, 1]


def test_the_unsettled_run_still_conflicts(tmp_path):
    """The positive control, and it is the important one.

    If `apply_authority=False` also came back clean, this fixture would have
    stopped exercising the conflict and every assertion above would be green
    over nothing.
    """
    out = oro.parse_run(_run(tmp_path), apply_authority=False)
    index = M.MetricIndex()
    refused = []
    for rec in out.records:
        try:
            index.add(rec)
        except M.MetricError as exc:
            refused.append((exc.code, rec["metric"]))
    assert sorted(m for c, m in refused) == sorted(_SETTLED), refused
    assert {c for c, _ in refused} == {"CONFLICTING_RECORD"}


def test_the_overridden_reading_is_kept_and_named(tmp_path):
    """NOTHING IS DELETED. A resolution that made the loser vanish would
    destroy the evidence that there was ever a question, which is the whole
    objection to a parser picking one."""
    out = oro.parse_run(_run(tmp_path))
    rec = _by(out.records, "route.via.count")[0]
    assert rec["source"]["kind"] == "metrics_json"
    lost = rec["source"]["overridden_by_authority"]
    assert len(lost) == 1
    assert lost[0]["value"] == 4151
    assert lost[0]["kind"] == "log"
    assert lost[0]["sha256"].startswith("sha256:")
    assert lost[0]["path"].endswith("openroad.log")
    auth = rec["source"]["authority"]
    assert auth["declared_in"] == "_ppa/contract.py:METRIC_ARTEFACT_AUTHORITY"
    assert auth["order"] == ["metrics_json", "log"]
    # A resolution with no stated reason is an unexplained overwrite.
    assert "routed.def" in auth["reason"] or "published result" in auth["reason"]
    # and it is announced in the diagnostics, not only buried in a record
    assert any(d.get("code") == "METRIC_AUTHORITY_RESOLVED"
               for d in out.diagnostics)


def test_a_metric_outside_the_declaration_is_still_refused(tmp_path):
    """OPT-IN BY NAME. The failure mode this guards is the fix quietly becoming
    "whichever artefact is read last wins", which would settle conflicts nobody
    ruled on -- including ones where the log is right."""
    assert set(C.METRIC_ARTEFACT_AUTHORITY) == set(_SETTLED), (
        "a metric was added to the declaration without a test saying why")
    a = {"schema": "vibeic.ppa.metric.v1", "metric": "route.wirelength.by_layer.um",
         "status": "MEASURED", "value": 1.0, "unit": "um",
         "scope": {"stage": "detailed_route", "tool": "openroad"},
         "source": {"path": "x/openroad.log", "sha256": "sha256:" + "a" * 64,
                    "kind": "log"}}
    b = dict(a, value=2.0,
             source=dict(a["source"], path="x/openroad.metrics.json",
                         sha256="sha256:" + "b" * 64, kind="metrics_json"))
    winner, overridden = C.resolve_metric_conflict([a, b])
    assert winner is None and overridden == []


def test_an_unranked_artefact_kind_is_not_resolved():
    """`None` is not "last". A kind no declaration ranks cannot be resolved
    AGAINST -- there is no winner to pick -- so the conflict must stand rather
    than be settled by arrival order."""
    a = {"metric": "route.via.count", "value": 1,
         "source": {"kind": "metrics_json"}}
    b = {"metric": "route.via.count", "value": 2,
         "source": {"kind": "some_future_artefact"}}
    assert C.resolve_metric_conflict([a, b]) == (None, [])
    assert C.metric_authority_rank("route.via.count", "some_future_artefact") is None
    assert C.metric_authority_rank("route.via.count", None) is None
    assert C.metric_authority_rank("area.die_um2", "log") is None


def test_agreement_is_not_a_resolution():
    """Two artefacts stating the SAME number is corroboration. Resolving it
    would drop a corroborating source and report an override that never
    happened."""
    a = {"metric": "route.via.count", "value": 4159,
         "source": {"kind": "metrics_json"}}
    b = {"metric": "route.via.count", "value": 4159, "source": {"kind": "log"}}
    assert C.resolve_metric_conflict([a, b]) == (None, [])


def test_every_declared_metric_states_its_reason():
    """A declaration a reviewer cannot read is not a decision anyone made."""
    for metric in C.METRIC_ARTEFACT_AUTHORITY:
        reason = C.METRIC_AUTHORITY_REASON.get(metric, "")
        assert len(reason) > 80, (metric, reason)
    assert set(C.METRIC_AUTHORITY_REASON) == set(C.METRIC_ARTEFACT_AUTHORITY)


def test_a_reading_with_no_number_may_be_overridden_but_never_wins():
    """THE ONE WAY THIS TABLE COULD DELETE EVIDENCE, closed by name.

    An artefact that could not report a figure has not CONTRADICTED one that
    did. If rank alone decided, a `NOT_MEASURED` row from the top-ranked
    artefact would beat the only real measurement in the group and the number
    would vanish under the word "authority".
    """
    silent_winner_kind = {
        "metric": "route.via.count", "status": "NOT_MEASURED",
        "reason": "the figure is absent though the stage ran",
        "source": {"kind": "metrics_json"}}
    real_number = {"metric": "route.via.count", "status": "MEASURED",
                   "value": 4151, "source": {"kind": "log"}}
    winner, overridden = C.resolve_metric_conflict(
        [silent_winner_kind, real_number])
    assert winner is not None
    assert winner["value"] == 4151 and winner["source"]["kind"] == "log"
    assert [o["source"]["kind"] for o in overridden] == ["metrics_json"]

    # ...and when NOTHING carries a number there is nothing to settle.
    other_silence = dict(silent_winner_kind, source={"kind": "log"},
                         reason="a different silence")
    assert C.resolve_metric_conflict(
        [silent_winner_kind, other_silence]) == (None, [])


def test_the_overridden_silence_is_recorded_without_a_null_value(tmp_path):
    """The no-sentinel rule reaches into the provenance too: an overridden
    reading that carried no number carries a `reason` here, never `value:
    null`. The log in this fixture cannot read a DRC count, and the JSON can."""
    out = oro.parse_run(_run(tmp_path))
    rec = _by(out.records, "route.drc.violation.count")[0]
    lost = rec["source"]["overridden_by_authority"]
    assert len(lost) == 1 and lost[0]["kind"] == "log"
    assert lost[0]["status"] == "NOT_MEASURED"
    assert "value" not in lost[0]
    assert lost[0]["reason"]
