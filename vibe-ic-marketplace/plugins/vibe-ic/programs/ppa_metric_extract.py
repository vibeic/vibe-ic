#!/usr/bin/env python3
"""Assemble metric records into ONE validated, indexed, canonically-identified
bundle — and refuse the record set that cannot be one.

WHAT THIS DOES AND, MORE IMPORTANTLY, WHAT IT DOES NOT
======================================================
It does NOT parse a tool. PPA_INTERFACES §4: a backend module parses one tool's
output into canonical records and does nothing else, and the domain modules
(`_ppa/timing.py`, `_ppa/power.py`, `_ppa/area.py`) own the rules over those
records. This program owns the SHAPE — it reads records other producers wrote,
validates every one against `vibeic.ppa.metric.v1`, indexes them by
`(metric, scope)`, and writes the bundle with its digest.

That split is the reason adding a tool never changes a rule, and it is why
`--backend` below refuses instead of guessing: a tool nobody has written a
backend for produces NO records here, and this program says so with rc=2 rather
than emitting an empty bundle that a reader would take for a clean run.

THE THREE THINGS IT REFUSES, AND WHY EACH IS NOT COSMETIC
=========================================================
1. AN INVALID RECORD (rc=1). A record carrying `value: 0` under
   `status: NOT_MEASURED`, or a MEASURED number with no `source`, or a unit that
   contradicts its own metric name. Each of those reaches arithmetic downstream
   as a legitimate number.

2. A CONFLICT (rc=1). Two records claiming to be the same `(metric, scope)`.
   Keeping the last one picks a winner on file-read order. If they are really
   different facts their scope differs, and then they do not collide at all.

3. A DOCUMENT IT CANNOT READ (rc=2, with a marker). Not `[]`. This repository's
   rule 9 — "I could not read it" and "I read it and it was empty" must never
   produce the same verdict — and an assembler that yields an empty bundle for
   an unparseable input violates it silently, in the one artefact every later
   claim is built on.

EXIT CODES (PPA_INTERFACES §1)
==============================
    0  a bundle was written and every record in it is valid
    1  REFUSED — a record cannot support the fact printed on it, or two
       records claim to be the same fact
    2  UNDETERMINED — nothing to read, or a document that could not be read,
       or a backend that does not exist. Marked `[CANNOT CHECK]`.
    3  bad invocation

chip-AGNOSTIC, PDK-AGNOSTIC, vendor-AGNOSTIC: no design, PDK, process, vendor or
part literal appears here or can affect a verdict.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent))  # sibling imports resolve however this is invoked
from _atomic_artefact import write_text as atomic_write_text  # vibe-ic#1082 (helper from PR #1094)
from _ppa import cli_exit  # PPA_INTERFACES §1: argparse exits 2; a bad invocation is 3
from _ppa import canonical_json as cj
from _ppa import metrics as M

RC_OK = 0
RC_REFUSED = 1
RC_UNDETERMINED = 2
RC_BAD_INVOCATION = 3

#: What a `--records DIR` sweep considers a record document. Stated as a
#: constant so the denominator a run prints is the denominator the code used.
_RECORD_GLOB = "*.json"


def _iter_documents(paths: List[Path]) -> List[Path]:
    """Every document named, with directories expanded. A named path that does
    not exist is NOT skipped — it is returned so the caller can report it, for
    the same reason as everything else in this file."""
    found: List[Path] = []
    for p in paths:
        if p.is_dir():
            found.extend(sorted(q for q in p.glob(_RECORD_GLOB) if q.is_file()))
        else:
            found.append(p)
    return found


def collect(paths: List[Path]) -> Dict[str, Any]:
    """Read, validate and index. Returns a report; never raises for input."""
    report: Dict[str, Any] = {
        "program": "ppa_metric_extract.py",
        "inputs": [str(p) for p in paths],
        "documents": [], "unreadable": [], "refusals": [],
        "records": 0,
    }
    docs = _iter_documents(paths)
    index = M.MetricIndex()
    for path in docs:
        entry: Dict[str, Any] = {"path": str(path)}
        try:
            raw = path.read_text(encoding="utf-8")
        except FileNotFoundError:
            entry["read"] = "MISSING"
            report["unreadable"].append(entry)
            report["documents"].append(entry)
            continue
        except OSError as exc:
            entry["read"] = f"UNREADABLE: {exc}"
            report["unreadable"].append(entry)
            report["documents"].append(entry)
            continue
        try:
            doc = json.loads(raw)
        except json.JSONDecodeError as exc:
            entry["read"] = f"BAD_JSON: {exc}"
            report["unreadable"].append(entry)
            report["documents"].append(entry)
            continue
        try:
            recs = M.records_from_document(doc)
        except M.MetricError as exc:
            entry["read"] = f"{exc.code}: {exc.message}"
            report["unreadable"].append(entry)
            report["documents"].append(entry)
            continue
        entry["read"] = "OK"
        entry["records"] = len(recs)
        report["documents"].append(entry)
        for i, rec in enumerate(recs):
            try:
                index.add(rec)
            except M.MetricError as exc:
                report["refusals"].append({
                    "path": str(path), "record_index": i,
                    "metric": rec.get("metric") if isinstance(rec, dict) else None,
                    "code": exc.code, "message": exc.message,
                })
    report["records"] = len(index)
    report["_index"] = index
    return report


def _expectations(path: Optional[Path], report: Dict[str, Any]):
    """The declared denominator, if one was named.

    A named expectation file that cannot be read is UNDETERMINED and says so.
    It is never quietly dropped: dropping it turns a coverage claim into a
    claim about whatever happened to be measured.
    """
    if path is None:
        return None
    try:
        doc = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        report["unreadable"].append({"path": str(path),
                                     "read": f"EXPECTATIONS_UNREADABLE: {exc}"})
        return None
    if isinstance(doc, dict):
        doc = doc.get("expected")
    if not isinstance(doc, list):
        report["unreadable"].append({
            "path": str(path),
            "read": "EXPECTATIONS_MALFORMED: expected a list, or an object "
                    "with an `expected` list"})
        return None
    return doc


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Assemble PPA metric records into one validated bundle.")
    ap.add_argument("--records", nargs="+", metavar="PATH", default=None,
                    help="record documents, or directories of them")
    ap.add_argument("--expect", metavar="FILE", default=None,
                    help="the declared denominator, carried into the bundle")
    ap.add_argument("--backend", metavar="TOOL", default=None,
                    help="extract from a tool artefact via _ppa/backends/TOOL.py "
                         "(no backend exists yet: this exits 2, it does not "
                         "emit an empty bundle)")
    ap.add_argument("--out", metavar="FILE", default=None,
                    help="write the bundle here")
    ap.add_argument("--json", metavar="FILE", default=None,
                    help="write the machine-readable report here")
    args, _rc = cli_exit.parse_or_refuse(ap, argv)
    if args is None:
        return _rc

    if args.backend is not None:
        # THE SEAM, AND IT REFUSES. Emitting an empty bundle for a tool nobody
        # has taught this system to read is the exact defect the contract
        # exists to remove: the run produces an artefact, the artefact is
        # well-formed, and it asserts that nothing was found.
        try:
            __import__(f"_ppa.backends.{args.backend}")
        except ImportError:
            print(f"[CANNOT CHECK] no backend module `_ppa/backends/"
                  f"{args.backend}.py`, so no record was extracted from any "
                  f"artefact. This is NOT an empty result — nothing looked. "
                  f"rc=2.", file=sys.stderr)
            return RC_UNDETERMINED
        print(f"[CANNOT CHECK] backend `{args.backend}` exists but "
              f"ppa_metric_extract does not drive backends yet; the domain "
              f"lane that owns it does. rc=2.", file=sys.stderr)
        return RC_UNDETERMINED

    if not args.records:
        return cli_exit.refuse(ap.prog, "give --records PATH [PATH ...] or --backend TOOL")

    paths = [Path(p) for p in args.records]
    report = collect(paths)
    index: M.MetricIndex = report.pop("_index")
    expected = _expectations(Path(args.expect) if args.expect else None, report)

    n_docs = len(report["documents"])
    n_bad = len(report["unreadable"])
    print(f"ppa_metric_extract: {n_docs} document(s) named, "
          f"{n_docs - n_bad} read, {n_bad} unreadable, "
          f"{report['records']} record(s) indexed, "
          f"{len(report['refusals'])} refused")

    rc = RC_OK
    if report["refusals"]:
        for r in report["refusals"]:
            print(f"[REFUSE] {r['path']} #{r['record_index']} "
                  f"{r['metric']!r}: {r['code']}: {r['message']}",
                  file=sys.stderr)
        rc = RC_REFUSED
    elif n_bad or n_docs == 0 or report["records"] == 0:
        for u in report["unreadable"]:
            print(f"[CANNOT CHECK] {u['path']}: {u['read']}", file=sys.stderr)
        if n_docs == 0:
            print("[CANNOT CHECK] no document was named or found under the "
                  "paths given, so no record set was assembled. An empty "
                  "bundle would read as a clean run. rc=2.", file=sys.stderr)
        elif report["records"] == 0:
            # THE SAME SENTENCE ONE LEVEL IN. `n_docs == 0` was guarded
            # because an empty bundle reads as a clean run; a document that
            # WAS read and holds no record produces the identical empty
            # bundle, and until this branch existed it exited 0. Measured on
            # `e36d81c0a`: `--records <a bundle with "records": []>` printed
            # "1 document(s) named, 1 read, 0 record(s) indexed" and returned
            # 0. Nothing was extracted and nothing said so.
            print(f"[CANNOT CHECK] {n_docs} document(s) were read and NOT ONE "
                  f"record was indexed, so the bundle is empty. An empty "
                  f"bundle is indistinguishable from a clean extraction. "
                  f"rc=2 — this is NOT a pass.", file=sys.stderr)
        rc = RC_UNDETERMINED

    doc = M.bundle(index, expected=expected)
    report["records_digest"] = doc["records_digest"]
    report["rc"] = rc
    # PPA_INTERFACES §1: a machine-readable code on every verdict, including
    # the ones a caller most needs to tell apart without parsing English.
    report["code"] = {RC_OK: "BUNDLE_WRITTEN",
                      RC_REFUSED: "RECORD_REFUSED",
                      RC_UNDETERMINED: ("NOTHING_TO_READ" if n_docs == 0
                                        else "EMPTY_RECORD_SET"
                                        if report["records"] == 0 and not n_bad
                                        else "INPUT_UNREADABLE")}[rc]
    if args.out and rc != RC_REFUSED:
        # A bundle is written for rc 0 and rc 2 (the second is a real, honest,
        # partial set) and NEVER for rc 1: a refused record set must not leave
        # an artefact behind that a later step can pick up as if it were one.
        atomic_write_text(Path(args.out), cj.dumps(doc) + "\n",
                          encoding="utf-8")
        print(f"bundle -> {args.out}  {doc['records_digest']}")
    elif args.out:
        print(f"[REFUSE] no bundle written to {args.out}: the record set was "
              f"refused, and an artefact left behind would be picked up as if "
              f"it were one.", file=sys.stderr)
    if args.json:
        atomic_write_text(Path(args.json),
                          json.dumps(report, indent=2, sort_keys=True) + "\n",
                          encoding="utf-8")
    return rc


if __name__ == "__main__":
    sys.exit(main())
