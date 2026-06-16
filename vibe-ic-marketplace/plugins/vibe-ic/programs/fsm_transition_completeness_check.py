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


# --------------------------------------------------------------------------- #
# ONE-HOT CONTINUOUS-ASSIGN next-state completeness (ORGANIC #791)             #
# --------------------------------------------------------------------------- #
# The case-driven analyser above is BLIND to a one-hot FSM authored as pure
# continuous-assigns (no `case`): such a design has no state `localparam` case
# items, so parse_states() returns [] and check_text() SKIPs (-no-state-
# declarations). VerilogEval Prob150_review2015_fsmonehot is exactly this shape
# — and a fresh author dropped a SPEC-DISCLOSED self-loop in-edge
# (`Count --done_counting=0--> Count`) from the `Count_next` equation, so the
# functionally-wrong sample shipped hard_gates_pass=true (hidden-TB mismatches
# on every cycle exercising that transition). The "enumerate every in-edge incl
# self-loops" rule lived only as ic-expert PROSE — unenforced.
#
# This check needs the SPEC's disclosed transition table (the in-edges live in
# the prompt, not the RTL), so it takes BOTH the RTL and the spec text. It is
# scoped TIGHT to be zero-false-fire (§4.05 NO-FALSE-FIRE):
#   * It fires ONLY when the spec discloses an arrow-form transition table
#     (`<src> ... --<cond>--> <dst>` rows, requiring a `--label-->` arrow — a
#     bare prose `A --> B` does NOT match) AND the RTL has parseable one-hot
#     next-state assigns (`assign <Dst>_next = ...` / `assign next_state[<i>] =
#     ...`) for the disclosed destinations.
#   * A CORRECT one-hot FSM (every disclosed in-edge present) is NOT flagged.
#   * A design with NO disclosed transition table stays SKIP (no false fire).
#   * A destination with no parseable next-state assign is UNDER-flagged (the
#     edge is skipped) rather than guessed — a miss is acceptable, a false flag
#     on a correct FSM is not.
# chip-AGNOSTIC: pure structure — no chip / state / opcode literal.

# A disclosed in-edge row: `<src> (<output>) --<input_cond>--> <dst>` — the
# `--label-->` arrow form. Anchored so the RHS is an identifier-only end-of-line
# (a real table row): a header `state ... --input--> next state` (trailing word)
# fails the `$` anchor, and a bare prose `data --> register` (no leading `--`)
# fails the mandatory `--<cond>--` segment.
_EDGE_RE = re.compile(
    r"^\s*([A-Za-z_]\w*)\b[^\n>]*?--[^\n>]*?-->\s*([A-Za-z_]\w*)\s*$",
    re.MULTILINE)

# one-hot encoding disclosure tuple:
#   (S, S1, ..., Wait) = (10'b0000000001, 10'b0000000010, ...)
# The bit index is the position in the left tuple (LSB-first, matching the
# first 10'b...0001 entry). The `= (` lookahead requires the RHS to BE another
# parenthesised list, which excludes a bare port-interface tuple. The list items
# are BARE identifiers (`S, S1`), so a Verilog port tuple (`input a, input b`)
# never matches.
_ENCODING_RE = re.compile(
    r"\(\s*([A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)+)\s*\)\s*=\s*\(", re.DOTALL)

# RTL next-state assigns.
#  Form A (per-destination named output):  assign <Dst>_next = <expr> ;
#  Form B (indexed next-state vector):      assign next_state[<idx|name>] = <expr> ;
_ASSIGN_NEXT_NAMED_RE = re.compile(
    r"\bassign\s+([A-Za-z_]\w*)_next\s*=\s*(.*?);", re.DOTALL)
_ASSIGN_NEXT_VEC_RE = re.compile(
    r"\bassign\s+(?:next_state|state_next|nstate|ns)\s*\[\s*([A-Za-z_0-9]\w*)\s*\]"
    r"\s*=\s*(.*?);", re.DOTALL)


def parse_transition_table(spec_text: str) -> List[Tuple[str, str]]:
    """Return disclosed (src, dst) in-edges from a spec arrow-form transition
    table. Empty when no such table is disclosed (→ caller SKIPs)."""
    return [(m.group(1), m.group(2)) for m in _EDGE_RE.finditer(spec_text)]


