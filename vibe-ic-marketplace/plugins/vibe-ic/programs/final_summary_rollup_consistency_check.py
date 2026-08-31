#!/usr/bin/env python3
"""final_summary_rollup_consistency_check.py — one document, one blocking-failure
count (ORGANIC #428).

THE CLASS
---------
`reports/final_summary.md` carries TWO verdict roll-ups over the SAME step
universe:

  (1) the `flow_compliance_check.py` tally quoted verbatim inside the
      ```-fence under **Verdict** —
      `PASS=35  FAIL=0  MISSING=0  WAIVED-DEFERRED=3  SKIPPED=22  VACUOUS-PASS=3`
      — which is the line `reports/audit/phase23_completion_audit.json`
      serialises `step_counts` from; and
  (2) the `### Verdict roll-up` table lower in the same file, which
      `final_report_generate.py` recomputes per-step from the same audit
      text.

They are supposed to be two views of one measurement. They are NOT two
questions: neither carries a qualifier, both print the same `Total`, and
`FAIL` in both means the same thing — the field that decides whether a
cell may be called converged. So a disagreement is always a defect, and
it is the invisible kind: the deltas cancel (a step moved out of PASS is
a step moved into MISSING), the totals still match, and each roll-up is
internally plausible on its own.

MEASURED (the shape that motivated this gate)
---------------------------------------------
On a real `spm × sky130A` run the recompute reported FAIL=3 / MISSING=6
while the quoted tally — three lines above it in the same file — and the
audit JSON both said FAIL=4 / MISSING=1. Root cause: the renderer's
verdict-line matcher enumerated only the `<n>` / `A<n>` / `M<n>` / `P0`
step-id shapes, so the flow's other lettered ids (`D1`, `FS1`, `DT1`,
`DT2`, `DT3`) matched nothing and their real verdicts — measured here as
VACUOUS-PASS, PASS, PASS, SKIPPED-CONDITION, PASS — were each defaulted
into the compliance bucket `MISSING`. A parse gap wearing a verdict's
name.

WHAT THIS GATE CHECKS
---------------------
`--repo` (DEFAULT, and what CI runs — needs no design, no PDK, no run dir)
    Every step id declared in `flow/phase1_phase2_phase3.yaml` must be
    readable by `final_report_generate._parse_verdicts`. This is the
    static invariant whose breach produced the disagreement, and it
    fires the moment a new id shape is added to the flow — before any
    run renders a wrong number.

`--project <run dir>`
    Compare roll-up (2) against tally (1) **inside one rendered
    `final_summary.md`**. Both are printed by a single render from a
    single `audit_text`, so this comparison can never be a stale-file
    artefact — unlike comparing a summary on disk against an audit JSON
    that a later or earlier render wrote. Any per-bucket disagreement is
    a FAIL. A renderer-emitted "Roll-up reconciliation FAILED" note is
    also a FAIL: the document declaring its own inconsistency does not
    make the inconsistency acceptable.

    `--check-audit-json` additionally compares against
    `reports/audit/phase23_completion_audit.json[step_counts]`. It is
    OFF by default and deliberately so: those are two files written by
    two invocations, so a mismatch there can mean "stale pair" as easily
    as "wrong count", and a gate that cannot tell those apart is a gate
    nobody can act on. The in-file check has no such ambiguity.

chip-AGNOSTIC: step ids, verdict buckets and markdown structure only —
no vendor, SKU, PDK or IC name is read or matched anywhere.

Exit: 0 = PASS, 1 = FAIL.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))

import final_report_generate as _frg  # noqa: E402

PLUGIN_ROOT = _HERE.parent
DEFAULT_FLOW = PLUGIN_ROOT / "flow" / "phase1_phase2_phase3.yaml"

# Bucket labels as the `### Verdict roll-up` table prints them, mapped to
# the canonical names `_parse_audit_tally` returns.
_TABLE_LABEL_TO_BUCKET = dict(_frg._TALLY_LABEL_TO_BUCKET)
_TABLE_LABEL_TO_BUCKET[_frg.NO_VERDICT] = _frg.NO_VERDICT
# `phase23_completion_audit.json` spells the vacuous bucket with an
# underscore and the waiver bucket without its `-DEFERRED` suffix.
_AUDIT_JSON_KEY_TO_BUCKET = {
    "PASS": "PASS",
    "FAIL": "FAIL",
    "MISSING": "MISSING",
    "WAIVED": "WAIVED-DEFERRED",
    "DEFERRED-BY-UPSTREAM": "DEFERRED-BY-UPSTREAM",
    "SKIPPED-CONDITION": "SKIPPED-CONDITION",
    "SKIPPED-SETUP-REQUIRED": "SKIPPED-SETUP-REQUIRED",
    "VACUOUS_PASS": "VACUOUS-PASS",
    "PARTIALLY-VACUOUS": "PARTIALLY-VACUOUS",
    "STRUCTURE-ONLY": "STRUCTURE-ONLY",
    "INCOMPLETE": "INCOMPLETE",
    "PASS_VOIDED_BY_DEPENDENCY": "PASS-VOIDED-BY-DEPENDENCY",
    "OUT-OF-SCOPE-BY-ENTRY": "OUT-OF-SCOPE-BY-ENTRY",
}

RECONCILIATION_FAILED_MARKER = "Roll-up reconciliation FAILED"


# ─── repo mode: every declared step id must be readable ──────────────────

def load_flow_step_ids(flow_path: Path) -> List[str]:
    """Step ids declared by the flow definition, in declaration order."""
    import yaml  # imported lazily: repo mode only
    data = yaml.safe_load(flow_path.read_text(encoding="utf-8"))
    return [str(s["id"]) for s in (data or {}).get("steps", [])]


def unreadable_step_ids(step_ids: List[str]) -> List[str]:
    """Ids whose verdict line `final_report_generate` cannot parse.

    Synthesises one verdict line per id in exactly the shape
    `flow_compliance_check.py` prints, then asks the REAL parser to read
    it back. Deriving the answer from the live parser (never from a
    copy of its regex) is what keeps this gate honest if the parser
    changes.
    """
    lines = [f"  x [{'PASS':<17}] Step {sid:>2}: synthetic  (stage)"
             for sid in step_ids]
    parsed = _frg._parse_verdicts("\n".join(lines))
    return [sid for sid in step_ids if sid not in parsed]


def check_repo(flow_path: Path) -> Tuple[bool, List[str]]:
    notes: List[str] = []
    if not flow_path.is_file():
        return False, [f"FAIL: flow definition not found: {flow_path}"]
    step_ids = load_flow_step_ids(flow_path)
    if not step_ids:
        return False, [f"FAIL: flow definition declares no steps: {flow_path}"]
    bad = unreadable_step_ids(step_ids)
    notes.append(f"flow: {flow_path}")
    notes.append(f"steps declared: {len(step_ids)}")
    if bad:
        notes.append(
            f"FAIL: {len(bad)} step id(s) cannot be read by "
            f"final_report_generate._parse_verdicts: {', '.join(bad)}")
        notes.append(
            "      Their real verdicts would never reach the roll-up; each "
            f"would be booked as `{_frg.NO_VERDICT}`, so the roll-up table "
            "and the flow_compliance_check tally quoted in the same report "
            "would disagree on PASS / FAIL / MISSING by that many steps.")
        return False, notes
    notes.append("PASS: every declared step id is readable by the verdict parser.")
    return True, notes


# ─── project mode: one document, one count ───────────────────────────────

def parse_rollup_table(summary_text: str) -> Optional[Dict[str, int]]:
    """Counts from the `### Verdict roll-up` table (excluding **Total**)."""
    i = summary_text.find("### Verdict roll-up")
    if i < 0:
        return None
    seg = summary_text[i:]
    end = seg.find("\n## ", 1)
    if end > 0:
        seg = seg[:end]
    out: Dict[str, int] = {}
    for m in re.finditer(r"^\|\s*(?:\S+\s+)?([A-Z][A-Z_-]*[A-Z])\s*\|\s*(\d+)\s*\|",
                         seg, re.M):
        bucket = _TABLE_LABEL_TO_BUCKET.get(m.group(1))
        if bucket is not None:
            out[bucket] = int(m.group(2))
    return out or None


def parse_rollup_total(summary_text: str) -> Optional[int]:
    i = summary_text.find("### Verdict roll-up")
    if i < 0:
        return None
    m = re.search(r"^\|\s*\*\*Total\*\*\s*\|\s*\*\*(\d+)\*\*\s*\|",
                  summary_text[i:], re.M)
    return int(m.group(1)) if m else None


def compare_buckets(left: Dict[str, int], right: Dict[str, int],
                    ) -> Dict[str, Tuple[int, int]]:
    """Per-bucket disagreement over the union of the two bucket sets."""
    return {b: (left.get(b, 0), right.get(b, 0))
            for b in sorted(set(left) | set(right))
            if left.get(b, 0) != right.get(b, 0)}


def check_project(project: Path, check_audit_json: bool = False,
                  ) -> Tuple[bool, List[str]]:
    notes: List[str] = []
    summary = project / "reports" / "final_summary.md"
    if not summary.is_file():
        return False, [f"FAIL: no rendered summary at {summary}"]
    text = summary.read_text(encoding="utf-8", errors="replace")
    notes.append(f"summary: {summary}")

    ok = True
    if RECONCILIATION_FAILED_MARKER in text:
        ok = False
        notes.append(
            "FAIL: the report declares its own roll-up reconciliation "
            "FAILED. A document naming its inconsistency is still an "
            "inconsistent document.")

    tally = _frg._parse_audit_tally(text)
    table = parse_rollup_table(text)
    if tally is None:
        # Not a pass: an unverifiable report is not a verified one.
        notes.append(
            "FAIL: the summary quotes no flow_compliance_check tally line, "
            "so its roll-up table cannot be cross-checked against the "
            "measurement it claims to summarise.")
        return False, notes
    if table is None:
        notes.append("FAIL: the summary has no `### Verdict roll-up` table.")
        return False, notes

    notes.append(f"quoted checker tally : {json.dumps(tally, sort_keys=True)}")
    notes.append(f"rendered roll-up table: {json.dumps(table, sort_keys=True)}")
    diff = compare_buckets(table, tally)
    if diff:
        ok = False
        notes.append(
            "FAIL: the roll-up table disagrees with the checker tally "
            "quoted in the SAME file, over the same steps of the same "
            "audit run:")
        for bucket, (t_n, c_n) in diff.items():
            notes.append(f"       {bucket}: table={t_n} checker={c_n}")
    else:
        notes.append("PASS: roll-up table == quoted checker tally, bucket by bucket.")

    total = parse_rollup_total(text)
    if total is not None:
        summed = sum(table.values())
        if summed != total:
            ok = False
            notes.append(
                f"FAIL: the roll-up rows sum to {summed} but the table "
                f"prints Total={total} — {total - summed} step(s) are in "
                f"the universe but in no printed bucket.")
        else:
            notes.append(f"PASS: roll-up rows sum to the printed Total={total}.")

    if check_audit_json:
        aj = project / "reports" / "audit" / "phase23_completion_audit.json"
        if not aj.is_file():
            notes.append(f"FAIL: --check-audit-json but no {aj}")
            ok = False
        else:
            raw = (json.loads(aj.read_text(encoding="utf-8", errors="replace"))
                   .get("step_counts") or {})
            js = {_AUDIT_JSON_KEY_TO_BUCKET[k]: v for k, v in raw.items()
                  if k in _AUDIT_JSON_KEY_TO_BUCKET}
            jdiff = compare_buckets(table, js)
            notes.append(f"audit JSON step_counts: {json.dumps(js, sort_keys=True)}")
            if jdiff:
                ok = False
                notes.append("FAIL: the roll-up table disagrees with "
                             "phase23_completion_audit.json[step_counts]:")
                for bucket, (t_n, j_n) in jdiff.items():
                    notes.append(f"       {bucket}: table={t_n} audit_json={j_n}")
            else:
                notes.append("PASS: roll-up table == audit JSON step_counts.")

    return ok, notes


# ─── CLI ─────────────────────────────────────────────────────────────────

def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description=("Guard that final_summary.md reports ONE blocking-failure "
                     "count (ORGANIC #428)."))
    ap.add_argument("--project", type=Path, default=None,
                    help="Run directory to audit (checks the rendered "
                         "reports/final_summary.md). Omit for repo mode.")
    ap.add_argument("--flow", type=Path, default=DEFAULT_FLOW,
                    help="Flow definition YAML for repo mode "
                         "(default: %(default)s).")
    ap.add_argument("--check-audit-json", action="store_true",
                    help="Also compare the roll-up against "
                         "reports/audit/phase23_completion_audit.json"
                         "[step_counts]. Off by default: those are two files "
                         "from two invocations, so a mismatch can mean a "
                         "stale pair rather than a wrong count.")
    args = ap.parse_args(argv)

    if args.project is not None:
        ok, notes = check_project(args.project,
                                  check_audit_json=args.check_audit_json)
        label = "final-summary roll-up consistency (project)"
    else:
        ok, notes = check_repo(args.flow)
        label = "final-summary roll-up consistency (repo)"

    print(f"=== {label} ===")
    for n in notes:
        print(f"  {n}")
    print(f"Overall: {'PASS' if ok else 'FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
