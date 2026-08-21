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
from _ppa import backends as BK
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
        index_records(index, recs, str(path), report)
    report["records"] = len(index)
    report["_index"] = index
    return report


def index_records(index: "M.MetricIndex", recs: List[Any], origin: str,
                  report: Dict[str, Any]) -> None:
    """Validate and index one producer's records, recording every refusal.

    ONE implementation for `--records` and `--backend` on purpose: a record
    extracted by driving a backend must face exactly the checks a record read
    from a file faces, or the CLI would have two standards for one shape and
    the looser one would be the one nobody tested.
    """
    for i, rec in enumerate(recs):
        try:
            index.add(rec)
        except M.MetricError as exc:
            report["refusals"].append({
                "path": origin, "record_index": i,
                "metric": rec.get("metric") if isinstance(rec, dict) else None,
                "code": exc.code, "message": exc.message,
            })


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


class _Parser(argparse.ArgumentParser):
    """`argparse` exits 2 on a usage error, and PPA_INTERFACES §1 gives 2 to
    UNDETERMINED — "I could not check". A misspelled flag is not a statement
    about the evidence; it is a bad invocation, which §1 numbers 3.

    `RC_BAD_INVOCATION` was defined in this file and never used, so every usage
    error here has been indistinguishable from "the input was unreadable" since
    the program landed. A caller switching on the exit code could not tell a
    typo from a run that opened its inputs and could not read them.
    """

    def error(self, message: str):                    # noqa: D102
        self.print_usage(sys.stderr)
        print(f"{self.prog}: error: {message}", file=sys.stderr)
        raise SystemExit(RC_BAD_INVOCATION)


def main(argv: Optional[List[str]] = None) -> int:
    ap = _Parser(
        description="Assemble PPA metric records into one validated bundle.")
    ap.add_argument("--records", nargs="+", metavar="PATH", default=None,
                    help="record documents, or directories of them")
    ap.add_argument("--expect", metavar="FILE", default=None,
                    help="the declared denominator, carried into the bundle")
    ap.add_argument("--backend", metavar="TOOL", default=None,
                    help="extract from a tool artefact via "
                         "_ppa/backends/TOOL.py; needs --from PATH. A backend "
                         "that cannot be driven exits 2 with its own reason, "
                         "never an empty bundle")
    ap.add_argument("--from", metavar="PATH", dest="from_path", default=None,
                    help="the artefact or run directory --backend reads")
    ap.add_argument("--stage", metavar="STAGE", default=None,
                    help="the scope stage a backend cannot derive from its "
                         "artefact (yosys: one transcript holds two)")
    ap.add_argument("--out", metavar="FILE", default=None,
                    help="write the bundle here")
    ap.add_argument("--json", metavar="FILE", default=None,
                    help="write the machine-readable report here")
    args = ap.parse_args(argv)

    if args.backend is not None:
        # THE SEAM. It DRIVES the backends that declare a driver and refuses,
        # with the module's own reason, for the ones that do not. It still
        # never emits an empty bundle for a tool nobody taught this system to
        # read: that is the defect the contract exists to remove.
        # ORDER MATTERS. "this tool has no backend" and "you forgot --from"
        # are both refusals, but only the first is a fact about this system,
        # and a caller who named a tool that does not exist is not helped by
        # being told which argument that tool would have wanted.
        try:
            BK.load(args.backend)
        except ImportError:
            print(f"[CANNOT CHECK] no backend module `_ppa/backends/"
                  f"{args.backend}.py`, so no record was extracted from any "
                  f"artefact. This is NOT an empty result — nothing looked. "
                  f"rc=2.", file=sys.stderr)
            return RC_UNDETERMINED
        try:
            driver = BK.driver_for(args.backend)
        except BK.BackendNotDrivable as exc:
            print(f"[CANNOT CHECK] backend `{args.backend}` cannot be driven "
                  f"from a path: {exc.reason} Drivable backends: "
                  f"{', '.join(BK.drivable()) or 'none'}. rc=2.",
                  file=sys.stderr)
            return RC_UNDETERMINED
        if not args.from_path:
            ap.error("--backend TOOL needs --from PATH: the artefact or run "
                     "directory to extract from. Without it there is nothing "
                     "to read, and a backend that read nothing must not "
                     "produce a record set at all.")
        missing = [k for k in BK.requirements(args.backend)
                   if not getattr(args, k, None)]
        if missing:
            ap.error(f"backend `{args.backend}` requires "
                     f"{', '.join('--' + k for k in missing)}: it will not "
                     f"guess a value that changes which fact a record states.")
        src = Path(args.from_path)
        if not src.exists():
            print(f"[CANNOT CHECK] {src}: no such artefact, so backend "
                  f"`{args.backend}` read nothing. rc=2.", file=sys.stderr)
            return RC_UNDETERMINED
        report = {"program": "ppa_metric_extract.py",
                  "inputs": [str(src)], "backend": args.backend,
                  "documents": [], "unreadable": [], "refusals": [],
                  "records": 0}
        index = M.MetricIndex()
        try:
            recs = driver(src, **{k: getattr(args, k, None)
                                  for k in BK.requirements(args.backend)})
        except Exception as exc:                     # noqa: BLE001 — reported
            print(f"[CANNOT CHECK] backend `{args.backend}` could not read "
                  f"{src}: {exc.__class__.__name__}: {exc}. Nothing was "
                  f"extracted, so nothing is claimed. rc=2.", file=sys.stderr)
            return RC_UNDETERMINED
        report["documents"].append({"path": str(src), "read": "OK",
                                    "records": len(recs)})
        index_records(index, recs, str(src), report)
        report["records"] = len(index)
        return _emit(args, report, index, n_docs=1, n_bad=0, expected=None)

    if not args.records:
        ap.error("give --records PATH [PATH ...] or --backend TOOL --from PATH")

    paths = [Path(p) for p in args.records]
    report = collect(paths)
    index: M.MetricIndex = report.pop("_index")
    expected = _expectations(Path(args.expect) if args.expect else None, report)
    n_docs = len(report["documents"])
    n_bad = len(report["unreadable"])
    return _emit(args, report, index, n_docs=n_docs, n_bad=n_bad,
                 expected=expected)


