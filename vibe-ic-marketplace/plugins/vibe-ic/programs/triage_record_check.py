#!/usr/bin/env python3
"""triage_record_check.py — self-consistency linter for benchmark
residual-triage records (open-benchmark-methodology § 4 + § 6.4).

A triage record assigns each residual benchmark fail to ONE of the § 4
A-H categories. The skill draws a hard line:

  * **A-E are FLOOR** — unsatisfiable blind / spec-ambiguous / tool-gap.
    A FLOOR case is NOT close-looped (close-loop's job is own-TB
    self-verify, not converging on the hidden oracle), so a FLOOR record
    must carry ``closeloop == false``.

  * **F-H are AGENT-FIXABLE** — the clue was in the prose (F), a genre
    convention (G), or a real RTL bug (H). § 6.4: "Anything in F-H
    without a close-loop attempt is **not allowed** — close-loop or
    document why close-loop was skipped." So an agent-fixable record must
    EITHER have been close-looped (``closeloop == true``) OR carry a
    non-empty skip justification.

Two failure shapes recur in real triage JSON (ORGANIC-20260606 #481):

  1. An agent-fixable letter (F/G/H) with ``closeloop == false`` and no
     skip justification — i.e. an F-H fail nobody actually attempted.
  2. A letter-vs-rationale contradiction: an agent-fixable letter whose
     rationale text reads like a FLOOR rationale ("two mutually-exclusive
     readings", "under-specified", "benchmark defect"). Either the letter
     is wrong (should be A-E) or the rationale is mislabeled. Flagged as
     a REVIEW finding because resolving it needs § 4 LLM judgment.

This linter checks the **mechanical self-consistency** of the records;
the *correctness* of each category assignment is still the § 4 LLM core.

Operational attempt receipts may instead use category PRODUCT_ENTRY_DEFECT or
PENDING_ACCEPTANCE with verdict NOT_MEASURED. Their evidence must reference
``solve_report.json#<id>`` and its sibling
``program_first_ai_review_acceptance.json`` must reconcile the same population.
The consumer reads only those metadata files, never project RTL or an oracle.
Missing provenance, measured failures, conflicting claims and forged completion
counts refuse this exception. Clean operational input yields VALID_UNMEASURED
(exit 0 means records valid), never benchmark completion or scoring permission.

Input
=====
A JSON file holding triage records. Both shapes are accepted:
  * a top-level list:           ``[ {record}, {record}, ... ]``
  * a wrapped object:           ``{"records": [ ... ]}``  (also
    ``triage`` / ``residual_triage`` / ``items`` keys)

Field naming is read liberally (real producers vary):
  * category letter: ``category`` | ``letter`` | ``bucket`` | ``cat``
    | ``category_letter`` (first char, upper-cased; "A. Benchmark…" → A)
  * close-loop flag: ``closeloop`` | ``close_loop`` | ``closed_loop``
    | ``close_looped`` | ``attempted`` (truthy)
  * skip justification: ``skip_justification`` | ``skip_reason``
    | ``why_skipped`` | ``skip_note`` | ``no_closeloop_reason``
  * rationale text:    ``rationale`` | ``reason`` | ``description``
    | ``note`` | ``evidence`` | ``why``

Canonical shape (documented, if no producer is found on disk)
============================================================
  {
    "id":        "radix2_div",        # problem id (optional, for messages)
    "category":  "F",                 # A-H, the § 4 letter
    "closeloop": true,                # bool; A-E ⇒ false, F-H ⇒ true|skip
    "skip_justification": "",         # required if F-H and closeloop false
    "rationale": "the clue WAS in the prose ..."   # free text
  }

Rules
=====
  (a) F/G/H  ⇒  closeloop == true  OR  non-empty skip_justification
  (b) A-E    ⇒  closeloop == false
  (c) letter-vs-rationale contradiction: an agent-fixable letter (F/G/H)
      whose rationale contains FLOOR-family keywords → REVIEW finding.

Exit codes
==========
  0 — clean (no violations, no review findings)
  1 — one or more rule violations (a/b) OR review findings (c)
  2 — IO / usage error (missing file, unparseable JSON, wrong shape)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ── category sets ────────────────────────────────────────────────────────
FLOOR_LETTERS = {"A", "B", "C", "D", "E"}
AGENT_FIXABLE_LETTERS = {"F", "G", "H"}
VALID_LETTERS = FLOOR_LETTERS | AGENT_FIXABLE_LETTERS

# ── liberal field-name aliases ───────────────────────────────────────────
_CATEGORY_KEYS = ("category", "letter", "bucket", "cat",
                  "category_letter", "class", "triage_category")
_CLOSELOOP_KEYS = ("closeloop", "close_loop", "closed_loop",
                   "close_looped", "closelooped", "attempted",
                   "close_loop_attempted")
_SKIP_KEYS = ("skip_justification", "skip_reason", "why_skipped",
              "skip_note", "no_closeloop_reason", "closeloop_skip_reason",
              "skipped_because")
_RATIONALE_KEYS = ("rationale", "reason", "description", "note",
                   "evidence", "why", "explanation", "justification",
                   "desc")
_ID_KEYS = ("id", "problem", "problem_id", "name", "case", "fail", "item")

# ── FLOOR-family rationale keywords (rule c) ─────────────────────────────
# Phrases that legitimately describe a FLOOR (A-E) rationale. If an
# agent-fixable letter (F-H) carries one of these, the letter and the
# prose disagree → REVIEW.
FLOOR_KEYWORDS = (
    "mutually exclusive reading",
    "mutually-exclusive reading",
    "two mutually exclusive",
    "two mutually-exclusive",
    "mutually exclusive",
    "mutually-exclusive",
    "under-specified",
    "under specified",
    "underspecified",
    "benchmark defect",
    "dataset defect",
    "unsatisfiable blind",
    "tool-substitution gap",
    "vcs-only",
    "xcelium-only",
    "spec ambiguity",
    "spec-ambiguity",
    "spec admits",
    "do not over-fit",
    "do not overfit",
    "leave spec-faithful",
    "positional with an undocumented",
    "tb wires a different",
    "prose never states",
)


class TriageInputError(Exception):
    """Raised on IO / shape problems (mapped to exit 2)."""


# ── extraction helpers ───────────────────────────────────────────────────
def _first_present(rec: Dict[str, Any], keys: Tuple[str, ...]) -> Optional[Any]:
    for k in keys:
        if k in rec and rec[k] is not None:
            return rec[k]
    # case-insensitive fallback
    low = {k.lower(): k for k in rec}
    for k in keys:
        if k.lower() in low and rec[low[k.lower()]] is not None:
            return rec[low[k.lower()]]
    return None


def extract_letter(rec: Dict[str, Any]) -> Optional[str]:
    raw = _first_present(rec, _CATEGORY_KEYS)
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    # A category name beginning with E or F is not itself a rubric letter.
    match = re.match(r"^(?:Category\s+)?([A-H])(?:$|[\s.:)\-])", s, re.I)
    return match[1].upper() if match else None


def extract_closeloop(rec: Dict[str, Any]) -> bool:
    raw = _first_present(rec, _CLOSELOOP_KEYS)
    if isinstance(raw, bool):
        return raw
    if raw is None:
        return False
    if isinstance(raw, (int, float)):
        return bool(raw)
    s = str(raw).strip().lower()
    return s in ("true", "yes", "1", "y", "done", "attempted", "pass")


def extract_skip_justification(rec: Dict[str, Any]) -> str:
    raw = _first_present(rec, _SKIP_KEYS)
    return str(raw).strip() if raw is not None else ""


def extract_rationale(rec: Dict[str, Any]) -> str:
    raw = _first_present(rec, _RATIONALE_KEYS)
    return str(raw).strip() if raw is not None else ""


def extract_id(rec: Dict[str, Any], index: int) -> str:
    raw = _first_present(rec, _ID_KEYS)
    return str(raw).strip() if raw is not None and str(raw).strip() else f"record[{index}]"


# ── input loading (liberal shape) ────────────────────────────────────────
def load_records(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        raise TriageInputError(f"triage records file not found: {path}")
    text = path.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        raise TriageInputError(f"triage records file is empty: {path}")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise TriageInputError(f"triage records file is not valid JSON: {e}")
    return _coerce_records(data)


def _coerce_records(data: Any) -> List[Dict[str, Any]]:
    if isinstance(data, list):
        recs = data
    elif isinstance(data, dict):
        recs = None
        for k in ("records", "triage", "residual_triage", "items",
                  "fails", "findings", "cases"):
            if isinstance(data.get(k), list):
                recs = data[k]
                break
        if recs is None:
            raise TriageInputError(
                "object input must wrap a list under one of: "
                "records / triage / residual_triage / items / fails / "
                "findings / cases")
    else:
        raise TriageInputError(
            "input must be a JSON list of records or an object wrapping one")
    out: List[Dict[str, Any]] = []
    for i, r in enumerate(recs):
        if not isinstance(r, dict):
            raise TriageInputError(f"record[{i}] is not an object")
        out.append(r)
    validate_operational_envelope(data, out)
    return out


# ── core checking ────────────────────────────────────────────────────────
OPERATIONAL_CATEGORIES = {"PRODUCT_ENTRY_DEFECT", "PENDING_ACCEPTANCE"}
_VERDICT_KEYS = ("verdict", "triage_verdict", "outcome", "classification", "label")
_BLIND_KEYS = ("independent_blind_passes", "blind_passes", "ai_blind_passes",
               "independent_solve_passes", "blind_solve_passes", "ai_solved_blind")
_BENCH_KEYS = ("bench", "benchmark", "dataset", "suite")
_PHASE_KEYS = ("phase1_routing", "phase2_solving", "phase3_verifying",
               "phase4_debugging")


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def _pending_claims(value: Dict[str, Any]) -> None:
    for key in ("benchmark_complete", "scorable", "accepted"):
        _require(value.get(key) in (None, False, 0),
                 f"operational input cannot claim {key}")
    for key in ("status", "benchmark_status", "acceptance_status"):
        if key in value:
            _require(str(value[key]).strip().upper() in
                     {"NOT_MEASURED", "PENDING", "BLOCKED", "BLOCKED_NOT_MEASURED", "ERROR"},
                     f"operational input has unsupported {key}")
    if "score_status" in value:
        _require(value["score_status"] == "NOT_MEASURED",
                 "operational score_status must remain NOT_MEASURED")


def validate_operational_envelope(data: Any, records: List[Dict[str, Any]]) -> None:
    """A wrapper cannot promote pending rows by inventing complete totals."""
    if not isinstance(data, dict) or not any(
            str(_first_present(r, _CATEGORY_KEYS)).strip().upper() in OPERATIONAL_CATEGORIES
            for r in records):
        return
    try:
        _pending_claims(data)
        for key in ("total", "n_records"):
            if key in data:
                _require(type(data[key]) is int and data[key] == len(records),
                         f"wrapper {key} must equal the retained record population")
    except ValueError as exc:
        raise TriageInputError(str(exc)) from exc


def _failure_path(value: Any, path: str = "record") -> Optional[str]:
    """Inspect status metadata, including nested native gate failures."""
    if isinstance(value, dict):
        for key, item in value.items():
            here = f"{path}.{key}"
            if key in {"failed", "failures", "unclassified_status"} and item:
                return here
            hit = _failure_path(item, here)
            if hit:
                return hit
    elif isinstance(value, list):
        for i, item in enumerate(value):
            hit = _failure_path(item, f"{path}[{i}]")
            if hit:
                return hit
    elif isinstance(value, str) and re.match(r"^FAIL(?:ED)?(?:$|[:_\s])", value, re.I):
        return path
    return None


def _load_operational_source(path: Path) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Validate existing dispatcher metadata without following its file refs."""
    raw = path.read_bytes()
    solve = json.loads(raw)
    acceptance_path = path.with_name("program_first_ai_review_acceptance.json")
    acceptance_raw = acceptance_path.read_bytes()
    acceptance = json.loads(acceptance_raw)
    _require(isinstance(solve, dict) and isinstance(acceptance, dict),
             "solve and acceptance metadata must be objects")
    rows, total = solve.get("results"), solve.get("total")
    _require(isinstance(rows, list) and type(total) is int and total > 0
             and len(rows) == total, "solve total must equal nonempty results")
    _require(all(isinstance(r, dict) and isinstance(r.get("id"), str)
                 and r["id"].strip() and type(r.get("accepted")) is bool
                 for r in rows), "every source row needs id and bool accepted")
    ids = [r["id"] for r in rows]
    _require(len(set(ids)) == total, "source ids must be unique")
    accepted_ids = [r["id"] for r in rows if r["accepted"]]
    _require(type(solve.get("accepted")) is int
             and solve["accepted"] == len(accepted_ids),
             "solve accepted count contradicts its rows")
    _require(acceptance.get("schema") == "vibeic.benchmark.program_first_ai_review.v3"
             and acceptance.get("status") == "PENDING",
             "operational provenance requires PENDING acceptance")
    _require(type(acceptance.get("total")) is int and acceptance["total"] == total
             and type(acceptance.get("accepted")) is int
             and acceptance["accepted"] == len(accepted_ids) < total
             and isinstance(acceptance.get("accepted_ids"), list)
             and sorted(acceptance["accepted_ids"]) == sorted(accepted_ids),
             "acceptance count/ids/total contradict solve population")
    proof = {"solve_path": str(path), "solve_sha256": hashlib.sha256(raw).hexdigest(),
             "acceptance_path": str(acceptance_path),
             "acceptance_sha256": hashlib.sha256(acceptance_raw).hexdigest(),
             "bench": solve.get("bench"), "total": total,
             "accepted": len(accepted_ids)}
    return solve, proof


