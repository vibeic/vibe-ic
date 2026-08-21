#!/usr/bin/env python3
"""The gate over a PPA record set: what was owed and was not measured, and the
comparison that must be refused instead of decided.

TWO QUESTIONS, AND THEY ARE THE SAME QUESTION SEEN TWICE
========================================================
--coverage   Against a DECLARED denominator, which expected measurements are
             present, which are honestly declared absent, and which are simply
             NOT THERE.
--compare    Given two records, may they be compared at all?

Both are the fourth invariant of the PPA contract (PPA_INTERFACES §2) applied at
a different scale. `0`, `-1` and `""` never mean "not measured" INSIDE a record;
an OMITTED ROW is that same lie one level up, where the sentinel is the reader's
own assumption that a report shows everything it was asked about. And a
comparison across differing scope is the lie one level up again: both numbers
are real, both are correctly recorded, and putting them side by side asserts a
relationship neither of them supports.

WHY AN OMITTED ROW IS rc=1 AND A DECLARED ABSENCE IS rc=2
=========================================================
    NOT_MEASURED, present, with a reason      the hole is VISIBLE.  rc=2
    no record at all                          the hole is INVISIBLE. rc=1

A run that measured six of nine things and says so has not passed — it is
UNDETERMINED, and rc=2 must never be mapped to PASS by a flow gate. A run that
measured six of nine things and publishes six rows has made a claim about the
other three by omission, and that is a finding about the record set. The whole
value of the distinction is that the second one is invisible to every reader
who does not have the denominator in front of them, which is why the
denominator is required and why this program refuses to compute coverage
without one rather than reporting a vacuous 100%.

THE COMPARISON REFUSAL IS THE POINT OF THE LANE
===============================================
Two records with the same `metric` and different `scope` are different facts:

    synthesis area              vs  post-route area
    vectorless power            vs  power off a VCD
    ss / 1.62 V / 125 C setup   vs  tt / 1.80 V / 25 C setup

Every pair above is two legitimate measurements, and in every pair the more
favourable one is the one somebody would rather quote. Both rows say the same
metric name, so nothing downstream can see which was used. This program answers
UNDETERMINED and prints the differing fields; it does not pick one, and it does
not name a winner even for a valid comparison unless the caller declares which
direction is better — that is domain policy (smaller area, MORE POSITIVE slack,
less power), and "lower is better" is wrong for slack and for frequency.

CORPUS MODE — THE THIRD QUESTION, WHICH IS THE FIRST TWO OVER A POPULATION
=========================================================================
`--coverage` and `--compare` name EXACT documents, so a bundle filed anywhere
the caller did not name was never measured. `--corpus DIR` runs the coverage
question over every metric bundle under DIR, resolved through
`_corpus_location` — the same seam `ppa_head_to_head_check` uses, so both
follow `$VIBE_IC_BENCHMARK_DATA` to a cloned corpus.

Bundles are selected by their DECLARED SCHEMA and never by filename: a record
under an unexpected name going unjudged is the defect this mode closes, and a
filename glob is a smaller version of that same defect.

AN EMPTY CORPUS IS rc=2 WITH THE ROOT NAMED. This program refuses to compute
coverage without a denominator precisely because a coverage number derived from
the records alone can only ever be 100%; a corpus mode that reported PASS over
zero bundles would have rebuilt that vacuous 100% one level up.

TWO BUNDLES CLAIMING ONE MEASUREMENT IS A CONFLICT. `MetricIndex.add` already
refuses two records for one `(metric, scope)` INSIDE a bundle. The corpus scan
applies the same identity ACROSS bundles and names both paths: taking the first
match would pick a winner on directory order, which is the exact thing
`CONFLICTING_RECORD` exists to prevent one level down.

`--corpus` with `--coverage` or `--compare` is rc=3, a bad invocation.

EXIT CODES (PPA_INTERFACES §1)
==============================
    0  every expected measurement is present and usable / the comparison holds
    1  REFUSED — an expected row is ABSENT from the set, or an ESTIMATE stands
       where a measurement was owed, or a record is invalid
    2  UNDETERMINED — a declared absence, an unreadable input, a missing
       denominator, or a comparison across differing scope. Always with a
       printed `[CANNOT CHECK]` / `[REFUSE]` marker, so a 2 can never be read
       as a silent skip.
    3  bad invocation, including --corpus given with --coverage or --compare

rc=2 IS NOT A PASS. A flow step that treats it as green has a gate that cannot
fail.

chip-AGNOSTIC, PDK-AGNOSTIC, vendor-AGNOSTIC: scope fields are carried and
compared as opaque values and are never interpreted.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

sys.path.insert(0, str(Path(__file__).resolve().parent))  # sibling imports resolve however this is invoked
import _ppa_corpus as corpus_seam  # one seam for all corpora
from _atomic_artefact import write_text as atomic_write_text  # vibe-ic#1082 (helper from PR #1094)
from _ppa import cli_exit  # PPA_INTERFACES §1: argparse exits 2; a bad invocation is 3
from _ppa import metrics as M

RC_OK = 0
RC_REFUSED = 1
RC_UNDETERMINED = 2
RC_BAD_INVOCATION = 3


class CannotCheck(Exception):
    """Input this program could not see. NEVER a finding about a design.

    Carries a `code` because PPA_INTERFACES §1 requires a machine-readable code
    on every verdict, and the verdicts that most need one are the ones a caller
    has to tell apart without parsing English: "the bundle is not there" and
    "the bundle is there and declares no denominator" are both rc=2 and they
    are different problems with different fixes.
    """

    def __init__(self, message: str, code: str = "CANNOT_CHECK"):
        super().__init__(message)
        self.message = message
        self.code = code


def _read_json(path: Path, what: str) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise CannotCheck(f"no such {what}: {path}", "INPUT_ABSENT")
    except OSError as exc:
        raise CannotCheck(f"{what} {path} could not be read: {exc}",
                          "INPUT_UNREADABLE")
    except json.JSONDecodeError as exc:
        raise CannotCheck(f"{what} {path} is not JSON: {exc}", "INPUT_BAD_JSON")


def _index_from(path: Path) -> Tuple[M.MetricIndex, List[Dict[str, Any]]]:
    """The record set at `path`, and any record it refused.

    A refused record is returned rather than raised so the caller can report
    ALL of them; one bad row must not hide the other nine.
    """
    doc = _read_json(path, "bundle")
    try:
        recs = M.records_from_document(doc)
    except M.MetricError as exc:
        raise CannotCheck(f"{path}: {exc.code}: {exc.message}", exc.code)
    index = M.MetricIndex()
    refusals: List[Dict[str, Any]] = []
    for i, rec in enumerate(recs):
        try:
            index.add(rec)
        except M.MetricError as exc:
            refusals.append({
                "record_index": i,
                "metric": rec.get("metric") if isinstance(rec, dict) else None,
                "code": exc.code, "message": exc.message})
    return index, refusals


def _expected_from(bundle_doc: Any, expect_path: Optional[Path]) -> List[Any]:
    """The denominator: from `--expect` if given, else from the bundle itself.

    If neither carries one, this raises. It does NOT fall back to "everything
    that happens to be in the set", which is the fallback that makes a coverage
    report agree with itself by construction and report 100% forever.
    """
    if expect_path is not None:
        doc = _read_json(expect_path, "expectation set")
        if isinstance(doc, dict):
            doc = doc.get("expected")
        if not isinstance(doc, list) or not doc:
            raise CannotCheck(
                f"{expect_path} carries no non-empty `expected` list, so "
                "there is no denominator to measure coverage against",
                "NO_EXPECTATION_SET")
        return doc
    if isinstance(bundle_doc, dict) and isinstance(bundle_doc.get("expected"),
                                                   list) and bundle_doc["expected"]:
        return bundle_doc["expected"]
    raise CannotCheck(
        "no expectation set: neither --expect nor the bundle declares what "
        "should have been measured. Coverage computed from the records alone "
        "can only ever be 100%, because the rows it would report missing are "
        "exactly the rows that are not there to iterate over.",
        "NO_EXPECTATION_SET")


def run_coverage(bundle_path: Path,
                 expect_path: Optional[Path]) -> Tuple[int, Dict[str, Any]]:
    index, refusals = _index_from(bundle_path)
    bundle_doc = _read_json(bundle_path, "bundle")
    expected = _expected_from(bundle_doc, expect_path)
    try:
        cov = M.coverage(index, expected)
    except M.MetricError as exc:
        raise CannotCheck(f"{exc.code}: {exc.message}", exc.code)
    report: Dict[str, Any] = {
        "program": "ppa_measurement_check.py", "mode": "coverage",
        "bundle": str(bundle_path),
        "expect": str(expect_path) if expect_path else "(from bundle)",
        "records_indexed": len(index),
        "record_refusals": refusals,
        "coverage": cov.as_dict(),
    }
    rc = M.coverage_rc(cov)
    if refusals:
        # An invalid record is a finding about the record set and outranks a
        # coverage gap, for the same reason 1 outranks 2 everywhere else here.
        rc = RC_REFUSED
    report["rc"] = rc
    report["code"] = ("RECORD_REFUSED" if refusals
                      else {0: "COVERAGE_COMPLETE", 1: "COVERAGE_" + cov.worst,
                            2: "COVERAGE_INCOMPLETE"}[rc])
    report["_text"] = M.format_coverage(cov)
    return rc, report


def run_compare(a_path: Path, b_path: Path,
                better: Optional[str]) -> Tuple[int, Dict[str, Any]]:
    def one(path: Path) -> Dict[str, Any]:
        doc = _read_json(path, "record")
        try:
            recs = M.records_from_document(doc)
        except M.MetricError as exc:
            raise CannotCheck(f"{path}: {exc.code}: {exc.message}", exc.code)
        if len(recs) != 1:
            raise CannotCheck(
                f"{path} carries {len(recs)} records; --compare takes exactly "
                "one on each side. Comparing a set to a set would have to "
                "choose which rows pair up, and choosing is what this gate "
                "refuses to do.", "NOT_ONE_RECORD")
        return recs[0]

    a, b = one(a_path), one(b_path)
    try:
        verdict = M.compare(a, b, better=better)
    except M.MetricError as exc:
        raise CannotCheck(f"{exc.code}: {exc.message}", exc.code)
    report = {"program": "ppa_measurement_check.py", "mode": "compare",
              "a_path": str(a_path), "b_path": str(b_path),
              "comparison": verdict}
    v = verdict["verdict"]
    if v == M.CMP_OK:
        rc = RC_OK
    elif v in (M.CMP_INVALID, M.CMP_UNIT_MISMATCH):
        rc = RC_REFUSED
    elif v == M.CMP_DIFFERENT_METRIC:
        # The caller named two files that are not two views of one quantity.
        # That is a bad question, not a bad design: rc=3, never a design FAIL.
        rc = RC_BAD_INVOCATION
    else:
        rc = RC_UNDETERMINED
    report["rc"] = rc
    report["code"] = v
    return rc, report


#: What this gate would have examined, for the NO_CORPUS / VACUOUS line.
_GATE = "PPA measurement records"
_SCANNED = "published metric bundle(s)"


def is_bundle(doc: Any) -> bool:
    """A corpus record for THIS gate, decided on the document, not its name."""
    return (isinstance(doc, dict)
            and doc.get("schema") == M.BUNDLE_SCHEMA_ID)


def check_corpus(named: Path, may_be_absent: bool = False,
                 json_out: Optional[str] = None) -> int:
    """Coverage over every metric bundle under `named`, aggregated by severity.

    The corpus-wide conflict scan keys on `_ppa.metrics.record_key` — the
    identity of a MEASUREMENT, `(metric, scope_digest)`, not the metric name,
    because two records naming one metric under different scope are different
    facts and both belong in one corpus.
    """
    corpus, rc = corpus_seam.open_corpus(named, _GATE, _SCANNED, may_be_absent)
    if corpus is None:
        return rc
    scan = corpus_seam.collect(corpus, is_bundle)
    print(f"ppa_measurement_check --corpus {corpus}: "
          f"{scan.denominator(_SCANNED)}")
    unread_rc = corpus_seam.report_unreadable(_GATE, scan)
    if not scan.records:
        return corpus_seam.worst_rc(
            [corpus_seam.vacuous(_GATE, corpus, _SCANNED, scan), unread_rc])

    rows: List[Any] = []
    unkeyed = 0
    for path, doc in scan.records:
        for rec in doc.get("records") or []:
            if not isinstance(rec, dict):
                unkeyed += 1
                continue
            metric, scope = M.record_key(rec)
            rows.append((path, f"{metric} @ {scope}", rec))
    if unkeyed:
        print(f"[{_GATE}] NOTE: {unkeyed} entr(ies) in the corpus are not "
              f"metric objects and could not be keyed for the conflict scan; "
              f"the per-bundle run still refuses them.", file=sys.stderr)
    conflicts, copies = corpus_seam.identity_conflicts(
        rows, _GATE, "measurement")
    conflict_rc = corpus_seam.print_conflicts(_GATE, conflicts, copies)

    rcs = [main(["--coverage", str(path)]) for path, _ in scan.records]
    worst = corpus_seam.worst_rc(rcs + [conflict_rc, unread_rc])
    refused = sum(1 for r in rcs if r == corpus_seam.RC_REFUSED)
    undet = sum(1 for r in rcs if r == corpus_seam.RC_UNDETERMINED)
    print(f"ppa_measurement_check --corpus {corpus}: {len(rcs)} bundle(s), "
          f"{refused} refused, {undet} undetermined, "
          f"{len(rcs) - refused - undet} accepted, {len(conflicts)} "
          f"measurement conflict(s) -> rc={worst}")
    if json_out:
        atomic_write_text(Path(json_out), json.dumps({
            "program": "ppa_measurement_check.py", "mode": "corpus",
            "corpus": str(corpus), "files_opened": scan.files,
            "bundles": [str(path) for path, _ in scan.records],
            "unreadable": [{"path": str(p), "why": w}
                           for p, w in scan.unreadable],
            "measurement_conflicts": conflicts,
            "measurement_copies": copies,
            "rc": worst,
        }, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return worst


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Coverage over a PPA record set, and the comparison "
                    "refusal that scope requires.")
    ap.add_argument("--coverage", metavar="BUNDLE", default=None,
                    help="the record set to measure coverage over")
    ap.add_argument("--expect", metavar="FILE", default=None,
                    help="the declared denominator; falls back to the "
                         "bundle's own `expected` and NEVER to the record set")
    ap.add_argument("--compare", nargs=2, metavar=("A", "B"), default=None,
                    help="two single-record documents")
    ap.add_argument("--better", choices=("lower", "higher"), default=None,
                    help="which direction wins for this metric. Domain "
                         "policy; without it no winner is named.")
    ap.add_argument("--corpus", metavar="DIR", default=None,
                    help="run the coverage question over every metric bundle "
                         "under DIR; exits 2 when the corpus carries none")
    ap.add_argument("--corpus-may-be-absent", action="store_true",
                    help="this repository need not carry the published "
                         "corpus. Turns 'nothing anywhere' into a stated "
                         "NO_CORPUS that names its zero, and NEVER excuses a "
                         "$VIBE_IC_BENCHMARK_DATA that is set and unreadable.")
    ap.add_argument("--json", metavar="FILE", default=None,
                    help="write the machine-readable report here")
    args, _rc = cli_exit.parse_or_refuse(ap, argv)
    if args is None:
        return _rc

    if args.corpus is not None:
        if args.coverage is not None or args.compare is not None:
            return corpus_seam.both_given(
                "ppa_measurement_check",
                "--coverage/--compare", "--corpus")
        return check_corpus(Path(args.corpus).resolve(),
                            args.corpus_may_be_absent, args.json)
    if (args.coverage is None) == (args.compare is None):
        return cli_exit.refuse(
            ap.prog,
            "give exactly one of --coverage BUNDLE, --compare A B, or --corpus DIR")

    try:
        if args.coverage is not None:
            rc, report = run_coverage(
                Path(args.coverage),
                Path(args.expect) if args.expect else None)
        else:
            rc, report = run_compare(Path(args.compare[0]),
                                     Path(args.compare[1]), args.better)
    except CannotCheck as exc:
        # THE VACUOUS ARM. Not rc=0 (nothing was checked) and not rc=1 (rc=1 is
        # a claim about silicon, and nothing here looked at any).
        print(f"[CANNOT CHECK] {exc.code}: {exc.message} rc=2.",
              file=sys.stderr)
        if args.json:
            atomic_write_text(
                Path(args.json),
                json.dumps({"program": "ppa_measurement_check.py",
                            "rc": RC_UNDETERMINED, "code": exc.code,
                            "cannot_check": exc.message},
                           indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return RC_UNDETERMINED

    text = report.pop("_text", None)
    if text:
        print(text)
    if report["mode"] == "compare":
        c = report["comparison"]
        print(f"ppa_measurement_check --compare: {c['verdict']} — {c['detail']}")

    for r in report.get("record_refusals", []):
        print(f"[REFUSE] record #{r['record_index']} {r['metric']!r}: "
              f"{r['code']}: {r['message']}", file=sys.stderr)

    if rc == RC_REFUSED:
        if report["mode"] == "coverage":
            absent = [row["metric"] for row in report["coverage"]["rows"]
                      if row["outcome"] == M.ABSENT]
            if absent:
                print(f"[REFUSE] {len(absent)} expected measurement(s) have NO "
                      f"RECORD AT ALL: {', '.join(absent)}. A report of the "
                      f"remaining rows asserts nothing about these, and that "
                      f"is exactly how a coverage gap becomes an implied "
                      f"zero. A missing number is a NOT_MEASURED row with a "
                      f"reason, never an omission. rc=1.", file=sys.stderr)
            est = [row["metric"] for row in report["coverage"]["rows"]
                   if row["outcome"] == M.UNUSABLE
                   and row["status"] == M.ESTIMATED]
            if est:
                print(f"[REFUSE] an ESTIMATE stands where a measurement was "
                      f"owed: {', '.join(est)}. An estimate is never part of a "
                      f"final PPA claim. rc=1.", file=sys.stderr)
        else:
            print(f"[REFUSE] {report['comparison']['detail']} rc=1.",
                  file=sys.stderr)
    elif rc == RC_UNDETERMINED:
        detail = (report["comparison"]["detail"] if report["mode"] == "compare"
                  else "expected measurements are declared absent or unusable; "
                       "a run that measured some of what it owed has not "
                       "passed")
        print(f"[CANNOT CHECK] {detail} rc=2. This is NOT a pass.",
              file=sys.stderr)
    elif rc == RC_BAD_INVOCATION:
        print(f"[REFUSE] {report['comparison']['detail']} rc=3 (bad "
              f"invocation, not a finding about any design).", file=sys.stderr)

    if args.json:
        atomic_write_text(Path(args.json),
                          json.dumps(report, indent=2, sort_keys=True) + "\n",
                          encoding="utf-8")
    return rc


if __name__ == "__main__":
    sys.exit(main())
