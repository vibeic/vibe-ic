#!/usr/bin/env python3
"""Re-encode published metric records with the CURRENT producer's own rules.

WHY THIS EXISTS
===============
`ppa-crosslayer/records/trials/*/records_flat.json` was written at v1.11.66 by
a producer that has since been corrected three times. The numbers in it are
fine; the way they were WRITTEN DOWN is not, and `ppa_measurement_check`
refuses 54 of b000's 148 records for it. Measured across all 21 trials with a
record set: every one is affected (50-54 refused each), so this is the shape of
the whole campaign and not one bad trial.

    SCOPE_SENTINEL           62 findings  `"rc_corner": null` in `scope`.
                             `null == null`, so two rows that could not read
                             their RC corner compare as rows taken AT THE SAME
                             corner. Fixed in the producer at v1.11.69: an
                             unestablished axis is ABSENT, and the reason moves
                             to `scope_gaps`. The reasons are already in these
                             records -- the producer wrote them and then wrote
                             the null anyway.

    SAME_ARTEFACT_TWO_VALUES  8 findings  one section's three reported paths
                             all emitted as `*.worst_path_slack_ns` under one
                             scope. Fixed in the producer at v1.11.69
                             (`_path_scope`): each reported path carries its
                             own identity. These rows still carry the
                             `source.line` that tells them apart.

    CONFLICTING_RECORD        2 findings  `route.wirelength.um` 16511 (log) vs
                             16522 (metrics_json), `route.via.count` 4151 vs
                             4159. The authority that settles both was declared
                             -- with a measured reason -- in
                             `_ppa/contract.py`, and the openroad backend has
                             applied it since. These records predate that.

    CONFLICTING_RECORD        2 findings  `timing.setup.worst_slack_ns` 1.98
                             from `sta_mcorner_ocv.rpt` vs 3.58 from
                             `sta_spef_based.rpt`. NOT a defect in either
                             number: two sign-off analyses of one design, and
                             the derated one is the pessimistic one. Owner
                             ruling 2026-08-25 -- TWO FACTS -- carried by the
                             `sta_view` scope axis (`timing.sta_view_of`).

THE ARTEFACTS ARE GONE, AND THAT IS WHY THIS IS A RE-ENCODING AND NOT A REPARSE
==============================================================================
The run tree these records cite (`_jxlayer/run/trials/*`) no longer exists, and
none of the three STA reports survives anywhere on the host: 5664 candidate
`sta_*.rpt` files hashed, 0 matching the recorded digests. So the records
cannot be produced again from source, and every rule applied here takes its
input from the record itself -- the null it must drop, the `source.line` that
orders the paths, the `source.path` that names the artefact. Nothing is
inferred from anything that is not written down.

WHAT MAY NOT CHANGE, AND IS CHECKED
===================================
`verify()` refuses the migration unless:

  * every input record is present in the output, or is preserved VERBATIM in a
    winner's `source.overridden_by_authority` (the producer's own behaviour --
    an overridden reading is recorded beside the winner, never deleted);
  * no `(metric, status, value, unit, source.sha256, source.path, source.line)`
    fingerprint is added or altered. Only `scope`, `scope_gaps` and the
    authority bookkeeping under `source` may differ.

A migration that cannot prove both raises. Re-encoding published measurements
is exactly the act that has to be provable rather than asserted.
"""
from __future__ import annotations

import argparse
import collections
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from _ppa import contract as _contract          # noqa: E402
from _ppa import timing as _timing              # noqa: E402

Row = Dict[str, Any]

#: `source.kind` is a fact about which artefact the bytes came from, and the
#: two the declaration ranks are named by their own file shape. A path this
#: does not recognise gets NO kind, and `resolve_metric_conflict` then returns
#: NOT SETTLED rather than guessing -- the conflict stays for the index.
def artefact_kind_of(path: Optional[str]) -> Optional[str]:
    if not path:
        return None
    name = Path(str(path)).name.lower()
    if name.endswith(".metrics.json"):
        return "metrics_json"
    if name.endswith(".log"):
        return "log"
    return None


def _fingerprint(rec: Row) -> Tuple:
    """The part of a record this migration is FORBIDDEN to touch."""
    src = rec.get("source") or {}
    return (rec.get("metric"), rec.get("status"),
            json.dumps(rec.get("value"), sort_keys=True), rec.get("unit"),
            src.get("sha256"), src.get("path"), src.get("line"))


def _drop_sentinels(rec: Row) -> bool:
    """`null`/`""` out of `scope`, the reason into `scope_gaps`. v1.11.69's rule."""
    scope = rec.get("scope")
    if not isinstance(scope, dict):
        return False
    dead = [k for k, v in scope.items() if v is None or v == ""]
    for k in dead:
        del scope[k]
        if k in _timing._SCOPE_OMISSION_REASON:
            rec.setdefault("scope_gaps", {}).setdefault(
                k, _timing._SCOPE_OMISSION_REASON[k])
    return bool(dead)


