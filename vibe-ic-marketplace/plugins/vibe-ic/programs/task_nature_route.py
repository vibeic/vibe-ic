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
# ── The five natures → the STEP each enters the canonical flow at ────────────
# `entry_step` names a REAL id in flow/phase1_phase2_phase3.yaml. Not a label:
# a label cannot be executed, and cannot be checked against the flow.
#
# THIS TABLE WAS WRONG IN ITS FIRST DRAFT AND THE FLOW SAID SO. The draft read
# "completion/modify/optimize/debug all enter at P0 first, then their own step".
# Checked against the YAML, four of five rows were wrong:
#
#  * P0 declares `blocks_on: [1]` and reads `from: 1`. It comes AFTER step 1,
#    not before, and its verdict is emitted at AUDIT time by
#    flow_compliance_check._run_structural_rtl_gates. P0 is an ADMISSION GATE,
#    never an entry — "P0 then 1" inverts both the declared edge and the real
#    execution order. It is recorded as `admission_gates` instead.
#  * Step 1 declares `from: D1, outputs: all`, which fans out to all 19 of D1's
#    required_outputs. Entering at 1 without D1 is REFUSED on 19 absent files.
#    Worse, step 1's required_output IS the RTL glob the user supplied, so
#    entering there targets the very file being completed — the runner WAIVEs.
#  * Step 13 is "Equivalence check (RTL ≡ post-DFT netlist)", blocks_on [12].
#    It proves synthesis and DFT did NOT change the semantics of one design. A
#    functional modification deliberately DOES change semantics, so 13 cannot
#    verify it — a category error, not merely an unsatisfiable input. The
#    flow's artefact for "old RTL ≡ new RTL" is step 2's
#    reports/crosslayer/rewrite_equivalence_check.json.
#  * Step 4 reads `from: 1` (the RTL) AND two D1 artefacts —
#    L10_TEST_CASES.json and L12_BEHAVIORAL_SEQUENCES.json. A user-supplied
#    failing testbench has no declared input slot in step 4 at all.
#
# The owner's directive — "if I am debugging, I do not enter at Phase 1" — is
# right about debug and optimization, and the flow's own declarations say the
# other three need D1's output before their step can read anything. Where those
# disagree, the YAML wins and the disagreement is recorded, not smoothed over.
# `route` and `entry_step` answer DIFFERENT questions, and conflating them is how
# the first draft lost information: `route` says which loop OWNS the transform,
# `entry_step` says where in the flow the work STARTS. Completion and
# functional-modification are owned by their own loops — the work is a transform,
# not a spec-to-RTL pass — yet they must START at D1, because step 1 declares it
# reads ALL of D1's outputs. Owned-by and starts-at are simply not the same axis.
NATURE_ENTRY: Dict[str, Dict[str, Any]] = {
    # Pure text spec → brand-new RTL. D1 reads `from: external` (a staged
    # prompt / input doc), so it is satisfiable from the prompt alone.
    "spec_generation": {
        "route": "phase1_entry",
        "entry_step": "D1",
        "then": ["1"],
        "verify_steps": ["2", "4"],
        "admission_gates": [],
        "plugin_entry": {
            "name": "phase1_spec_to_rtl",
            "deterministic_first": ["phase1_one_shot_runner.py",
                                    "deterministic_rtl_dispatcher.py"],
            "ai_backup": ["spec-to-rtl"],
            "verify": ["rtl_hygiene_lint.py", "spec_conformance_check.py",
                       "phase2-rtl-verify"],
        }},
    # Given a partial interface/RTL → complete the design. Enters at D1 because
    # step 1 declares it reads ALL of D1's outputs; the supplied RTL is a SEED
    # for that pass, not a substitute for the spec of what to complete.
    "completion": {
        "route": "plugin_loop",
        "entry_step": "D1",
        "then": ["1"],
        "verify_steps": ["2", "4"],
        "admission_gates": ["P0"],
        "plugin_entry": {
            "name": "completion_loop",
            "deterministic_first": ["cvdp_context_interface_recover.py",
                                    "modify_complete_synth.py"],
            "ai_backup": ["spec-to-rtl"],
            "verify": ["rtl_hygiene_lint.py", "spec_conformance_check.py",
                       "phase2-rtl-verify"],
        }},
    # Given RTL → change its behaviour per a spec delta (functional ECO).
    # Verified by 2 (rewrite fidelity) / 4 (simulation) / 5 (formal), NOT by 13.
    "functional_modification": {
        "route": "plugin_loop",
        "entry_step": "D1",
        "then": ["1"],
        "verify_steps": ["2", "4", "5"],
        "admission_gates": ["P0"],
        "plugin_entry": {
            "name": "modify_loop",
            "deterministic_first": ["cvdp_context_interface_recover.py",
                                    "modify_complete_synth.py"],
            "ai_backup": ["rtl-repair", "eco-plan"],
            "verify": ["equivalence-check", "phase2-rtl-verify",
                       "rtl_hygiene_lint.py"],
        }},
    # Reduce area / pass lint thresholds. Step 2 declares exactly ONE input —
    # `from: 1`, the RTL glob — so it is the only stage-1 step fully satisfiable
    # from existing RTL alone, which is exactly what an optimization supplies.
    # Step 9 follows because area is only measurable after synthesis.
    "optimization": {
        "route": "plugin_loop",
        "entry_step": "2",
        "then": ["9"],
        "verify_steps": ["2", "4"],
        "admission_gates": ["P0"],
        "plugin_entry": {
            "name": "optimize_loop",
            "deterministic_first": ["rtl_hygiene_lint.py"],
            "ai_backup": ["rtl-review", "synth-doctor", "ppa-predict"],
            "verify": ["equivalence-check", "phase2-rtl-verify"],
        }},
    # Given buggy RTL → fix it. Entry IS step 4, per the owner's directive, but
    # step 4 reads two D1 artefacts for its stimulus. They are named here so the
    # requirement is visible before the run, not discovered as a refusal; when
    # they cannot be staged, `fallback_entry_step` says where to go and why.
    "debug": {
        "route": "plugin_loop",
        "entry_step": "4",
        "then": [],
        "verify_steps": ["4", "5"],
        "admission_gates": ["P0"],
        "entry_requires": [
            "phase2/stage1/rtl/*.sv OR phase2/stage1/rtl/*.v",
            "phase1/generated_docs/L10_TEST_CASES.json",
            "phase1/generated_docs/L12_BEHAVIORAL_SEQUENCES.json",
        ],
        "fallback_entry_step": "D1",
        "fallback_reason": ("step 4 reads L10_TEST_CASES.json and "
                            "L12_BEHAVIORAL_SEQUENCES.json, which only D1 "
                            "produces; without them staged there is no "
                            "declared stimulus source to simulate against"),
        "plugin_entry": {
            "name": "debug_loop",
            "deterministic_first": ["cvdp_context_interface_recover.py",
                                    "debug_first_pass.py"],
            "ai_backup": ["rtl-repair"],
            "verify": ["phase2-rtl-verify", "equivalence-check",
                       "formal-verify", "rtl_hygiene_lint.py"],
        }},
}

