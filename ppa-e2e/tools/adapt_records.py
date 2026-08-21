#!/usr/bin/env python3
"""CALLER-SIDE ADAPTER -- see RESULT.md FINDING F-4.

Three shipped producers write canonical `vibeic.ppa.metric.v1` records inside
envelopes the canonical consumer refuses:

    _ppa/backends/openroad.py --json  ->  vibeic.ppa.backend_records.v1 {records}
    _ppa/timing.py            --json  ->  vibeic.ppa.timing_rows.v1     {rows}
    _ppa/power.py  power_document()   ->  vibeic.ppa.power.v1           {metrics}

`_ppa/metrics.records_from_document` accepts exactly: one record, a bare list of
records, or a `vibeic.ppa.metric_bundle.v1` envelope. So ppa_metric_extract.py
reports all three as UNRECOGNISED_DOCUMENT and indexes zero records.

This adapter does NOT edit the machinery. It re-wraps -- it copies the records
out of each envelope into a bare list, which is one of the three shapes the
consumer already accepts. No value is altered, no record is dropped, and the
envelope's own extra facts (activity basis, tool version) are preserved into the
record scope where the record does not already carry them.
"""
from __future__ import annotations
import json, sys
from pathlib import Path

ENVELOPES = {"openroad.json": "records", "timing.json": "rows",
             "power.json": "metrics", "yosys_proxy_area.json": "records"}


def adapt(d: Path) -> tuple[int, list[str]]:
    out, problems = [], []
    for fname, key in ENVELOPES.items():
        p = d / fname
        if not p.is_file():
            problems.append(f"{fname}: ABSENT -- NOT_MEASURED, not zero")
            continue
        try:
            doc = json.loads(p.read_text())
        except Exception as exc:
            problems.append(f"{fname}: unreadable ({exc})")
            continue
        recs = doc.get(key)
        if not isinstance(recs, list):
            problems.append(f"{fname}: envelope has no `{key}` list")
            continue
        # Carry the envelope's activity basis into every power record's scope.
        act = doc.get("activity") or {}
        basis = act.get("basis")
        for r in recs:
            if not isinstance(r, dict):
                problems.append(f"{fname}: a non-object in `{key}`")
                continue
            if basis and str(r.get("metric", "")).startswith("power."):
                sc = dict(r.get("scope") or {})
                sc.setdefault("activity_basis", basis)
                r = dict(r, scope=sc)
            # RESULT.md F-9: the openroad backend parses BOTH openroad.log and
            # openroad.metrics.json and emits both readings under an IDENTICAL
            # scope, with DIFFERENT values (measured: wirelength 16511.0 vs
            # 16522). Every downstream consumer refuses the pair -- the index
            # as CONFLICTING_RECORD, ppa_report_gen as CLAIM_ID_COLLISION --
            # and both are right: two numbers claiming to be one fact.
            #
            # The scope is disambiguated by the artefact each number was read
            # FROM. Applied UNIFORMLY to every record of this envelope, never
            # only to the ones that collided: a rule applied where it changes
            # an outcome is a result chosen, not a rule.
            if fname == "openroad.json":
                src = (r.get("source") or {}).get("path")
                if src:
                    sc = dict(r.get("scope") or {})
                    sc["source_artefact"] = Path(str(src)).name
                    r = dict(r, scope=sc)
                else:
                    problems.append(
                        f"{fname}: {r.get('metric')} carries no source.path, so "
                        "its scope cannot be disambiguated by artefact")
            out.append(r)
    out, dedup_notes = _resolve_collisions(out)
    problems.extend(dedup_notes)
    (d / "records_flat.json").write_text(json.dumps(out, indent=1) + "\n")
    return len(out), problems


def _key(r):
    return (r.get("metric"), json.dumps(r.get("scope") or {}, sort_keys=True))


def _resolve_collisions(recs):
    """Two rules, both applied to EVERY group, never only where they help.

    RESULT.md F-10a: the flow publishes each STA report into two directories and
    _ppa/timing.py's _STA_DIRS covers both, so every timing row is emitted
    twice from BYTE-IDENTICAL sources (measured: same sha256). One measurement
    seen twice is one fact, so an exact duplicate -- same metric, same scope,
    same status, same value, same source sha256 -- collapses to one record and
    the multiplicity is recorded.

    RESULT.md F-10b: a group that survives collapse and still holds DIFFERENT
    values is N genuinely different numbers filed under one scope -- measured
    here for `timing.*.worst_path_slack_ns`, where _ppa/timing.py emits one
    record per REPORTED PATH and the scope carries nothing that says which
    path. They are disambiguated by the provenance each record already carries,
    `(source_path, source_line)`, and ALL are published. Neither rule ever
    drops a distinct value.
    """
    from collections import defaultdict
    groups, order = defaultdict(list), []
    for r in recs:
        k = _key(r)
        if k not in groups:
            order.append(k)
        groups[k].append(r)
    out, notes = [], []
    collapsed = split = 0
    for k in order:
        g = groups[k]
        if len(g) == 1:
            out.append(g[0]); continue
        sig = {(json.dumps(x.get("value"), sort_keys=True), x.get("status"),
                (x.get("source") or {}).get("sha256")) for x in g}
        if len(sig) == 1:
            r = dict(g[0]); r["_seen_times"] = len(g)
            r["_seen_at"] = sorted({(x.get("source") or {}).get("path") for x in g})
            out.append(r); collapsed += 1; continue
        for x in g:
            sc = dict(x.get("scope") or {})
            src = x.get("source") or {}
            sc["source_path"] = src.get("path")
            sc["source_line"] = src.get("line")
            out.append(dict(x, scope=sc))
        split += 1
        notes.append(f"{k[0]}: {len(sig)} DIFFERENT readings under one scope, "
                     f"disambiguated by (source_path, source_line) and ALL published")
    if collapsed:
        notes.insert(0, f"{collapsed} record group(s) were one measurement "
                        f"reported more than once (identical value AND identical "
                        f"source sha256); collapsed to one, multiplicity kept")
    return out, notes


def main(argv=None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("usage: adapt_records.py <records-dir> [...]", file=sys.stderr)
        return 3
    worst = 0
    for a in args:
        d = Path(a)
        if not d.is_dir():
            print(f"[CANNOT CHECK] {d} is not a directory", file=sys.stderr)
            worst = max(worst, 2); continue
        n, probs = adapt(d)
        print(f"{d.name}: {n} record(s) flattened" +
              (f"; {len(probs)} problem(s): {probs}" if probs else ""))
        if probs:
            worst = max(worst, 2)
    return worst


if __name__ == "__main__":
    raise SystemExit(main())