def _add_declared_analysis(rec: Row) -> bool:
    """Separate the sign-off analyses a maintainer DECLARED to be separate.

    Gated by `_ppa/contract.LEGACY_DISTINCT_STA_ANALYSES` -- an allow-list of
    three artefact stems from two named campaigns -- and by the row naming the
    opensta backend as its parser. A stem outside the list gets nothing and its
    conflict stands, which is the difference between recording one ruling and
    inventing a rule that a report's NAME tells you what the report is.
    """
    src = rec.get("source") or {}
    if not str(src.get("parser", "")).endswith("opensta.py"):
        return False
    stem = Path(str(src.get("path") or "")).stem.strip().lower()
    if stem not in _contract.LEGACY_DISTINCT_STA_ANALYSES:
        return False
    scope = rec.get("scope")
    if not isinstance(scope, dict) or "sta_analysis" in scope:
        return False
    scope["sta_analysis"] = stem
    src["sta_analysis_declared_in"] = (
        "_ppa/contract.py:LEGACY_DISTINCT_STA_ANALYSES")
    return True


def _add_path_ordinals(rows: Sequence[Row]) -> int:
    """One reported path per row gets its own identity (v1.11.69 `_path_scope`).

    ORDINAL, NOT ENDPOINTS. `_path_scope` prefers the (startpoint, endpoint)
    pair, and these records kept only the `Startpoint:` line in `source.raw`;
    the endpoint is not recoverable. The ordinal is the branch that function
    already takes when the names cannot identify a path, and it carries the
    same caveat: it orders rows inside ONE document and is not an identity
    across documents. `source.line` is what it is computed from, so the order
    is the artefact's own, not this program's.
    """
    groups: Dict[Tuple, List[Row]] = collections.defaultdict(list)
    for rec in rows:
        if not str(rec.get("metric", "")).endswith(_timing._PATH_METRIC_SUFFIX):
            continue
        src = rec.get("source") or {}
        groups[(rec.get("metric"), src.get("sha256"), src.get("path"),
                json.dumps(rec.get("scope"), sort_keys=True))].append(rec)
    n = 0
    for _, group in groups.items():
        if len(group) < 2:
            continue
        for ordinal, rec in enumerate(
                sorted(group, key=lambda r: (r.get("source") or {}).get("line") or 0)):
            rec["scope"]["path_ordinal"] = ordinal
            n += 1
    return n


def _apply_declared_authority(rows: List[Row]) -> Tuple[List[Row], List[str]]:
    """Settle the conflicts `_ppa/contract.py` already ranked, its way.

    The loser is not deleted: it is recorded in full under the winner's
    `source.overridden_by_authority`, which is what the openroad backend does
    at emit time and what makes this reversible by reading.
    """
    notes: List[str] = []
    groups: Dict[Tuple, List[Row]] = collections.defaultdict(list)
    for rec in rows:
        groups[(rec.get("metric"),
                json.dumps(rec.get("scope"), sort_keys=True))].append(rec)
    dropped: set = set()
    for (metric, _), group in sorted(groups.items(), key=lambda kv: str(kv[0])):
        if len(group) < 2 or metric not in _contract.METRIC_ARTEFACT_AUTHORITY:
            continue
        for rec in group:
            kind = artefact_kind_of((rec.get("source") or {}).get("path"))
            if kind:
                rec.setdefault("source", {})["kind"] = kind
        winner, overridden = _contract.resolve_metric_conflict(group)
        if winner is None:
            continue
        keep = next((r for r in group
                     if (r.get("source") or {}).get("path")
                     == (winner.get("source") or {}).get("path")
                     and r.get("value") == winner.get("value")), None)
        if keep is None:                                     # pragma: no cover
            continue
        keep["source"]["overridden_by_authority"] = [
            {"path": (lost.get("source") or {}).get("path"),
             "sha256": (lost.get("source") or {}).get("sha256"),
             "kind": (lost.get("source") or {}).get("kind"),
             "status": lost.get("status"),
             **({"value": lost["value"]} if "value" in lost
                else {"reason": lost.get("reason")})}
            for lost in overridden]
        keep["source"]["authority"] = {
            "declared_in": "_ppa/contract.py:METRIC_ARTEFACT_AUTHORITY",
            "order": list(_contract.METRIC_ARTEFACT_AUTHORITY[metric]),
            "reason": _contract.METRIC_AUTHORITY_REASON[metric]}
        for rec in group:
            if rec is not keep:
                dropped.add(id(rec))
        notes.append(
            "METRIC_AUTHORITY_RESOLVED %s: kept %s, overrode %d reading(s)"
            % (metric, (keep.get("source") or {}).get("kind"), len(overridden)))
    return [r for r in rows if id(r) not in dropped], notes


