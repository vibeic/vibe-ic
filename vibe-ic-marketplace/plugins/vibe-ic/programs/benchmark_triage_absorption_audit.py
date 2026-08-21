#!/usr/bin/env python3
"""benchmark_triage_absorption_audit.py — open-benchmark-methodology § 4.2

Machine-checkable CONVERGENCE BAR for the program-first + AI-backup doctrine
(user directive 2026-06-18; pairs with `triage_record_check.py` § 4 self-
consistency and `convergence_doctrine_present_check.py` #716 dual-track).

THE DOCTRINE THIS ENFORCES
==========================
"program-first, AI-backup: every benchmark fail case must be DUAL-verified — by
a PROGRAM (the plugin scorer/gate) AND by an AI independent blind solve. The AI
must genuinely TRY ITS BEST. IF the AI CAN solve it with a GENERAL + NO-CHEATING
method, that recovery MUST be absorbed into the plugin — as a deterministic
PROGRAM rule, OR as an AI step GATED BY A PROGRAM. A 'RECOVERABLE_AUTHORING' /
'AUTHORING' label is NOT a free pass to skip."

A campaign CONVERGES only when EVERY residual fail is one of:
  (a) TRUE_FLOOR   — the AI ALSO cannot solve it without cheating (over-fitting
                     the hidden TB / reading the oracle), the golden is self-
                     consistent, and the spec genuinely under-discloses;
  (b) DATASET_DEFECT — the golden fails its OWN testbench; or
  (c) ABSORBED     — its AI-recovery has been absorbed into the plugin (a
                     deterministic program rule, OR an AI step gated by a
                     program) and field-verified.

So this audit's load-bearing assertion is the inverse: **any fail whose verdict
implies the AI COULD solve it MUST carry an `absorption_ref`.** A fail may be
exempt from absorption ONLY if it is a documented floor/defect WITH evidence:
  * TRUE_FLOOR    requires `floor_evidence` AND independent_blind_passes == false
                  (you cannot dodge a hard solve by merely labelling FLOOR — the
                  blind solve must actually have FAILED);
  * DATASET_DEFECT requires `floor_evidence` carrying golden-fails-own-TB proof.

This is the deterministic half. The READING judgment — *is this genuinely a
floor or did the AI just not try hard enough* — stays the § 4 LLM core; this
program only enforces that the bookkeeping cannot wave through an un-solved,
un-absorbed, AI-solvable fail.

INPUT
=====
A triage-result JSON. Both shapes accepted:
  * top-level list:   ``[ {record}, ... ]``
  * wrapped object:   ``{"records": [ ... ]}``  (also triage / residual_triage /
    items / fails / findings / cases)

Per-record fields (read liberally — real producers vary):
  * id                       problem id (optional, for messages)
  * bench                    benchmark name (optional)
  * verdict                  the convergence verdict (see VERDICTS below)
  * is_plugin_gap            bool (optional, informational)
  * independent_blind_passes bool — did the AI's independent blind solve PASS?
  * absorption_ref           program-rule patch id / gated-AI-step + test ref
  * floor_evidence           evidence string/obj for a TRUE_FLOOR / DATASET_DEFECT

VERDICT vocabulary
==================
AI-SOLVABLE verdicts (MUST carry an absorption_ref):
    RECOVERABLE_AUTHORING, AUTHORING, LESSON_GATE_GAP, SCORING_HARNESS_GAP,
    EXTRACTION_GAP, COVERAGE_GAP, CONVENTION_INFERENCE, REAL_RTL_BUG
ABSORPTION-EXEMPT verdicts (require floor_evidence, see rules):
    TRUE_FLOOR, DATASET_DEFECT
Additionally, ANY record with independent_blind_passes == true is AI-solvable
(the AI demonstrably solved it blind) and MUST carry an absorption_ref,
regardless of its verdict label — this is what stops a "FLOOR" label from
laundering a fail the AI actually solved.

Exit codes
==========
  0 — PASS  (every AI-solvable fail absorbed; every floor/defect has evidence)
  1 — FAIL  (>=1 un-absorbed AI-solvable fail, or an evidence-less exemption)
  2 — IO / usage error
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

# ── verdict vocabulary ────────────────────────────────────────────────────
# Verdicts whose meaning is "the AI can solve this with a general no-cheat
# method" — they MUST be absorbed (program rule OR AI-step-gated-by-program).
AI_SOLVABLE_VERDICTS = {
    "RECOVERABLE_AUTHORING",
    "AUTHORING",
    "LESSON_GATE_GAP",
    "SCORING_HARNESS_GAP",
    "EXTRACTION_GAP",
    "COVERAGE_GAP",
    "CONVENTION_INFERENCE",
    "REAL_RTL_BUG",
}
# Verdicts exempt from absorption ONLY with floor/defect evidence.
TRUE_FLOOR = "TRUE_FLOOR"
DATASET_DEFECT = "DATASET_DEFECT"
EXEMPT_VERDICTS = {TRUE_FLOOR, DATASET_DEFECT}
ALL_KNOWN_VERDICTS = AI_SOLVABLE_VERDICTS | EXEMPT_VERDICTS

# ── liberal field-name aliases ────────────────────────────────────────────
# `category` IS LAST, AND A BARE RUBRIC LETTER IN IT IS IGNORED.
#
# The same skill that defines §4.2 (which this audit enforces) also defines the
# §4/§6.4 triage rubric, whose values are the LETTERS A-H. `category` is the
# field that rubric uses. The one real published input carries BOTH — 87
# records of `{"category": "H", "verdict": "REAL_RTL_BUG"}` — and was audited
# correctly only because `verdict` happened to come first in this tuple.
#
# Measured on that file, one field removed at a time:
#   * drop `verdict`, keep `category: "H"`  ->  rc=1, 121 of 121 records
#     accused of `unknown_verdict (verdict='H')`. Every one of them carries an
#     absorption_ref; not one is a real finding.
#   * a producer that writes the rubric letter in `category` and the real
#     verdict in any OTHER alias (`outcome`, `label`, `classification`) was
#     accused the same way, because `category` SHADOWED them from position 2.
#
# So a rubric letter is not a verdict and must not be read as one. It is not
# silently dropped either: if a record offers nothing BUT a rubric letter, the
# violation says so by name (`rubric_letter_not_a_verdict`) instead of
# inviting the author to add "H" to the vocabulary.
_VERDICT_KEYS = ("verdict", "triage_verdict", "outcome", "classification",
                 "label", "category")
#: §4/§6.4 triage rubric letters — a CATEGORY, never a §4.2 convergence verdict.
_RUBRIC_LETTERS = frozenset("ABCDEFGH")
_BLIND_KEYS = ("independent_blind_passes", "blind_passes", "ai_blind_passes",
               "independent_solve_passes", "blind_solve_passes",
               "ai_solved_blind")
_ABSORB_KEYS = ("absorption_ref", "absorbed_ref", "absorption", "absorbed_by",
                "absorption_id", "patch_ref", "gate_ref")
_FLOOR_EV_KEYS = ("floor_evidence", "floor_proof", "defect_evidence",
                  "evidence", "floor_ev")
_PLUGIN_GAP_KEYS = ("is_plugin_gap", "plugin_gap", "is_gap")
_ID_KEYS = ("id", "problem", "problem_id", "name", "case", "fail", "item")
_BENCH_KEYS = ("bench", "benchmark", "dataset", "suite")


class AuditInputError(Exception):
    """Raised on IO / shape problems (mapped to exit 2)."""


# ── extraction helpers ────────────────────────────────────────────────────
def _first_present(rec: Dict[str, Any], keys: Tuple[str, ...]) -> Optional[Any]:
    for k in keys:
        if k in rec and rec[k] is not None:
            return rec[k]
    low = {k.lower(): k for k in rec}
    for k in keys:
        if k.lower() in low and rec[low[k.lower()]] is not None:
            return rec[low[k.lower()]]
    return None


def _normalise_verdict(raw: Any) -> Optional[str]:
    s = str(raw).strip().upper().replace("-", "_").replace(" ", "_")
    return s or None


def is_rubric_letter(value: Optional[str]) -> bool:
    """A bare §4/§6.4 rubric letter (A-H), not a §4.2 convergence verdict."""
    return bool(value) and value in _RUBRIC_LETTERS


def extract_verdict(rec: Dict[str, Any]) -> Optional[str]:
    """First alias holding something that is not a bare rubric letter.

    Scanning the aliases in order and SKIPPING rubric letters is what stops
    `category: "H"` shadowing a real verdict sitting in `outcome`/`label`.
    """
    for key in _VERDICT_KEYS:
        raw = _first_present(rec, (key,))
        if raw is None:
            continue
        v = _normalise_verdict(raw)
        if v is None or is_rubric_letter(v):
            continue
        return v
    return None


def only_rubric_letter(rec: Dict[str, Any]) -> Optional[str]:
    """The rubric letter a record offers when it offers no verdict at all."""
    for key in _VERDICT_KEYS:
        raw = _first_present(rec, (key,))
        if raw is None:
            continue
        v = _normalise_verdict(raw)
        if is_rubric_letter(v):
            return v
    return None


def extract_bool(rec: Dict[str, Any], keys: Tuple[str, ...]) -> Optional[bool]:
    """Tri-state: True / False / None(absent). Absent matters — an AI-solvable
    blind flag that is simply missing is NOT treated as a passing blind solve."""
    raw = _first_present(rec, keys)
    if raw is None:
        return None
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return bool(raw)
    s = str(raw).strip().lower()
    if s in ("true", "yes", "1", "y", "pass", "passed"):
        return True
    if s in ("false", "no", "0", "n", "fail", "failed"):
        return False
    return None


def extract_str(rec: Dict[str, Any], keys: Tuple[str, ...]) -> str:
    raw = _first_present(rec, keys)
    if raw is None:
        return ""
    if isinstance(raw, (dict, list)):
        # a structured evidence object counts as present iff non-empty
        return json.dumps(raw) if raw else ""
    return str(raw).strip()


def extract_id(rec: Dict[str, Any], index: int) -> str:
    raw = _first_present(rec, _ID_KEYS)
    return str(raw).strip() if raw is not None and str(raw).strip() else f"record[{index}]"


# ── input loading (liberal shape) ─────────────────────────────────────────
def load_records(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        raise AuditInputError(f"triage-result file not found: {path}")
    text = path.read_text(encoding="utf-8", errors="replace")
    if not text.strip():
        raise AuditInputError(f"triage-result file is empty: {path}")
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise AuditInputError(f"triage-result file is not valid JSON: {e}")
    return _coerce_records(data)


def _coerce_records(data: Any) -> List[Dict[str, Any]]:
    if isinstance(data, list):
        recs = data
    elif isinstance(data, dict):
        recs = None
        for k in ("records", "triage", "residual_triage", "items",
                  "fails", "findings", "cases", "results"):
            if isinstance(data.get(k), list):
                recs = data[k]
                break
        if recs is None:
            raise AuditInputError(
                "object input must wrap a list under one of: records / triage "
                "/ residual_triage / items / fails / findings / cases / results")
    else:
        raise AuditInputError(
            "input must be a JSON list of records or an object wrapping one")
    out: List[Dict[str, Any]] = []
    for i, r in enumerate(recs):
        if not isinstance(r, dict):
            raise AuditInputError(f"record[{i}] is not an object")
        out.append(r)
    return out


# ── core audit ─────────────────────────────────────────────────────────────
def audit_records(records: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Return the audit report. Each violation is one of:
      * unabsorbed_ai_solvable   — AI-solvable verdict with no absorption_ref
      * blind_pass_unabsorbed    — independent_blind_passes==true, no absorption_ref
      * floor_without_evidence   — TRUE_FLOOR/DATASET_DEFECT with no floor_evidence
      * true_floor_blind_passed  — TRUE_FLOOR but the blind solve PASSED (so it
                                   was actually solvable — not a floor)
      * unknown_verdict          — verdict not in the recognised vocabulary
    """
    violations: List[Dict[str, Any]] = []
    absorbed: List[str] = []
    exempt: List[str] = []

    for i, rec in enumerate(records):
        rid = extract_id(rec, i)
        verdict = extract_verdict(rec)
        blind = extract_bool(rec, _BLIND_KEYS)
        # ORGANIC #812 r2 (Step-2.7 §4.05) — distinguish a blind field that is
        # ABSENT from one that is PRESENT-BUT-UNPARSEABLE. `extract_bool` collapses
        # both to None; a present-but-unparseable blind result (e.g.
        # `independent_blind_passes: "solved on retry"`) is AMBIGUOUS and must NOT
        # let an EXEMPT verdict launder a possibly-solved fail to a PASS. A raw
        # value present with a None tri-state means "present but unparseable".
        blind_present_unparseable = (
            _first_present(rec, _BLIND_KEYS) is not None and blind is None)
        absorb = extract_str(rec, _ABSORB_KEYS)
        floor_ev = extract_str(rec, _FLOOR_EV_KEYS)

        if verdict is None or verdict not in ALL_KNOWN_VERDICTS:
            letter = only_rubric_letter(rec) if verdict is None else None
            if letter is not None:
                violations.append({
                    "id": rid, "rule": "rubric_letter_not_a_verdict",
                    "verdict": letter,
                    "detail": (
                        f"the only verdict-shaped value on this record is "
                        f"{letter!r}, which is a § 4/§ 6.4 TRIAGE RUBRIC "
                        "letter, not a § 4.2 convergence verdict. The two live "
                        "in the same records and mean different things — emit "
                        "`verdict` beside `category` (AI-solvable set or "
                        "TRUE_FLOOR / DATASET_DEFECT); do NOT add the letter "
                        "to the verdict vocabulary"),
                })
                continue
            violations.append({
                "id": rid, "rule": "unknown_verdict", "verdict": verdict,
                "detail": (f"verdict {verdict!r} is not a recognised "
                           "convergence verdict (AI-solvable set or "
                           "TRUE_FLOOR / DATASET_DEFECT)"),
            })
            continue

        # An AI that demonstrably solved it blind is AI-solvable regardless of
        # the verdict label — this stops a FLOOR label laundering a solved fail.
        ai_solvable = verdict in AI_SOLVABLE_VERDICTS or blind is True

        if verdict in EXEMPT_VERDICTS and blind is not True:
            # ORGANIC #812 r2 (§4.05) — a PRESENT-BUT-UNPARSEABLE blind result
            # cannot certify ANY exempt verdict: the string `"solved on retry"`
            # carries the same fact as `independent_blind_passes: true` (the AI
            # solved it blind) but slips past the bool guard. Treat an ambiguous
            # blind result as a hard violation for both TRUE_FLOOR and
            # DATASET_DEFECT — fail-safe, never launder a possibly-solved fail.
            if blind_present_unparseable:
                violations.append({
                    "id": rid, "rule": "exempt_blind_unparseable",
                    "verdict": verdict,
                    "detail": ("independent_blind_passes is present but not a "
                               "parseable true/false — an exempt verdict "
                               "(TRUE_FLOOR/DATASET_DEFECT) cannot be certified "
                               "by an ambiguous blind result; emit a bool"),
                })
                continue
            # candidate exemption — must carry floor evidence
            if not floor_ev:
                violations.append({
                    "id": rid, "rule": "floor_without_evidence",
                    "verdict": verdict,
                    "detail": (f"{verdict} is absorption-exempt ONLY with "
                               "`floor_evidence` (a TRUE_FLOOR/DATASET_DEFECT "
                               "label without evidence cannot dodge a hard "
                               "solve)"),
                })
                continue
            if verdict == TRUE_FLOOR and blind is None:
                # TRUE_FLOOR demands the blind solve actually have been run AND
                # failed; an absent blind result cannot certify a floor.
                violations.append({
                    "id": rid, "rule": "true_floor_blind_absent",
                    "verdict": verdict,
                    "detail": ("TRUE_FLOOR requires independent_blind_passes"
                               "==false (the AI must have TRIED and FAILED); "
                               "the blind result is absent"),
                })
                continue
            exempt.append(rid)
            continue

        if verdict == TRUE_FLOOR and blind is True:
            # contradiction: labelled floor but the blind solve passed
            violations.append({
                "id": rid, "rule": "true_floor_blind_passed",
                "verdict": verdict,
                "detail": ("TRUE_FLOOR but independent_blind_passes==true — the "
                           "AI solved it blind, so it is NOT a floor; absorb "
                           "the recovery (program or AI+gate)"),
            })
            continue

        # AI-solvable → must be absorbed.
        if ai_solvable:
            if not absorb:
                rule = ("blind_pass_unabsorbed" if blind is True
                        else "unabsorbed_ai_solvable")
                violations.append({
                    "id": rid, "rule": rule, "verdict": verdict,
                    "independent_blind_passes": blind,
                    "detail": ("AI-solvable fail MUST carry an `absorption_ref` "
                               "(a program-rule patch id OR a gated-AI-step + "
                               "test reference) — a RECOVERABLE_AUTHORING / "
                               "AUTHORING label is NOT a free pass to skip"),
                })
                continue
            absorbed.append(rid)
            continue

        # Fallthrough: a DATASET_DEFECT with blind True but evidence present is
        # handled above (exempt). Any other shape is a logic gap — flag it.
        violations.append({
            "id": rid, "rule": "unclassified",
            "verdict": verdict,
            "detail": "record did not match any absorption/exemption rule",
        })

    n_v = len(violations)
    return {
        "program": "benchmark_triage_absorption_audit",
        "n_records": len(records),
        "n_absorbed": len(absorbed),
        "n_exempt": len(exempt),
        "absorbed": absorbed,
        "exempt": exempt,
        "violations": violations,
        "n_violations": n_v,
        "verdict": "PASS" if n_v == 0 else "FAIL",
    }


