#!/usr/bin/env python3
"""dfm_screen_check.py — Step 35 DFM screen (v2.3).

Design-for-Manufacturability, scoped HONESTLY for an open-source
130-180nm flow. Flow v2.3.1 (external review P0-1): the THREE density
touchpoints have DISTINCT natures and this screen no longer re-gates
what Step 34 owns —
  Step 31 = RULE compliance (the sign-off DRC deck's min-density
            rules — legal/illegal),
  Step 34 = EXECUTION verification (metal_fill_density_check gates
            that the fill actually achieved the window),
  Step 35 = OPTIMIZATION advisory (THIS screen: "could be filled
            better / via redundancy could improve yield" — findings,
            never a duplicate FAIL of Step 34).

  1. CMP density — CROSS-REFERENCE only: reads Step 34's gate result
     (reports/phase2/gates/metal_fill_density.json) and surfaces its
     verdict as an INFO/REVIEW finding; the gate itself lives at 34.
  2. Redundant-via ratio — the via UNIVERSE is what the routed DEF's
     NETS section actually REFERENCES (DEF regularWiring grammar), not
     only what the DEF happens to DECLARE. Cut counts are resolved
     per referenced name: from the DEF VIAS section (ROWCOL r c →
     r*c cuts) when declared there, else from a locatable tech LEF
     (cut-layer RECT/POLYGON count inside the fixed-via block). A name
     that resolves NOWHERE is counted into `unresolved_via_uses` and
     disclosed — it is NEVER assumed single-cut, because inferring a
     cut count from an absent declaration would be a fabricated
     measurement. A high single-cut fraction among the RESOLVED uses is
     a YIELD advisory (WARN, never a fabricated FAIL — OpenROAD has no
     via-doubling pass to repair it with).
  3. Litho / min-width margins — cross-referenced to the Step-31
     sign-off DRC deck (not re-executed here; ownership disclosed).
  4. FOUNDRY_SIDE items — OPC / RET / SRAF / PSM are mask-synthesis
     work the FOUNDRY performs on the delivered GDS. They are listed
     by name at their correct flow position (status FOUNDRY_SIDE),
     never pretended as designer-executed. At <=28nm these become
     designer-collaboration items (noted).

Always writes the canonical step artifact
`reports/phase3/dfm_screen.json` (in addition to --json).

flow v2.3.1: ADVANCED-NODE trigger — process node derived from the PDK's
own liberty filenames (the foundry_handoff_pack_gen heuristic); at
<= 28 nm the FOUNDRY_SIDE items escalate to DESIGNER_COLLAB_REVIEW
findings (dormant at this flow's 130-180 nm PDKs, mechanism present).

ROLE: producer/classifier

The two verdict tiers this screen computes used to share ONE exit code.
`audit()` resolved `PASS` vs `PASS_WITH_ADVISORIES` and then returned a
hard-coded ``"rc": 0`` for both, so every finding this program raised was
invisible at the process boundary. The tiers are now separated:

  0  PASS                    — screen ran, no advisory
  1  PASS_WITH_ADVISORIES    — screen ran and RAISED a finding
  2  vacuous SKIP            — nothing to screen yet (no routed.def and
                               no density artifacts)

Issue #1980 declares the canonical JSON as a Step-35 program output rather
than a gate. The screen has no refusal predicate; file presence is the step's
blocking predicate, while the structured verdict remains visible without
inflating gate coverage.

chip-AGNOSTIC: DEF structure + window numbers only.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import _path_layout as _pl  # noqa: E402

# advisory threshold: fraction of signal-net via USES that are
# single-cut. Industry DFM aims for dual-via where room allows; at
# 130-180nm this is yield-advisory, not sign-off.
_SINGLE_CUT_ADVISORY = 0.90

_FOUNDRY_SIDE_ITEMS = [
    {"item": "OPC (optical proximity correction)",
     "status": "FOUNDRY_SIDE",
     "note": "mask synthesis on the delivered GDS — foundry mask shop"},
    {"item": "RET / SRAF (sub-resolution assist features)",
     "status": "FOUNDRY_SIDE",
     "note": "resolution enhancement — foundry mask shop"},
    {"item": "PSM (phase-shift mask)",
     "status": "FOUNDRY_SIDE",
     "note": "mask technology selection — foundry"},
]
_ADVANCED_NODE_NOTE = (
    "at <=28nm the FOUNDRY_SIDE items become designer-collaboration "
    "items (litho-friendly design rules, OPC-aware routing) — out of "
    "scope for this 130-180nm open-source flow")


def _via_cut_counts(def_text: str):
    """{via_name: cuts} from the DEF VIAS section (ROWCOL r c → r*c;
    no ROWCOL → 1 cut)."""
    cuts = {}
    m = re.search(r"^VIAS\s+\d+\s*;(.*?)^END VIAS", def_text,
                  re.DOTALL | re.MULTILINE)
    if not m:
        return cuts
    for block in re.split(r"^\s*-\s+", m.group(1), flags=re.MULTILINE):
        name_m = re.match(r"(\S+)", block)
        if not name_m:
            continue
        rc = re.search(r"\+\s*ROWCOL\s+(\d+)\s+(\d+)", block)
        cuts[name_m.group(1)] = (int(rc.group(1)) * int(rc.group(2))
                                 if rc else 1)
    return cuts


# ── via USES, derived from the DEF routing grammar ────────────────────
# Measured defect this replaces: the old `_via_usage` was handed the DEF's
# DECLARED via names and counted only those. A router whose default vias are
# defined in the tech LEF (and therefore declared NOWHERE in the DEF) made the
# universe empty, so the screen reported `signal_via_uses: 0` on a routed.def
# holding 2240 real via references and emitted no via finding at all — a
# structurally unreachable measurement, not a wrong number.
#
# LEF/DEF 5.8 regularWiring, NETS section:
#
#   + (ROUTED|FIXED|COVER|NOSHIELD) layer routingPoints
#     [ NEW layer routingPoints ]...
#   routingPoints ::= ( x y [ext] )
#                     { ( x y [ext] ) | [MASK n] viaName [orient]
#                     | RECT ( d d d d ) | VIRTUAL ( x y ) }
#
# A via USE is therefore an identifier that follows the closing `)` of a
# routing point (optionally behind `MASK <n>`) and is not a DEF keyword.
# Keying on that grammar — rather than scanning the section for tokens — is
# what keeps net and instance names out of the count.
_NETS_RE = re.compile(r"^NETS\s+\d+\s*;(.*?)^END NETS",
                      re.DOTALL | re.MULTILINE)
_NET_ENTRY_SPLIT_RE = re.compile(r"^\s*-\s+", re.MULTILINE)
_WIRING_START_RE = re.compile(r"\+\s*(?:ROUTED|FIXED|COVER|NOSHIELD)\b")
# Properties whose VALUES are free text and may contain `)` + a word.
_WIRING_STOP_RE = re.compile(r"\+\s*(?:PROPERTY|SOURCE|ORIGINAL|PATTERN)\b")
_VIA_REF_RE = re.compile(
    r"\)\s*(?:MASK\s+\d+\s+)?([A-Za-z_][\w$\[\]<>./\\-]*)")
_DEF_WIRING_KEYWORDS = frozenset({
    # routingPoints / regularWiring vocabulary
    "NEW", "RECT", "VIRTUAL", "MASK", "TAPER", "TAPERRULE", "STYLE",
    "ROUTED", "FIXED", "COVER", "NOSHIELD", "POLYGON",
    # net-level properties that can follow a `)`
    "USE", "NONDEFAULTRULE", "SUBNET", "SHIELDNET", "PROPERTY", "SOURCE",
    "ORIGINAL", "WEIGHT", "PATTERN", "ESTCAP", "XTALK", "FREQUENCY",
    "SHAPE", "VPIN", "PLACED", "SPACING", "DESIGNRULEWIDTH",
    # section / use-class keywords
    "END", "NETS", "SPECIALNETS", "SIGNAL", "POWER", "GROUND", "CLOCK",
    "RESET", "SCAN", "TIEOFF", "ANALOG", "DIST", "NETLIST", "TIMING",
    "USER", "TEST", "FIXEDBUMP",
    # placement orientations (a via named `N` is not a thing; this is a
    # belt-and-braces guard, orientations follow a NAME not a `)`)
    "N", "S", "E", "W", "FN", "FS", "FE", "FW",
})


def _via_uses_from_nets(def_text: str) -> dict:
    """{via_name: uses} — every via REFERENCED by signal-net routing.

    Independent of whether the DEF declares the via: an undeclared name is
    still a real use, and hiding it is what made the screen vacuous.
    """
    m = _NETS_RE.search(def_text)
    if not m:
        return {}
    uses: dict = {}
    for entry in _NET_ENTRY_SPLIT_RE.split(m.group(1)):
        start = _WIRING_START_RE.search(entry)
        if not start:
            continue
        wiring = entry[start.end():]
        stop = _WIRING_STOP_RE.search(wiring)
        if stop:
            wiring = wiring[:stop.start()]
        for ref in _VIA_REF_RE.finditer(wiring):
            name = ref.group(1)
            if name.upper() in _DEF_WIRING_KEYWORDS:
                continue
            uses[name] = uses.get(name, 0) + 1
    return uses


# ── cut counts from a tech LEF ────────────────────────────────────────
# The router's default vias (Via1_YY, Via2_YX, …) are FIXED VIAs declared in
# the tech LEF, not in the DEF. When that LEF is reachable the cut count is a
# real measurement; when it is not, the uses stay UNRESOLVED and are disclosed
# as such. "Undeclared therefore single-cut" would be a fabricated number and
# is never inferred.
_LEF_CUT_LAYER_RE = re.compile(r"\bLAYER\s+(\S+)\s+TYPE\s+CUT\s*;")
_LEF_VIA_RE = re.compile(
    r"^[ \t]*VIA[ \t]+(\S+)[^\n]*\n(.*?)^[ \t]*END[ \t]+\1[ \t]*$",
    re.MULTILINE | re.DOTALL)
_LEF_VIA_LAYER_SPLIT_RE = re.compile(r"^\s*LAYER\s+(\S+)\s*;", re.MULTILINE)
_LEF_CUT_SHAPE_RE = re.compile(r"^\s*(?:RECT|POLYGON)\b", re.MULTILINE)
_MAX_LEF_FILES = 8
_MAX_LEF_BYTES = 64 * 1024 * 1024
# Bound the in-project sweep so a large run directory cannot turn this screen
# into a tree walk with no ceiling.
_MAX_LEF_CANDIDATES = 64


def _locate_lef_files(project: Path) -> list:
    """Tech/cell LEFs this run can actually reach, most authoritative first.

    (a) the exact files the router itself read (`read_lef <path>` in the run's
        own pnr tcl) — when they still exist on this filesystem;
    (b) any LEF shipped inside the project tree.
    """
    found: list = []
    seen: set = set()

    def _add(p: Path):
        try:
            rp = p.resolve()
        except OSError:
            return
        if rp in seen or len(found) >= _MAX_LEF_FILES:
            return
        try:
            if not rp.is_file() or rp.stat().st_size > _MAX_LEF_BYTES:
                return
        except OSError:
            return
        seen.add(rp)
        found.append(rp)

    pnr = _pl.pnr_dir(project)
    if pnr.is_dir():
        for tcl in sorted(pnr.glob("*.tcl")):
            try:
                text = tcl.read_text(errors="replace")
            except OSError:
                continue
            for m in re.finditer(r"^\s*read_lef\s+(\S+)", text, re.MULTILINE):
                raw = m.group(1).strip("\"'")
                p = Path(raw)
                _add(p if p.is_absolute() else (pnr / p))
    candidates: list = []
    for p in project.rglob("*.lef"):
        candidates.append(p)
        if len(candidates) >= _MAX_LEF_CANDIDATES:
            break
    for p in sorted(candidates):   # sorted -> deterministic resolution order
        _add(p)
        if len(found) >= _MAX_LEF_FILES:
            break
    return found


def _lef_via_cut_counts(lef_text: str) -> dict:
    """{via_name: cuts} from a LEF's FIXED VIA blocks (cut-layer shapes)."""
    cut_layers = set(_LEF_CUT_LAYER_RE.findall(lef_text))
    if not cut_layers:
        # No layer declares TYPE CUT in this file, so which shapes are cuts is
        # unknown here. Returning {} keeps the uses UNRESOLVED rather than
        # guessing — the whole point of this branch.
        return {}
    out: dict = {}
    for m in _LEF_VIA_RE.finditer(lef_text):
        name, body = m.group(1), m.group(2)
        parts = _LEF_VIA_LAYER_SPLIT_RE.split(body)
        cuts = 0
        for i in range(1, len(parts) - 1, 2):
            if parts[i] in cut_layers:
                cuts += len(_LEF_CUT_SHAPE_RE.findall(parts[i + 1]))
        if cuts:
            out[name] = cuts
    return out


