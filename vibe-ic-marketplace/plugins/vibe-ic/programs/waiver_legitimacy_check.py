#!/usr/bin/env python3
"""
waiver_legitimacy_check.py — v0.116 (BACKLOG-v11 candidate).

Detects "lazy waivers" — waiver entries whose reason matches well-known
patterns indicating the agent skipped real work that open-source tooling
can actually do. Closes the v0.115 <benchmark> attack vector where a fresh
agent waivered 30 of 34 canonical steps with reasons like "commercial
deck needed" or "Yosys rejects SystemVerilog", even though prior runs
on the same chip + same toolchain successfully completed those steps.

The previous waivers gates only check schema correctness
(waivers_schema_check.py) and growth tracking
(waiver_growth_check.py); they do NOT inspect the reason TEXT for
known-fake patterns.

False-positive design:
  - WARN-only on pattern match by default. ERROR mode requires --strict.
    Reason: a few legitimate waivers genuinely cite "commercial deck"
    when the OPEN-source flow truly can't reach the precision a tape-out
    needs (e.g. some advanced-node DRC). We default WARN so users can
    waive those legitimately while still being prompted to review.
  - Skip if waivers.json absent.

Detected anti-patterns (chip-AGNOSTIC):

  1. SYNTH_FAKE — waiver on step 9 (Synthesis) with reason mentioning
     "yosys reject" / "yosys does not support" / "SystemVerilog
     unsupported by yosys".
     Counter-evidence: yosys-slang plugin (`read_slang -sv` /
     `plugin -i slang`) handles SV packages, enums, structs.

  2. PNR_FAKE — waiver on steps 14-33 (PnR + sign-off) with reason
     mentioning "commercial OpenROAD/Innovus deck" / "Cadence Innovus
     required" / "Synopsys ICC required" without parallel "and we
     attempted OpenROAD which produced X".
     Counter-evidence: OpenROAD + custom-PDK liberty/LEF works for most
     designs; v0.108 <benchmark> round 3 produced GDS via OpenROAD on
     a <foundry> commercial PDK.

  3. DRC_FAKE — waiver on step 28 (PV) citing "KLayout L_lname not
     defined".
     Counter-evidence: v0.112 added structural-only fallback that
     unblocks this exact case.

  4. ANALOG_OVERWAIVER — waiver on A1-A8 covering >5 steps with reason
     "vendor hardmacro" without enumerating which sub-blocks ARE
     hardmacro vs which ARE under-design. Hardmacros legitimately
     skip A5-A7 (layout/post-layout/macro-gen) but A1-A4 spec + corner
     sweep + A8 cosim should still execute on top-level integration.

  5. CASCADE_OVERREACH — root waiver cascades_to 10+ canonical steps
     without per-step justification + foundry_signoff_plan.yaml closure
     entry per cascade target.

Output: per-finding `severity` (WARN / ERROR), `pattern` (one of the 5
above), `step_id`, `quoted_reason_excerpt`, `counter_evidence`.

Usage:
  python3 waiver_legitimacy_check.py <project_dir> [--strict] [--json [PATH]]
Exit 0 PASS, 1 FAIL (only in --strict mode), 2 IO error.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple


@dataclass
class Finding:
    severity: str
    pattern: str
    step_id: Any
    cascades_count: int
    quoted_reason_excerpt: str
    counter_evidence: str
    suggestion: str


# Anti-pattern detectors. Each returns (matched: bool, excerpt: str).

_RE_SYNTH_FAKE = re.compile(
    r"\byosys\b.*?(reject\w*|does\s*not\s*support|unsupported|fail(s|ed|\s)*to\s*parse|cannot\s*parse|"
    r"systemverilog\s*unsupported|sv\s*idiom\w*)",
    re.IGNORECASE | re.DOTALL,
)
_RE_PNR_FAKE = re.compile(
    r"(\bcommercial\b.*\b(deck|tooling|openroad|innovus|encounter)\b|"
    r"\b(cadence|synopsys)\s+(innovus|icc|tetramax|prime\s*time)\s+required\b|"
    r"\bproprietary\s+(deck|toolchain|sign-?off)\s+(needed|required)\b|"
    r"\bopen-?source.+\bdoes\s*not\s+(work|suffice)\b)",
    re.IGNORECASE,
)
_RE_DRC_FAKE = re.compile(
    r"\bL_lname\s*(not\s*defined|undefined|error)\b|"
    r"\bklayout\b.*\b(no\s*deck|cannot\s*derive)\b",
    re.IGNORECASE,
)
_RE_ANALOG_OVERWAIVER_HINT = re.compile(
    r"\bvendor\s+(hardmacro|black-?box|supplied)\b",
    re.IGNORECASE,
)


def _is_synth_step(sid: Any) -> bool:
    return isinstance(sid, int) and sid == 9


def _is_pnr_step(sid: Any) -> bool:
    return isinstance(sid, int) and 14 <= sid <= 33


def _is_pv_step(sid: Any) -> bool:
    return isinstance(sid, int) and sid == 28


def _is_analog_step(sid: Any) -> bool:
    return isinstance(sid, str) and re.fullmatch(r"A\d+", str(sid))


def _excerpt(text: str, n: int = 160) -> str:
    if not isinstance(text, str):
        return repr(text)[:n]
    s = text.strip().replace("\n", " ")
    return s if len(s) <= n else s[: n - 3] + "..."


def _root_waivers(doc: Dict[str, Any]) -> List[Dict[str, Any]]:
    entries = doc.get("waived_steps", []) or []
    cascade_targets: set = set()
    for e in entries:
        for c in e.get("cascades_to", []) or []:
            cascade_targets.add(c)
    out = []
    for e in entries:
        if e.get("id") in cascade_targets:
            continue
        if e.get("cascade_source") is not None:
            continue
        out.append(e)
    return out


def _detect_patterns(waiver: Dict[str, Any], plan_covers: set) -> List[Finding]:
    findings: List[Finding] = []
    sid = waiver.get("id")
    reason = waiver.get("reason", "")
    cascades = waiver.get("cascades_to", []) or []
    cascades_count = len(cascades)

    if _is_synth_step(sid) and _RE_SYNTH_FAKE.search(reason):
        findings.append(Finding(
            severity="WARN",
            pattern="SYNTH_FAKE",
            step_id=sid,
            cascades_count=cascades_count,
            quoted_reason_excerpt=_excerpt(reason),
            counter_evidence=(
                "yosys-slang plugin (`plugin -i slang; read_slang -sv ...`) "
                "handles SystemVerilog packages / enums / structs. "
                "v0.108 <benchmark> round 3 successfully synth'd <chip-class> RTL "
                "via Yosys 0.64 + slang plugin on iic-osic-tools docker."
            ),
            suggestion=(
                "Re-attempt synth with `read_slang -sv` instead of "
                "`read_verilog -sv`. If still failing, document the "
                "specific construct + slang issue tracker URL."
            ),
        ))

    if _is_pnr_step(sid) and _RE_PNR_FAKE.search(reason):
        findings.append(Finding(
            severity="WARN",
            pattern="PNR_FAKE",
            step_id=sid,
            cascades_count=cascades_count,
            quoted_reason_excerpt=_excerpt(reason),
            counter_evidence=(
                "OpenROAD + custom-PDK liberty/LEF works for the canonical "
                "PnR steps 14-33. v0.108 <benchmark> round 3 produced a 3.93 MB "
                "GDS via OpenROAD on a <foundry> commercial PDK (md5 "
                "407946cd...). Commercial deck adds tape-out-grade "
                "DRC/timing margins but is NOT required for engineering "
                "PASS through step 33."
            ),
            suggestion=(
                "Run `mcp__eda-tools__eda_pnr` with custom-PDK args. If "
                "specific steps fail (e.g. RCX), waive only those with "
                "the specific OpenROAD error code, not the whole flow."
            ),
        ))

    if _is_pv_step(sid) and _RE_DRC_FAKE.search(reason):
        findings.append(Finding(
            severity="WARN",
            pattern="DRC_FAKE",
            step_id=sid,
            cascades_count=cascades_count,
            quoted_reason_excerpt=_excerpt(reason),
            counter_evidence=(
                "v0.112 added KLayout structural-only fallback for the "
                "L_lname / no-layermap case. `eda_drc_klayout` now "
                "returns success=true with deck_mode='structural_only' + "
                "advisory rather than hard-failing."
            ),
            suggestion=(
                "Re-run `mcp__eda-tools__eda_drc_klayout` — it should "
                "now produce a structural_only PASS. Reserve waiver for "
                "production tape-out where full deck is required."
            ),
        ))

    if _is_analog_step(sid) and _RE_ANALOG_OVERWAIVER_HINT.search(reason) and cascades_count >= 5:
        findings.append(Finding(
            severity="WARN",
            pattern="ANALOG_OVERWAIVER",
            step_id=sid,
            cascades_count=cascades_count,
            quoted_reason_excerpt=_excerpt(reason),
            counter_evidence=(
                "Vendor hardmacros legitimately skip A5 (layout) / A6 "
                "(post-layout resim) / A7 (hardmacro gen) but A1 (spec "
                "extract) / A2 (topology) / A3 (netlist) / A4 (corner "
                "sweep) / A8 (cosim) typically still apply to TOP-LEVEL "
                "integration around the hardmacro. v0.108 <benchmark> round 4 "
                "executed A1+A2+A3+A4+A8 PASS even though analog blocks "
                "were vendor-supplied."
            ),
            suggestion=(
                "Split the waiver: enumerate vendor-hardmacro "
                "sub-blocks vs top-level analog integration. Waive only "
                "A5/A6/A7 for hardmacros; execute A1/A2/A3/A4/A8 on "
                "integration."
            ),
        ))

    # Cascade overreach: root with very large cascade_to list AND no
    # foundry_signoff_plan closure entry per target.
    if cascades_count >= 10:
        unplanned = [c for c in cascades if c not in plan_covers]
        if unplanned:
            findings.append(Finding(
                severity="WARN",
                pattern="CASCADE_OVERREACH",
                step_id=sid,
                cascades_count=cascades_count,
                quoted_reason_excerpt=_excerpt(reason),
                counter_evidence=(
                    f"Root waiver cascades to {cascades_count} steps but "
                    f"{len(unplanned)} of them lack a per-step closure "
                    f"entry in foundry_signoff_plan.yaml. Large cascades "
                    f"need per-target accountability."
                ),
                suggestion=(
                    "For each cascaded step, add a `closures:` entry in "
                    "foundry_signoff_plan.yaml listing tool / input / "
                    "proof_artefact / acceptance_criterion specific to "
                    "that step (not just the root)."
                ),
            ))

    return findings


def _load_plan_covers(project: Path) -> set:
    """Return set of waiver_ids covered by foundry_signoff_plan."""
    out: set = set()
    for ext in ("yaml", "yml", "json"):
        p = project / f"foundry_signoff_plan.{ext}"
        if not p.exists():
            continue
        try:
            text = p.read_text()
            if ext == "json":
                d = json.loads(text)
            else:
                try:
                    import yaml  # type: ignore
                    d = yaml.safe_load(text) or {}
                except ImportError:
                    # Fall back to JSON parse
                    d = json.loads(text)
            plan = d.get("foundry_signoff_plan") or d
            for c in plan.get("closures", []) or []:
                if isinstance(c, dict) and "waiver_id" in c:
                    out.add(c["waiver_id"])
        except Exception:
            continue
    return out


def main():
    ap = argparse.ArgumentParser(description=(
        "Detect lazy/fake waivers via well-known anti-pattern regexes."
    ))
    ap.add_argument("project_dir")
    ap.add_argument("--strict", action="store_true",
                    help="Promote WARNs to ERRORs (gate fails on lazy waivers)")
    ap.add_argument("--json", nargs="?", const="-", default=None)
    args = ap.parse_args()

    project = Path(args.project_dir).resolve()
    if not project.is_dir():
        print(f"[ERROR] project_dir not found: {project}", file=sys.stderr)
        return 2

    waivers_path = project / "waivers.json"
    if not waivers_path.exists():
        result = {
            "program": "waiver_legitimacy_check",
            "version": "1.0.0",
            "project": str(project),
            "summary": {"skip": True, "reason": "no waivers.json", "pass": True},
            "findings": [],
        }
        if args.json is None:
            print("[PASS] waiver_legitimacy_check (skip — no waivers)")
        elif args.json == "-":
            print(json.dumps(result, indent=2))
        else:
            Path(args.json).write_text(json.dumps(result, indent=2))
        return 0

    try:
        doc = json.loads(waivers_path.read_text())
    except Exception as exc:
        print(f"[ERROR] cannot parse {waivers_path}: {exc}", file=sys.stderr)
        return 2

    plan_covers = _load_plan_covers(project)
    roots = _root_waivers(doc)

    all_findings: List[Finding] = []
    for w in roots:
        all_findings.extend(_detect_patterns(w, plan_covers))

    # Strict mode: WARN → ERROR
    if args.strict:
        for f in all_findings:
            if f.severity == "WARN":
                f.severity = "ERROR"

    pass_flag = not any(f.severity == "ERROR" for f in all_findings)

    result = {
        "program": "waiver_legitimacy_check",
        "version": "1.0.0",
        "project": str(project),
        "summary": {
            "root_waivers": len(roots),
            "anti_patterns_detected": len(all_findings),
            "strict_mode": args.strict,
            "plan_covers": sorted(plan_covers, key=str),
            "pass": pass_flag,
        },
        "findings": [asdict(f) for f in all_findings],
    }

    if args.json is None:
        verdict = "PASS" if pass_flag else "FAIL"
        print(f"[{verdict}] waiver_legitimacy_check{' (strict)' if args.strict else ''}")
        print(f"  root waivers: {len(roots)}")
        print(f"  anti-patterns detected: {len(all_findings)}")
        for f in all_findings:
            print(f"  [{f.severity}] {f.pattern} @ step {f.step_id} (cascades={f.cascades_count})")
            print(f"    reason: {f.quoted_reason_excerpt}")
            print(f"    counter: {f.counter_evidence}")
            print(f"    suggestion: {f.suggestion}")
            print()
    elif args.json == "-":
        print(json.dumps(result, indent=2))
    else:
        Path(args.json).write_text(json.dumps(result, indent=2))
        print(f"json: {args.json}")

    return 0 if pass_flag else 1


if __name__ == "__main__":
    sys.exit(main())
