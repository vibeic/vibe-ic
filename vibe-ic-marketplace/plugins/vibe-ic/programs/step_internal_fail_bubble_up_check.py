#!/usr/bin/env python3
"""
step_internal_fail_bubble_up_check.py — anti-fabrication gate (v1.6.44).

Doctrine rule #4: a step-internal sub-gate `verdict: FAIL` (or MISSING)
MUST bubble up to the project's overall verdict — either by being
explicitly waived in `waivers.json`, or by causing the parent step's
`pass.flag` to be absent. Silently keeping `pass.flag` while a
`reports/**/*.json` declares FAIL is the fabrication shape this gate
catches.

Real-world inspiration (from v1.6.36 review):
  `flow_compliance_check.py` evaluates each step's `pass.flag` and
  classifies the project as PASS / PASS_WITH_WAIVERS / FAIL. It does
  NOT walk the per-step report JSON. So a step can ship pass.flag
  while one of its sub-reports declares verdict=FAIL — the project
  shows green but the substantive evidence says otherwise.

Audit shape (chip-AGNOSTIC, no per-step ID hardcoded)
-----------------------------------------------------
For every `reports/**/*.json` whose `verdict` field is in
{FAIL, MISSING}:

  1. Derive a set of "name candidates" from the report's filepath:
     basename without extension, basename split on `_`, parent
     directory name. Example for `reports/phase3/ir_drop.json`:
     candidates = {ir_drop, ir, drop, phase3, ir-drop, ir drop}.

  2. Acknowledge the FAIL by either:

     (a) WAIVER MATCH — `waivers.json::waived_steps[*]` contains an
         entry whose `reason`, `ticket`, or `evidence` text mentions
         any candidate (case-insensitive, normalised across `_`/`-`/space).

     (b) BUBBLED — any other JSON under `reports/orchestrator/` or
         `reports/<phase>/<pass.flag-anchored-step>/` records a
         matching FAIL/MISSING verdict for the same name.

  3. If neither (a) nor (b), flag `STEP_FAIL_NOT_BUBBLED`.

Files audited:
  reports/**/*.json  (excluding files inside reports/audit/ which are
                     human-authored review artefacts)

Files used as evidence of bubble-up:
  reports/orchestrator/*.json
  reports/audit/*.json
  reports/phase23_completion_audit.json (if present)

NOT_EXAMINED conditions (rc=2, never a pass — vibe-ic#693 follow-up):
  * no `reports/` tree on disk → pre-output project
  * `reports/` exists but no file in it declares a verdict

Both mean NOTHING WAS EXAMINED. Through v1.9.62 they returned rc=0 printing
`VACUOUS_PASS`, which put them in the same exit class as a genuine clean run
over a hundred reports — and a step that crashed before writing any report
produces exactly this. The denominator is now disclosed on every pass, so
"no FAIL/MISSING reports" can no longer be read without knowing how many
reports that was over.

Usage:
    python3 step_internal_fail_bubble_up_check.py <project_dir>
                                                   [--json <out>]

Exit codes:
    0  PASS — reports were examined and every FAIL/MISSING one is acknowledged
    1  FAIL — at least one FAIL report is not bubbled / waivered
    2  NOT EXAMINED (nothing to look at), or argument / I/O error

chip-AGNOSTIC. No vendor / IC / specific filename hardcoded.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple


_FAIL_VERDICTS = {"FAIL", "MISSING"}

# Verdict tokens we treat as "honestly accounted for already" — don't
# flag them at all. These are explicit non-PASS but the report itself
# self-declares the gap; the runner-level enforcement is the gate's
# concern, not this audit.
_NEUTRAL_VERDICTS = {
    "INSUFFICIENT_DATA",  # honest "tool did not run / data missing"
    "VACUOUS_PASS",        # gate inapplicable
    "SKELETON_EMITTED",    # placeholder marker
    "FALLBACK",            # alt-path used; orthogonal to bubble-up
    "WARN", "WARNING",
    "WAIVED", "WAIVED_DEFERRED",
}


@dataclass
class BubbleFinding:
    rule: str
    report_file: str
    verdict: str
    name_candidates: List[str]
    detail: str = ""


def _normalise(s: str) -> str:
    """Lower-case + collapse `_` / `-` / whitespace to a single space."""
    return re.sub(r"[\s_\-]+", " ", s.strip().lower())


def _name_candidates(report_path: Path, project: Path) -> Set[str]:
    """Derive name candidates that a waiver / bubble-up record might
    use to identify this report."""
    cand: Set[str] = set()
    stem = report_path.stem
    cand.add(stem)
    cand.add(_normalise(stem))
    # Split on `_` and `-`
    for tok in re.split(r"[_\-]", stem):
        if len(tok) >= 3:
            cand.add(tok.lower())
    # Parent directory name (e.g. phase3 / phase2 / orchestrator)
    parent = report_path.parent.name
    if parent and parent not in {"reports", "."}:
        cand.add(parent.lower())
    return cand


def _read_json(p: Path) -> Optional[Any]:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _waiver_text_corpus(project: Path) -> str:
    """Concatenate searchable text from every waiver entry. Used to
    test name-candidate substring matches."""
    waivers_path = project / "waivers.json"
    if not waivers_path.is_file():
        return ""
    d = _read_json(waivers_path)
    if not isinstance(d, dict):
        return ""
    parts: List[str] = []
    parts.append(str(d.get("_doc", "")))
    for entry in d.get("waived_steps", []) or []:
        if not isinstance(entry, dict):
            continue
        for k in ("reason", "ticket", "evidence", "approver",
                  "rationale", "note", "notes"):
            v = entry.get(k)
            if isinstance(v, str):
                parts.append(v)
        # Step ID itself can match like "step29" / "step 29" / "step-29"
        sid = entry.get("id")
        if sid is not None:
            parts.append(f"step{sid} step {sid} step-{sid}")
    return _normalise(" | ".join(parts))


def _bubbled_corpus(project: Path) -> str:
    """Concatenate searchable text from orchestrator + completion-audit
    JSONs. A FAIL report is "bubbled up" if a top-level audit also
    records the failure for the same name."""
    parts: List[str] = []
    candidates: List[Path] = []
    odir = project / "reports" / "orchestrator"
    if odir.is_dir():
        candidates.extend(sorted(odir.rglob("*.json")))
    audit_dir = project / "reports" / "audit"
    if audit_dir.is_dir():
        candidates.extend(sorted(audit_dir.rglob("*.json")))
    cad = project / "reports" / "phase23_completion_audit.json"
    if cad.is_file():
        candidates.append(cad)
    for p in candidates:
        try:
            txt = p.read_text(encoding="utf-8")
        except OSError:
            continue
        # Only include lines that look like they reference a FAIL.
        for line in txt.splitlines():
            ll = line.lower()
            if "fail" in ll or "missing" in ll:
                parts.append(line)
    return _normalise("\n".join(parts))


def _candidate_in_corpus(cand: str, corpus: str) -> bool:
    """Word-bounded substring match. Avoids `ir` matching `dir`."""
    if len(cand) < 3:
        return False
    pat = r"(?<![a-z0-9])" + re.escape(cand) + r"(?![a-z0-9])"
    return re.search(pat, corpus) is not None


def _iter_report_files(project: Path) -> List[Path]:
    """All reports/**/*.json EXCEPT reports/audit/ (human-authored)
    and reports/orchestrator/ (top-level audit, used for bubble-up
    evidence — not a leaf report we audit)."""
    rdir = project / "reports"
    if not rdir.is_dir():
        return []
    out: List[Path] = []
    for p in sorted(rdir.rglob("*.json")):
        rel = p.relative_to(project)
        # Exclude human-authored / aggregation files
        if rel.parts[1] in ("audit", "orchestrator"):
            continue
        out.append(p)
    return out


def audit(project: Path) -> Tuple[str, List[BubbleFinding], int]:
    """Returns (verdict, findings, examined) — `examined` is the DENOMINATOR:
    how many report files actually carried a readable verdict.

    It is returned because without it "no FAIL/MISSING reports" is the same
    sentence whether a hundred reports were read and all were clean, or the
    step crashed before writing any report at all. The second is the state this
    gate exists to notice, and it was the one that read as a pass."""
    if not project.is_dir():
        return "NOT_EXAMINED", [], 0
    if not (project / "reports").is_dir():
        return "NOT_EXAMINED", [], 0

    waiver_text = _waiver_text_corpus(project)
    bubbled_text = _bubbled_corpus(project)

    findings: List[BubbleFinding] = []
    saw_any_fail = False
    examined = 0

    for rp in _iter_report_files(project):
        d = _read_json(rp)
        if not isinstance(d, dict):
            continue
        verdict_raw = d.get("verdict")
        if not isinstance(verdict_raw, str):
            continue
        examined += 1
        verdict = verdict_raw.strip().upper()
        if verdict in _NEUTRAL_VERDICTS:
            continue
        if verdict not in _FAIL_VERDICTS:
            continue
        saw_any_fail = True

        cands = _name_candidates(rp, project)
        # (a) waiver match
        waiver_ok = any(_candidate_in_corpus(_normalise(c), waiver_text)
                        for c in cands)
        # (b) bubble-up match
        bubbled_ok = any(_candidate_in_corpus(_normalise(c), bubbled_text)
                         for c in cands)

        if waiver_ok or bubbled_ok:
            continue

        rel = rp.relative_to(project)
        findings.append(BubbleFinding(
            rule="STEP_FAIL_NOT_BUBBLED",
            report_file=str(rel),
            verdict=verdict,
            name_candidates=sorted(cands),
            detail=("report declares verdict=" + verdict +
                    " but no waivers.json entry references it AND no "
                    "orchestrator / completion-audit JSON records the "
                    "matching FAIL. Either: add a waivers.json entry "
                    "for this artefact, or remove the surrounding step's "
                    "pass.flag so the project's overall verdict reflects "
                    "the failure."),
        ))

    if examined == 0:
        # `reports/` exists but nothing in it declares a verdict. Nothing was
        # examined, so there is no result — not a clean one.
        return "NOT_EXAMINED", [], 0
    if not saw_any_fail:
        # A REAL pass over a REAL population: reports were read and none of
        # them declares a FAIL, so the property holds. Formerly returned as
        # VACUOUS_PASS, which is this repo's word for a verdict issued over
        # nothing — and it collapsed into the same rc as the genuinely empty
        # case above.
        return "PASS", [], examined
    return ("FAIL" if findings else "PASS"), findings, examined


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Doctrine rule #4 — every step-internal "
                    "verdict=FAIL must be acknowledged (waivered or "
                    "bubbled up).")
    ap.add_argument("project_dir")
    ap.add_argument("--json", help="write JSON report to this path")
    args = ap.parse_args(argv)

    proj = Path(args.project_dir).resolve()
    if not proj.is_dir():
        print(f"error: not a directory: {proj}", file=sys.stderr)
        return 2

    verdict, findings, examined = audit(proj)
    report = {
        "gate": "step_internal_fail_bubble_up_check",
        "verdict": verdict,
        "project": str(proj),
        "reports_examined": examined,
        "findings_count": len(findings),
        "findings": [asdict(f) for f in findings[:200]],
    }
    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(json.dumps(report, indent=2) + "\n")

    if verdict == "NOT_EXAMINED":
        why = ("no reports/ tree (pre-output project)"
               if not (proj / "reports").is_dir()
               else "reports/ exists but no file in it declares a verdict")
        print(f"[CANNOT DETERMINE] step_internal_fail_bubble_up: {why}, so no "
              f"report was examined. NOT a pass — a step that crashed before "
              f"writing its report produces exactly this, and it is the state "
              f"this gate exists to notice.", file=sys.stderr)
        return 2
    if verdict == "PASS":
        print(f"PASS: {examined} report(s) examined; every FAIL/MISSING one is "
              f"acknowledged (waivered or bubbled up)")
        return 0
    print(f"FAIL: {len(findings)} unacknowledged step-internal "
          "FAIL(s):", file=sys.stderr)
    for f in findings[:10]:
        print(f"  [{f.rule}] {f.report_file}  verdict={f.verdict}",
              file=sys.stderr)
    if len(findings) > 10:
        print(f"  … and {len(findings) - 10} more", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
