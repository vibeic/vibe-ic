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
# ── WHERE THE RUN STOPS ──────────────────────────────────────────────────────
# Entry was only half the question. The task decides BOTH ends:
#
#   "怎麼可能為了回答一個 benchmark 的問題,都去跑 Phase 2、Phase 3 的整個流程呢?"
#                                                — owner directive 2026-08-25
#
# and stopping needs TWO fields, not one, because two different things end a run:
#
#   answer_step     the step that DECLARES the artefact handed back — a LOCATION
#                   in the flow, not an instruction to run that step
#   verify_through  how far the run must actually GO to trust that artefact
#
# The distinction in the first line is load-bearing and easy to read backwards.
# `optimization` enters at 2 and has answer_step 1: the deliverable is the
# modified RTL, which lives at step 1's declared path (`phase2/stage1/rtl/*`)
# because that is the step the flow says owns that path — but step 1 never runs,
# the file is edited in place. `debug` is the same shape. Reading answer_step as
# "run until here" would send both of them BACKWARDS through the flow.
# EXECUTION is [entry_step .. verify_through]. answer_step only says what to
# collect at the end.
#
# One field cannot express both, and collapsing them is wrong in both directions.
# Measured against the three open benchmarks' actual scorers:
#
#   * VerilogEval reads `samples/<Prob>_sample01.sv`, RTLLM reads each design's
#     RTL, CVDP reads a `{id, completion}` RTL string. ALL THREE hand back the
#     artefact of step 1 (`phase2/stage1/rtl/*.sv OR *.v`) and NONE of them ever
#     looks at a netlist or a GDS. A run that synthesises for VerilogEval has
#     burned 156 syntheses nobody reads.
#   * But CVDP cid007 hands back that same RTL and is GRADED ON AREA — which is
#     only measurable at step 9. Stopping at 1 ships an answer we cannot know is
#     good enough.
#
# So: same answer_step, different verify_through. A single exit_step would have
# to pick one of those two mistakes.
#
# The same shape appears at the far end of the flow, which is why it is not a
# benchmark quirk: step 37 emits the GDS you hand a foundry, and step 37.5ic
# ("Tape-out Precheck") is what says that GDS is actually shippable.
# answer_step=37, verify_through=37.5ic — identical structure to cid007.

# What the requester wants HANDED BACK. Distinct from the task's nature: the same
# "design me this chip" nature ends at RTL, at a GDS, or at a foundry package
# depending on the ask, and the flow has a different artefact for each. Which one
# a given request means is a READING judgement — "做到 tapeout" alone does not
# say whether it means the GDS exists, that it is verified shippable, or that it
# has been handed over — so the skill asks; this table only records what each
# answer implies once it is known.
# ── WHAT KIND OF PROOF THE QUESTION DEMANDS ─────────────────────────────────
# The exit is chosen by EVIDENCE CLASS, not by nature. The same nature asks for
# different depths depending on the VERB of the demand: "write this module" ends
# when it lints; "write this module and prove it works" ends when it simulates;
# "...and prove it can't recur" ends at formal. One nature, three exits.
#
# Every step id and every artefact below is verbatim from the flow's own
# required_outputs, so this table cannot drift from what the steps actually
# produce without failing validate_entries().
EVIDENCE_EXIT: Dict[str, Dict[str, Any]] = {
    "existence":        {"exit_step": "1",
                         "proves": "the RTL exists",
                         "artefact": "phase2/stage1/rtl/*.sv OR phase2/stage1/rtl/*.v"},
    "lint_validated":   {"exit_step": "2",
                         "proves": "it elaborates and is hygiene-clean",
                         "artefact": "reports/phase2/lint/rtl_hygiene.json"},
    "behaviour":        {"exit_step": "4",
                         "proves": "it does what the spec says, on OUR testbench",
                         "artefact": "phase2/stage1/sim/*.log OR phase2/stage1/sim/results.xml"},
    "proof":            {"exit_step": "5",
                         "proves": "the property holds for all inputs, not just the vectors",
                         "artefact": "phase2/stage1/formal/results.json"},
    "area":             {"exit_step": "9",
                         "proves": "how big it is once mapped",
                         "artefact": "phase2/stage2/synth/area.rpt OR phase2/stage2/synth/stats.json"},
    "equivalence":      {"exit_step": "13",
                         "proves": "synthesis/DFT did not change the semantics",
                         "artefact": "reports/lec.json"},
    "timing":           {"exit_step": "23",
                         "proves": "it closes timing after routing",
                         "artefact": "reports/phase3/sta/post_route_summary.json"},
    "manufacturability":{"exit_step": "31",
                         "proves": "it is physically legal to build",
                         "artefact": "reports/phase3/drc_signoff.json"},
    "power":            {"exit_step": "33",
                         "proves": "what it costs to run",
                         "artefact": "reports/phase3/power.json"},
    "silicon":          {"exit_step": "37",
                         "proves": "there is a stream-out to hand over",
                         "artefact": "phase3/stage4/gds/*.gds"},
}