def operational_records(records: List[Dict[str, Any]],
                        source_path: Optional[Path] = None) -> Dict[str, Any]:
    """Shared consumer seam: validate an operational claim before exemption.

    Invalid operational records are retained as violations, not fed back into
    first-letter parsing. Functional records still traverse the original rubric.
    """
    violations, unmeasured, provenance = [], [], {}
    operational = set()
    cache = {}
    if not records:
        violations.append({"id": "population", "rule": "empty_population",
                           "detail": "zero records cannot establish completion"})
    for i, rec in enumerate(records):
        category = str(_first_present(rec, _CATEGORY_KEYS) or "").strip().upper()
        verdict = str(_first_present(rec, _VERDICT_KEYS) or "").strip().upper()
        rid = extract_id(rec, i)
        if category not in OPERATIONAL_CATEGORIES:
            if verdict == "NOT_MEASURED":
                violations.append({"id": rid, "rule": "unmeasured_requires_operational_category",
                                   "detail": "NOT_MEASURED alone cannot bypass functional triage"})
            continue
        operational.add(i)
        try:
            _require(verdict == "NOT_MEASURED", "operational verdict must be NOT_MEASURED")
            _pending_claims(rec)
            for keys, expected in [(_CATEGORY_KEYS, category), (_VERDICT_KEYS, verdict)]:
                _require(all(str(v).strip().upper() == expected
                             for k, v in rec.items() if k.lower() in keys and v is not None),
                         "conflicting category/verdict aliases")
            _require(all(v is None for k, v in rec.items() if k.lower() in _BLIND_KEYS),
                     "an operational record cannot claim a measured blind result")
            _require(not _failure_path(rec), "record contains a measured FAIL")
            _require(isinstance(rec.get("id"), str) and bool(rec["id"].strip())
                     and isinstance(rec.get("bench"), str) and bool(rec["bench"].strip()),
                     "operational record requires explicit id and bench")
            evidence = rec.get("evidence")
            _require(isinstance(evidence, str) and evidence.count("#") == 1,
                     "evidence must reference solve_report.json#id")
            filename, fragment = evidence.rsplit("#", 1)
            path = Path(filename)
            _require(path.name == "solve_report.json" and fragment == rid,
                     "evidence must name solve_report.json and the same id")
            if not path.is_absolute():
                _require(source_path is not None, "relative evidence needs the input JSON path")
                path = source_path.parent / path
            path = path.resolve()
            if path not in cache:
                cache[path] = _load_operational_source(path)
            solve, proof = cache[path]
            bench = rec["bench"]
            _require(solve.get("bench") == bench, "source bench does not match record")
            population = [extract_id(r, j) for j, r in enumerate(records)
                          if _first_present(r, _BENCH_KEYS) == bench]
            ids = [r["id"] for r in solve["results"]]
            _require(sorted(population) == sorted(ids),
                     "triage ids must retain the exact source population for this bench")
            if "evidence_sha256" in rec:
                _require(rec["evidence_sha256"] == proof["solve_sha256"],
                         "source SHA-256 does not match evidence_sha256")
            row = next(r for r in solve["results"] if r["id"] == rid)
            _require(row["accepted"] is False, "accepted row is not pending")
            _require(all(v is None for k, v in row.items() if k.lower() in _BLIND_KEYS),
                     "source contains a measured blind result")
            phases = row.get("phases")
            _require(isinstance(phases, dict)
                     and all(isinstance(phases.get(k), dict) for k in _PHASE_KEYS),
                     "source requires all four phase metadata objects")
            failure = _failure_path(row)
            _require(not failure,
                     f"measured FAIL at {failure}; retain original functional triage obligations")
            if category == "PRODUCT_ENTRY_DEFECT":
                _require(row.get("worker_status") == "ERROR"
                         and isinstance(row.get("worker_error"), str)
                         and bool(row["worker_error"].strip())
                         and row.get("candidate_ready") is False
                         and row.get("candidate_origin") == "NONE"
                         and all(phases[k].get("status") == "NOT_MEASURED"
                                 for k in _PHASE_KEYS),
                         "entry defect requires worker ERROR, no candidate and unmeasured phases")
            else:
                _require(row.get("worker_status") != "ERROR"
                         and not row.get("worker_error")
                         and ((row.get("candidate_origin") in {"PROGRAM", "AI_BACKUP", "AI_REPAIR"}
                               and row.get("candidate_ready") is True
                               and row.get("awaiting_ai_review") is True)
                              or (row.get("candidate_origin") == "AI_BACKUP_PENDING"
                                  and row.get("candidate_ready") is False
                                  and row.get("awaiting_ai_backup") is True)),
                         "pending acceptance requires an outstanding AI acceptance obligation")
            provenance[str(path)] = proof
            unmeasured.append({"index": i, "id": rid, "bench": bench, "category": category})
        except (OSError, ValueError, TypeError, StopIteration) as exc:
            violations.append({"id": rid, "bench": rec.get("bench"),
                               "rule": "operational_provenance_invalid", "detail": str(exc)})
    return {"indices": operational, "violations": violations,
            "unmeasured": unmeasured, "n_unmeasured": len(unmeasured),
            "n_invalid_operational": len(operational) - len(unmeasured),
            "n_functional": len(records) - len(operational),
            "provenance": list(provenance.values()),
            "benchmark_complete": False, "scorable": False,
            "score_status": "NOT_MEASURED" if operational else "NOT_VERIFIED"}