# ---------------------------------------------------------------------------
# vibe-ic#562 — RE-ADJUDICATION RULES for this gate's published records.
#
# THE DRIFT: `verdict = "PASS_WITH_ADVISORIES" if advisories else "PASS"`, where
# `advisories` counts only WARNING findings. When the via-redundancy screen
# cannot run — routed.def has no parseable VIAS section, or its NETS section
# references no via — the gate says so HONESTLY, but it says it as an INFO
# finding. INFO does not reach `advisories`, so the record carries a plain PASS,
# indistinguishable from a run whose vias were screened and found redundant.
#
# The gate's own message calls that skip "honest", and it is — at the moment it
# is printed. What is not visible later is that the PASS covers a screen that
# never ran, which is the whole reason a published record needs re-adjudicating
# rather than re-reading.
import _record_adjudication as _ra  # noqa: E402

#: The INFO categories this gate emits when the via screen could not run.
_VIA_SCREEN_SKIPPED = ("VIA_DEFS_NOT_FOUND", "VIA_USES_NOT_FOUND")


def _via_screen_vacuity(record: dict):
    """Would this gate still call this a plain PASS, given what it screened?"""
    if record.get("verdict") != "PASS":
        return None                    # PASS_WITH_ADVISORIES already says more
    cats = {str(f.get("category", "")) for f in (record.get("findings") or [])
            if isinstance(f, dict)}
    skipped = sorted(cats & set(_VIA_SCREEN_SKIPPED))
    if not skipped:
        return None                    # the screen really did run
    return _ra.Supersession(
        would_issue="VACUOUS_PASS",
        because=("the record carries a plain PASS while also carrying "
                 f"{', '.join(skipped)} — the via-redundancy screen could not "
                 "run on that design, so the PASS covers a check that never "
                 "examined a via. The skip was disclosed as INFO, which does "
                 "not reach the advisory tier the verdict is built from, so "
                 "the verdict alone reads as a screened-and-clean result"),
    )