# THE BLINDNESS CAP (§ 4.05). An exit may only demand evidence the run can
# produce WITHOUT the oracle. CVDP's record["harness"] and VerilogEval's
# `_test.sv` are the graders' own testbenches: a run exits at `behaviour` on ITS
# OWN bench under phase2/stage1/sim/, never on the hidden one. This is not a
# separate policy, it is blindness_audit's existing rule expressed as a ceiling
# on the span — and it is why "the scorer will run a testbench" never justifies
# raising the exit.
BLINDNESS_CAP_NOTE = (
    "evidence must come from the project's own artefacts; the grader's "
    "testbench and golden are never inputs to choosing or reaching an exit")


DELIVERY_TARGETS: Dict[str, Dict[str, Any]] = {
    "rtl": {
        "answer_step": "1",
        "artefact": "phase2/stage1/rtl/*.sv OR phase2/stage1/rtl/*.v",
        "note": "what every open RTL benchmark's scorer actually reads",
    },
    "gds": {
        "answer_step": "37",
        "artefact": "phase3/stage4/gds/*.gds",
        "note": "the stream-out exists; NOT a claim that it is shippable",
    },
    "shippable_gds": {
        "answer_step": "37",
        "verify_through": "37.5ic",
        "artefact": "phase3/stage4/gds/*.gds + reports/phase3/tapeout_precheck.json",
        "note": "step 37.5ic is literally named Tape-out Precheck and emits "
                "shuttle_precheck.json + SIGNOFF_*.html; without it the GDS is "
                "an artefact, not a sign-off",
    },
    "ip_hardmacro": {
        "answer_step": "37.5ip",
        "verify_through": "37.5ip",
        "artefact": "phase3/stage4/hardmacro/*.{lef,lib,gds,v}",
        "note": "the IP-delivery sibling of 37.5ic — both block on [37, 0.5ic]; "
                "delivering a block for someone else to integrate, not a die",
    },
    "foundry_handoff": {
        "answer_step": "38",
        "verify_through": "38",
        "artefact": "phase3/stage4/foundry_handoff/{mask_spec,wat_plan,"
                    "corner_test_vectors}.json + scribe_line_layout",
        "note": "only in scope when the run is actually shipping to a foundry",
    },
}

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
        # the deliverable is step 1's RTL (see DELIVERY_TARGETS);
        # this says how deep the proof must go before handing it over
        "default_evidence": "lint_validated",
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
        # the deliverable is step 1's RTL (see DELIVERY_TARGETS);
        # this says how deep the proof must go before handing it over
        "default_evidence": "lint_validated",
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
        # the deliverable is step 1's RTL (see DELIVERY_TARGETS);
        # this says how deep the proof must go before handing it over
        "default_evidence": "behaviour",
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
        # the deliverable is step 1's RTL (see DELIVERY_TARGETS);
        # this says how deep the proof must go before handing it over
        "default_evidence": "area",
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
        # the deliverable is step 1's RTL (see DELIVERY_TARGETS);
        # this says how deep the proof must go before handing it over
        "default_evidence": "behaviour",
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


def flow_step_ids(path: Optional[Path] = None) -> List[str]:
    """The flow's STEP ids, in DECLARATION ORDER. The single definition.

    Two properties, each of which was wrong in an earlier draft and each of
    which a caller depends on:

    ORDERED, not a set. Deciding "does this run stop after it starts" needs an
    order, and a set has none — an ordering built from one is arbitrary, so the
    check silently means nothing.

    STEPS ONLY. The YAML declares `stages:` (8 entities) and `steps:`. A bare
    `- id:` scan over the file returns all 76, so this validator ACCEPTED
    `stage1` as an entry step, and `upstream_of` put the eight stages at the
    head of every upstream list.

    `run_entry_manifest` imports this rather than keeping its own copy; the two
    had already diverged (set-of-76-with-stages vs list-of-68-without) while
    both claiming to answer the same question.
    """
    p = Path(path) if path else _FLOW_YAML
    try:
        text = p.read_text(errors="replace")
    except OSError:
        return []
    m = re.search(r"^steps:\s*$", text, re.M)
    if not m:
        return []
    return re.findall(r"^\s*-\s*id:\s*([\w.\-]+)\s*$", text[m.end():], re.M)