def parse_onehot_encoding(spec_text: str) -> dict:
    """Map state-name → bit index from the disclosed one-hot encoding tuple.
    Empty when no encoding tuple is disclosed."""
    m = _ENCODING_RE.search(spec_text)
    if not m:
        return {}
    names = [n.strip() for n in m.group(1).split(",")]
    return {n: i for i, n in enumerate(names)}


def _parse_int_localparams(body: str) -> dict:
    """Map NAME→int for integer `localparam/parameter NAME=val` declarations —
    used to resolve a named one-hot index (`state[Count]` where Count=8)."""
    out: dict = {}
    for m in re.finditer(
            r"\b(?:localparam|parameter)\b\s*(?:\[[^\]]*\]\s*)?"
            r"((?:[A-Za-z_]\w*\s*=\s*[^;,]+[,;]\s*)+)", body):
        for am in re.finditer(r"([A-Za-z_]\w*)\s*=\s*([^;,]+)[,;]", m.group(1)):
            mnum = re.match(r"^(\d+)$", am.group(2).strip())
            if mnum:
                out[am.group(1)] = int(mnum.group(1))
    return out


def _state_vector_names(dst_exprs) -> "set":
    """ORGANIC #791 Step-2.7 — DERIVE the current-state one-hot vector name(s)
    from the RTL instead of hard-coding `state`. The one-hot source terms are
    `<VEC>[<idx|name>]` where VEC is the registered current-state vector; common
    real spellings are `state` / `state_q` / `state_reg` / `cur_state` / `cs` /
    `q`. VEC is the base read MOST OFTEN as `VEC[...]` across the next-state
    equations (a data bus is indexed in at most one equation; the state vector in
    essentially all). Return the maximal-frequency base(s); ties keep all (a
    permissive source-term match under-flags rather than false-fires)."""
    from collections import Counter
    cnt: "Counter" = Counter()
    for expr in dst_exprs:
        for base in set(re.findall(r"\b([A-Za-z_]\w*)\s*\[", expr)):
            cnt[base] += 1
    if not cnt:
        return set()
    top = max(cnt.values())
    return {b for b, c in cnt.items() if c == top}


def _expr_refs_source(expr: str, src: str, src_idx: Optional[int],
                      localparams: dict, state_vecs: "set") -> bool:
    """True if `expr` references the source state `src` as a one-hot term —
    `<VEC>[src]` (named) or `<VEC>[src_idx]` (numeric) or `<VEC>[ALIAS]` where a
    localparam ALIAS resolves to src_idx, for any current-state vector VEC the
    design uses (derived, NOT hard-coded — #791 Step-2.7: a correct FSM whose
    register is named `state_q`/`cur_state`/`q` must not be falsely flagged)."""
    if not state_vecs:
        return False
    vec_alt = "|".join(re.escape(v) for v in sorted(state_vecs, key=len,
                                                     reverse=True))
    for tok in re.findall(rf"\b(?:{vec_alt})\s*\[\s*([A-Za-z_0-9]\w*)\s*\]",
                          expr):
        if tok == src:
            return True
        if tok.isdigit() and src_idx is not None and int(tok) == src_idx:
            return True
        if (tok in localparams and src_idx is not None
                and localparams[tok] == src_idx):
            return True
    return False


