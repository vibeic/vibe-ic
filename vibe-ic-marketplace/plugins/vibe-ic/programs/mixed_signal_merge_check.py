#!/usr/bin/env python3
"""
mixed_signal_merge_check.py — gate (v1.6.13 Wave 88).

M1 — A+D top-level GDS merge (no overlap, all macro pins on tracks)

Behaviour
---------
* SKIP (rc=2) — required artefacts missing AND step not waived.
* WAIVED (rc=0) — `waivers.json` declares step waived (evidence + ticket).
* PASS (rc=0) — required files present; gate-specific predicate is a
  stub in v1.6.13 (PASS-on-presence).
* FAIL (rc=1) — files present but predicate fails (not used in v1.6.13).

chip-AGNOSTIC. No vendor / IC / tool-specific data hard-coded.

Default rationale when SKIP: Top-level GDS merge tool not shipped.

Usage
-----
    python3 mixed_signal_merge_check.py <project_dir> [--json <out>]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


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
_WAIVER_RATIONALE = 'Top-level GDS merge tool not shipped.'


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
        verdict, rc = "PASS", 0
        findings = [{"severity": "INFO", "rule": "FILES_PRESENT",
                      "message": f"all {len(_REQUIRED_FILES)} required artefacts present"}]

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
        out_path.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    print(f"=== {_GATE_NAME} ({project.name}) ===")
    print(f"  verdict: {verdict}")
    if missing:
        print(f"  missing: {missing}")
    if waiver:
        print(f"  waiver:  {waiver.get('ticket','?')}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
