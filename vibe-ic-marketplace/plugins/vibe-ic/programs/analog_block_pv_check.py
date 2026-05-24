#!/usr/bin/env python3
"""
analog_block_pv_check.py — gate (v1.6.13 Wave 88, integerised in
v1.6.14 Wave 90).

Analog A6 — per-block DRC + LVS verification

Behaviour
---------
* SKIP (rc=2) — required artefacts missing AND step not waived.
* WAIVED (rc=0) — `waivers.json` declares step waived (evidence + ticket).
* PASS (rc=0) — required files present; gate-specific predicate is a
  stub in v1.6.13 (PASS-on-presence).
* FAIL (rc=1) — files present but predicate fails (not used in v1.6.13).

chip-AGNOSTIC. No vendor / IC / tool-specific data hard-coded.

Default rationale when SKIP: Magic / KLayout / Calibre per-block DRC + LVS not yet shipped; production runs at backend.

Usage
-----
    python3 analog_block_pv_check.py <project_dir> [--json <out>]
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


_GATE_NAME = 'analog_block_pv_check'
_GATE_LABEL = 'analog_block_pv'
# v1.6.607 — v2-rename cascade leftover. Each gate-required artefact
# (drc_clean.flag + lvs_match.flag, one per analog block) can live
# under EITHER the v2-canonical phase3/analog/<block>/ tree (added
# v1.6.607) OR the legacy v1 root-level analog/<block>/ tree
# (preserved for backward-compat). The list below is grouped in
# (group_name, [pattern_variants]) pairs; each group is satisfied
# when ANY of its patterns matches at least one file.
_REQUIRED_FILE_GROUPS = [
    ("drc_clean", [
        'phase3/analog/*/drc_clean.flag',  # v2 canonical
        'analog/*/drc_clean.flag',         # v1 legacy fallback
    ]),
    ("lvs_match", [
        'phase3/analog/*/lvs_match.flag',  # v2 canonical
        'analog/*/lvs_match.flag',         # v1 legacy fallback
    ]),
]
# Flattened patterns retained for backwards-compatible JSON output.
_REQUIRED_FILES = [pat for _, pats in _REQUIRED_FILE_GROUPS for pat in pats]
_WAIVER_RATIONALE = 'Magic / KLayout / Calibre per-block DRC + LVS not yet shipped; production runs at backend.'


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

    # Group-level satisfaction: each artefact group passes if ANY
    # of its pattern variants (v2-canonical or v1 legacy) hits.
    group_status = []
    for name, patterns in _REQUIRED_FILE_GROUPS:
        hit_pattern = next(
            (p for p in patterns if list(project.glob(p))), None)
        group_status.append((name, patterns, hit_pattern))
    found = [hit for _, _, hit in group_status if hit]
    missing = [name for name, _, hit in group_status if hit is None]

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
                      "message": (f"all {len(_REQUIRED_FILE_GROUPS)} required "
                                  "artefact groups present "
                                  f"(via patterns: {found})")}]

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
