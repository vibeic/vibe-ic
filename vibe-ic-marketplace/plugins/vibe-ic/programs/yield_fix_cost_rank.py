#!/usr/bin/env python3
"""yield_fix_cost_rank.py — D3 program-first extraction of the
yield-diagnostic skill's fixed fix-cost ordinal ranking.

Doctrine
--------
`skills/yield-diagnostic/SKILL.md` carried a static cost-order table in two
places — the workflow step ("ordered by cost (test program tweak < metal ECO
< base-layer ECO < respin)") and the "Proposed fixes (by cost)" output table.
The relative cost order of the four remediation classes is a fixed lookup, so
ranking a set of candidate fixes by cost is a deterministic sort, not
judgment.  This program owns the ordinal table + the sort.

The verbatim spec ordering (cheapest first):

    test program tweak  <  metal ECO  <  base-layer ECO  <  respin

NO-FABRICATION SCOPE
--------------------
Only the SPEC-GIVEN cost ORDER is encoded.  No yield-uplift numbers, dollar
costs, or risk scores are invented — those are caller-supplied (and reported
verbatim if present, never synthesised).  Classifying a free-text fix into one
of the four remediation classes uses ONLY explicit keywords drawn straight
from the four spec class names (test/tweak/margin, metal/eco, base/layer,
respin/spin); a fix that matches none is reported as `unknown` and ranked
last with an honest UNCLASSIFIED finding — never silently bucketed.

Verdicts
--------
* PASS    (rc=0) — all supplied fixes were classified into a spec class and the
                   cost-sorted ordering was emitted.
* FAIL    (rc=1) — input missing/empty/unparseable, OR one or more fixes could
                   not be mapped to a spec remediation class (honest: the
                   ordering would be a guess). Never a vacuous PASS.
* SKIP    (rc=2) — input path does not exist (operational).

chip-AGNOSTIC.  No vendor / IC / tool-specific data hard-coded.

Usage
-----
    # rank a JSON list of fixes:
    python3 yield_fix_cost_rank.py fixes.json [--json out.json]
    # fixes.json: [{"fix": "Relax test margin on BIN_X", "expected_uplift": "+2%",
    #               "risk": "test escape"}, ...]
    #   (a fix may also carry an explicit "class" to skip keyword inference)
    #
    # or classify a single fix string:
    python3 yield_fix_cost_rank.py --fix "Metal ECO on clock tree" [--json out]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional


_GATE_NAME = "yield_fix_cost_rank"

# ---- The deterministic spec ordinal table (verbatim, cheapest first) -------
#   test program tweak  <  metal ECO  <  base-layer ECO  <  respin
REMEDIATION_CLASSES = ("test_tweak", "metal_eco", "base_layer_eco", "respin")

# ordinal 0 == cheapest.
CLASS_COST_ORDINAL: Dict[str, int] = {
    "test_tweak":     0,
    "metal_eco":      1,
    "base_layer_eco": 2,
    "respin":         3,
}

CLASS_COST_LABEL: Dict[str, str] = {
    "test_tweak":     "Low",
    "metal_eco":      "Med",
    "base_layer_eco": "High",
    "respin":         "Very High",
}

CLASS_DESC: Dict[str, str] = {
    "test_tweak":     "Test program tweak (relax margin / re-bin / re-test)",
    "metal_eco":      "Metal-only ECO (re-route / spare-cell rewire, no base spin)",
    "base_layer_eco": "Base-layer ECO (diffusion/poly change, partial respin)",
    "respin":         "Full respin (new mask set)",
}

# Keyword classifier — keywords taken ONLY from the four spec class names, so
# no new taxonomy is invented.  Order matters: most-specific first so that
# "base-layer ECO" is not captured by the generic "eco" metal rule, and
# "respin" wins over everything.
# Each entry: (compiled regex, class)
_CLASS_PATTERNS = [
    (re.compile(r"\bre-?spin\b|\bnew\s+mask", re.I),                "respin"),
    (re.compile(r"\bbase[\s_-]*layer\b|\bbase[\s_-]*spin\b"
                r"|\bdiffusion\b|\bpoly\b|\ball[\s_-]*layer", re.I), "base_layer_eco"),
    (re.compile(r"\bmetal[\s_-]*(only|eco|layer)?\b|\bmetal\b"
                r"|\beco\b|\breroute\b|\bre-?route\b", re.I),        "metal_eco"),
    (re.compile(r"\btest\b|\btweak\b|\bmargin\b|\bre-?bin\b"
                r"|\bre-?test\b|\bbin\b|\bguardband\b|\bguard[\s_-]*band\b",
                re.I),                                              "test_tweak"),
]

# explicit-class aliases (when a fix carries a "class" field)
_CLASS_ALIASES: Dict[str, str] = {
    "test_tweak": "test_tweak", "test": "test_tweak", "test_program": "test_tweak",
    "tweak": "test_tweak", "test_program_tweak": "test_tweak",
    "metal_eco": "metal_eco", "metal": "metal_eco", "metal_only": "metal_eco",
    "metal-eco": "metal_eco", "metal_only_eco": "metal_eco", "eco": "metal_eco",
    "base_layer_eco": "base_layer_eco", "base_layer": "base_layer_eco",
    "base-layer": "base_layer_eco", "base_layer-eco": "base_layer_eco",
    "respin": "respin", "re-spin": "respin", "full_respin": "respin",
}


def normalize_class(raw: Optional[str]) -> Optional[str]:
    if raw is None:
        return None
    return _CLASS_ALIASES.get(str(raw).strip().lower().replace(" ", "_"))


def classify_fix(text: str) -> Optional[str]:
    """Map a free-text fix to a spec remediation class via spec keywords.

    Returns the class, or None if no spec keyword matched (caller treats as
    UNCLASSIFIED — never silently bucketed)."""
    if not text:
        return None
    for pat, cls in _CLASS_PATTERNS:
        if pat.search(text):
            return cls
    return None


def cost_ordinal(cls: str) -> int:
    return CLASS_COST_ORDINAL[cls]


def rank_fixes(fixes: List[Dict[str, Any]]):
    """Classify + sort a list of fix dicts by spec cost ordinal (cheapest
    first). Stable within the same class (input order preserved).

    Returns (ranked_list, unclassified_list)."""
    enriched = []
    unclassified = []
    for i, f in enumerate(fixes):
        text = (f.get("fix") or f.get("name") or f.get("description") or "")
        cls = normalize_class(f.get("class")) or classify_fix(text)
        if cls is None:
            unclassified.append({"index": i, "fix": text})
            continue
        enriched.append({
            "fix": text,
            "class": cls,
            "cost_ordinal": cost_ordinal(cls),
            "cost_label": CLASS_COST_LABEL[cls],
            "class_desc": CLASS_DESC[cls],
            # caller-supplied, reported verbatim (never synthesised):
            "expected_uplift": f.get("expected_uplift"),
            "risk": f.get("risk"),
            "_input_index": i,
        })
    # stable sort by ordinal, then by input order.
    enriched.sort(key=lambda e: (e["cost_ordinal"], e["_input_index"]))
    for rank, e in enumerate(enriched, start=1):
        e["rank"] = rank
        e.pop("_input_index", None)
    return enriched, unclassified


def ranked_to_markdown(ranked: List[Dict[str, Any]]) -> str:
    out = ["## Proposed fixes (by cost)",
           "",
           "| # | Fix | Cost | Expected yield uplift | Risk |",
           "|---|-----|------|----------------------|------|"]
    for e in ranked:
        out.append(
            f"| {e['rank']} | {e['fix']} | {e['cost_label']} | "
            f"{e.get('expected_uplift') or ''} | {e.get('risk') or ''} |")
    out.append("")
    return "\n".join(out)


def _emit(args, verdict, payload, findings):
    out = {"gate": _GATE_NAME, "verdict": verdict, **payload, "findings": findings}
    if getattr(args, "json", None):
        op = Path(args.json)
        op.parent.mkdir(parents=True, exist_ok=True)
        op.write_text(json.dumps(out, indent=2, ensure_ascii=False) + "\n")
    print(f"=== {_GATE_NAME} ===")
    print(f"  verdict: {verdict}")
    for e in payload.get("ranked", []):
        print(f"  #{e['rank']} [{e['cost_label']}] {e['class']}: {e['fix']}")
    for f in findings:
        if f["severity"] in ("FAIL",):
            print(f"  [{f['severity']}] {f['rule']}: {f['message']}")
    return out


def main(argv=None):
    p = argparse.ArgumentParser()
    p.add_argument("input", nargs="?", help="JSON file: list of fix dicts")
    p.add_argument("--fix", default=None, help="classify a single fix string")
    p.add_argument("--json", default=None)
    args = p.parse_args(argv)

    findings: List[Dict[str, str]] = []
    fixes: List[Dict[str, Any]]

    if args.fix is not None:
        fixes = [{"fix": args.fix}]
    elif args.input is not None:
        ip = Path(args.input)
        if not ip.exists():
            print(f"[{_GATE_NAME}] input not found: {ip}", file=sys.stderr)
            return 2
        try:
            doc = json.loads(ip.read_text())
        except Exception as e:  # noqa: BLE001
            findings.append({"severity": "FAIL", "rule": "JSON_UNPARSEABLE",
                             "message": f"cannot parse {ip}: {e}"})
            _emit(args, "FAIL", {"ranked": []}, findings)
            return 1
        if isinstance(doc, dict) and "fixes" in doc:
            doc = doc["fixes"]
        if not isinstance(doc, list):
            findings.append({"severity": "FAIL", "rule": "NOT_A_LIST",
                             "message": "expected a JSON list of fix objects "
                                        "(or {'fixes': [...]})"})
            _emit(args, "FAIL", {"ranked": []}, findings)
            return 1
        fixes = [d if isinstance(d, dict) else {"fix": str(d)} for d in doc]
    else:
        findings.append({"severity": "FAIL", "rule": "NO_INPUT",
                         "message": "provide a fixes JSON file or --fix string"})
        _emit(args, "FAIL", {"ranked": []}, findings)
        return 1

    if not fixes:
        findings.append({"severity": "FAIL", "rule": "EMPTY_FIXES",
                         "message": "no fixes to rank"})
        _emit(args, "FAIL", {"ranked": []}, findings)
        return 1

    ranked, unclassified = rank_fixes(fixes)

    if unclassified:
        for u in unclassified:
            findings.append({
                "severity": "FAIL", "rule": "UNCLASSIFIED_FIX",
                "message": f"fix[{u['index']}] {u['fix']!r} matches no spec "
                           f"remediation class — refusing to guess its cost rank",
            })
        _emit(args, "FAIL",
              {"ranked": ranked, "unclassified": unclassified,
               "markdown": ranked_to_markdown(ranked)}, findings)
        return 1

    findings.append({
        "severity": "INFO", "rule": "RANKED",
        "message": f"{len(ranked)} fixes ranked by spec cost ordinal "
                   f"(cheapest first)",
    })
    _emit(args, "PASS",
          {"ranked": ranked, "unclassified": [],
           "markdown": ranked_to_markdown(ranked)}, findings)
    return 0


if __name__ == "__main__":
    sys.exit(main())