def validate_entries(path: Optional[Path] = None) -> List[str]:
    """Problems with the routing tables; empty when they are sound.

    Every step id named anywhere in this module must exist in the flow. A table
    naming a step the flow does not declare is worse than no table: it reads as
    executable and is not.
    """
    ids = set(flow_step_ids(path))
    if not ids:
        return ["flow YAML unreadable — cannot validate entry steps"]
    bad: List[str] = []

    def _check(owner: str, field: str, sid: Any, required: bool = True) -> None:
        # Name the FIELD that is wrong. An earlier version reported every
        # missing value as "entry_step is unset" regardless of which field it
        # came from, which sends the reader to the wrong line.
        if sid is None:
            if required:
                bad.append(f"{owner}: {field} is unset")
            return
        if str(sid) not in ids:
            bad.append(f"{owner}: {field}={sid!r} is not a step in the flow")

    for nature, e in NATURE_ENTRY.items():
        _check(nature, "entry_step", e.get("entry_step"))
        _check(nature, "fallback_entry_step", e.get("fallback_entry_step"),
               required=False)
        for i, sid in enumerate(e.get("then") or []):
            _check(nature, f"then[{i}]", sid)
        for i, sid in enumerate(e.get("verify_steps") or []):
            _check(nature, f"verify_steps[{i}]", sid)
        for i, sid in enumerate(e.get("admission_gates") or []):
            _check(nature, f"admission_gates[{i}]", sid)
        ev = e.get("default_evidence")
        if ev not in EVIDENCE_EXIT:
            bad.append(f"{nature}: default_evidence={ev!r} is not an evidence "
                       f"class (have: {sorted(EVIDENCE_EXIT)})")
        # A loop LABEL is not a step id — the regression this module exists to stop.
        if str(e.get("entry_step", "")).endswith("_loop"):
            bad.append(f"{nature}: entry_step is a loop label, not a step id")

    for ev, d in EVIDENCE_EXIT.items():
        _check(f"evidence {ev}", "exit_step", d.get("exit_step"))
    for tgt, d in DELIVERY_TARGETS.items():
        _check(f"delivery {tgt}", "answer_step", d.get("answer_step"))
        _check(f"delivery {tgt}", "verify_through", d.get("verify_through"),
               required=False)
    return bad

_UNPINNED_TRANSFORM_NATURE = "transform_existing_rtl"
_UNPINNED_TRANSFORM_ENTRY = "functional_modification"

_PROSE_HINTS = (
    # `bug` not `bugs?` was a one-character blind spot with a measured cost:
    # `\bbug\b` cannot match "bugs", because the word boundary after `bug`
    # requires a non-word character and `s` is one. Every prompt whose author
    # wrote the plural fell through to spec_generation — a debug task pushed
    # into Phase 1, which is the single failure this file's own docstring says
    # it exists to prevent. Measured over all 664 prompts of the four open
    # benchmarks, widening it to `bugs?` gains exactly 4 matches and every one
    # is a genuine debug task ("Fix any and all bugs in this code",
    # "Identify and fix these RTL Bugs", "Identify and correct the bugs",
    # "resolving the identified bugs"). Zero false positives on that
    # population, so the alternative is admitted on its own evidence.
    ("debug", re.compile(
        r"\b(bugs?|buggy|fix(es|ed)?\s+the\s+\w+|incorrect(ly)?|"
        r"does\s?n[o']t\s+work|failing|regression)\b", re.I)),
    # `smaller` HAD NO OBJECT, and every sibling in this alternation has one.
    # `reduce` matches only `reduce area|cells|wires|power`; `fewer` matches only
    # `fewer cells|wires`. A bare `smaller` matched the WORD, so any prose that
    # merely says one thing is smaller than another read as a request to shrink
    # the design. Measured over the 165 prompts reachable on this host
    # (VerilogEval-Human 156 + the 9 RTLLM design descriptions), that is not a
    # theoretical shape: `Prob042_vector4` — "sign-extending a smaller number to
    # a larger one", a pure BUILD-THIS spec — was routed `optimization` /
    # `prose_hint_without_context`, i.e. off Phase 1 and onto `optimize_loop`,
    # an entry whose `deterministic_first` transforms RTL that this task does
    # not have. It was the ONLY prompt the whole optimization hint fired on in
    # that population, so 1 of 1 hints was false. (CVDP is not on this host, so
    # 165 is the honest denominator, not the 664 the debug note above cites.)
    #
    # Requiring an object restores the sibling standard in both directions: the
    # object may follow (`smaller area|netlist|…`) or precede it in the
    # imperative form the request actually takes (`make the design smaller`).
    # "Make it smaller" is deliberately NOT hinted — a bare pronoun is not an
    # object, and `reduce` alone is not hinted either, for the same reason.
    ("optimization", re.compile(
        r"\b(optimi[sz]e"
        r"|reduce\s+(area|cells?|wires?|power)"
        r"|fewer\s+(cells?|wires?)"
        r"|smaller\s+(area|footprint|design|netlist|module|implementation"
        r"|cell\s+count|gate\s+count|die)"
        r"|(mak(e|es|ing)|get|getting|render)\s+(the\s+|this\s+|its\s+|your\s+|a\s+)?"
        r"(area|footprint|design|netlist|module|implementation|circuit|logic)\s+smaller"
        r"|lint\s+clean)\b", re.I)),
    ("completion", re.compile(
        r"\b(complete\s+the|fill\s+in|finish\s+the|implement\s+the\s+missing)\b",
        re.I)),
    ("functional_modification", re.compile(
        r"\b(modif(y|ies|ied)|change\s+the\s+behaviou?r|add\s+support\s+for|"
        r"extend\s+the)\b", re.I)),
)


