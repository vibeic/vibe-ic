#!/usr/bin/env python3
"""spare_cell_preservation_check.py — Design-for-ECO PRESERVATION gate.

THE user's key concern: spare/ECO cells/gates/pads look exactly like
dead logic and WILL be stripped by any optimizer (yosys opt_clean,
post-DFT resynth, OpenROAD remove_buffers/repair_design/opt, metal
fill) unless they are protected. This checker proves they SURVIVED.

It takes the spare-cell set recorded at insertion time
(`phase3/stage3/pnr/spare_cells.json`) and compares it against the
FINAL artefacts — the post-PnR netlist, the routed / filled DEF, and
the GDS — asserting that EVERY spare instance (by name) is still
present, and that its dont_touch / keep tag is intact wherever the
artefact format carries one.

  FAIL if any spare/ECO cell/gate/pad:
    * was removed (name absent from every final artefact searched), or
    * lost its keep attribute (present in a netlist but no `keep`/
      `dont_touch` marker on it when at least one final artefact records
      such markers).

Emits reports/spare_preservation.json:
  {inserted, survived, removed:[...], untagged:[...],
   all_keep_attr_intact:bool, verdict}

Exit 0 PASS / 1 FAIL / 2 IO-arg error. chip-AGNOSTIC.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple

try:
    import _path_layout as _pl  # type: ignore
except Exception:  # pragma: no cover
    _pl = None


def _load_json(path: Path) -> Optional[dict]:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def _spare_names_and_types(plan: dict) -> List[Tuple[str, str]]:
    """Return [(name, type), ...] for every inserted spare instance +
    spare pad. Pure."""
    out: List[Tuple[str, str]] = []
    for inst in plan.get("instances", []) or []:
        if isinstance(inst, dict) and inst.get("name"):
            out.append((str(inst["name"]), str(inst.get("type", ""))))
    for pad in plan.get("spare_pads", []) or []:
        if isinstance(pad, dict) and pad.get("name"):
            out.append((str(pad["name"]), "pad"))
    return out


def name_present_in_text(name: str, text: str) -> bool:
    """Word-boundary-anchored presence test for an instance name in a
    netlist / DEF / GDS-ascii blob. Pure, chip-AGNOSTIC."""
    if not name or not text:
        return False
    return re.search(r"(?<![A-Za-z0-9_])" + re.escape(name)
                     + r"(?![A-Za-z0-9_])", text) is not None


def keep_attr_present_for(name: str, texts: Dict[str, str]) -> bool:
    """Return True iff at least one artefact records a keep / dont_touch
    marker associated with `name`. We accept several canonical forms:
      * a `set_dont_touch <name>` / `dont_touch ... <name>` directive,
      * a `(* keep *)` attribute on the same line as the instance,
      * a DEF `+ FIXED` placement status on the instance (a fixed spare
        is functionally protected from legalization), or
      * a `keep` / `dont_touch` token on the same line as the name.
    Pure, chip-AGNOSTIC."""
    nre = re.escape(name)
    patterns = [
        re.compile(r"set_dont_touch\b[^\n]*\b" + nre + r"\b"),
        re.compile(r"\bdont_touch\b[^\n]*\b" + nre + r"\b"),
        re.compile(nre + r"\b[^\n]*\bdont_touch\b"),
        re.compile(r"\(\*[^\n]*\bkeep\b[^\n]*\*\)[^\n]*\b" + nre + r"\b"),
        re.compile(nre + r"\b[^\n]*\bkeep\b"),
        re.compile(r"\b" + nre + r"\b[^\n]*\+\s*FIXED\b"),
        re.compile(r"\b" + nre + r"\b[^\n]*\+\s*COVER\b"),
    ]
    for text in texts.values():
        if not text:
            continue
        for pat in patterns:
            if pat.search(text):
                return True
    return False


def evaluate_preservation(plan: dict,
                          final_texts: Dict[str, str]) -> dict:
    """Pure evaluator. `plan` is spare_cells.json; `final_texts` maps an
    artefact label (e.g. 'netlist', 'def', 'gds') to its text content.

    For each spare: it SURVIVES iff its name is present in at least one
    final artefact. Its keep attr is INTACT iff a keep/dont_touch marker
    is found in some artefact (only required when at least one artefact
    carries any keep/dont_touch markers at all — a pure GDS-only set,
    which has no such concept, does not fail on the tag check).

    Returns {inserted, survived, removed[], untagged[],
    all_keep_attr_intact, verdict, artefacts}. chip-AGNOSTIC."""
    spares = _spare_names_and_types(plan)
    inserted = len(spares)
    removed: List[Dict[str, str]] = []
    untagged: List[Dict[str, str]] = []
    survived_names: Set[str] = set()

    # Does ANY artefact carry keep/dont_touch markers? If none do (e.g.
    # only a GDS was provided), we cannot assert on tags — so the tag
    # check is skipped and only survival is required.
    any_keep_capable = any(
        ("dont_touch" in t or "keep" in t or "FIXED" in t or "COVER" in t)
        for t in final_texts.values() if t
    )

    for name, typ in spares:
        present = any(name_present_in_text(name, t)
                      for t in final_texts.values())
        if not present:
            removed.append({"name": name, "type": typ})
            continue
        survived_names.add(name)
        if any_keep_capable and not keep_attr_present_for(name, final_texts):
            untagged.append({"name": name, "type": typ})

    survived = len(survived_names)
    all_keep_attr_intact = (len(untagged) == 0)
    # PASS iff nothing removed AND (no tag-capable artefact OR all tagged)
    # AND there was actually something to preserve.
    verdict = "PASS" if (inserted > 0
                         and not removed
                         and all_keep_attr_intact) else "FAIL"
    return {
        "inserted": inserted,
        "survived": survived,
        "removed": removed,
        "untagged": untagged,
        "all_keep_attr_intact": all_keep_attr_intact,
        "keep_check_applied": any_keep_capable,
        "verdict": verdict,
        "artefacts": sorted(final_texts.keys()),
    }


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return ""


def _collect_final_artefacts(project: Path) -> Dict[str, Path]:
    """Locate the final netlist / DEF / GDS to search. Prefers the
    most-final variant of each (filled.def > routed.def; <top>.gds in
    the canonical GDS dir; post-PnR netlist <top>_pnr.v). chip-AGNOSTIC.
    Returns label -> Path for files that exist."""
    if _pl is not None:
        pnr = _pl.pnr_dir(project)
        gds_dir = _pl.gds_dir(project)
    else:  # pragma: no cover
        pnr = project / "phase3/stage3/pnr"
        gds_dir = project / "phase3/stage4/gds"
    out: Dict[str, Path] = {}

    # Final netlist: post-PnR write_verilog, else canonicalized synth.
    for cand in sorted(pnr.glob("*_pnr.v")) if pnr.is_dir() else []:
        out["netlist"] = cand
        break

    # Final DEF: filled.def (post metal fill) preferred, else routed.def,
    # else the top-level <top>.def.
    if pnr.is_dir():
        for fname in ("filled.def", "routed.def"):
            cand = pnr / fname
            if cand.is_file():
                out["def"] = cand
                break
        if "def" not in out:
            top_defs = [d for d in sorted(pnr.glob("*.def"))
                        if d.name not in ("floorplan.def", "placed.def",
                                          "post_cts.def", "post_hold.def")]
            if top_defs:
                out["def"] = top_defs[0]

    # GDS (ASCII text scan only catches ascii-gds / oasis-text; binary
    # GDS will not name-match but DEF/netlist cover survival).
    if gds_dir.is_dir():
        for cand in sorted(gds_dir.glob("*.gds")):
            out["gds"] = cand
            break

    return out


def audit(project: Path) -> dict:
    if _pl is not None:
        spare_json = _pl.pnr_dir(project) / "spare_cells.json"
    else:  # pragma: no cover
        spare_json = project / "phase3/stage3/pnr/spare_cells.json"
    base = {
        "program": "spare_cell_preservation_check",
        "version": "1.0.0",
        "project_dir": str(project),
    }
    if not spare_json.is_file():
        return {**base, "verdict": "FAIL", "inserted": 0,
                "reasons": [f"spare_cells.json not found at {spare_json}"]}
    plan = _load_json(spare_json)
    if plan is None:
        return {**base, "verdict": "FAIL", "inserted": 0,
                "reasons": [f"spare_cells.json is not valid JSON: {spare_json}"]}

    artefact_paths = _collect_final_artefacts(project)
    if not artefact_paths:
        return {**base, "verdict": "FAIL", "inserted": len(
                    _spare_names_and_types(plan)),
                "reasons": ["no final netlist/DEF/GDS artefact found to "
                            "verify spare survival against"]}
    final_texts = {label: _read_text(p)
                   for label, p in artefact_paths.items()}
    result = evaluate_preservation(plan, final_texts)
    result.update(base)
    result["artefact_paths"] = {k: str(v)
                                for k, v in artefact_paths.items()}
    return result


def main(argv: Optional[list] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Design-for-ECO spare-cell preservation check")
    ap.add_argument("project_dir", help="Project root directory")
    ap.add_argument("--json", default=None, help="JSON report output path")
    args = ap.parse_args(argv)

    project = Path(args.project_dir)
    if not project.is_dir():
        print(f"ERROR: not a directory: {project}", file=sys.stderr)
        return 2

    report = audit(project)

    # Canonical output: reports/spare_preservation.json (in addition to
    # any explicit --json path). Written to the literal flow-declared
    # path (NOT via the report auto-router, which would file an unknown
    # name under reports/audit/).
    canon = project / "reports" / "spare_preservation.json"
    out = json.dumps(report, indent=2, ensure_ascii=False)
    try:
        canon.parent.mkdir(parents=True, exist_ok=True)
        canon.write_text(out + "\n")
    except Exception:
        pass
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(out + "\n")
    print(out)
    return 0 if report.get("verdict") == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