# Every id above must exist in the flow. A table naming a step the flow does
# not declare is worse than no table: it reads as executable and is not.
_FLOW_YAML = Path(__file__).resolve().parents[1] / "flow" / "phase1_phase2_phase3.yaml"


def flow_step_ids(path: Optional[Path] = None) -> set:
    """Every `- id:` declared in the canonical flow, as strings."""
    p = Path(path) if path else _FLOW_YAML
    try:
        text = p.read_text(errors="replace")
    except OSError:
        return set()
    return set(re.findall(r"^\s*-\s*id:\s*([\w.\-]+)\s*$", text, re.M))


def validate_entries(path: Optional[Path] = None) -> List[str]:
    """Return the problems with NATURE_ENTRY, empty when it is sound."""
    ids = flow_step_ids(path)
    if not ids:
        return ["flow YAML unreadable — cannot validate entry steps"]
    bad: List[str] = []
    for nature, e in NATURE_ENTRY.items():
        named = ([e.get("entry_step")] + list(e.get("then") or [])
                 + list(e.get("verify_steps") or [])
                 + list(e.get("admission_gates") or [])
                 + ([e["fallback_entry_step"]] if e.get("fallback_entry_step")
                    else []))
        for sid in named:
            if sid is None:
                bad.append(f"{nature}: entry_step is unset")
            elif str(sid) not in ids:
                bad.append(f"{nature}: {sid!r} is not a step in the flow")
        # The Change-4 regression guard: a loop LABEL is not a step id.
        if str(e.get("entry_step", "")).endswith("_loop"):
            bad.append(f"{nature}: entry_step is a loop label, not a step id")
    return bad


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