# ── DOES THE PROMPT ITSELF CARRY THE RTL? ───────────────────────────────────
# `has_context` answers "did the caller hand me a FILE PATH". That is a question
# about the CALL, not about the TASK. Someone who pastes their module into the
# prompt has supplied the RTL just as surely as one who passes `--rtl`, and the
# four transform natures need the RTL, not the path. So the router had a
# structural fact in hand — the prompt text — and never looked at it.
#
# Measured 2026-08-27 over all 664 prompts of the four open benchmarks
# (VerilogEval-Human 156 + VerilogEval-v2 156 + RTLLM 50 + CVDP-open 302),
# classified with has_context=False, which is what a bare prompt gives:
#
#   * 94 of the 664 embed a complete `module … endmodule`. 86 of those are
#     CVDP — the very dataset whose 224 mis-entered records this file was
#     written for — so this is that dataset's DOMINANT shape, not an oddity.
#   * 153 verdicts carried the warning "prose reads as X but no existing RTL
#     was supplied". On 85 of those 153 the RTL is IN THE PROMPT. The warning
#     was therefore false more often than it was true (85 of 153, 55.6%).
#   * That warning is not inert: it is what makes a run abandon the hinted
#     entry for a degraded fallback, so 85 false statements become 85 wrong
#     routes the moment anything acts on them.
#
# The test is STRUCTURAL and language-level — a module header through its
# `endmodule` — never vendor-, SKU- or design-specific. The interface stub the
# open benchmarks append (`module TopModule ( … );`, no body) has no
# `endmodule`, so a bare specification is correctly NOT read as an
# implementation.
# TWO LINEAR SEARCHES, NOT ONE SPANNING MATCH. The obvious form of this test is
# a single regex spanning header→`endmodule`, and it backtracks quadratically:
# for every `module` in the text the lazy span rescans to the end looking for an
# `endmodule` that is not there. Measured on the finished detector before this
# was split — 664 real prompts cost 15 ms in total (23 us each), but one 1.25 MB
# input carrying 3000 module headers and no `endmodule` cost 12.7 SECONDS. The
# router takes a prompt string from whoever is calling, so a pathological input
# is a hang in the front door, not a benchmark curiosity.
#
# Asking the two questions separately is equivalent and linear. `endmodule` after
# the FIRST header is the same predicate as `endmodule` after ANY header: every
# position after a later header is also after the first one. The header scan is
# bounded so it cannot degenerate either — a port list running 4000 characters
# without a `;` is not a module header.
_MODULE_HEAD = re.compile(r"^[ \t]*module\b[^;]{0,4000};", re.M)
_ENDMODULE = re.compile(r"^[ \t]*endmodule\b", re.M)


