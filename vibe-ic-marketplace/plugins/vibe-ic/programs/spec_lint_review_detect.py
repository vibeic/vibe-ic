#!/usr/bin/env python3
r"""spec_lint_review_detect.py — PROGRAM-FIRST lint-review-task detector.

GENERAL CORE (benchmark-AGNOSTIC). A distinct class of spec asks NOT for new
behavior but for a **lint-clean** rewrite of an existing module: *"Perform a LINT
code review … addressing Unused parameter / Width mismatch / Latch inference /
Undriven signal / Combinational logic in sequential block / Uninitialized
register … Only provide the Lint-clean RTL code."* (the CVDP `IIR_filter`
coverage-gap: every FUNCTIONAL check passed, the ONLY failing gate was
`verilator --lint-only -Wall` returning `%Warning-UNUSEDSIGNAL` on an over-wide
intermediate reg whose upper bits were never read).

Our self-verification never exercised the lint slice, so a blind author had no
signal that lint — not function — was the graded axis. This detector fires
deterministically on that class so the flow routes it to the
`verilog_selfcheck_lint` self-gate (run `verilator --lint-only -Wall`, close to
zero) BEFORE emit. Reads ONLY the supplied prompt (§4.05).

Usage:
    from spec_lint_review_detect import detect_lint_review
    r = detect_lint_review(prompt)     # -> dict (see below)

    python3 spec_lint_review_detect.py --prompt @file.md    # CLI, JSON out
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List

# ── unambiguous lint-review markers (any one fires) ───────────────────────────
_MARKERS = [
    (re.compile(r"\blint\s+code\s+review\b", re.IGNORECASE), "lint-code-review"),
    (re.compile(r"\blint[-\s]?clean\b", re.IGNORECASE), "lint-clean"),
    (re.compile(r"\blint\s+(?:issues?|violations?|warnings?|errors?)\b",
                re.IGNORECASE), "lint-issues"),
    (re.compile(r"\blint\s+review\b", re.IGNORECASE), "lint-review"),
    (re.compile(r"--lint-only\b", re.IGNORECASE), "verilator-lint-only"),
    (re.compile(r"\bverilator\b", re.IGNORECASE), "verilator"),
    (re.compile(r"-Wall\b"), "wall-flag"),
]

# the concrete lint issues a prompt may enumerate — handed back as a checklist so
# the author knows exactly which classes verilator will flag.
_ISSUE_CATALOG = [
    (re.compile(r"\bunused\s+parameter\b", re.IGNORECASE), "unused-parameter"),
    (re.compile(r"\bwidth\s+mismatch\b", re.IGNORECASE), "width-mismatch"),
    (re.compile(r"\b(?:latch\s+infer\w*|infer\w*\s+(?:a\s+)?latch|inferred\s+latch)\b",
                re.IGNORECASE), "latch-inference"),
    (re.compile(r"\bundriven\s+signal\b", re.IGNORECASE), "undriven-signal"),
    (re.compile(r"\bunused\s+signal\b", re.IGNORECASE), "unused-signal"),
    (re.compile(r"\bcombinational\s+logic\s+in(?:\s+a)?\s+sequential\b",
                re.IGNORECASE), "comb-in-seq-block"),
    (re.compile(r"\buninitialized\s+register\b", re.IGNORECASE),
     "uninitialized-register"),
    (re.compile(r"\bimplicit\s+(?:net|wire)\b", re.IGNORECASE), "implicit-net"),
    (re.compile(r"\bblocking\b.{0,20}\bnon[-\s]?blocking\b", re.IGNORECASE),
     "blocking-nonblocking-mix"),
]

# guard: require a "lint" token to be a REQUESTED deliverable, not a passing
# mention like "this will not cause lint warnings". Fires only when the marker
# is an instruction (imperative/deliverable). Kept simple: any marker match plus
# either an imperative verb near it or an explicit "provide … lint-clean".
_DELIVERABLE_RE = re.compile(
    r"\b(perform|provide|fix|resolve|address|clean\s+up|remove|eliminate|"
    r"make|ensure)\b", re.IGNORECASE)


def detect_lint_review(prompt: str) -> Dict[str, Any]:
    """Return whether the task is a lint-review / lint-clean rewrite.

    Returns a dict::

        {
          "is_lint_review": bool,
          "evidence": [str, ...],           # markers that fired
          "issues_requested": [str, ...],   # named lint classes (checklist)
          "requirement": str|None,          # ready-to-inject author directive
        }
    """
    p = prompt or ""
    # collect EVERY marker occurrence with its position (finditer, not just first)
    hits: List[tuple] = []
    for rx, tag in _MARKERS:
        for m in rx.finditer(p):
            hits.append((tag, m.start()))
    evidence = sorted({t for t, _ in hits})

    issues = [tag for rx, tag in _ISSUE_CATALOG if rx.search(p)]

    # "lint code review" / "lint-clean" / "lint review" is ALWAYS the deliverable.
    strong = any(t in ("lint-code-review", "lint-clean", "lint-review")
                 for t, _ in hits)

    # a weaker marker ("lint issues", bare "verilator"/"-Wall") counts only when a
    # deliverable verb sits NEAR it — this keeps a passing "won't produce any lint
    # warnings" aside out (the verb-proximity is what separates task from mention).
    def _near(pos: int, window: int = 60) -> bool:
        return bool(_DELIVERABLE_RE.search(p[max(0, pos - window):pos + window]))

    deliverable_near = any(_near(pos) for _, pos in hits)
    is_lint = bool(hits) and (strong or len(issues) >= 2 or deliverable_near)

    requirement = None
    if is_lint:
        checklist = (" Named classes: " + ", ".join(issues) + "." if issues else "")
        requirement = (
            "This is a LINT-review task — the graded axis is lint-cleanliness, not "
            "just function. Run `verilator --lint-only -Wall` (via "
            "verilog_selfcheck_lint) on your RTL and drive EVERY warning to zero "
            "before emit (size intermediate regs to their used width to kill "
            "UNUSEDSIGNAL; no inferred latches; no unused params; fully drive every "
            "declared signal). The harness lint gate fails on ANY non-zero return "
            "(`verilator --lint-only -Wall -Wno-EOFNEWLINE`), so a SINGLE residual "
            "warning fails the task — do NOT leave a WIDTHTRUNC/WIDTHEXPAND or any "
            "warning as 'pre-existing' or 'out of scope'; every warning on the "
            "reviewed module must be resolved (width-cast the operand, don't just "
            "note it)." + checklist)

    return {
        "is_lint_review": is_lint,
        "evidence": evidence,
        "issues_requested": issues,
        "requirement": requirement,
    }


def main(argv: List[str] | None = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--prompt", required=True, help="prompt text or @file")
    a = ap.parse_args(argv)
    prompt = a.prompt
    if prompt.startswith("@"):
        prompt = Path(prompt[1:]).read_text()
    print(json.dumps(detect_lint_review(prompt), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
