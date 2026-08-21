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
  4. SUPPLY-TERMINAL DECLARATION — a macro supply pin the power-intent
     layer does not account for: IP_MACRO_SUPPLY_UNDECLARED /
     IP_MACRO_SUPPLY_RAIL_UNDECLARED (WARNING, #309). An abstract that
     types NO pin at all is reported on its own terms rather than read as
     a macro with no supply terminal: IP_MACRO_ABSTRACT_UNTYPED
     (WARNING, #785 — see the block at the foot of `audit`).

Exit codes: 0 PASS / PASS_WITH_REVIEW, 1 FAIL (file-set incomplete),
2 vacuous (no macros present — nothing to integrate).
chip-AGNOSTIC: file-set structure + token rules only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

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


def _l21_supplies(project: Path):
    l21 = project / "phase1" / "generated_docs" / "L21_POWER_INTENT.json"
    try:
        d = json.loads(l21.read_text(errors="replace"))
    except (OSError, ValueError):
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

    # #309 — LEF-typed POWER/GROUND macro pins the design's power-intent layer
    # does not account for. Raised HERE, in Phase 1, because the information is
    # already available here (the macro's own LEF says USE POWER) and the cost
    # of losing it is paid five steps later: a signal net on a POWER terminal
    # makes TritonRoute abort ALL detailed routing (3278 nets, 0 routed).
    #
    # WARNING, not ERROR, and rc stays 0: the point is to make the requirement
    # flow into the power-intent layer NOW. Phase 3 is where it blocks — via
    # the SAME decision module, so this warning and that block cannot drift.
    #
    # #785 — AND THE SILENCE THAT INHERITED FROM IT. This block consumed
    # `assess()["gaps"]` and nothing else, so it inherited that function's
    # false-clean verbatim: MEASURED on ONE macro, two abstracts of the same
    # layout, this check emitted `IP_MACRO_SUPPLY_UNDECLARED` from the
    # hand-written LEF and NOTHING AT ALL from the same macro's abstract as
    # `magic`'s `lef write` emits it (neither `DIRECTION` nor `USE` on any PIN).
    # Regenerating the abstract HONESTLY silenced the integration checklist.
    #
    # `project` is now passed so `assess` can read the macro's own Liberty view,
    # which is where the typing survives a `lef write`. Everything stays a
    # WARNING for the reason above: this is Phase 1, the point is to make the
    # requirement flow into the power-intent layer NOW.
    try:
        import hardmacro_supply_intent as _hmsi
        _lefs = _hmsi.load_macro_lefs(project)
        if _lefs:
            _rep = _hmsi.assess(_lefs, _hmsi.load_l21(project), project=project)
            for _g in _rep["gaps"]:
                _rule = ("IP_MACRO_SUPPLY_RAIL_UNDECLARED"
                         if _g["status"] == "rail_undeclared"
                         else "IP_MACRO_SUPPLY_UNDECLARED")
                findings.append({
                    "severity": "WARNING", "rule": _rule,
                    "message": (
                        f"{_g['master']}/{_g['pin']} is LEF-typed "
                        f"{_g.get('use', 'POWER')} but {_g['detail']}. If RTL "
                        f"ties this pin, synthesis drives it with a TIE cell "
                        f"and detailed routing aborts (DRT-0307). Declare the "
                        f"rail in L21.fields.hard_macro_supplies, or mark it "
                        f"integration_gap: true.")})
            # The SAME finding, for a pin whose supply role was RECOVERED from
            # the design's own independent view because its abstract types
            # nothing. Same clause, same remedy — only the provenance differs,
            # and it is named so a reader can check it.
            for _g in _rep.get("recovered_gaps", []):
                _rule = ("IP_MACRO_SUPPLY_RAIL_UNDECLARED"
                         if _g["status"] == "rail_undeclared"
                         else "IP_MACRO_SUPPLY_UNDECLARED")
                findings.append({
                    "severity": "WARNING", "rule": _rule,
                    "message": (
                        f"{_g['master']}/{_g['pin']}: this macro's own abstract "
                        f"types NO pin at all, but {_g['typing_source']}, so it "
                        f"is a {_g.get('use') or 'supply'} terminal — and "
                        f"{_g['detail']}. If RTL ties this pin, synthesis "
                        f"drives it with a TIE cell and detailed routing aborts "
                        f"(DRT-0307). Declare the rail in "
                        f"L21.fields.hard_macro_supplies, or mark it "
                        f"integration_gap: true.")})
            # And the abstract itself, whether or not anything corroborated it.
            # A macro the binder cannot see is not a macro with nothing to bind.
            for _a in _rep.get("untyped_abstracts", []):
                _why = (
                    "CORROBORATED: "
                    + ", ".join(
                        "{} ({}, via {})".format(
                            r["pin"], r.get("use") or "polarity unstated",
                            r["typing_source"])
                        for r in _a["recovered"])
                    + " — so this abstract is UNDER-DECLARED, not supply-less."
                ) if _a["corroborated"] else (
                    "No independent view of this macro is staged (no Liberty "
                    "`pg_pin` beside the abstract, and the design declares no "
                    "rail matching any of its pin names), so the supply "
                    "contract is UNVERIFIABLE from either side — which is a "
                    "different fact from a macro with no supply pin to "
                    "declare.")
                findings.append({
                    "severity": "WARNING", "rule": "IP_MACRO_ABSTRACT_UNTYPED",
                    "message": (
                        f"{_a['master']}: the staged abstract declares "
                        f"{len(_a['pins'])} PIN(s) and types NONE of them with "
                        f"a `USE` record, so every consumer keyed on `USE "
                        f"POWER`/`USE GROUND` — this checklist, the "
                        f"global-connect binder, and the binder's own "
                        f"HARDMACRO_SUPPLY_UNCONNECTED report — sees zero "
                        f"supply terminals AND zero findings at once. A "
                        f"tool-written abstract is the common case: `magic`'s "
                        f"`lef write` emits neither `DIRECTION` nor `USE` on "
                        f"any PIN, so re-attach the typing after it. {_why}")})
    except Exception:  # noqa: BLE001 — a Phase-1 advisory must never hard-fail
        pass

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