RECORD_ADJUDICATION = _ra.declare(
    __file__,
    gate="dfm_screen_check",
    decision_roots=("audit",),
    # Re-reviewed for #2000 against #1980 (867f807a): that landing removed
    # only the producer metadata field `verdict_mode`.  The rule below reads
    # `verdict` and `findings`; both decision paths and their meanings remain
    # unchanged, so no published record changes adjudication.
    decision_digest="fa9ef091026cbcf75998b2adc6446e8f8f05f4505b3e40260d5f0aa8532a2372",
    rules=(
        _ra.Rule(
            rule_id="dfm_screen_check.via-screen-did-not-run",
            landed_in="#562",
            requires=("verdict", "findings"),
            decide=_via_screen_vacuity,
            what=("a plain PASS carrying VIA_*_NOT_FOUND screened no via at all"),
        ),
    ),
)


def audit(project: Path) -> dict:
    findings = []
    routed = _pl.pnr_dir(project) / "routed.def"
    density_json = project / "reports" / "density.json"
    if not routed.is_file() and not density_json.is_file() \
            and not _pl.report_path(project, "density.json").is_file():
        return {"verdict": "SKIP", "rc": 2,
                "reason": ("no routed.def and no density artifacts yet — "
                           "run routing + metal fill first")}

    # 1) CMP density — CROSS-REFERENCE Step 34's gate (flow v2.3.1: no
    # duplicate gating; three-natures split 31/34/35).
    gate_json = project / "reports" / "phase2" / "gates" / \
        "metal_fill_density.json"
    density_ref = None
    if gate_json.is_file():
        try:
            g = json.loads(gate_json.read_text(errors="replace"))
            density_ref = {
                "step34_pass": bool(g.get("summary", {}).get("pass")),
                "errors": g.get("summary", {}).get("errors_count"),
                "source": str(gate_json.relative_to(project)),
            }
        except (OSError, ValueError):
            density_ref = {"unparseable": True,
                           "source": str(gate_json.relative_to(project))}
    if density_ref is None:
        findings.append({
            "severity": "INFO", "category": "DENSITY_REF",
            "message": ("Step-34 metal-fill density gate result not "
                        "present yet — density is GATED at Step 34, "
                        "referenced here (run metal_fill_density_check)")})
    elif density_ref.get("step34_pass"):
        findings.append({
            "severity": "INFO", "category": "DENSITY_REF",
            "message": "Step-34 density gate: PASS (cross-reference)"})
    else:
        findings.append({
            "severity": "WARNING", "category": "DENSITY_REF",
            "message": ("Step-34 density gate did not PASS — resolve at "
                        "Step 34 (this screen is optimization advisory, "
                        "not a duplicate gate)")})

    # 2) redundant-via ratio ------------------------------------------------
    via_summary = None
    if routed.is_file():
        txt = routed.read_text(errors="replace")
        cuts = _via_cut_counts(txt)              # DEF-declared vias
        uses = _via_uses_from_nets(txt)          # what routing REFERENCES
        total = sum(uses.values())
        if not uses and not cuts:
            findings.append({
                "severity": "INFO", "category": "VIA_DEFS_NOT_FOUND",
                "message": ("routed.def has no parseable VIAS section and "
                            "its NETS section references no via — "
                            "via-redundancy screen skipped (honest)")})
        elif not uses:
            findings.append({
                "severity": "INFO", "category": "VIA_USES_NOT_FOUND",
                "message": (f"routed.def declares {len(cuts)} via(s) but its "
                            f"NETS section references none — no signal-net "
                            f"via redundancy to screen (honest)")})
        else:
            # Resolve a cut count per REFERENCED name. DEF declaration wins;
            # a locatable tech LEF is the fallback; anything left over stays
            # UNRESOLVED and is disclosed, never assumed single-cut.
            resolved_cuts = {v: c for v, c in cuts.items() if v in uses}
            lef_sources: list = []
            if len(resolved_cuts) < len(uses):
                for lef in _locate_lef_files(project):
                    try:
                        lef_cuts = _lef_via_cut_counts(
                            lef.read_text(errors="replace"))
                    except OSError:
                        continue
                    hit = {v: c for v, c in lef_cuts.items()
                           if v in uses and v not in resolved_cuts}
                    if hit:
                        resolved_cuts.update(hit)
                        lef_sources.append(str(lef))
                    if len(resolved_cuts) >= len(uses):
                        break
            unresolved_names = sorted(v for v in uses
                                      if v not in resolved_cuts)
            unresolved = sum(uses[v] for v in unresolved_names)
            resolved = total - unresolved
            single = sum(n for v, n in uses.items()
                         if v in resolved_cuts and resolved_cuts[v] <= 1)
            frac = (single / resolved) if resolved else None
            via_summary = {
                "via_defs": len(cuts),
                "multi_cut_defs": sum(1 for c in cuts.values() if c > 1),
                "signal_via_uses": total,
                "resolved_via_uses": resolved,
                "unresolved_via_uses": unresolved,
                "unresolved_via_names": unresolved_names[:20],
                "single_cut_uses": single,
                "single_cut_fraction": (round(frac, 4)
                                        if frac is not None else None),
                "advisory_threshold": _SINGLE_CUT_ADVISORY,
                "cut_count_sources": ["routed.def VIAS"] + lef_sources,
            }
            if unresolved:
                findings.append({
                    "severity": "WARNING",
                    "category": "VIA_CUTS_UNRESOLVED",
                    "message": (
                        f"{unresolved}/{total} signal-net via uses reference "
                        f"via(s) declared neither in the DEF VIAS section nor "
                        f"in any locatable tech LEF "
                        f"({', '.join(unresolved_names[:6])}"
                        f"{' …' if len(unresolved_names) > 6 else ''}) — via "
                        f"redundancy is UNMEASURED for them. The screen does "
                        f"not infer a cut count from an absent declaration; "
                        f"put the tech LEF where the run can reach it to "
                        f"measure this")})
            if frac is not None and frac > _SINGLE_CUT_ADVISORY:
                findings.append({
                    "severity": "WARNING",
                    "category": "VIA_REDUNDANCY_LOW",
                    "message": (f"{frac:.1%} of the {resolved} RESOLVED "
                                f"signal-net via uses are single-cut "
                                f"(> {_SINGLE_CUT_ADVISORY:.0%} "
                                f"advisory) — dual-via insertion improves "
                                f"yield; OpenROAD has no via-doubling "
                                f"repair pass (advisory only)")})
            elif frac is not None:
                findings.append({
                    "severity": "INFO", "category": "VIA_REDUNDANCY_OK",
                    "message": (f"single-cut via fraction {frac:.1%} of the "
                                f"{resolved} RESOLVED signal-net via uses "
                                f"(<= {_SINGLE_CUT_ADVISORY:.0%} advisory)")})

    # 3) litho / min-width ownership ----------------------------------------
    findings.append({
        "severity": "INFO", "category": "LITHO_MIN_WIDTH_OWNERSHIP",
        "message": ("litho-friendly / min-width-margin rules are enforced "
                    "by the Step-31 sign-off DRC deck (KLayout) — not "
                    "re-executed here")})

    # flow v2.3.1 — advanced-node trigger: derive the process node from the
    # PDK's own liberty filenames (input/pdk/liberty/*.lib); at <=28nm
    # the foundry-side items escalate to designer-collaboration REVIEW.
    process_nm = _derive_process_nm(project)
    advanced_node = process_nm is not None and process_nm <= 28
    foundry_side = [dict(i) for i in _FOUNDRY_SIDE_ITEMS]
    if advanced_node:
        for item in foundry_side:
            item["status"] = "DESIGNER_COLLAB_REVIEW"
        findings.append({
            "severity": "WARNING", "category": "ADVANCED_NODE_DFM",
            "message": (f"process node {process_nm} nm <= 28 nm — "
                        f"OPC/RET/litho-friendly items escalate to "
                        f"designer-collaboration review (flow v2.3.1)")})

    advisories = [f for f in findings if f["severity"] == "WARNING"]
    verdict = "PASS_WITH_ADVISORIES" if advisories else "PASS"
    return {
        "verdict": verdict,
        # The two producer tiers retain distinct process exit codes for direct
        # callers. Step 35 consumes the structured output, not a gate slot.
        "rc": 1 if advisories else 0,
        "density_ref": density_ref,
        "via_redundancy": via_summary,
        "process_nm": process_nm,
        "advanced_node": advanced_node,
        "foundry_side": foundry_side,
        "advanced_node_note": _ADVANCED_NODE_NOTE,
        "findings": findings,
    }


