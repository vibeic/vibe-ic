#!/usr/bin/env python3
"""
foundry_signoff_plan_check.py — v0.113 (BACKLOG-v10 P1.2).

Enforces that any project with waivers also has a `foundry_signoff_plan.yaml`
documenting WHO will close each waiver, WHEN, with WHAT tool, and what
proof artefact closes it. Without this, "deferred to foundry tapeout review"
becomes a magic incantation with no accountability.

Schema (chip-AGNOSTIC, applies to any custom-PDK project):

```yaml
foundry_signoff_plan:
  foundry: <foundry>          # or TSMC, GF, IBM, etc.
  contact: signoff@example.com
  expected_review_date: 2026-12-01
  closures:
    - waiver_id: 20            # MUST match a waivers.json id
      tool: Cadence Quantus QRC
      input: gds/<top>.gds
      proof_artefact: extracted/parasitic.spef
      acceptance_criterion: "WNS @ post-route SS corner ≥ 0 ns with extracted SPEF"
    - waiver_id: 22
      ...
```

Gate logic:
  - If waivers.json has 0 entries → SKIP (no plan needed)
  - If waivers.json has N entries:
      - foundry_signoff_plan.yaml MUST exist
      - top-level fields foundry / contact / expected_review_date required
      - every waiver_id MUST appear as a closure entry
      - every closure entry MUST have tool / input / proof_artefact /
        acceptance_criterion non-empty
      - cascaded children (cascade_source != null) inherit parent's
        closure plan; explicit child entry NOT required
  - PASS only if every root waiver has a complete closure entry.

Usage:
  python3 foundry_signoff_plan_check.py <project_dir> [--json [PATH]]

Exit codes: 0 PASS, 1 FAIL, 2 IO error.
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List


@dataclass
class Finding:
    severity: str
    category: str
    message: str
    details: str = ""


REQUIRED_TOP = ["foundry", "contact", "expected_review_date"]
REQUIRED_PER_CLOSURE = ["waiver_id", "tool", "input", "proof_artefact", "acceptance_criterion"]


def _load_yaml_or_json(path: Path) -> Dict[str, Any]:
    """Best-effort: try YAML first via PyYAML if available, else JSON."""
    text = path.read_text()
    try:
        import yaml  # type: ignore
        return yaml.safe_load(text) or {}
    except ImportError:
        try:
            return json.loads(text)
        except Exception as exc:
            raise RuntimeError(f"PyYAML unavailable and {path} is not JSON: {exc}")


def _root_waiver_ids(waivers_doc: Dict[str, Any]) -> List[Any]:
    """Return root waiver ids only — cascade children inherit closure."""
    entries = waivers_doc.get("waived_steps", []) or []
    cascade_targets: set = set()
    for entry in entries:
        for child in entry.get("cascades_to", []) or []:
            cascade_targets.add(child)
    out = []
    for entry in entries:
        sid = entry.get("id")
        if sid in cascade_targets:
            continue
        if entry.get("cascade_source") is not None:
            continue
        out.append(sid)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=(
        "Verify foundry_signoff_plan.yaml provides closure plan for every waiver."
    ))
    ap.add_argument("project_dir")
    ap.add_argument("--json", nargs="?", const="-", default=None)
    args = ap.parse_args(argv)

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"[ERROR] project_dir not found: {project}", file=sys.stderr)
        return 2

    waivers_path = project / "waivers.json"
    plan_path_yaml = project / "foundry_signoff_plan.yaml"
    plan_path_yml = project / "foundry_signoff_plan.yml"
    plan_path_json = project / "foundry_signoff_plan.json"

    findings: List[Finding] = []
    waivers = []
    if waivers_path.exists():
        try:
            waivers_doc = json.loads(waivers_path.read_text())
            waivers = _root_waiver_ids(waivers_doc)
        except Exception as exc:
            findings.append(Finding("ERROR", "WAIVERS_PARSE",
                f"cannot parse {waivers_path}: {exc}"))

    if not waivers:
        # No waivers → no plan needed
        result = {
            "program": "foundry_signoff_plan_check",
            "version": "1.0.0",
            "project": str(project),
            "summary": {
                "skip": True,
                "reason": "no waivers in project — no signoff plan required",
                "pass": True,
            },
            "findings": [],
        }
        if args.json is None:
            print("[PASS] foundry_signoff_plan_check (skip — no waivers)")
        elif args.json == "-":
            print(json.dumps(result, indent=2))
        else:
            Path(args.json).write_text(json.dumps(result, indent=2))
            print(f"json: {args.json}")
        return 0

    # Find plan
    plan_path = None
    for cand in [plan_path_yaml, plan_path_yml, plan_path_json]:
        if cand.exists():
            plan_path = cand
            break

    if plan_path is None:
        findings.append(Finding(
            severity="ERROR",
            category="PLAN_MISSING",
            message=(
                f"Project has {len(waivers)} root waiver(s) but no "
                f"foundry_signoff_plan.{{yaml,yml,json}} exists. Production "
                f"tapeout review needs a documented closure plan: who runs "
                f"each waiver on the foundry deck, with what tool, producing "
                f"what proof. Without this, 'deferred to foundry tapeout' is "
                f"untrackable."
            ),
            details=(
                "Schema: foundry_signoff_plan: { foundry, contact, "
                "expected_review_date, closures: [{waiver_id, tool, input, "
                "proof_artefact, acceptance_criterion}, ...] }. See "
                "vibe-ic/programs/foundry_signoff_plan_check.py docstring."
            ),
        ))
    else:
        try:
            doc = _load_yaml_or_json(plan_path)
        except Exception as exc:
            findings.append(Finding("ERROR", "PLAN_PARSE",
                f"cannot parse {plan_path}: {exc}"))
            doc = None

        if doc is not None:
            plan = doc.get("foundry_signoff_plan") or doc
            for k in REQUIRED_TOP:
                if not plan.get(k):
                    findings.append(Finding("ERROR", "PLAN_FIELD_MISSING",
                        f"foundry_signoff_plan.{k} is required"))
            closures = plan.get("closures", []) or []
            covered = set()
            for i, c in enumerate(closures):
                if not isinstance(c, dict):
                    findings.append(Finding("ERROR", "CLOSURE_TYPE",
                        f"closures[{i}] must be a mapping"))
                    continue
                wid = c.get("waiver_id")
                if wid is None:
                    findings.append(Finding("ERROR", "CLOSURE_NO_WID",
                        f"closures[{i}] missing waiver_id"))
                    continue
                covered.add(wid)
                for field in REQUIRED_PER_CLOSURE:
                    if not c.get(field):
                        findings.append(Finding("ERROR", "CLOSURE_FIELD_MISSING",
                            f"closures[{i}] (waiver_id={wid}) missing {field!r}"))

            for wid in waivers:
                if wid not in covered:
                    findings.append(Finding(
                        severity="ERROR",
                        category="WAIVER_NOT_PLANNED",
                        message=(
                            f"Root waiver id={wid!r} has no closure entry "
                            f"in foundry_signoff_plan. Add a closures: entry "
                            f"with tool / input / proof_artefact / "
                            f"acceptance_criterion."
                        ),
                    ))

    pass_flag = not any(f.severity == "ERROR" for f in findings)
    result = {
        "program": "foundry_signoff_plan_check",
        "version": "1.0.0",
        "project": str(project),
        "summary": {
            "waiver_root_count": len(waivers),
            "plan_path": str(plan_path) if plan_path else None,
            "pass": pass_flag,
        },
        "findings": [asdict(f) for f in findings],
    }

    if args.json is None:
        verdict = "PASS" if pass_flag else "FAIL"
        print(f"[{verdict}] foundry_signoff_plan_check")
        print(f"  waivers (root): {len(waivers)}")
        print(f"  plan: {plan_path}")
        for f in findings:
            print(f"  [{f.severity}] {f.category}: {f.message}")
    elif args.json == "-":
        print(json.dumps(result, indent=2))
    else:
        Path(args.json).write_text(json.dumps(result, indent=2))
        print(f"json: {args.json}")

    return 0 if pass_flag else 1


if __name__ == "__main__":
    sys.exit(main())
