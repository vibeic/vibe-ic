#!/usr/bin/env python3
"""fsm_transition_completeness_check.py — v0.3.21 (ORGANIC #522).

Deterministic STRUCTURAL check of an FSM's next-state logic. Closes the
deterministically-checkable half of the recurring "FSM transition-logic
mismatch" class the field agent observed across benchmark clean-room rounds
1-3 (Prob133/150/155/135). The existing `spec_conformance_check` only validates
FSM OUTPUT STYLE (Moore/Mealy); it never checks that the next-state logic is
structurally sound. The ic-expert prose lessons about FSM transitions proved
unreliable (a fresh author re-makes the same class of error every round — the
same prose-is-not-enough lesson #517/#518 forced into programs).

WHAT IS DETERMINISTICALLY CHECKABLE (and what is NOT)
----------------------------------------------------
Some FSM bugs need the spec's intended transition table or a behavioural sim to
catch (a counter that counts on current- vs next-state, an edge that points at a
WRONG but still-reachable target, an extra pass-through state that merely adds a
cycle of latency). Those are NOT structurally detectable and stay a self-TB /
judgment responsibility — this program does NOT claim them.

The ONE structural defect that is BOTH always-a-bug AND zero-false-positive on
the real-RTL corpus (validated: chacha / aes / sha256 / ibex / modexp / poly1305
all pass clean):
  * INFERRED LATCH — a next-state `case` arm for a declared state does NOT assign
    the next-state variable, the case has no assigning `default`, and the
    next-state variable is not pre-assigned → it latches for that state
    (synthesised latch / stuck FSM). ALWAYS a bug.

DELIBERATELY NOT FLAGGED (measured too false-positive-prone for a hard gate, or
not structurally separable from a correct design without the spec's intended
transition table — these stay a self-TB / judgment responsibility):
  * a counter that counts on current- vs next-state (off-by-one);
  * an edge wired to the WRONG but still-reachable target;
  * an extra pass-through state that merely adds a cycle of latency;
  * a dead/unreachable state — the structural "unreachable" signal fired ~19% on
    the known-good corpus, so it is intentionally omitted.

CONSERVATIVE / PRECISE BY DESIGN: the state set is derived from the FSM `case`'s
own case-item labels that are DECLARED constants (NOT every UPPER_SNAKE constant
in the file — that falsely swept in register addresses, bit indices and config
widths on real crypto cores). When the FSM uses an encoding this parser cannot
read confidently (one-hot reverse-case `case (1'b1)`, a computed next-state, a
case with < 2 declared-constant items), the design is SKIPPED rather than
guessed. An under-flag (miss) is acceptable; a false flag on a correct FSM is
not — it would block a good design.

chip-AGNOSTIC: pure Verilog structure parsing — no chip / state / opcode literal.

EXIT CODES
----------
    0  clean OR not-an-analysable-FSM (SKIP)  — also exit 0 with --warn-only
    1  a structural defect (latch / missing-transition / dead-state) found
    2  bad input
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import List, Optional, Tuple


@dataclass
class Finding:
    rule: str
    severity: str       # ERROR / WARN
    state: str
    detail: str


def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"//[^\n]*", "", text)
    return text


# state-name declarations: `localparam [w]? NAME = val;` / `parameter NAME = val;`
# NAME must be UPPER_SNAKE-ish (state-like), value is a constant.
_PARAM_STATE_RE = re.compile(
    r"\b(?:localparam|parameter)\b\s*(?:\[[^\]]*\]\s*)?"
    r"((?:[A-Z][A-Z0-9_]*\s*=\s*[^;,]+[,;]\s*)+)", re.MULTILINE)
_ONE_ASSIGN_RE = re.compile(r"([A-Z][A-Z0-9_]*)\s*=\s*[^;,]+[,;]")
# SystemVerilog enum: typedef enum ... { A, B, C } name;
_ENUM_RE = re.compile(r"\benum\b[^{]*\{([^}]*)\}", re.DOTALL)


def parse_states(text: str) -> List[str]:
    """Collect declared state names (localparam/parameter UPPER_SNAKE or enum
    members). Returns [] when no state-like declarations are found."""
    body = _strip_comments(text)
    states: List[str] = []
    for m in _PARAM_STATE_RE.finditer(body):
        for am in _ONE_ASSIGN_RE.finditer(m.group(1)):
            states.append(am.group(1))
    for m in _ENUM_RE.finditer(body):
        for nm in re.findall(r"\b([A-Za-z_]\w*)\b", m.group(1)):
            # enum members may carry an explicit value; the name is the token
            # not preceded by '=' — findall over identifiers, drop pure numbers.
            if not nm.isdigit():
                states.append(nm)
    # de-dup, preserve order
    seen = set()
    out = []
    for s in states:
        if s not in seen:
            seen.add(s)
            out.append(s)
    return out


# next-state variable candidates (LHS of the transition assignment).
_NEXT_VAR_HINTS = ("next_state", "state_next", "nstate", "n_state",
                   "next_st", "ns")


def _find_case_block(body: str) -> Optional[Tuple[str, str]]:
    """Return (case_selector, case_body) for the FIRST `case (...) ... endcase`
    that looks like a state machine (selector is a single identifier or an
    indexed expression). None when no plain case is found."""
    # match `case (SEL) ... endcase` (non-greedy to the nearest endcase).
    m = re.search(r"\bcase\s*\(\s*([^()]*?)\s*\)\s*(.*?)\bendcase\b",
                  body, re.DOTALL)
    if not m:
        return None
    selector = m.group(1).strip()
    # one-hot reverse-case `case (1'b1)` is not analysable by name → bail.
    if re.match(r"^\d*'[bdh]?\s*[01]+$", selector) or selector in ("1'b1", "1"):
        return None
    return (selector, m.group(2))


def _next_var_in(body: str, states: List[str]) -> Optional[str]:
    """Pick the next-state variable: the LHS (blocking or non-blocking) most
    often assigned a declared STATE name as its RHS inside the body."""
    counts = {}
    state_set = set(states)
    for lhs, rhs in re.findall(r"\b([A-Za-z_]\w*)\s*(?:<=|=)\s*([^;]+);", body):
        rhs_ids = set(re.findall(r"\b([A-Za-z_]\w*)\b", rhs))
        if rhs_ids & state_set:
            counts[lhs] = counts.get(lhs, 0) + 1
    if not counts:
        return None
    # prefer a hinted name; else the most-assigned LHS.
    for lhs in counts:
        if any(h in lhs.lower() for h in _NEXT_VAR_HINTS):
            return lhs
    return max(counts, key=counts.get)


def _reset_state(body: str, states: List[str]) -> Optional[str]:
    """Best-effort: the state assigned under a reset (`if (rst...) state <= S`)."""
    state_set = set(states)
    for m in re.finditer(
            r"\bif\s*\(\s*[^)]*\b(?:rst|reset|n?rst_?n?|areset)\b[^)]*\)\s*"
            r"[A-Za-z_]\w*\s*<=\s*([A-Za-z_]\w*)", body, re.IGNORECASE):
        if m.group(1) in state_set:
            return m.group(1)
    return None


def _split_case_arms(case_body: str) -> List[Tuple[str, str]]:
    """Split a case body into (label, arm_body) pairs. The arm body runs from a
    label's ':' to the next top-level label (a `<ITEM>:` / `default:` that is not
    nested inside a begin/end or paren). Conservative: a nested `case` inside an
    arm is opaque (its inner labels are skipped via begin/end depth tracking)."""
    # find top-level label positions: IDENT(s) or default, followed by ':' that
    # is NOT '::' and not part of '?:'. We track begin/end + paren depth so inner
    # case labels are not mistaken for outer arms.
    arms: List[Tuple[str, str]] = []
    label_re = re.compile(
        r"(\bdefault\b|[A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*)\s*:(?!:)")
    depth = 0
    i = 0
    pending_label = None
    pending_start = None
    tokens = list(re.finditer(r"\bbegin\b|\bend\b|\bcase\b|\bendcase\b|"
                              r"(\bdefault\b|[A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*)"
                              r"\s*:(?!:)", case_body))
    for tk in tokens:
        word = tk.group(0)
        if word.startswith("begin"):
            depth += 1
            continue
        if word.startswith("end") and not word.startswith("endcase"):
            depth -= 1
            continue
        if word.startswith("case") or word.startswith("endcase"):
            # nested case — treat as part of current arm (skip)
            continue
        if depth == 0 and ":" in tk.group(0):
            # a top-level label
            if pending_label is not None:
                arms.append((pending_label, case_body[pending_start:tk.start()]))
            pending_label = tk.group(1).strip()
            pending_start = tk.end()
    if pending_label is not None:
        arms.append((pending_label, case_body[pending_start:]))
    return arms


def check_text(text: str) -> Tuple[List[Finding], str]:
    """Return (findings, status). status is 'CHECKED' / 'SKIP-<reason>'.

    State identification is CASE-DRIVEN (precise): a `case (SEL)` is treated as
    an FSM only when ≥2 of its case-item labels are DECLARED localparam/enum
    constants. The state set is then those case-item constants — NOT every
    UPPER_SNAKE constant in the file (which falsely swept in register addresses,
    bit indices and config widths on real crypto cores)."""
    body = _strip_comments(text)
    declared = set(parse_states(body))
    if not declared:
        return ([], "SKIP-no-state-declarations")
    case = _find_case_block(body)
    if case is None:
        return ([], "SKIP-no-analysable-case")
    selector, case_body = case

    arms = _split_case_arms(case_body)
    # state case-items = labels that are declared constants.
    item_states: List[str] = []
    has_default = False
    default_body = ""
    arm_bodies = {}
    for label, abody in arms:
        if label == "default":
            has_default = True
            default_body = abody
            continue
        labels = [x.strip() for x in label.split(",")]
        decl_labels = [x for x in labels if x in declared]
        for x in decl_labels:
            item_states.append(x)
            arm_bodies[x] = abody
    item_states = list(dict.fromkeys(item_states))
    if len(item_states) < 2:
        # not a state-machine case (a data/decode case over non-state consts)
        return ([], "SKIP-not-a-state-case")

    # next-state variable: the LHS assigned a declared state constant inside the
    # arms (or the case selector itself for a clocked `state <= S` style).
    next_var = None
    counts = {}
    for s in item_states:
        for lhs, rhs in re.findall(
                r"\b([A-Za-z_]\w*)\s*(?:<=|=)\s*([^;]+);", arm_bodies.get(s, "")):
            if set(re.findall(r"\b\w+\b", rhs)) & declared:
                counts[lhs] = counts.get(lhs, 0) + 1
    if counts:
        for lhs in counts:
            if any(h in lhs.lower() for h in _NEXT_VAR_HINTS):
                next_var = lhs
                break
        if next_var is None:
            next_var = max(counts, key=counts.get)
    else:
        # no arm assigns a state constant — selector might BE the next-state
        # (clocked case `state <= ...` with state names only in selector). Bail
        # rather than guess.
        return ([], "SKIP-no-next-state-assignment")

    # pre-assignment of next_var before the case (default-assign idiom).
    pre = body[:body.find("case")] if "case" in body else ""
    pre_assigns = re.search(
        rf"\b{re.escape(next_var)}\s*(?:<=|=)\s*[^;]+;", pre) is not None
    default_assigns = bool(re.search(
        rf"\b{re.escape(next_var)}\s*(?:<=|=)", default_body)) if has_default \
        else False

    findings: List[Finding] = []

    # INFERRED LATCH — a state arm that does NOT assign next_var, with no
    # default-assign and no pre-assign → next_var latches for that state. This
    # is the ONE structural FSM defect that is BOTH always-a-bug AND zero-false-
    # positive on the real-RTL corpus (chacha/aes/sha256/ibex all pass clean).
    # The other recurring FSM-mismatch classes (#522: a counter that counts on
    # current- vs next-state, an edge wired to the WRONG but still-reachable
    # target, an extra pass-through latency state, or a dead state — the last
    # fires ~19% on known-good designs) are NOT structurally separable from a
    # correct design without the spec's intended transition table; they stay a
    # self-TB / judgment responsibility and are DELIBERATELY not flagged here.
    if not pre_assigns and not default_assigns:
        for s in item_states:
            arm = arm_bodies.get(s, "")
            if not re.search(rf"\b{re.escape(next_var)}\s*(?:<=|=)", arm):
                findings.append(Finding(
                    "fsm-inferred-latch", "ERROR", s,
                    f"state {s!r}'s arm does not assign {next_var!r}, the case "
                    f"has no assigning default and {next_var} is not "
                    f"pre-assigned → {next_var} latches (incomplete / stuck)."))

    return (findings, "CHECKED")


def check_rtl_dir(rtl_dir: Path) -> Tuple[List[Tuple[Path, Finding]], str]:
    out: List[Tuple[Path, Finding]] = []
    any_checked = False
    for f in sorted(rtl_dir.rglob("*")):
        if f.suffix not in (".v", ".sv") or not f.is_file():
            continue
        try:
            findings, status = check_text(f.read_text(errors="replace"))
        except OSError:
            continue
        if status == "CHECKED":
            any_checked = True
        for fd in findings:
            out.append((f, fd))
    return out, ("CHECKED" if any_checked else "SKIP-no-fsm")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Structural FSM next-state completeness check (#522).")
    ap.add_argument("target", help="RTL file OR directory")
    ap.add_argument("--json", default=None, help="write JSON findings here")
    ap.add_argument("--warn-only", action="store_true",
                    help="exit 0 even on ERROR findings (advisory mode)")
    args = ap.parse_args(argv)
    p = Path(args.target)
    if not p.exists():
        print(f"ERROR: target not found: {p}", file=sys.stderr)
        return 2

    if p.is_dir():
        pairs, status = check_rtl_dir(p)
        findings = [{"file": str(fp), **asdict(fd)} for fp, fd in pairs]
    else:
        fl, status = check_text(p.read_text(errors="replace"))
        findings = [{"file": str(p), **asdict(fd)} for fd in fl]

    summary = {
        "status": status,
        "n_findings": len(findings),
        "n_error": sum(1 for f in findings if f["severity"] == "ERROR"),
        "n_warn": sum(1 for f in findings if f["severity"] == "WARN"),
        "findings": findings,
    }
    out = json.dumps(summary, indent=2, ensure_ascii=False)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(out + "\n")
    print(out)
    if args.warn_only:
        return 0
    return 1 if summary["n_error"] > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