def record_validity(report: Dict[str, Any], operational: Dict[str, Any]) -> None:
    """Record validity is not a claim about benchmark completion or scoring."""
    report.update({k: v for k, v in operational.items() if k not in {"indices", "violations"}})
    report["records_valid"] = not (report["n_violations"] or report.get("n_reviews", 0))
    report["verdict"] = ("FAIL" if not report["records_valid"] else
                         "VALID_UNMEASURED" if operational["indices"] else "PASS")


def floor_keyword_hit(text: str) -> Optional[str]:
    low = text.lower()
    for kw in FLOOR_KEYWORDS:
        if kw in low:
            return kw
    return None


def check_records(records: List[Dict[str, Any]],
                  source_path: Optional[Path] = None) -> Dict[str, Any]:
    operational = operational_records(records, source_path)
    violations: List[Dict[str, Any]] = list(operational["violations"])
    reviews: List[Dict[str, Any]] = []

    for i, rec in enumerate(records):
        if i in operational["indices"]:
            continue
        rid = extract_id(rec, i)
        letter = extract_letter(rec)
        closeloop = extract_closeloop(rec)
        skip = extract_skip_justification(rec)
        rationale = extract_rationale(rec)

        if letter is None or letter not in VALID_LETTERS:
            violations.append({
                "id": rid, "rule": "letter_invalid",
                "category": letter,
                "detail": (f"category letter {letter!r} is not one of A-H "
                           "(§ 4 triage rubric)"),
            })
            continue

        # Rule (a): F/G/H must be close-looped OR carry a skip justification.
        if letter in AGENT_FIXABLE_LETTERS:
            if not closeloop and not skip:
                violations.append({
                    "id": rid, "rule": "agent_fixable_no_closeloop_no_skip",
                    "category": letter, "closeloop": closeloop,
                    "detail": (f"agent-fixable letter {letter} requires "
                               "closeloop=true OR a non-empty skip "
                               "justification (§ 6.4)"),
                })
        # Rule (b): A-E (FLOOR) must NOT be close-looped.
        elif letter in FLOOR_LETTERS:
            if closeloop:
                violations.append({
                    "id": rid, "rule": "floor_with_closeloop",
                    "category": letter, "closeloop": closeloop,
                    "detail": (f"FLOOR letter {letter} must have "
                               "closeloop=false (§ 4: FLOOR is not "
                               "close-looped)"),
                })

        # Rule (c): agent-fixable letter + FLOOR-family rationale → REVIEW.
        if letter in AGENT_FIXABLE_LETTERS:
            blob = " ".join(x for x in (rationale, skip) if x)
            kw = floor_keyword_hit(blob)
            if kw:
                reviews.append({
                    "id": rid, "rule": "letter_vs_rationale_contradiction",
                    "category": letter, "floor_keyword": kw,
                    "detail": (f"agent-fixable letter {letter} but rationale "
                               f"reads FLOOR ('{kw}') — letter or rationale "
                               "is mislabeled (§ 4 judgment needed)"),
                })

    report = {
        "program": "triage_record_check",
        "n_records": len(records),
        "violations": violations,
        "reviews": reviews,
        "n_violations": len(violations),
        "n_reviews": len(reviews),
    }
    record_validity(report, operational)
    return report


