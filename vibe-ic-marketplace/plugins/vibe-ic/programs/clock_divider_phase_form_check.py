#!/usr/bin/env python3
"""clock_divider_phase_form_check.py — deterministic emit gate for the odd /
double-edge clock-divider PHASE-FORM trap.

WHY (benchmark close-loop, freq_divbyodd pass@6 = 0/6 — PRIME DIRECTIVE capture):
A divide-by-odd-N (and half-integer) clock divider built as the canonical
TWO-intermediate-clock OR structure — `clk_div = clk_div1 | clk_div2`, one
intermediate registered on each clock edge — has an EXACT phase the hidden TB
checks from the first cycle. The golden realises each intermediate as a
LEVEL-DECODE of its counter, reset HIGH:

    clk_div1 <= 1'b1;                 // on reset
    else if (cnt1 < NUM_DIV/2) clk_div1 <= 1'b1; else clk_div1 <= 1'b0;

A blind author who instead writes the tempting SELF-TOGGLE form, reset 0:

    clk_div1 <= 1'b0;                 // on reset
    if (cnt1 == ... ) clk_div1 <= ~clk_div1;   // self-toggle

gets the right 50% duty / average period but a PHASE-INVERTED first cycle, which
the TB's `expected=1`-at-start check rejects. The ic-expert-agent digest already
carries this lesson in full — yet 6/6 fresh blind authors wrote the self-toggle
form and host-FAILed. A lesson the author ignores has NOT converged the case;
this promotes the discriminator to a DETERMINISTIC structural gate so the wrong
form cannot silently emit.

WHAT it detects (the specific, narrow anti-pattern — NOT every toggle divider):
a divided-CLOCK output (name carries a `clk`/`clock` root) that is the OR of >=2
intermediate clock registers, where >=2 of those OR-operand registers are each
driven by a SELF-TOGGLE (`X <= ~X` / `X <= !X`) and NONE of them is reset HIGH.
That is exactly the two-edge-OR phase-form trap (one self-toggle per clock edge,
reset LOW). The fix is the level-decode form (`Xk <= (cntk < N/2)`), reset HIGH.

§4.05 SAFETY — the load-bearing half is the NEGATIVE no-leak proof: the gate must
NEVER fire on a correct design. It SKIPs (rc 0) unless ALL structural conditions
hold, so (each bullet a Step-2.7 §4.05 reproduced false-fire now pinned SKIP):
  - the LEVEL-DECODE golden (no self-toggle operand) → SKIP/clean;
  - a plain even divider that toggles a SINGLE output (no OR of two intermediates)
    → SKIP (the legitimate even-divide idiom);
  - the DEGENERATE OR form of an even divider — `clk_div = clk_div1 | clk_div2`
    with only ONE self-toggle operand (the other constant) — is phase-CORRECT
    (proven waveform-identical to the golden) → SKIP (requires >=2 self-toggles);
  - a NON-clock signal merely named with a `div` substring (`bank_a_div`,
    `divmod_done`, `dividend`) → SKIP (the name lacks a `clk`/`clock` root);
  - a self-toggle OR-form whose intermediates are reset HIGH → SKIP (plausibly
    phase-correct; the gate errs to false-SKIP, the safe direction);
  - any module whose divided output is not an OR of >=2 registers → SKIP.
A BLOCK fires ONLY on a CLOCK-named OR-of->=2-intermediates with >=2 reset-LOW
self-toggle operands — the form the golden never uses and the lesson proves is
phase-wrong.

chip-AGNOSTIC, prompt-blind (reads only the authored RTL), deterministic.

CLI:
    clock_divider_phase_form_check.py <rtl.v> [--strict] [--json OUT]
    rc 0 = clean / not-applicable (SKIP);  rc 1 = phase-risky self-toggle OR-form.
    --strict only changes the exit message wording (emit-block vs advisory); the
    detection + rc are identical (deterministic).
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


def strip_comments(src: str) -> str:
    src = re.sub(r"/\*.*?\*/", " ", src, flags=re.S)
    src = re.sub(r"//[^\n]*", " ", src)
    return src


# a divided-CLOCK output name. MUST carry a clock root (`clk`/`clock`) AND a
# divide/output token (`div`/`out`) — so a NON-clock signal merely named with a
# bare `div` substring (dividend / division / divmod_done / bank_a_div) is NOT
# matched. The earlier loose `\w*div\w*` arm false-fired on such non-clock names
# (Step-2.7 §4.05 reproduced: a `bank_a_div | bank_b_en` status OR was blocked).
_DIVOUT_RE = re.compile(r"\b(?=\w*(?:clk|clock))\w*(?:div|out)\w*\b", re.I)
_SELFTOGGLE_RE = re.compile(r"\b(\w+)\s*<=\s*[~!]\s*\1\b")


def _resets_high(src: str, reg: str) -> bool:
    """True if `reg` is ever assigned a constant 1 (`<= 1'b1` / `1'd1` / `1`).

    The level-decode golden resets each intermediate HIGH; the phase-wrong trap
    resets LOW. A self-toggle operand that is reset HIGH is plausibly a
    phase-CORRECT form, so the gate must NOT block it (errs toward false-SKIP,
    the safe direction for an emit-block gate)."""
    return bool(re.search(
        rf"\b{re.escape(reg)}\s*<=\s*(?:1\s*'\s*[bdh]?\s*1|1)\s*;", src))


def _or_operands(rhs: str) -> list[str]:
    """Return the identifier OR-operands of an RHS like `a | b | c` (no other ops)."""
    rhs = rhs.strip().rstrip(";").strip()
    if "|" not in rhs:
        return []
    parts = [p.strip() for p in rhs.split("|")]
    ids = []
    for p in parts:
        m = re.fullmatch(r"\(?\s*([A-Za-z_]\w*)\s*\)?", p)
        if not m:
            return []  # a non-trivial operand → not the clean two-edge-OR idiom
        ids.append(m.group(1))
    return ids


def analyze(rtl: str) -> dict:
    src = strip_comments(rtl)
    self_toggled = set(_SELFTOGGLE_RE.findall(src))

    # find divided-clock outputs assigned as an OR of >=2 identifiers
    findings = []
    # continuous: assign <out> = a | b ...;
    for m in re.finditer(r"\bassign\s+(\w+)\s*=\s*([^;]+);", src):
        out, rhs = m.group(1), m.group(2)
        ops = _or_operands(rhs)
        if len(ops) >= 2 and (_DIVOUT_RE.search(out) or any(_DIVOUT_RE.search(o) for o in ops)):
            risky = sorted(set(ops) & self_toggled)
            # The genuine two-edge-OR trap has >=2 self-toggling intermediates
            # (one per clock edge), each reset LOW. Require BOTH:
            #  - len(risky) >= 2 : excludes a plain even divider written in the
            #    degenerate OR form (one self-toggle + one constant operand),
            #    which is phase-CORRECT (Step-2.7 §4.05 reproduced it firing);
            #  - no risky reg reset HIGH : a reset-HIGH self-toggle is plausibly
            #    phase-correct, so don't block it (errs to safe false-SKIP).
            if len(risky) >= 2 and not any(_resets_high(src, r) for r in risky):
                findings.append({"output": out, "or_operands": ops, "self_toggled": risky})
    # procedural: <out> <= a | b ...;  (registered OR of two intermediates)
    for m in re.finditer(r"\b(\w+)\s*<=\s*([^;]+);", src):
        out, rhs = m.group(1), m.group(2)
        ops = _or_operands(rhs)
        if len(ops) >= 2 and (_DIVOUT_RE.search(out) or any(_DIVOUT_RE.search(o) for o in ops)):
            risky = sorted(set(ops) & self_toggled)
            # The genuine two-edge-OR trap has >=2 self-toggling intermediates
            # (one per clock edge), each reset LOW. Require BOTH:
            #  - len(risky) >= 2 : excludes a plain even divider written in the
            #    degenerate OR form (one self-toggle + one constant operand),
            #    which is phase-CORRECT (Step-2.7 §4.05 reproduced it firing);
            #  - no risky reg reset HIGH : a reset-HIGH self-toggle is plausibly
            #    phase-correct, so don't block it (errs to safe false-SKIP).
            if len(risky) >= 2 and not any(_resets_high(src, r) for r in risky):
                findings.append({"output": out, "or_operands": ops, "self_toggled": risky})

    return {"self_toggled_regs": sorted(self_toggled), "findings": findings,
            "phase_risky": bool(findings)}


_FIX = ("use the LEVEL-DECODE form for each intermediate — `clk_divK <= (cntK < N/2)` "
        "(reading the CURRENT counter), each reset HIGH (`1'b1`) so the first half-period "
        "is HIGH; a self-toggle `X <= ~X` reset-0 form gives the right duty but a "
        "phase-INVERTED first cycle the TB rejects.")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("rtl", type=Path)
    ap.add_argument("--strict", action="store_true")
    ap.add_argument("--json", type=Path)
    a = ap.parse_args(argv)
    if not a.rtl.is_file():
        print(f"ERROR: no such file {a.rtl}", file=sys.stderr)
        return 2
    res = analyze(a.rtl.read_text(errors="replace"))
    if a.json:
        a.json.write_text(json.dumps(res, indent=1))
    if not res["phase_risky"]:
        print("PASS: no two-edge-OR self-toggle clock-divider phase-form trap (SKIP if not a divider).")
        return 0
    f = res["findings"][0]
    head = "BLOCK" if a.strict else "WARN"
    print(f"{head}: phase-risky clock-divider form — output `{f['output']}` ORs intermediates "
          f"{f['or_operands']} but {f['self_toggled']} is a SELF-TOGGLE (`X <= ~X`). {_FIX}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