def verify(before: Sequence[Row], after: Sequence[Row]) -> None:
    """Raise unless every measurement survived unchanged. See the header."""
    kept = collections.Counter(_fingerprint(r) for r in after)
    preserved: collections.Counter = collections.Counter()
    for rec in after:
        for lost in ((rec.get("source") or {}).get("overridden_by_authority")
                     or []):
            preserved[(rec.get("metric"), lost.get("status"),
                       json.dumps(lost.get("value"), sort_keys=True),
                       rec.get("unit"), lost.get("sha256"),
                       lost.get("path"), None)] += 1
    missing = []
    for fp, n in collections.Counter(_fingerprint(r) for r in before).items():
        if kept[fp] >= n:
            continue
        loose = (fp[0], fp[1], fp[2], fp[3], fp[4], fp[5], None)
        if preserved[loose] >= n - kept[fp]:
            continue
        missing.append(fp)
    if missing:
        raise AssertionError(
            "%d measurement(s) neither present nor recorded as overridden: %s"
            % (len(missing), missing[:3]))
    invented = [fp for fp in kept if fp not in
                collections.Counter(_fingerprint(r) for r in before)]
    if invented:
        raise AssertionError("%d measurement(s) INVENTED: %s"
                             % (len(invented), invented[:3]))


def migrate(records: Sequence[Row]) -> Tuple[List[Row], List[str]]:
    """The whole re-encoding, verified before it is returned."""
    before = json.loads(json.dumps(list(records)))
    rows = json.loads(json.dumps(list(records)))
    sentinels = sum(1 for r in rows if _drop_sentinels(r))
    views = sum(1 for r in rows if _add_declared_analysis(r))
    ordinals = _add_path_ordinals(rows)
    rows, notes = _apply_declared_authority(rows)
    verify(before, rows)
    return rows, [
        "dropped a null/empty scope key on %d record(s); the reason is in "
        "scope_gaps" % sentinels,
        "separated %d record(s) by the DECLARED sign-off analysis "
        "(_ppa/contract.LEGACY_DISTINCT_STA_ANALYSES)" % views,
        "gave %d colliding worst-path row(s) their own path_ordinal" % ordinals,
    ] + notes


#: THE SAME RECORDS LIVE IN THREE CONTAINERS PER TRIAL, and migrating one of
#: them is worse than migrating none: the trial would then state a scope two
#: ways and a reader could not tell which is current. Measured on b000 --
#: `records_flat.json` 148 rows, `candidates.json` 148 (embedded under
#: `candidates[*].metrics`), `timing_records.json` 56 (under `rows`, with a
#: parallel `row_digests`) -- and all three carry the same 62 null scope keys.
def migrate_document(doc: Any) -> Tuple[Any, List[str], int, int]:
    """Migrate whichever of the three shapes `doc` is. Returns (doc, notes, before, after)."""
    if isinstance(doc, list):
        rows, notes = migrate(doc)
        return rows, notes, len(doc), len(rows)
    if isinstance(doc, dict) and isinstance(doc.get("rows"), list):
        before = len(doc["rows"])
        rows, notes = migrate(doc["rows"])
        doc["rows"] = rows
        doc["row_count"] = len(rows)
        # The identities are derived from the rows; leaving the old ones would
        # make every digest name a document that no longer exists.
        if "row_digests" in doc:
            doc["row_digests"] = [_timing.row_digest(r) for r in rows]
            notes.append("recomputed %d row_digest(s)" % len(rows))
        return doc, notes, before, len(rows)
    if isinstance(doc, dict) and isinstance(doc.get("candidates"), list):
        notes: List[str] = []
        before = after = 0
        for cand in doc["candidates"]:
            metrics = cand.get("metrics")
            if not isinstance(metrics, list):
                continue
            before += len(metrics)
            rows, ns = migrate(metrics)
            cand["metrics"] = rows
            after += len(rows)
            notes.extend(ns)
        return doc, notes, before, after
    raise SystemExit("unrecognised document shape: not a record list, "
                     "not `rows`, not `candidates`")


def main(argv: Optional[Sequence[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("records", nargs="+", type=Path)
    ap.add_argument("--write", action="store_true",
                    help="rewrite each file in place (default: report only)")
    a = ap.parse_args(argv)
    for path in a.records:
        doc, notes, before, after = migrate_document(json.loads(path.read_text()))
        print("%s: %d -> %d record(s)" % (path, before, after))
        for n in notes:
            print("   " + n)
        if a.write:
            path.write_text(json.dumps(doc, indent=1, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":                                   # pragma: no cover
    raise SystemExit(main())
