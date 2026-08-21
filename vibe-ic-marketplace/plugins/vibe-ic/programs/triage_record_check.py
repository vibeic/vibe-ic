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
import json
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
    # "A. Benchmark ↔ TB" / "Category F" / "F" → first alpha char
    for ch in s:
        if ch.isalpha():
            return ch.upper()
    return None


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
    return out


# ── core checking ────────────────────────────────────────────────────────
def floor_keyword_hit(text: str) -> Optional[str]:
    low = text.lower()
    for kw in FLOOR_KEYWORDS:
        if kw in low:
            return kw
    return None


def check_records(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    violations: List[Dict[str, Any]] = []
    reviews: List[Dict[str, Any]] = []

    for i, rec in enumerate(records):
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

    return {
        "program": "triage_record_check",
        "n_records": len(records),
        "violations": violations,
        "reviews": reviews,
        "n_violations": len(violations),
        "n_reviews": len(reviews),
    }


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

    report = check_records(records)
    report["path"] = str(path)

    n_v = report["n_violations"]
    n_r = report["n_reviews"]
    if n_v == 0 and n_r == 0:
        report["verdict"] = "PASS"
        _emit(a, report)
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