def _emit(args, report: Dict[str, Any], index: "M.MetricIndex",
          *, n_docs: int, n_bad: int, expected) -> int:
    """Print the summary, decide the rc, and write the artefacts."""
    n_read = n_docs - n_bad
    print(f"ppa_metric_extract: {n_docs} document(s) named, "
          f"{n_read} read, {n_bad} unreadable, "
          f"{report['records']} record(s) indexed, "
          f"{len(report['refusals'])} refused")

    rc = RC_OK
    if report["refusals"]:
        for r in report["refusals"]:
            print(f"[REFUSE] {r['path']} #{r['record_index']} "
                  f"{r['metric']!r}: {r['code']}: {r['message']}",
                  file=sys.stderr)
        rc = RC_REFUSED
    elif n_bad or n_docs == 0:
        for u in report["unreadable"]:
            print(f"[CANNOT CHECK] {u['path']}: {u['read']}", file=sys.stderr)
        if n_docs == 0:
            print("[CANNOT CHECK] no document was named or found under the "
                  "paths given, so no record set was assembled. An empty "
                  "bundle would read as a clean run. rc=2.", file=sys.stderr)
        rc = RC_UNDETERMINED

    doc = M.bundle(index, expected=expected)
    # THE FILE MUST BE AS HONEST AS THE EXIT CODE. A caller that opens the
    # bundle and not the exit code has to be able to see that some input was
    # unreadable, so the incompleteness travels IN the document.
    if report["unreadable"]:
        doc["inputs_unreadable"] = [
            {"path": u.get("path"), "read": u.get("read")}
            for u in report["unreadable"]]
    report["records_digest"] = doc["records_digest"]
    report["rc"] = rc
    # PPA_INTERFACES §1: a machine-readable code on every verdict, including
    # the ones a caller most needs to tell apart without parsing English.
    report["code"] = {RC_OK: "BUNDLE_WRITTEN",
                      RC_REFUSED: "RECORD_REFUSED",
                      RC_UNDETERMINED: ("NOTHING_TO_READ" if n_docs == 0
                                        else "INPUT_UNREADABLE")}[rc]

    # A bundle is written when at least one document was READ. It is never
    # written for rc=1, and -- since v1.11.33 -- never when NOTHING was read.
    #
    # The second case is the one that was wrong. `{"records": []}` from a run
    # where every input was unreadable is byte-identical to a run that read a
    # tree and found nothing, and rule 9 says those two must never reach a
    # caller as the same answer. The exit code was honest and the FILE was not,
    # and a downstream step that opens the file is the reader this contract is
    # written for.
    if args.out and rc != RC_REFUSED and n_read > 0:
        atomic_write_text(Path(args.out), cj.dumps(doc) + "\n",
                          encoding="utf-8")
        print(f"bundle -> {args.out}  {doc['records_digest']}")
    elif args.out and rc == RC_REFUSED:
        print(f"[REFUSE] no bundle written to {args.out}: the record set was "
              f"refused, and an artefact left behind would be picked up as if "
              f"it were one.", file=sys.stderr)
    elif args.out:
        print(f"[CANNOT CHECK] no bundle written to {args.out}: not one "
              f"document was read, so there is no record set — empty or "
              f"otherwise — to write. A bundle of zero records here would be "
              f"indistinguishable from a clean run that found nothing.",
              file=sys.stderr)
    if args.json:
        atomic_write_text(Path(args.json),
                          json.dumps(report, indent=2, sort_keys=True) + "\n",
                          encoding="utf-8")
    return rc


if __name__ == "__main__":
    sys.exit(main())
