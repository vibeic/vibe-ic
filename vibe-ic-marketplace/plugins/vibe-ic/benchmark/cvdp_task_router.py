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

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "programs"))
import task_nature_route as _G  # noqa: E402  the GENERAL front door

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
# ── THIN ADAPTER (§ 0 GENERAL-CORE / THIN-ADAPTER) ───────────────────────────
# The ONLY CVDP-specific knowledge in this file: which `cidNNN` label means
# which task NATURE. The natures themselves, and the normal plugin entry each
# one takes, are GENERAL IC-design knowledge and live in
# `programs/task_nature_route.py` — reachable from a plain user prompt with no
# benchmark present. Do not re-add an entry table here: a benchmark adapter
# that owns routing logic is the naming debt § 0's naming test forbids, and it
# is why a 2026-08-24 run could enter CVDP through a hand-rolled harness while
# the general layer had no multi-entry front door at all.
_CID_NATURE: Dict[str, str] = {
    "cid003": "spec_generation",           # pure spec  → brand-new RTL
    "cid002": "completion",                # partial RTL → complete it
    "cid004": "functional_modification",   # RTL + spec delta → RTL modification
    "cid007": "optimization",              # RTL → smaller / lint-clean
    "cid016": "debug",                     # buggy RTL → fix to spec
}

# Back-compat view for callers that read the old shape. Derived, never edited.
_CID_TASK: Dict[str, Dict[str, Any]] = {
    cid: {"nature": nat,
          "route": _G.NATURE_ENTRY[nat]["route"],
          "plugin_entry": _G.NATURE_ENTRY[nat]["plugin_entry"]}
    for cid, nat in _CID_NATURE.items()
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
    """Map a CVDP `cidNNN` label to a NATURE, then delegate the routing to the
    general front door. Kept as a named function because the CVDP drivers call
    it; it holds no routing logic of its own."""
    verdict = _G.classify_task_nature(prompt, has_context,
                                      _CID_NATURE.get(cid or ""))
    if cid in _CID_NATURE:
        verdict = dict(verdict, source="cid_label")
    return verdict


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
