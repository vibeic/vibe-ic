#!/usr/bin/env python3
"""ip_integration_check.py — hard-macro / IP integration checklist gate
(flow v2.3.1, external review R3).

Hard macros (SRAM / PLL / IO / analog A8 packs) flow into Step 15 via
`input/pdk_local/<vendor>/` and `phase3/analog/hardmacro/` — but no
gate ever verified the INTEGRATION contract. Three deterministic
checks per macro:

  1. FILE-SET ALIGNMENT — every macro needs the full handoff set:
     LEF + GDS + Liberty (+ Verilog stub). A macro shipping a LEF
     without its GDS (or vice versa) breaks merge/PV downstream:
     IP_FILESET_INCOMPLETE (ERROR).
  2. LIBERTY CORNER COVERAGE — count distinct corner-named .lib files
     per macro (tt/ss/ff tokens in stems). Single-corner macros are a
     named REVIEW item (multi-corner STA at Step 23 cannot cover what
     the macro never characterised): IP_SINGLE_CORNER_LIB (WARNING).
  3. POWER-DOMAIN CONSISTENCY — when L21 declares power domains and a
     macro's Liberty names a supply (`voltage_map`/related_power_pin),
     the supply must appear among the L21 domain supplies:
     IP_POWER_DOMAIN_MISMATCH (WARNING — L21 may legitimately lag).
  4. MACRO-SUPPLY POWER-INTENT COVERAGE — every POWER/GROUND pin a macro
     types in its OWN LEF must be ACCOUNTED for in L21: bound to a declared
     rail, name-matches a declared rail, or marked an acknowledged
     integration gap (`hard_macro_supplies`). A pin accounted for by none is
     an undeclared supply: IP_MACRO_SUPPLY_UNDECLARED (WARNING — surfaces the
     requirement at Phase 1 so it flows into L21 instead of aborting detailed
     routing five steps later). A mapping to a rail the design does not
     declare is IP_MACRO_SUPPLY_RAIL_UNDECLARED (WARNING — a phantom rail is
     not coverage). See hardmacro_supply_intent.

Exit codes: 0 PASS / PASS_WITH_REVIEW, 1 FAIL (file-set incomplete),
2 vacuous (no macros present — nothing to integrate).
chip-AGNOSTIC: file-set structure + token rules + the macros' own LEF USE
records + the design's own L21 — no PDK / design / pin-name literal.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import hardmacro_supply_intent as _hmsi  # shared LEF-driven supply-intent logic

_CORNER_TOKENS = ("tt", "ss", "ff", "fs", "sf", "typ", "slow", "fast",
                  "wcl", "bc", "wc")
_SUPPLY_RE = re.compile(
    r"voltage_map\s*\(\s*([A-Za-z_]\w*)|related_power_pin\s*:\s*\"?"
    r"([A-Za-z_]\w*)", re.IGNORECASE)


def _macro_roots(project: Path):
    roots = {}
    for base in (project / "input" / "pdk_local",
                 project / "phase3" / "analog" / "hardmacro"):
        if not base.is_dir():
            continue
        for d in sorted(p for p in base.rglob("*") if p.is_dir()):
            files = [f for f in d.iterdir() if f.is_file()]
            if any(f.suffix.lower() in (".lef", ".gds", ".lib", ".v")
                   for f in files):
                roots[str(d.relative_to(project))] = files
    return roots


def _corners_of(libs):
    corners = set()
    for f in libs:
        stem = f.stem.lower()
        for tok in _CORNER_TOKENS:
            if re.search(rf"(?:^|[_\-]){tok}(?:[_\-0-9]|$)", stem):
                corners.add(tok)
    return corners


def _l21_obj(project: Path) -> dict:
    """Return the parsed L21_POWER_INTENT object, or ``{}`` if absent/malformed."""
    l21 = project / "phase1" / "generated_docs" / "L21_POWER_INTENT.json"
    try:
        d = json.loads(l21.read_text(errors="replace"))
    except (OSError, ValueError):
        return {}
    return d if isinstance(d, dict) else {}


def _l21_supplies(project: Path):
    d = _l21_obj(project)
    if not d:
        return None
    fields = d.get("fields", d)
    doms = fields.get("power_domains") or []
    supplies = {str(x.get("supply")).upper() for x in doms
                if isinstance(x, dict) and x.get("supply")}
    return supplies or None


def audit(project: Path) -> dict:
    macros = _macro_roots(project)
    if not macros:
        return {"verdict": "SKIP", "rc": 2,
                "reason": ("no hard macros under input/pdk_local/ or "
                           "phase3/analog/hardmacro/ — nothing to "
                           "integrate")}
    findings = []
    summary = {}
    l21_supplies = _l21_supplies(project)
    for rel, files in macros.items():
        by_ext = {}
        for f in files:
            by_ext.setdefault(f.suffix.lower(), []).append(f)
        have = {e for e in (".lef", ".gds", ".lib", ".v") if by_ext.get(e)}
        missing = {".lef", ".gds", ".lib"} - have
        libs = by_ext.get(".lib", [])
        corners = _corners_of(libs)
        summary[rel] = {
            "files": {e: len(v) for e, v in by_ext.items()},
            "lib_corners": sorted(corners),
            "verilog_stub": ".v" in have,
        }
        if missing:
            findings.append({
                "severity": "ERROR", "rule": "IP_FILESET_INCOMPLETE",
                "message": (f"{rel}: macro handoff set missing "
                            f"{sorted(missing)} — a LEF without its "
                            f"GDS/Liberty (or vice versa) breaks "
                            f"merge/PV/STA downstream (flow v2.3.1 R3)")})
        if libs and len(corners) <= 1:
            findings.append({
                "severity": "WARNING", "rule": "IP_SINGLE_CORNER_LIB",
                "message": (f"{rel}: Liberty characterised at "
                            f"{sorted(corners) or ['(unnamed)']} only — "
                            f"Step-23 multi-corner STA cannot cover "
                            f"uncharacterised macro corners (review)")})
        if l21_supplies:
            for lib in libs[:4]:
                try:
                    head = lib.read_text(errors="replace")[:20000]
                except OSError:
                    continue
                for m in _SUPPLY_RE.finditer(head):
                    sup = (m.group(1) or m.group(2) or "").upper()
                    if sup and sup not in l21_supplies \
                            and not sup.startswith(("VSS", "GND")):
                        findings.append({
                            "severity": "WARNING",
                            "rule": "IP_POWER_DOMAIN_MISMATCH",
                            "message": (f"{rel}: Liberty names supply "
                                        f"{sup!r} not among L21 domain "
                                        f"supplies {sorted(l21_supplies)} "
                                        f"— align L21 or the macro pick")})
                        break
                else:
                    continue
                break

    # 4. MACRO-SUPPLY POWER-INTENT COVERAGE — every POWER/GROUND pin a macro
    #    types in its OWN LEF must be ACCOUNTED for in L21: bound to a declared
    #    rail, name-matches a declared rail, or marked an acknowledged
    #    integration gap. A pin accounted for by none is an undeclared supply —
    #    a NAMED review finding so the requirement flows into L21 now, instead
    #    of surfacing five steps later when a constant-tied supply pin lands a
    #    signal net on a POWER/GROUND terminal and aborts detailed routing.
    #    Non-blocking (WARNING) at Phase 1: it drives L21 completion without
    #    regressing a design whose supplies are fine; the HARD block lives in
    #    Phase 3, where the real rails + gate netlist make the crash provable.
    #    chip-AGNOSTIC — masters/pins from the macros' own LEFs, rails/mapping
    #    from the design's own L21. See hardmacro_supply_intent.
    lef_texts = []
    for _rel, _files in macros.items():
        for _f in _files:
            if _f.suffix.lower() == ".lef":
                try:
                    lef_texts.append(_f.read_text(errors="replace"))
                except OSError:
                    continue
    l21_obj = _l21_obj(project)
    cov = _hmsi.coverage_findings(
        lef_texts,
        _hmsi.declared_supply_rails(l21_obj),
        _hmsi.parse_declared_supply_map(l21_obj))
    summary["macro_supply_coverage"] = {
        "total_pins": cov["total_pins"],
        "covered": cov["covered_count"],
        "undeclared": len(cov["undeclared"]),
    }
    for u in cov["undeclared"]:
        findings.append({
            "severity": "WARNING", "rule": "IP_MACRO_SUPPLY_UNDECLARED",
            "message": (f"{u['master']}/{u['pin']} (USE {u['use']}): macro "
                        f"types this supply pin but L21_POWER_INTENT accounts "
                        f"for it by no declared rail, name-match, or "
                        f"integration gap — declare its rail binding or mark "
                        f"it an integration gap (hard_macro_supplies), else "
                        f"Phase-3 routing blocks on a signal-net-on-a-power-"
                        f"pin it cannot bind)")})
    for r in cov["rail_undeclared"]:
        findings.append({
            "severity": "WARNING", "rule": "IP_MACRO_SUPPLY_RAIL_UNDECLARED",
            "message": (f"{r['master']}/{r['pin']}: hard_macro_supplies binds "
                        f"it to rail {r['rail']!r}, which the design does not "
                        f"declare as a supply — name a real declared rail or "
                        f"mark an integration gap (a phantom rail is not "
                        f"coverage)")})

    errors = [f for f in findings if f["severity"] == "ERROR"]
    reviews = [f for f in findings if f["severity"] == "WARNING"]
    return {
        "verdict": ("FAIL" if errors else
                    "PASS_WITH_REVIEW" if reviews else "PASS"),
        "rc": 1 if errors else 0,
        "macros": summary,
        "l21_supplies": sorted(l21_supplies) if l21_supplies else None,
        "findings": findings,
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)
    if not args.project_dir.is_dir():
        print(f"ERROR: not a directory: {args.project_dir}", file=sys.stderr)
        return 1
    rep = audit(args.project_dir.resolve())
    rc = rep.pop("rc")
    rep = {"program": "ip_integration_check", "version": "1.0.0", **rep}
    out = json.dumps(rep, indent=2, ensure_ascii=False)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(out)
    print(out)
    return rc


if __name__ == "__main__":
    sys.exit(main())