# ── CLI ──────────────────────────────────────────────────────────────────
def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("records_json",
                    help="path to the triage-records JSON (list or {records:[...]})")
    ap.add_argument("--json", help="write the JSON report to this path")
    a = ap.parse_args(argv)

    path = Path(a.records_json)
    try:
        records = load_records(path)
    except TriageInputError as e:
        report = {"program": "triage_record_check", "path": str(path),
                  "verdict": "IO_ERROR", "reason": str(e)}
        _emit(a, report)
        print(f"IO ERROR: {e}", file=sys.stderr)
        return 2

    report = check_records(records, path)
    report["path"] = str(path)

    n_v = report["n_violations"]
    n_r = report["n_reviews"]
    if n_v == 0 and n_r == 0:
        _emit(a, report)
        if report["n_unmeasured"]:
            print(f"VALID_UNMEASURED: {report['n_unmeasured']} operational record(s); "
                  "records valid; benchmark incomplete; score NOT_MEASURED; unscorable")
            return 0
        print(f"PASS: {report['n_records']} triage record(s) self-consistent "
              "(§ 4 A-E⇒floor / F-H⇒closeloop|skip; no letter↔rationale clash)")
        return 0

    report["verdict"] = "FAIL"
    _emit(a, report)
    print(f"FAIL: {n_v} violation(s), {n_r} review finding(s) in "
          f"{report['n_records']} record(s):", file=sys.stderr)
    for v in report["violations"]:
        print(f"  VIOLATION [{v['rule']}] {v['id']} (cat={v.get('category')}): "
              f"{v['detail']}", file=sys.stderr)
    for r in report["reviews"]:
        print(f"  REVIEW [{r['rule']}] {r['id']} (cat={r.get('category')}): "
              f"{r['detail']}", file=sys.stderr)
    return 1


def _emit(a, report: Dict[str, Any]) -> None:
    if getattr(a, "json", None):
        Path(a.json).write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
