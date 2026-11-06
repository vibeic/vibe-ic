"""Select native metric readings by their declared report authority."""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Sequence, Tuple

from . import metrics as _metrics

from .canonical_json import digest_of

METRIC_ARTEFACT_AUTHORITY: Dict[str, Tuple[str, ...]] = {
    "route.wirelength.um": ("metrics_json", "log"),
    "route.via.count": ("metrics_json", "log"),
    "route.drc.violation.count": ("metrics_json", "log"),
}

METRIC_AUTHORITY_REASON = {
    "route.wirelength.um": (
        "openroad.metrics.json records EVERY detailed_route invocation, "
        "including the re-route that postroute_antenna_repair triggers; the log "
        "prints a `Total wire length` summary only for invocations that ran the "
        "full router loop. Measured on 10 run trees, the JSON's last entry is "
        "the routed.def that ships and the log's last total is a pre-repair "
        "state."),
    "route.via.count": (
        "Same mechanism as route.wirelength.um, and directly counted: on "
        "_tim_priv/run_base, routed_preantenna.def carries 1944 via placements "
        "(the log's number) and routed.def carries 1951 (the JSON's)."),
    "route.drc.violation.count": (
        "The tool says which is published: `[WARNING DRT-0701] Post-route "
        "verification found N violation(s) that the routing loop did not report "
        "(M in-loop). The published result is the verified one.` The log's "
        "summary is M; openroad.metrics.json carries N."),
}

def metric_authority_rank(metric: str, artefact_kind: Optional[str]) -> Optional[int]:
    """Where `artefact_kind` ranks for `metric`; None if nothing ranks it.

    None is not "last". A kind no declaration ranks cannot be resolved AGAINST
    -- there is no winner to pick -- and the caller must leave the conflict
    standing rather than choose whichever record happened to arrive first.
    """
    order = METRIC_ARTEFACT_AUTHORITY.get(metric)
    if not order or artefact_kind is None:
        return None
    try:
        return order.index(str(artefact_kind))
    except ValueError:
        return None

def resolve_metric_conflict(records: Sequence[Mapping[str, Any]]
                            ) -> Tuple[Optional[Dict[str, Any]],
                                       List[Dict[str, Any]]]:
    """Settle ONE identity's competing readings by declared artefact authority.

    `records` are canonical metric records that an index would refuse as
    CONFLICTING_RECORD: same metric, same scope, different values, different
    artefacts. Each must carry `source.kind` naming which artefact it was read
    from -- that is a fact about where the bytes came from, which a backend IS
    entitled to state.

    Returns `(winner, overridden)`, or `(None, [])` when this metric is not
    opted in, when fewer than two readings disagree, when any reading names a
    kind the declaration does not rank, or when NO reading carries a number.
    Every one of those is the same answer: NOT SETTLED -- leave the conflict
    for the index to refuse.

    A reading with no `value` may be OVERRIDDEN but can never WIN: an artefact
    that could not report a figure has not contradicted one that did.

    NOTHING IS DELETED. The overridden readings come back in full so the caller
    can record them beside the winner; a resolution that made the losing number
    vanish would destroy the evidence that there was ever a question, which is
    the whole objection to a parser picking one.
    """
    if len(records) < 2:
        return None, []
    metric = str(records[0].get("metric", ""))
    if metric not in METRIC_ARTEFACT_AUTHORITY:
        return None, []
    ranked: List[Tuple[int, Dict[str, Any]]] = []
    for rec in records:
        rank = metric_authority_rank(
            metric, (rec.get("source") or {}).get("kind"))
        if rank is None:
            return None, []
        ranked.append((rank, dict(rec)))
    # AGREEMENT IS ASKED WITH THE INDEX'S OWN PREDICATE, not a second copy of
    # it. Until v1.11.70 this compared `digest_of(value)`, which spells
    # `14246.0` and `14246` differently while `metrics.states_the_same_fact`
    # -- the function that decides whether the index REFUSES the pair --
    # compares them with `==` and calls them one measurement. So a group the
    # index had already accepted as corroboration arrived here, was declared a
    # conflict, and had a perfectly agreeing reading "overridden". MEASURED on
    # the 30 PnR run trees on this host: 5 of 22 collapsed groups were of that
    # kind, every one an integral float from the log against an int from the
    # JSON. One question, one reader.
    first = ranked[0][1]
    if all(_metrics.states_the_same_fact(first, rec) for _, rec in ranked[1:]):
        return None, []          # they agree: corroboration, not a conflict

    # ONLY A READING THAT CARRIES A NUMBER CAN WIN. An artefact that could not
    # report a figure has not CONTRADICTED one that did -- it has said nothing
    # -- and letting it win by rank would throw away the only measurement in
    # the group and call the result an authority decision. That is the one way
    # this table could delete evidence, so it is closed here rather than left
    # to each caller.
    bearers = [(rank, rec) for rank, rec in ranked if "value" in rec]
    if not bearers:
        return None, []
    bearers.sort(key=lambda pair: (pair[0], digest_of(pair[1].get("value"))))
    winner = bearers[0][1]
    return winner, [r for _, r in ranked if r is not winner]
