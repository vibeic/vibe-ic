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

# CVDP category-id → (task nature, route). The ONLY spec→RTL nature is cid003.
_CID_TASK: Dict[str, Dict[str, str]] = {
    "cid003": {"nature": "spec_generation", "route": "phase1_entry"},
    "cid002": {"nature": "completion", "route": "ai_led"},
    "cid004": {"nature": "functional_modification", "route": "ai_led"},
    "cid007": {"nature": "optimization", "route": "ai_led"},
    "cid016": {"nature": "debug", "route": "ai_led"},
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
                "source": "cid_label", "needs_ai_parse": False}
    # Unlabelled: deterministic fallback + AI-parse flag.
    if has_context:
        return {"nature": "transform_existing_rtl", "route": "ai_led",
                "source": "context_heuristic", "needs_ai_parse": True}
    return {"nature": "spec_generation", "route": "phase1_entry",
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
    ai_led = [r for r in routed if r["route"] == "ai_led"]
    by_nature: Dict[str, int] = {}
    for r in routed:
        by_nature[r["nature"]] = by_nature.get(r["nature"], 0) + 1
    report = {
        "dataset": str(ds),
        "n": len(routed),
        "phase1_entry": len(phase1),
        "ai_led": len(ai_led),
        "by_nature": by_nature,
        "records": routed,
    }
    if a.report:
        Path(a.report).write_text(
            json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    print(f"cvdp_task_router: {len(routed)} record(s)")
    print(f"  route → phase1_entry : {len(phase1)}  (spec_generation only)")
    print(f"  route → ai_led       : {len(ai_led)}  (completion/modify/optimize/debug)")
    print("  by nature:")
    for nat in sorted(by_nature):
        print(f"    {nat:26} {by_nature[nat]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