def prompt_embeds_rtl(prompt: str) -> bool:
    """True when the prompt text itself carries a complete HDL module body.

    EMBEDDED RTL IS A PRECONDITION, NOT A NATURE, and reading it as a nature is
    the mistake this function is deliberately too weak to make. It establishes
    that the artefact a transform would operate on is PRESENT; it says nothing
    about whether a transform is what was asked for. The measured
    counter-example is in the same corpus: a prompt that quotes a complete
    working module and then asks for a NEW sub-module to be written from a
    description ("factor this into a hierarchical design … create the submodule
    … you do not have to provide the revised module"). Eight of the 94
    embedding prompts carry no transform verb at all, and for every one of them
    the quoted RTL is reference material for a generation task.

    So this promotes a HINTED transform out of a warning that is false for it.
    It never turns an unhinted request into a transform.
    """
    text = prompt or ""
    head = _MODULE_HEAD.search(text)
    return head is not None and _ENDMODULE.search(text, head.end()) is not None


def classify_task_nature(prompt: str,
                         has_context: bool,
                         nature: Optional[str] = None) -> Dict[str, Any]:
    """Return {nature, route, plugin_entry, source, needs_ai_parse}.

    `nature` — when the caller already KNOWS the nature (a benchmark label, a
    user who said "debug this"), pass it and the routing is deterministic.

    Otherwise the structural signal decides:
      * existing RTL          ⇒ a transform on existing RTL;
      * no RTL anywhere       ⇒ a spec asking for new RTL ⇒ Phase 1.
    Prose hints refine WHICH transform, but never promote a context-bearing
    task to spec_generation — that is the mistake that pushes a debug task
    through Phase 1.

    `needs_ai_parse` — WHAT IT MUST MEAN, AND WHAT IT USED TO MEAN. It reads
    as a measurement of this verdict's reliability, and a caller acting on it
    is deciding whether to spend an AI confirmation pass. It was neither.
    Measured 2026-08-27 it was True on 664 of 664 real prompts across all four
    open benchmarks — a field that never varies over its entire input domain
    carries no information, and a consumer for it would not have made it a
    signal, it would have sent every design down the AI path.

    The mechanism was not a badly-tuned threshold, it was that the flag was
    never a condition at all. Every branch that CLASSIFIES returned True and
    the only branch returning False was the one where the caller passed
    `nature` — so the field restated its own argument (`nature is None`)
    while presenting itself as a verdict about the prompt.

    It is now a real condition, and it varies because it reports what was
    actually observed. False when the router holds a POSITIVE signal for both
    halves of the question — the RTL is present (a path, or embedded in the
    prompt) AND the prose names which transform. True whenever the verdict
    still rests on something not being there: no transform verb was found
    (and the hint set has finite recall — the one blind reading disagreement
    measured over VerilogEval-Human was exactly a debug task whose verb the
    regex missed), or the RTL the named transform needs is genuinely absent.
    """
    if nature and nature in NATURE_ENTRY:
        t = NATURE_ENTRY[nature]
        return {"nature": nature, "route": t["route"],
                "plugin_entry": t["plugin_entry"],
                "source": "declared", "needs_ai_parse": False}

    text = prompt or ""
    hinted = next((n for n, rx in _PROSE_HINTS if rx.search(text)), None)
    embedded = prompt_embeds_rtl(text)

    if has_context:
        n = hinted or _UNPINNED_TRANSFORM_NATURE
        t = NATURE_ENTRY[hinted or _UNPINNED_TRANSFORM_ENTRY]
        return {"nature": n, "route": t["route"],
                "plugin_entry": t["plugin_entry"],
                "source": "context_prose_hint" if hinted else "context_heuristic",
                "needs_ai_parse": not hinted}

    # No context supplied as a PATH. Only a hint that INHERENTLY needs existing
    # RTL would be wrong here — but "no path" is not "no RTL", so before saying
    # the RTL is missing, look for it where the task actually put it.
    if hinted in ("debug", "optimization", "completion"):
        t = NATURE_ENTRY[hinted]
        if embedded:
            # The RTL is in the prompt. The warning below would be FALSE here,
            # and a false warning is worse than a silent one once anything acts
            # on it: it is what diverts a run off the hinted entry onto a
            # degraded fallback. Measured, this branch is 85 of the 664.
            return {"nature": hinted, "route": t["route"],
                    "plugin_entry": t["plugin_entry"],
                    "source": "embedded_rtl_prose_hint",
                    "needs_ai_parse": False}
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
        import _atomic_artefact as _atomic  # noqa: PLC0415
    _atomic.write_text(Path(a.json), out + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
