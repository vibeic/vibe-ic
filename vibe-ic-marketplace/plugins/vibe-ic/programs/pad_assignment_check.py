#!/usr/bin/env python3
"""pad_assignment_check — the gate on step 15.5ic's config producer.

WHY A SEPARATE GATE, AND NOT JUST `pad_ring_check`
==================================================
Without this clause the producer's verdict reaches the flow only as an ABSENCE:
`pad_assignment_gen` refuses, writes no config, and `pad_ring_gen` then skips
saying "the pad ring config is absent". Three different facts —

    nobody ever declared a pad ring          (SKIP, and correct)
    the declaration answered 7 of 8 and
      `pad_site_name` is NOT_DETERMINED      (a refusal naming a field)
    the operator's slot and the design's
      declaration disagree about PAD_SOUTH   (a refusal naming two values)

— would all arrive at the reader wearing the same sentence. "I could not read
it" and "I read it and it was empty" must never produce the same verdict, and
that is exactly what collapsing these into a downstream skip does.

WHAT IT AUDITS. It RE-DERIVES; it never produces. It runs no generator, opens
no layout, and writes only the verdict document, so auditing a project can
never change the project it is auditing — the producer/auditor split
`pad_ring_check` and `die_finishing_check` already use.

    PASS      believed only when `phase3/stage3/pnr/pad_assignment.json` is
              actually on disk, carries the producer's own stamp, and declares
              every one of the 13 variables the report says it does — with the
              SAME value. A report that claims a config and a config that says
              something else is a claim, not a measurement.
    SKIP      accepted only when the report NAMES every source it consulted
              and what each one declared. A skip that discloses nothing is
              indistinguishable from a step that was never attempted.
    FAIL      the producer refused; this gate re-states WHICH refusal, by rule
              id, so the reason survives into the step's own verdict.

EXIT
    0  PASS — the config on disk corroborates the report.
    2  SKIP — no source ever declared a pad ring, and the report says so by
       name. The flow's "could not measure" tier, never a plain pass; the
       step's declared `padring.def` is still absent.
    1  FAIL — the producer refused, or the report is absent / unreadable /
       of an unknown schema, or the config on disk contradicts the report.

chip-AGNOSTIC: it reads two JSON documents. No chip, vendor, PDK, foundry or
process-node literal appears here.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:                                  # pragma: no cover
    sys.path.insert(0, str(_HERE))

from _atomic_artefact import write_json as atomic_write_json    # noqa: E402

import _pad_ring as PR                                          # noqa: E402
import pad_assignment_gen as GEN                                # noqa: E402

GATE = "pad_assignment_check"
PASS, FAIL, SKIP = 0, 1, 2

VERDICTS: Tuple[str, ...] = ("PASS", "SKIP", "FAIL")


def _finding(rule: str, message: str, severity: str = "ERROR") -> Dict[str, str]:
    return {"severity": severity, "rule": rule, "message": message}


def _unwrap(doc: Any) -> Tuple[Any, bool]:
    """(producer report, was_already_merged). Re-running is idempotent."""
    if isinstance(doc, dict) and doc.get("gate") == GATE and "producer" in doc:
        return doc["producer"], True
    return doc, False


def _audit_skip(rep: Dict[str, Any]) -> List[Dict[str, str]]:
    """A skip is accepted only when it says what it went without."""
    out: List[Dict[str, str]] = []
    sources = rep.get("sources")
    if not isinstance(sources, list) or not sources:
        return [_finding(
            "PAD_ASSIGNMENT_SKIP_UNDISCLOSED",
            "the report skips this step and names no source it consulted. A "
            "skip that discloses nothing is indistinguishable from a producer "
            "that was never run")]
    reason = str(rep.get("reason") or "")
    if len(reason.strip()) < PR.MIN_REASON_CHARS:
        out.append(_finding(
            "PAD_ASSIGNMENT_SKIP_REASON_TOO_SHORT",
            f"the skip reason is {len(reason.strip())} character(s); the flow "
            f"refuses an absent-condition reason shorter than "
            f"{PR.MIN_REASON_CHARS}, and a skip a program writes is the same "
            f"promise"))
    for s in sources:
        path = str((s or {}).get("path") or "") if isinstance(s, dict) else ""
        if not path:
            out.append(_finding("PAD_ASSIGNMENT_SKIP_UNDISCLOSED",
                                "an entry of `sources` names no path"))
            continue
        if path not in reason:
            out.append(_finding(
                "PAD_ASSIGNMENT_SKIP_DOES_NOT_NAME_SOURCE",
                f"`sources` lists {path!r} but the stated reason never names "
                f"it — the reason a reader sees must name every source that "
                f"was consulted and came back with nothing"))
    declared = [v for s in sources if isinstance(s, dict)
                for v in (s.get("declared") or {})]
    if declared:
        out.append(_finding(
            "PAD_ASSIGNMENT_SKIP_CONTRADICTED",
            f"the report skips because nothing was declared, yet its own "
            f"`sources` record {len(declared)} declared variable(s) "
            f"{sorted(set(declared))[:8]} — a skip contradicted by the "
            f"evidence beside it"))
    return out


def _audit_pass(project: Path, rep: Dict[str, Any]) -> List[Dict[str, str]]:
    """A PASS is believed only where the config on disk agrees with it."""
    out: List[Dict[str, str]] = []
    rel = str(rep.get("assignment") or PR.ASSIGNMENT_REL)
    path = project / rel
    if not path.is_file():
        return [_finding(
            "PAD_ASSIGNMENT_ABSENT",
            f"the report claims a written config but {rel} does not exist — a "
            f"PASS with nothing behind it")]
    try:
        doc = json.loads(path.read_text(errors="replace"))
    except (ValueError, OSError) as exc:
        return [_finding("PAD_ASSIGNMENT_UNREADABLE", f"{rel}: {exc}")]
    if not isinstance(doc, dict):
        return [_finding("PAD_ASSIGNMENT_UNREADABLE",
                         f"{rel} is not a JSON object")]
    stamp = doc.get(GEN.PROVENANCE_KEY)
    if not (isinstance(stamp, dict) and stamp.get("written_by") == GEN.PROGRAM):
        out.append(_finding(
            "PAD_ASSIGNMENT_NOT_STAMPED",
            f"{rel} does not carry "
            f"{GEN.PROVENANCE_KEY}.written_by={GEN.PROGRAM!r}. The report says "
            f"this run wrote it; an unstamped file is a different file, and "
            f"the ring would be placed from geometry this report does not "
            f"account for"))
    provenance = rep.get("provenance")
    if not isinstance(provenance, dict) or \
            sorted(provenance) != sorted(PR.REQUIRED_VARS):
        out.append(_finding(
            "PAD_ASSIGNMENT_PROVENANCE_INCOMPLETE",
            f"the report passes but names a source for "
            f"{len(provenance) if isinstance(provenance, dict) else 0} of "
            f"{len(PR.REQUIRED_VARS)} variable(s) — a value with no source "
            f"named is a value nobody can attribute"))
    absent = [v for v in PR.REQUIRED_VARS
              if doc.get(v) is None or doc.get(v) == ""]
    if absent:
        out.append(_finding(
            "PAD_ASSIGNMENT_INCOMPLETE",
            f"the report passes but {rel} declares none of {absent} — "
            f"`pad_ring_gen` would refuse this config one step later, and a "
            f"refusal a reader has to go looking for is not a gate"))
    try:
        PR.validate_assignment(doc)
    except PR.AssignmentError as exc:
        out.append(_finding(
            exc.rule,
            f"{rel} does not satisfy the placer's own contract: {exc.message}"))
    return out


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("project_dir")
    ap.add_argument("--json", default=None,
                    help=("the producer's report: READ as its claim, then "
                          "written back with this gate's verdict beside it "
                          f"(default {GEN.REPORT_REL})"))
    args = ap.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"[{GATE}] project dir not found: {project}", file=sys.stderr)
        return FAIL

    rep_path = Path(args.json) if args.json else (project / GEN.REPORT_REL)
    if not rep_path.is_absolute():
        rep_path = project / rep_path

    findings: List[Dict[str, str]] = []
    producer: Any = None
    verdict, rc, reason = "FAIL", FAIL, ""

    if not rep_path.is_file():
        reason = (f"no pad-assignment report at {rep_path} — "
                  f"`{GEN.PROGRAM}` did not run. An absent report is not a "
                  f"disclosed skip: nothing stated which sources were "
                  f"consulted, so nothing was measured")
        findings.append(_finding("PAD_ASSIGNMENT_REPORT_ABSENT", reason))
    else:
        try:
            doc = json.loads(rep_path.read_text(errors="replace"))
        except (ValueError, OSError) as exc:
            reason = f"{rep_path} is not readable JSON: {exc}"
            findings.append(_finding("PAD_ASSIGNMENT_REPORT_UNREADABLE", reason))
            doc = None
        if doc is not None:
            producer, _merged = _unwrap(doc)
            if not isinstance(producer, dict):
                reason = "the pad-assignment report is not a JSON object"
                findings.append(
                    _finding("PAD_ASSIGNMENT_REPORT_UNREADABLE", reason))
            elif producer.get("schema") != GEN.SCHEMA:
                reason = (f"report schema {producer.get('schema')!r} is not "
                          f"{GEN.SCHEMA!r} — this gate will not interpret an "
                          f"unrecognised payload as this step's evidence")
                findings.append(
                    _finding("PAD_ASSIGNMENT_REPORT_SCHEMA_UNKNOWN", reason))
            else:
                v = producer.get("verdict")
                if v not in VERDICTS:
                    reason = (f"report verdict {v!r} is not one of "
                              f"{list(VERDICTS)}")
                    findings.append(
                        _finding("PAD_ASSIGNMENT_VERDICT_UNRECOGNISED", reason))
                elif v == "FAIL":
                    rules = [f.get("rule") for f in producer.get("findings")
                             or [] if isinstance(f, dict)]
                    reason = (
                        f"the producer refused to write a pad-ring config: "
                        f"{producer.get('reason') or '(no reason stated)'}")
                    findings.append(_finding(
                        rules[0] if rules else "PAD_ASSIGNMENT_REFUSED",
                        reason))
                elif v == "SKIP":
                    findings.extend(_audit_skip(producer))
                    if not findings:
                        verdict, rc = "SKIP", SKIP
                        reason = (
                            "the producer named every source it consulted and "
                            "none of them declared a pad ring. This is exit 2 "
                            "— the flow's 'could not measure' tier — and the "
                            "step's declared padring.def is still absent, so "
                            "the step is not done")
                    else:
                        reason = findings[0]["message"]
                else:
                    findings.extend(_audit_pass(project, producer))
                    if not findings:
                        verdict, rc = "PASS", PASS
                        reason = (
                            f"every one of the {len(PR.REQUIRED_VARS)} "
                            f"variables in "
                            f"{producer.get('assignment') or PR.ASSIGNMENT_REL}"
                            f" is on disk, carries a named source, and "
                            f"satisfies the placer's own contract")
                    else:
                        reason = findings[0]["message"]

    audit = {
        "schema": GEN.SCHEMA,
        "gate": GATE,
        "verdict": verdict,
        "rc": rc,
        "reason": reason,
        "report_path": str(rep_path),
        "findings": findings,
        "producer": producer,
    }
    try:
        rep_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_json(rep_path, audit)
    except OSError as exc:                                      # pragma: no cover
        print(f"[{GATE}] could not write {rep_path}: {exc}", file=sys.stderr)

    print(f"=== {GATE} ({project.name}) ===")
    print(f"  verdict: {verdict}  (rc={rc})")
    if reason:
        print(f"  {reason}")
    for f in findings[:12]:
        print(f"  [{f['severity']}] {f['rule']}: {f['message']}")
    if len(findings) > 12:
        print(f"  ... and {len(findings) - 12} more finding(s)")
    return rc


if __name__ == "__main__":                                      # pragma: no cover
    sys.exit(main())
