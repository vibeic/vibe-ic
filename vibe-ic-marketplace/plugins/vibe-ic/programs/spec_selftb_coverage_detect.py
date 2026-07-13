#!/usr/bin/env python3
r"""spec_selftb_coverage_detect.py — PROGRAM-FIRST self-TB coverage advisory.

GENERAL CORE (benchmark-AGNOSTIC). A whole class of CVDP failures is NOT a wrong
interface or a dropped requirement — the interface is right and the requirement
IS in the chain, but the AUTHOR'S OWN self-verification testbench never exercised
the behavior slice the hidden TB checks, so a functionally-buggy design "passed"
self-check and shipped. The COVERAGE_GAP residuals:

  * signed_adder / vending_machine — a request/ready or handshake FSM whose
    self-TB drove one transaction and sampled the output on the WRONG phase
    (a terminal state that never re-arms only shows up under BACK-TO-BACK
    stimulus + external-checker sampling: drive, DEASSERT, check the pulse on the
    FOLLOWING clock).
  * axil_precision_counter — an AXI-Lite register peripheral whose self-TB poked
    a register but never ADVANCED SIM TIME, so a running counter/elapsed that is
    wrong-by-time read back "correct" at t=0.
  * interrupt_controller — an IRQ controller whose self-TB never exercised the
    ack→next-IRQ re-assert latency / deassert-during-ack / request-sync slices.
  * binary_search_tree_sorting — a "complete the partial FSM/algorithm" task
    whose self-TB used degenerate (empty/reset) stimulus and asserted only a
    done flag, never the real data result on a populated structure.

This detector reads the prompt (the design INPUT), classifies which of those
verification-relevant SHAPES the design has, and injects the matching self-TB
coverage slices as an ADVISORY requirement into the AI-backup hand-off — so the
author's close-loop self-check exercises the slice BEFORE emit. It is advisory
(never a gate/strip): stronger self-verification is always-safe guidance, so a
broad fire cannot mis-steer authoring. Reads ONLY the prompt (§4.05).

Usage:
    from spec_selftb_coverage_detect import detect_selftb_coverage
    r = detect_selftb_coverage(prompt)     # -> dict

    python3 spec_selftb_coverage_detect.py --prompt @file.md   # CLI, JSON out
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# ── shape markers (prompt prose / skeleton) ───────────────────────────────────
_TRIGGER_RE = re.compile(
    r"\b(i_)?start\b|\bvalid\b|\breq(?:uest)?\b|\bs_?axis_?tvalid\b|\bgo\b|\bkick\b",
    re.IGNORECASE)
_DONE_RE = re.compile(
    r"\b(o_)?ready\b|\b(o_)?done\b|\bbusy\b|\back(?:nowledge)?\b"
    r"|\bm_?axis_?tready\b|\bvalid_out\b|\bo_valid\b", re.IGNORECASE)
_AXI_LITE_RE = re.compile(
    r"AXI4?[-\s]?Lite|\bs_?axi\b|\baxil\b|awvalid|awready|araddr|arvalid|\bslv_reg",
    re.IGNORECASE)
_APB_RE = re.compile(r"\bAPB\b|\bpaddr\b|\bpsel|\bpenable|\bprdata|\bpwrite", re.IGNORECASE)
_DYN_STATE_RE = re.compile(
    r"\bcounter\b|countdown|\belapsed\b|\btimer\b|decrement|increment(?:s|ing)?"
    r"|\bcycles?\b.{0,20}\b(count|elapse)|running", re.IGNORECASE)
_INTERRUPT_RE = re.compile(
    r"interrupt\s+controller|\bIRQ\b|\binterrupt(?:s)?\b|cpu_interrupt|cpu_ack",
    re.IGNORECASE)
_INT_HANDSHAKE_RE = re.compile(
    r"\back(?:nowledge)?\b|cpu_ack|cpu_interrupt|\bpending\b|\bmask\b|\bvector\b",
    re.IGNORECASE)
_PULSE_RE = re.compile(
    r"\bpulse\b|assert\w*\s+(?:it\s+)?(?:high\s+)?for\s+(?:exactly\s+)?one"
    r"|one[-\s](?:clock\s+)?cycle|\bon\s+the\s+(?:next|following)\s+(?:clock|cycle|edge)",
    re.IGNORECASE)
# a "complete/finish/fill-in the (partial) …" instruction — the CVDP completion
# framing (broad; used by many non-FSM problems too, so it is gated below on
# FSM/algorithm CONTEXT before it earns the fsm_completion slice).
_COMPLETION_RE = re.compile(
    r"\bcomplet\w+\s+(?:the\s+)?(?:partial\s+)?(?:\w+\s+){0,3}?"
    r"(?:FSM|state\s+machine|algorithm|module|logic|design|implementation|code)"
    r"|\bpartial\b[^.\n]{0,30}"
    r"(?:FSM|state\s+machine|algorithm|implementation|design|code)"
    r"|\bfill\s+in\b|\bfinish\s+(?:the|implementing)\b", re.IGNORECASE)
# the design must actually BE an FSM / multi-state algorithm for the
# non-degenerate-stimulus slice to be relevant (excludes a plain "complete the
# code" combinational block).
_FSM_CONTEXT_RE = re.compile(
    r"\bFSM\b|\bstate\s+machine\b|\bstates?\b\s*(?:S_|:|are|include)|\bS_[A-Z]"
    r"|\bnext[-\s]?state\b|\btransition\b|\balgorithm\b|\btraverse\b|\bsorted\b"
    r"|\bsearch\b|\biterat", re.IGNORECASE)


def detect_selftb_coverage(prompt: str) -> Dict[str, Any]:
    """Classify the design's verification-relevant shapes and return the self-TB
    coverage advisory.

    Returns a dict::

        {
          "shapes": [str, ...],     # any of handshake_fsm / register_dynamic /
                                    #   interrupt_controller / fsm_completion
          "slices": [str, ...],     # the concrete self-TB slices to exercise
          "requirement": str|None,  # ready-to-inject author directive
        }
    """
    p = prompt or ""
    shapes: List[str] = []
    slices: List[str] = []

    has_trigger = bool(_TRIGGER_RE.search(p))
    has_done = bool(_DONE_RE.search(p))
    # 1) handshake / request-ready / start-done FSM
    if has_trigger and has_done:
        shapes.append("handshake_fsm")
        slices.append(
            "HANDSHAKE FSM: drive BACK-TO-BACK transactions (assert the next "
            "start/valid on the SAME cycle the previous one signals ready/done) — "
            "a terminal state that never re-arms only fails here; and sample pulse "
            "outputs as an EXTERNAL checker: drive stimulus, DEASSERT it, then "
            "check the output pulse on the FOLLOWING clock edge; hold data-valid "
            "outputs until consumed.")

    # 2) register peripheral (AXI-Lite / APB) with time-varying internal state
    if (_AXI_LITE_RE.search(p) or _APB_RE.search(p)) and _DYN_STATE_RE.search(p):
        shapes.append("register_dynamic")
        slices.append(
            "REGISTER PERIPHERAL with dynamic state: drive real HANDSHAKED "
            "read-after-write transactions (full valid/ready handshake, not a "
            "blind poke) AND ADVANCE SIMULATION TIME between write and read-back — "
            "a running counter/timer/elapsed must have CHANGED by read-back time; "
            "asserting at t=0 hides a wrong-by-time value.")

    # 3) interrupt controller
    if _INTERRUPT_RE.search(p) and _INT_HANDSHAKE_RE.search(p):
        shapes.append("interrupt_controller")
        slices.append(
            "INTERRUPT CONTROLLER: exercise the handshake-latency slices — after "
            "an ack clears one IRQ the interrupt line must RE-ASSERT for remaining "
            "pending IRQs within tolerance, DEASSERT exactly during ack, and the "
            "request synchronizer's latency must stay within bounds.")

    # 4) 'complete the partial FSM/algorithm' task — gated on FSM/algorithm
    # context so a plain "complete the code" combinational block does not earn
    # the non-degenerate-stimulus slice.
    if _COMPLETION_RE.search(p) and _FSM_CONTEXT_RE.search(p):
        shapes.append("fsm_completion")
        slices.append(
            "FSM/ALGORITHM COMPLETION: exercise the primary NON-DEGENERATE path "
            "with real structured stimulus (a populated data structure / non-reset "
            "state, not just empty/idle), and assert the actual DATA RESULT and the "
            "prose-stated latencies — never only a done/valid flag.")

    requirement = None
    if slices:
        requirement = (
            "SELF-TB COVERAGE — your close-loop self-verification (not just the "
            "RTL) is the graded axis here; a weak self-TB lets a real bug ship. "
            "Before emit, ensure your self-TB exercises: " + " ".join(slices))

    return {"shapes": shapes, "slices": slices, "requirement": requirement}


def main(argv: Optional[List[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--prompt", required=True, help="prompt text or @file")
    a = ap.parse_args(argv)
    prompt = a.prompt
    if prompt.startswith("@"):
        prompt = Path(prompt[1:]).read_text()
    print(json.dumps(detect_selftb_coverage(prompt), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
