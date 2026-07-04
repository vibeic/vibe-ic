#!/usr/bin/env python3
r"""cvdp_task_router.py — FIRST-LAYER task-nature router for CVDP (before Phase 1).

Owner architecture (2026-07-05): CVDP is NOT a uniform "spec/prompt → RTL"
benchmark like VerilogEval / RTLLM. Its records span FIVE task natures, and only
ONE of them is the plugin's Phase-1 (spec → design-doc → RTL) domain. A FIRST
LAYER must parse each problem's NATURE and route it:

  route = phase1_entry   — a PURE-TEXT SPEC that asks for a brand-new RTL. This
                           is exactly what Phase-1 (L1-L23 doc extraction →
                           json-to-rtl / spec-to-rtl) is for.
  route = ai_led         — completion / functional-modification / optimization /
                           debug. The task hands you EXISTING RTL (or a partial
                           interface) to transform against a goal. This is NOT
                           the plugin's spec→RTL pipeline; an AI leads it
                           directly (read the given RTL, apply the change, keep
                           the interface). Forcing it through Phase-1's
                           doc-extraction would be the wrong tool.

For CVDP the nature is LABELLED in `record.categories` (the `cidNNN` token), so
the routing is DETERMINISTIC — no AI needed to classify what the dataset already
labels:

  cid003  spec_generation          → phase1_entry
  cid002  completion               → ai_led
  cid004  functional_modification  → ai_led
  cid007  optimization             → ai_led
  cid016  debug                    → ai_led

For a GENERAL (non-CVDP) prompt there is no cid label, so the first layer is a
genuine AI parse. `classify_task_nature()` gives the deterministic fallback
signal (context RTL present → a transform task → ai_led; else → phase1_entry)
AND sets `needs_ai_parse=True` so the caller knows an AI should confirm the
nature on the unlabelled prompt.

CLI:
    python3 cvdp_task_router.py --dataset <cvdp.jsonl> [--report out.json]
      → prints the phase1_entry vs ai_led split by task nature.

chip-AGNOSTIC. Deterministic for labelled records.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# CVDP category-id → task nature + the PLUGIN ENTRY (a step or loop-of-steps)
# that nature enters. NONE of these is "out of scope": every nature maps to a
# concrete plugin capability. Each entry names its deterministic-first program(s)
# (program-first), the AI skill that leads the novel-case body, and the verify
# gates that close the loop. All programs/skills referenced here exist in the
# plugin (programs/*.py, skills/*/SKILL.md).
#
# `route` is coarse: `phase1_entry` (Phase-1 owns spec→RTL) vs `plugin_loop`
# (a different plugin loop owns the transform). `plugin_entry` carries the
# concrete step list for the caller to execute.
_CID_TASK: Dict[str, Dict[str, Any]] = {
    # Pure text spec → brand-new RTL: the Phase-1 (spec→design-doc→RTL) domain.
    "cid003": {
        "nature": "spec_generation", "route": "phase1_entry",
        "plugin_entry": {
            "name": "phase1_spec_to_rtl",
            "deterministic_first": ["phase1_one_shot_runner.py",
                                    "deterministic_rtl_dispatcher.py"],
            "ai_backup": ["spec-to-rtl"],
            "verify": ["rtl_hygiene_lint.py", "spec_conformance_check.py",
                       "phase2-rtl-verify"],
        }},
    # Given a partial interface/RTL → complete the design.
    "cid002": {
        "nature": "completion", "route": "plugin_loop",
        "plugin_entry": {
            "name": "completion_loop",
            "deterministic_first": ["cvdp_context_interface_recover.py",
                                    "modify_complete_synth.py"],
            "ai_backup": ["spec-to-rtl"],
            "verify": ["rtl_hygiene_lint.py", "spec_conformance_check.py",
                       "phase2-rtl-verify"],
        }},
    # Given RTL → change its behaviour per a spec delta (functional ECO).
    "cid004": {
        "nature": "functional_modification", "route": "plugin_loop",
        "plugin_entry": {
            "name": "modify_loop",
            "deterministic_first": ["cvdp_context_interface_recover.py",
                                    "modify_complete_synth.py"],
            "ai_backup": ["rtl-repair", "eco-plan"],
            "verify": ["equivalence-check", "phase2-rtl-verify",
                       "rtl_hygiene_lint.py"],
        }},
    # Reduce area / pass lint thresholds (yosys cell/wire, verilator -Wall).
    "cid007": {
        "nature": "optimization", "route": "plugin_loop",
        "plugin_entry": {
            "name": "optimize_loop",
            "deterministic_first": ["rtl_hygiene_lint.py"],
            "ai_backup": ["rtl-review", "synth-doctor", "ppa-predict"],
            "verify": ["equivalence-check", "phase2-rtl-verify"],
        }},
    # Given buggy RTL → fix until it matches the spec.
    "cid016": {
        "nature": "debug", "route": "plugin_loop",
        "plugin_entry": {
            "name": "debug_loop",
            "deterministic_first": ["cvdp_context_interface_recover.py",
                                    "debug_first_pass.py"],
            "ai_backup": ["rtl-repair"],
            "verify": ["phase2-rtl-verify", "equivalence-check",
                       "formal-verify", "rtl_hygiene_lint.py"],
        }},
}

_CID_RE = re.compile(r"^cid0*\d+$", re.IGNORECASE)


def _cid_of(record: Dict[str, Any]) -> Optional[str]:
    """The cidNNN token in record.categories, normalised to `cidNNN`, or None."""
    for c in (record.get("categories") or []):
        s = str(c).strip().lower()
        if _CID_RE.match(s):
            # normalise cid3 / cid03 → cid003
            m = re.match(r"cid0*(\d+)$", s)
            if m:
                return f"cid{int(m.group(1)):03d}"
    return None


def classify_task_nature(prompt: str,
                         has_context: bool,
                         cid: Optional[str] = None) -> Dict[str, Any]:
    """Return {nature, route, source, needs_ai_parse} for one problem.

    * A known CVDP `cid` decides deterministically (source='cid_label').
    * Otherwise (general prompt) fall back to the structural signal — existing
      RTL context ⇒ a transform task ⇒ ai_led; no context ⇒ phase1_entry — and
      flag `needs_ai_parse` so the caller runs the real AI first-layer parse to
      confirm the nature on the unlabelled prompt. Chip-AGNOSTIC."""
    if cid and cid in _CID_TASK:
        t = _CID_TASK[cid]
        return {"nature": t["nature"], "route": t["route"],
                "plugin_entry": t["plugin_entry"],
                "source": "cid_label", "needs_ai_parse": False}
    # Unlabelled general prompt: deterministic fallback + AI-parse flag. Existing
    # RTL context ⇒ a transform → the modify_loop entry (the closest general
    # plugin loop); no context ⇒ Phase-1 spec→RTL.
    if has_context:
        return {"nature": "transform_existing_rtl", "route": "plugin_loop",
                "plugin_entry": _CID_TASK["cid004"]["plugin_entry"],
                "source": "context_heuristic", "needs_ai_parse": True}
    return {"nature": "spec_generation", "route": "phase1_entry",
            "plugin_entry": _CID_TASK["cid003"]["plugin_entry"],
            "source": "no_context_heuristic", "needs_ai_parse": True}


def route_record(record: Dict[str, Any]) -> Dict[str, Any]:
    cid = _cid_of(record)
    inp = record.get("input") or {}
    has_ctx = bool(isinstance(inp, dict) and inp.get("context"))
    verdict = classify_task_nature(
        str(inp.get("prompt") or "") if isinstance(inp, dict) else "",
        has_ctx, cid)
    return {"id": record.get("id"), "cid": cid, "has_context": has_ctx,
            **verdict}


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dataset", required=True, help="CVDP dataset JSONL")
    ap.add_argument("--report", default="", help="report JSON path")
    a = ap.parse_args(argv)

    ds = Path(a.dataset)
    if not ds.is_file():
        print(f"cvdp_task_router: dataset not found: {ds}", file=sys.stderr)
        return 2

    routed: List[Dict[str, Any]] = []
    with ds.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                routed.append(route_record(json.loads(line)))
            except Exception:
                continue

    phase1 = [r for r in routed if r["route"] == "phase1_entry"]
    plugin_loop = [r for r in routed if r["route"] == "plugin_loop"]
    by_nature: Dict[str, int] = {}
    entry_of: Dict[str, str] = {}
    for r in routed:
        by_nature[r["nature"]] = by_nature.get(r["nature"], 0) + 1
        pe = r.get("plugin_entry") or {}
        entry_of[r["nature"]] = pe.get("name", "?")
    report = {
        "dataset": str(ds),
        "n": len(routed),
        "phase1_entry": len(phase1),
        "plugin_loop": len(plugin_loop),
        "by_nature": by_nature,
        "records": routed,
    }
    if a.report:
        Path(a.report).write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"cvdp_task_router: {len(routed)} record(s) — every nature enters a plugin step/loop")
    print(f"  route → phase1_entry : {len(phase1)}  (spec_generation)")
    print(f"  route → plugin_loop  : {len(plugin_loop)}  (completion/modify/optimize/debug)")
    print("  by nature → plugin entry:")
    for nat in sorted(by_nature):
        print(f"    {nat:26} {by_nature[nat]:>4}  → {entry_of.get(nat)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
