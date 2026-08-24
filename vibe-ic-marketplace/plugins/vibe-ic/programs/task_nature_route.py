#!/usr/bin/env python3
r"""task_nature_route.py — WHICH ENTRY does an IC-design task come in at?

THE GENERAL FRONT DOOR. "Enter through Phase 1" is right for exactly one kind
of task — a pure text spec asking for brand-new RTL. It is WRONG for the other
four kinds, and saying it anyway is how a debug task gets pushed through a
spec→design-doc→RTL pipeline it has no business in.

    "我走任何的 benchmark 應該都是要走正常路徑嘛，只是說你要知道我正常路徑
     是從哪一個接口進來。比如說我是 debug，我 debug 就不是從 phase 1 進來嘛。"
                                              — owner directive 2026-08-25

FIVE NATURES, FIVE ENTRIES. Every one is a NORMAL plugin flow; none is a
benchmark-only path:

  spec_generation          → phase1_spec_to_rtl   (Phase 1 → Phase 2)
  completion               → completion_loop      (recover interface → Phase 2)
  functional_modification  → modify_loop          (ECO / rtl-repair)
  optimization             → optimize_loop        (synth-doctor / ppa)
  debug                    → debug_loop           (NOT Phase 1)

WHY THIS FILE EXISTS SEPARATELY FROM ANY BENCHMARK (§ 0 GENERAL-CORE /
THIN-ADAPTER). This routing is general IC-design knowledge — it is the same
decision whether the task arrives from a user prompt, a design doc, or a
benchmark record. It previously lived only inside `benchmark/cvdp_task_router.py`,
reachable only when running CVDP, which is exactly the naming debt § 0's naming
test describes: a `cvdp_…` file whose logic is pure prose/param handling. The
consequence was concrete — a 2026-08-24 CVDP run entered through a hand-rolled
prompt→drafts→gate loop because the general layer had no multi-entry front door
to enter through, so 224 of 302 records that should have taken completion /
modify / optimize / debug loops were pushed through free-hand authoring instead.

A BENCHMARK ADAPTER MUST NOT REIMPLEMENT THIS. Its only job is to map its own
record format onto a NATURE (e.g. CVDP's `cidNNN` label) and delegate here.
Chip-AGNOSTIC and dataset-AGNOSTIC: no SKU, no vendor, no dataset literal.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── The five natures → the normal plugin entry each one takes ────────────────
# `route` is coarse: `phase1_entry` (Phase-1 owns spec→RTL) vs `plugin_loop`
# (a different normal plugin loop owns the transform). `plugin_entry` carries
# the concrete step list for the caller to execute: deterministic PROGRAM
# first, AI skill as backup, then the verify gates that close the loop.
NATURE_ENTRY: Dict[str, Dict[str, Any]] = {
    # Pure text spec → brand-new RTL: the Phase-1 (spec→design-doc→RTL) domain.
    "spec_generation": {
        "route": "phase1_entry",
        "plugin_entry": {
            "name": "phase1_spec_to_rtl",
            "deterministic_first": ["phase1_one_shot_runner.py",
                                    "deterministic_rtl_dispatcher.py"],
            "ai_backup": ["spec-to-rtl"],
            "verify": ["rtl_hygiene_lint.py", "spec_conformance_check.py",
                       "phase2-rtl-verify"],
        }},
    # Given a partial interface/RTL → complete the design.
    "completion": {
        "route": "plugin_loop",
        "plugin_entry": {
            "name": "completion_loop",
            "deterministic_first": ["cvdp_context_interface_recover.py",
                                    "modify_complete_synth.py"],
            "ai_backup": ["spec-to-rtl"],
            "verify": ["rtl_hygiene_lint.py", "spec_conformance_check.py",
                       "phase2-rtl-verify"],
        }},
    # Given RTL → change its behaviour per a spec delta (functional ECO).
    "functional_modification": {
        "route": "plugin_loop",
        "plugin_entry": {
            "name": "modify_loop",
            "deterministic_first": ["cvdp_context_interface_recover.py",
                                    "modify_complete_synth.py"],
            "ai_backup": ["rtl-repair", "eco-plan"],
            "verify": ["equivalence-check", "phase2-rtl-verify",
                       "rtl_hygiene_lint.py"],
        }},
    # Reduce area / pass lint thresholds (yosys cell/wire, verilator -Wall).
    "optimization": {
        "route": "plugin_loop",
        "plugin_entry": {
            "name": "optimize_loop",
            "deterministic_first": ["rtl_hygiene_lint.py"],
            "ai_backup": ["rtl-review", "synth-doctor", "ppa-predict"],
            "verify": ["equivalence-check", "phase2-rtl-verify"],
        }},
    # Given buggy RTL → fix until it matches the spec. NOT a Phase-1 task.
    "debug": {
        "route": "plugin_loop",
        "plugin_entry": {
            "name": "debug_loop",
            "deterministic_first": ["cvdp_context_interface_recover.py",
                                    "debug_first_pass.py"],
            "ai_backup": ["rtl-repair"],
            "verify": ["phase2-rtl-verify", "equivalence-check",
                       "formal-verify", "rtl_hygiene_lint.py"],
        }},
}

# A transform on existing RTL whose exact nature the caller has NOT pinned and
# whose prose gave no usable hint. It routes to the modify_loop entry (the
# closest general loop) but reports its nature as `transform_existing_rtl` —
# an HONEST label saying "this is a transform, which kind is unresolved". Do
# not relabel it `functional_modification`: that claims a specificity the
# router does not have, and the caller uses `needs_ai_parse` to resolve it.
_UNPINNED_TRANSFORM_NATURE = "transform_existing_rtl"
_UNPINNED_TRANSFORM_ENTRY = "functional_modification"

# Prose signals, weakest evidence — used ONLY to seed `needs_ai_parse`, never
# to override an explicitly supplied nature. Deliberately small: a real parse
# is the AI's job, and a long keyword table would fake determinism.
_PROSE_HINTS = (
    ("debug", re.compile(
        r"\b(bug|buggy|fix(es|ed)?\s+the\s+\w+|incorrect(ly)?|"
        r"does\s?n[o']t\s+work|failing|regression)\b", re.I)),
    ("optimization", re.compile(
        r"\b(optimi[sz]e|reduce\s+(area|cells?|wires?|power)|"
        r"smaller|fewer\s+(cells?|wires?)|lint\s+clean)\b", re.I)),
    ("completion", re.compile(
        r"\b(complete\s+the|fill\s+in|finish\s+the|implement\s+the\s+missing)\b",
        re.I)),
    ("functional_modification", re.compile(
        r"\b(modif(y|ies|ied)|change\s+the\s+behaviou?r|add\s+support\s+for|"
        r"extend\s+the)\b", re.I)),
)


def classify_task_nature(prompt: str,
                         has_context: bool,
                         nature: Optional[str] = None) -> Dict[str, Any]:
    """Return {nature, route, plugin_entry, source, needs_ai_parse}.

    `nature` — when the caller already KNOWS the nature (a benchmark label, a
    user who said "debug this"), pass it and the routing is deterministic.

    Otherwise the structural signal decides and `needs_ai_parse` is set so the
    caller runs the real AI first-layer parse to confirm:
      * existing RTL context  ⇒ a transform on existing RTL;
      * no context            ⇒ a spec asking for new RTL ⇒ Phase 1.
    Prose hints refine WHICH transform, but never promote a context-bearing
    task to spec_generation — that is the mistake that pushes a debug task
    through Phase 1.
    """
    if nature and nature in NATURE_ENTRY:
        t = NATURE_ENTRY[nature]
        return {"nature": nature, "route": t["route"],
                "plugin_entry": t["plugin_entry"],
                "source": "declared", "needs_ai_parse": False}

    text = prompt or ""
    hinted = next((n for n, rx in _PROSE_HINTS if rx.search(text)), None)

    if has_context:
        n = hinted or _UNPINNED_TRANSFORM_NATURE
        t = NATURE_ENTRY[hinted or _UNPINNED_TRANSFORM_ENTRY]
        return {"nature": n, "route": t["route"],
                "plugin_entry": t["plugin_entry"],
                "source": "context_prose_hint" if hinted else "context_heuristic",
                "needs_ai_parse": True}

    # No context. Only a hint that INHERENTLY needs existing RTL would be wrong
    # here, so a hint of debug/optimization/completion without context means the
    # caller has not supplied the RTL yet — say so rather than guessing.
    if hinted in ("debug", "optimization", "completion"):
        t = NATURE_ENTRY[hinted]
        return {"nature": hinted, "route": t["route"],
                "plugin_entry": t["plugin_entry"],
                "source": "prose_hint_without_context",
                "needs_ai_parse": True,
                "warning": f"prose reads as {hinted!r} but no existing RTL was "
                           f"supplied — that entry needs the RTL to transform"}

    t = NATURE_ENTRY["spec_generation"]
    return {"nature": "spec_generation", "route": "phase1_entry",
            "plugin_entry": t["plugin_entry"],
            "source": "no_context_heuristic", "needs_ai_parse": True}


def route_task(prompt: str = "",
               rtl_paths: Optional[List[str]] = None,
               nature: Optional[str] = None) -> Dict[str, Any]:
    """Route ONE general IC-design task (not a benchmark record)."""
    return classify_task_nature(prompt, bool(rtl_paths), nature)


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Which normal plugin entry does this IC task come in at?")
    ap.add_argument("--prompt", default=None, help="the task prompt text")
    ap.add_argument("--prompt-file", default=None, help="file holding it")
    ap.add_argument("--rtl", action="append", default=[],
                    help="existing RTL the task operates on (repeatable)")
    ap.add_argument("--nature", default=None, choices=sorted(NATURE_ENTRY),
                    help="declare the nature when you already know it")
    ap.add_argument("--list-entries", action="store_true",
                    help="print the nature→entry table and exit")
    ap.add_argument("--json", default=None, help="write the verdict here")
    a = ap.parse_args(argv)

    if a.list_entries:
        print(json.dumps(NATURE_ENTRY, indent=2))
        return 0

    text = a.prompt or ""
    if a.prompt_file:
        text = Path(a.prompt_file).read_text(errors="replace")
    if not text and not a.rtl and not a.nature:
        print("ERROR: give --prompt/--prompt-file, --rtl, or --nature",
              file=sys.stderr)
        return 2

    v = route_task(text, a.rtl, a.nature)
    out = json.dumps(v, indent=2, ensure_ascii=False)
    print(out)
    if a.json:
        Path(a.json).write_text(out + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