def _derive_process_nm(project: Path):
    """Process node from the PDK's own liberty filenames — the same
    PDK-namespaced heuristic foundry_handoff_pack_gen uses."""
    lib_dir = project / "input" / "pdk" / "liberty"
    if not lib_dir.is_dir():
        return None
    for tag in ("180", "130", "65", "45", "28", "22", "16", "12", "7", "5"):
        if any(tag in f.name for f in lib_dir.glob("*.lib")):
            return int(tag)
    return None


def advisory_trailer(rep: dict) -> str:
    """One terse line naming the advisories, printed LAST.

    `flow_compliance_check._check_program_exit_zero` keeps only the final 300
    characters of stdout as the gate's reason snippet, and this program's
    stdout is a multi-KiB JSON document — so without a trailer the ADVISORY
    line on the step listing shows a fragment of the JSON body instead of the
    finding. A finding that is recorded but unreadable is the same defect this
    change exists to remove, one layer further out.
    """
    warns = [f for f in rep.get("findings") or []
             if f.get("severity") == "WARNING"]
    if not warns:
        return f"dfm_screen_check: {rep.get('verdict')} — no advisory finding"
    cats = ",".join(f.get("category", "?") for f in warns)
    return (f"dfm_screen_check: {rep.get('verdict')} — {len(warns)} advisory "
            f"finding(s) [{cats}]: {warns[0].get('message', '')[:150]}")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    ap.add_argument("project_dir", type=Path)
    ap.add_argument("--json", default=None)
    args = ap.parse_args(argv)
    if not args.project_dir.is_dir():
        print(f"ERROR: not a directory: {args.project_dir}", file=sys.stderr)
        return 1
    project = args.project_dir.resolve()
    rep = audit(project)
    rc = rep.pop("rc")
    rep = {"program": "dfm_screen_check", "version": "1.0.0", **rep}
    out = json.dumps(rep, indent=2, ensure_ascii=False)
    # canonical step artifact (Step 35 required_outputs) — always written
    # when the screen actually ran (not on vacuous SKIP).
    if rc != 2:
        canon = project / "reports" / "phase3" / "dfm_screen.json"
        canon.parent.mkdir(parents=True, exist_ok=True)
        canon.write_text(out + "\n")
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(out)
    print(out)
    # MUST stay the last thing printed — see advisory_trailer's docstring.
    print(advisory_trailer(rep))
    return rc


if __name__ == "__main__":
    sys.exit(main())
