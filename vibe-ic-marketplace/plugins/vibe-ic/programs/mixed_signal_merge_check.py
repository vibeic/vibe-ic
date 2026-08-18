#!/usr/bin/env python3
"""
mixed_signal_merge_check.py — M1 gate (v0.2.84: SUBSTANCE, not presence).

M1 — A+D top-level GDS merge (no overlap, all macro pins on tracks)

v0.2.84 (flow-completeness review): the v1.6.13 PASS-on-presence stub
is RETIRED. A merged GDS is a CLAIM; the claim needs the top-level
LVS that `mixed_signal_top_lvs_run.py` executes (KLayout merge +
Magic extraction + real netgen compare). PASS now requires
`reports/analog/mixed_signal/top_lvs.json` with verdict PASS.

Behaviour
---------
* SKIP (rc=2) — top_merged.gds missing AND step not waived.
* WAIVED (rc=0) — `waivers.json` declares step waived (evidence + ticket).
* PASS (rc=0) — merged GDS present AND top-level LVS verdict PASS.
* FAIL (rc=1) — merged GDS present but top-level LVS missing or FAIL
  (presence is not substance).

chip-AGNOSTIC. No vendor / IC / tool-specific data hard-coded.

Usage
-----
    python3 mixed_signal_merge_check.py <project_dir> [--json <out>]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from _atomic_artefact import write_text as atomic_write_text  # vibe-ic#1082 (helper from PR #1094)


def _load_waivers(project):
    p = project / "waivers.json"
    if not p.is_file():
        return []
    try:
        return (json.loads(p.read_text()).get("waived_steps") or [])
    except Exception:
        return []


def _step_waived(project, step_label):
    for w in _load_waivers(project):
        sid = str(w.get("id", "")).strip()
        ticket = w.get("ticket", "")
        if sid == step_label or step_label in ticket:
            return w
    return None


_GATE_NAME = 'mixed_signal_merge_check'
_GATE_LABEL = 'mixed_signal_merge'
_REQUIRED_FILES = ['phase3/mixed_signal/top_merged.gds']
_WAIVER_RATIONALE = 'Top-level merge+LVS not runnable in this environment (see mixed_signal_top_lvs_run SKIP reason).'


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument("project_dir")
    parser.add_argument("--json", default=None)
    parser.add_argument("--step-label", default=_GATE_LABEL)
    args = parser.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"[{_GATE_NAME}] project dir not found: {project}", file=sys.stderr)
        return 2

    found = [p for p in _REQUIRED_FILES if list(project.glob(p))]
    missing = [p for p in _REQUIRED_FILES if p not in found]

    waiver = _step_waived(project, args.step_label)
    if missing and not waiver:
        verdict, rc = "SKIP", 2
        findings = [{"severity": "INFO", "rule": "REQUIRED_FILES_MISSING",
                      "message": f"missing: {missing}"}]
    elif missing and waiver:
        verdict, rc = "WAIVED", 0
        findings = [{"severity": "WAIVED", "rule": "STEP_WAIVED",
                      "message": f"waiver={waiver.get('ticket','?')}: {waiver.get('reason','?')}"}]
    else:
        # v0.2.84 — SUBSTANCE: the merged GDS must be LVS-substantiated
        # by mixed_signal_top_lvs_run (Magic extraction + real netgen
        # compare). Presence alone never PASSes again.
        top_lvs = None
        for rel in ("reports/analog/mixed_signal/top_lvs.json",
                     "reports/mixed_signal/top_lvs.json"):
            cand = project / rel
            if cand.is_file():
                try:
                    top_lvs = json.loads(cand.read_text(errors="replace"))
                except (OSError, ValueError):
                    top_lvs = {"verdict": "UNPARSEABLE"}
                break
        if top_lvs is None:
            verdict, rc = "FAIL", 1
            findings = [{"severity": "ERROR",
                          "rule": "MERGE_NOT_LVS_SUBSTANTIATED",
                          "message": ("top_merged.gds present but no "
                                      "top-level LVS result — run "
                                      "mixed_signal_top_lvs_run; a merge "
                                      "claim without LVS is presence, "
                                      "not substance (v0.2.84)")}]
        elif str(top_lvs.get("verdict")) == "PASS":
            verdict, rc = "PASS", 0
            findings = [{"severity": "INFO", "rule": "MERGE_LVS_OK",
                          "message": ("merged GDS present + top-level "
                                      "netgen LVS PASS "
                                      f"({top_lvs.get('lvs_report', '?')})")}]
        elif str(top_lvs.get("verdict")) == "SKIP":
            # vibe-ic#614 — a SKIP means NO COMPARISON WAS PERFORMED, and this
            # branch used to publish it as "the merged layout does not match
            # the schematic". That is a statement about the ENVIRONMENT
            # published as a statement about the DESIGN, and in `merge.json` it
            # was indistinguishable from a real mismatch: the same producer,
            # run where it can see the project, returns FAIL with
            # `compared: true` and a netgen report — a materially different
            # fact flattened into one message.
            #
            # Still non-PASS: a step that returned no verdict must not pass.
            # The producer's own reason travels verbatim rather than being
            # re-narrated.
            verdict, rc = "FAIL", 1
            findings = [{"severity": "ERROR", "rule": "MERGE_LVS_NOT_RUN",
                          "message": ("top-level LVS did NOT run, so nothing "
                                      "compared the merged layout to the "
                                      "schematic — this is not a mismatch, it "
                                      "is an absent comparison. Producer "
                                      f"reason: {top_lvs.get('reason', '(none stated)')}")}]
        else:
            verdict, rc = "FAIL", 1
            findings = [{"severity": "ERROR", "rule": "MERGE_LVS_FAIL",
                          "message": ("top-level LVS verdict "
                                      f"{top_lvs.get('verdict')!r} — the "
                                      "merged layout does not match the "
                                      "schematic")}]

    out = {
        "gate": _GATE_NAME,
        "verdict": verdict,
        "step_label": args.step_label,
        "required_files": _REQUIRED_FILES,
        "found": found,
        "missing": missing,
        "waiver": waiver,
        "rationale_when_skipped": _WAIVER_RATIONALE,
        "findings": findings,
    }
    if args.json:
        out_path = Path(args.json)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        atomic_write_text(out_path, json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    print(f"=== {_GATE_NAME} ({project.name}) ===")
    print(f"  verdict: {verdict}")
    if missing:
        print(f"  missing: {missing}")
    if waiver:
        print(f"  waiver:  {waiver.get('ticket','?')}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