# ── CLI ─────────────────────────────────────────────────────────────────────
def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description=("Convergence-bar audit: every AI-solvable benchmark fail "
                     "MUST be absorbed (program rule OR AI-step-gated-by-"
                     "program); a TRUE_FLOOR/DATASET_DEFECT exemption requires "
                     "evidence. open-benchmark-methodology § 4.2."),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=("verdict vocabulary:\n"
                "  AI-solvable (need absorption_ref): "
                + ", ".join(sorted(AI_SOLVABLE_VERDICTS)) + "\n"
                "  exempt (need floor_evidence): "
                + ", ".join(sorted(EXEMPT_VERDICTS))))
    ap.add_argument("triage_json",
                    help="path to the triage-result JSON (list or {records:[...]})")
    ap.add_argument("--json", help="write the JSON audit report to this path")
    a = ap.parse_args(argv)

    path = Path(a.triage_json)
    try:
        records = load_records(path)
    except AuditInputError as e:
        report = {"program": "benchmark_triage_absorption_audit",
                  "path": str(path), "verdict": "IO_ERROR", "reason": str(e)}
        _emit(a, report)
        print(f"IO ERROR: {e}", file=sys.stderr)
        return 2

    report = audit_records(records)
    report["path"] = str(path)
    _emit(a, report)

    if report["verdict"] == "PASS":
        print(f"PASS: {report['n_records']} fail(s) — {report['n_absorbed']} "
              f"absorbed, {report['n_exempt']} floor/defect-exempt; every "
              "AI-solvable fail carries an absorption_ref (§ 4.2 convergence)")
        return 0

    print(f"FAIL: {report['n_violations']} un-converged fail(s) in "
          f"{report['n_records']} record(s):", file=sys.stderr)
    for v in report["violations"]:
        print(f"  VIOLATION [{v['rule']}] {v['id']} "
              f"(verdict={v.get('verdict')}): {v['detail']}", file=sys.stderr)
    return 1


def _emit(a, report: Dict[str, Any]) -> None:
    if getattr(a, "json", None):
        Path(a.json).parent.mkdir(parents=True, exist_ok=True)
        Path(a.json).write_text(json.dumps(report, indent=2), encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