def check_onehot_continuous_assign(
        rtl_text: str, spec_text: str) -> Tuple[List[Finding], str]:
    """One-hot continuous-assign next-state completeness vs the spec's disclosed
    transition table. Flags a disclosed in-edge (incl self-loop) absent from the
    destination state's next-state equation.

    SKIP (no false fire) when: no spec text, no disclosed transition table, or
    the RTL has no parseable one-hot next-state assigns / no matched
    destination. Returns (findings, 'CHECKED-ONEHOT' | 'SKIP-<reason>')."""
    if not spec_text:
        return ([], "SKIP-no-spec")
    edges = parse_transition_table(spec_text)
    if len(edges) < 2:
        return ([], "SKIP-no-transition-table")
    enc = parse_onehot_encoding(spec_text)

    body = _strip_comments(rtl_text)
    localparams = _parse_int_localparams(body)

    dst_expr = {m.group(1): m.group(2)
                for m in _ASSIGN_NEXT_NAMED_RE.finditer(body)}
    vec_dst_expr = {m.group(1): m.group(2)
                    for m in _ASSIGN_NEXT_VEC_RE.finditer(body)}
    if not dst_expr and not vec_dst_expr:
        return ([], "SKIP-no-onehot-next-state-assign")

    # ORGANIC #791 Step-2.7 — DERIVE the current-state vector name(s) from the
    # next-state equations (NOT hard-coded `state`). If the equations index NO
    # `<vec>[...]` at all, the one-hot source terms cannot be judged → SKIP
    # (a non-bit-indexed encoding we do not parse — under-flag, never a false
    # block of a correct design).
    state_vecs = _state_vector_names(
        list(dst_expr.values()) + list(vec_dst_expr.values()))
    if not state_vecs:
        return ([], "SKIP-no-state-vector")

    findings: List[Finding] = []
    checked_any = False
    for src, dst in edges:
        expr = None
        if dst in dst_expr:
            expr = dst_expr[dst]
        elif dst in vec_dst_expr:
            expr = vec_dst_expr[dst]
        elif enc.get(dst) is not None and str(enc[dst]) in vec_dst_expr:
            expr = vec_dst_expr[str(enc[dst])]
        if expr is None:
            # destination has no parseable next-state assign — under-flag, don't
            # guess.
            continue
        checked_any = True
        src_idx = enc.get(src)
        if not _expr_refs_source(expr, src, src_idx, localparams, state_vecs):
            kind = "self-loop" if src == dst else "in-edge"
            _vec = sorted(state_vecs)[0]
            findings.append(Finding(
                "fsm-onehot-missing-transition", "ERROR", dst,
                f"spec discloses the {kind} {src!r} --> {dst!r} but the one-hot "
                f"next-state equation for {dst!r} omits the {src!r} source term "
                f"(e.g. `{_vec}[{src}]`"
                + (f"/`{_vec}[{src_idx}]`" if src_idx is not None else "")
                + "). The hidden TB exercising that transition will mismatch — "
                "enumerate EVERY disclosed in-edge (incl self-loops) into the "
                "destination's one-hot next-state OR."))
    if not checked_any:
        return ([], "SKIP-no-matched-destination")
    return (findings, "CHECKED-ONEHOT")


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
        description="Structural FSM next-state completeness check (#522; "
                    "#791 one-hot continuous-assign extension).")
    ap.add_argument("target", help="RTL file OR directory")
    ap.add_argument("--json", default=None, help="write JSON findings here")
    ap.add_argument("--spec", default=None,
                    help="spec/prompt file disclosing the transition table — "
                         "enables the one-hot continuous-assign next-state "
                         "completeness check (#791). Single-RTL targets only.")
    ap.add_argument("--warn-only", action="store_true",
                    help="exit 0 even on ERROR findings (advisory mode)")
    args = ap.parse_args(argv)
    p = Path(args.target)
    if not p.exists():
        print(f"ERROR: target not found: {p}", file=sys.stderr)
        return 2

    spec_text = ""
    if args.spec:
        sp = Path(args.spec)
        if not sp.is_file():
            print(f"ERROR: --spec not found: {sp}", file=sys.stderr)
            return 2
        spec_text = sp.read_text(errors="replace")

    if p.is_dir():
        pairs, status = check_rtl_dir(p)
        findings = [{"file": str(fp), **asdict(fd)} for fp, fd in pairs]
    else:
        rtl_text = p.read_text(errors="replace")
        fl, status = check_text(rtl_text)
        findings = [{"file": str(p), **asdict(fd)} for fd in fl]
        # #791: one-hot continuous-assign next-state completeness (needs spec).
        if spec_text:
            ohfl, ohstatus = check_onehot_continuous_assign(rtl_text, spec_text)
            findings += [{"file": str(p), **asdict(fd)} for fd in ohfl]
            if status.startswith("SKIP") and ohstatus == "CHECKED-ONEHOT":
                status = ohstatus
            elif status.startswith("SKIP") and ohstatus.startswith("SKIP"):
                status = f"{status}+{ohstatus}"

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
