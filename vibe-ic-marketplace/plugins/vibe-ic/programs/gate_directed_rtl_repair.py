#!/usr/bin/env python3
"""gate_directed_rtl_repair.py — act on a blocking gate's OWN verdict instead of
giving up.

WHY
---
Two of our gates do their job perfectly and then throw the result away. When
`shape_b_sample_export.guard_export` rejects a sample it `unlink()`s the file and
returns `{"verdict": "FAIL", "reason": "guard_rejected"}`; when
`design_one_shot_runner.step_determinism_gates` fires it returns a bare `FAIL`.
In both paths the gate has already NAMED the defect precisely — which port, which
cycle, which expression — and nothing consumes that. The flow detects a real
defect and then ships nothing rather than repairing it.

This module is the missing consumer. Given the authored RTL and the spec, it
re-runs the blocking gates, looks up a deterministic source transform for the
defect class the gate named, applies it, and RE-RUNS THE SAME GATE as the
acceptance test.

THE INVARIANT — an independent MEASURING oracle must accept the repair
------------------------------------------------------------------------
A repair is accepted ONLY when a simulation against a contract derived from the
SPEC returns an explicit PASS on the repaired RTL. "The structural pattern no
longer matches" is NEVER sufficient, and this is the whole design:

    If a purely STRUCTURAL gate were its own acceptance test, the cheapest
    passing "repair" is one that perturbs the syntax until the pattern stops
    matching while leaving the behaviour broken. The loop would then ship a
    still-wrong design carrying a GREEN gate — strictly worse than the honest
    rejection it replaced, because a false certificate is believed.

So the repairability of a defect class is decided by whether an oracle exists
that MEASURES the property the gate stands for, independently of the syntax the
gate matches on. A class whose only gate is structural is NOT repaired here; it
is reported with a stated `why_not_bucket_a` and routed to the expert-DB / skill
layer. That routing is a result, not a failure.

Every oracle used here is spec-derived: it builds its own testbench from prose
the author is entitled to read. No hidden testbench, no golden reference, no
scorer verdict is ever opened (§4.05).

WHAT IS REPAIRED TODAY
----------------------
`output-cycle-alignment` — the spec discloses a cycle-by-cycle input->output
worked example, and the authored RTL reproduces the right sequence one cycle
late because the output is registered (Moore) where the example requires it in
the same cycle as its trigger (Mealy). The gate for this class,
`worked_example_sequence_oracle_check`, is ALREADY a simulation of the spec's own
example — so it is a legitimate acceptance test, and the transform below is
accepted only on its explicit PASS.

The transform is a pure statement-level split of one edge-triggered block into
(a) the same block with the output assignments removed and (b) a combinational
copy carrying ONLY the output assignments. It adds no logic and invents no
expression: the value the flop was about to capture becomes the value the port
presents in that same cycle. Deleted statements are replaced by the null
statement `;`, which is legal wherever a statement is legal, so the surrounding
`if` / `case` structure survives untouched.

WHAT IS NOT REPAIRED, AND WHY
-----------------------------
`clock-divider-phase-form` — `clock_divider_phase_form_check` is a STRUCTURAL
gate: it matches an OR of >=2 self-toggling, reset-LOW intermediates. Its own
docstring states the property it stands for is "a wrong FIRST-CYCLE phase at a
CORRECT period", and the one measuring oracle we have for dividers,
`clock_divider_ratio_oracle_check`, measures period / duty / reset value — by
construction blind to a first-cycle phase error at a correct period. There is
therefore NO independent oracle that could accept a repair for this class, and
the gate's own condition is trivially satisfiable by flipping a reset literal.
See `why_not_bucket_a` in NOT_REPAIRABLE below.

`edge-history-reset-to-constant` — a history register whose reset arm assigns a
CONSTANT while an edge term over (sig, prev) exists, so the edge fires on a
transition that never happened the moment reset releases. Its gate,
`edge_history_reset_phantom_check`, NAMES a transform (`prev <= sig` in the reset
arm) and still cannot be Bucket A, for a reason its own sweep measured rather
than argued: what separates a defect from a correct synchroniser is whether
`sig` can be HIGH at the instant reset releases, and that lives in the STIMULUS,
not in the RTL either program is handed. That gate's recorded sweep fires on 7
of 57 known-failing drafts AND on 9 of 302 known-passing deliveries, and it
names two designs on OPPOSITE sides of that split that are structurally
identical — so the split is not decidable from the text, no oracle here can
accept a candidate, and the class routes to the author.

THIS IS THE ROUTER, NOT THE EMIT GATE, and that is what makes the wiring
admissible. `ESCALATE`/rc 1 here discards nothing and refuses no delivery — it
says a defect stands unrepaired and names who decides. A signature with a
measured false-fire rate may therefore reach THIS verdict, where it may not
reach an emit gate's BLOCK or `step_determinism_gates`' FAIL list (§4.05: a
false BLOCK is irreversible; a false ESCALATE costs one author one look).

chip-AGNOSTIC: the logic reads a spec string and an RTL string. It contains no
benchmark record format, no design name, and no expected value.

CLI:
    gate_directed_rtl_repair.py --rtl <f.v> --spec <design_description.txt>
                               [--write] [--json OUT]
    rc 0 = repaired, or nothing to repair;  rc 1 = a defect stands unrepaired.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional, Tuple

_HERE = Path(__file__).resolve().parent
if str(_HERE) not in sys.path:
    sys.path.insert(0, str(_HERE))


# ── defect classes the loop knows how to route ──────────────────────────────
# A class is REPAIRABLE only when an oracle MEASURES the property its gate
# stands for. See the module docstring for why this is the deciding question.
NOT_REPAIRABLE: Dict[str, Dict[str, str]] = {
    "clock-divider-phase-form": {
        "gate": "clock_divider_phase_form_check",
        "why_not_bucket_a":
            "The program would see: the RTL text, and the gate's finding "
            "{output, or_operands, self_toggled}. From that input it cannot "
            "decide the ONE thing a repair needs — the correct level-decode "
            "threshold for each intermediate — because the gate names the "
            "wrong FORM, not the right VALUE, and the divisor lives in the "
            "spec prose plus the RTL's own parameter in forms a static read "
            "cannot resolve uniquely. Worse, no oracle can ACCEPT a candidate: "
            "clock_divider_ratio_oracle_check measures period/duty/reset value "
            "and is by construction blind to a first-cycle phase error at a "
            "correct period, which is exactly this defect. The gate's own "
            "condition is satisfiable by flipping a reset literal from 1'b0 to "
            "1'b1, which changes the waveform without being known to fix it. A "
            "repair accepted on that basis would ship a wrong design under a "
            "green gate.",
        "escalate_to":
            "agents/lessons/ic_expert_L9 (RTL authoring craft) — author the "
            "level-decode form from the spec's divisor rather than patching "
            "the self-toggle form after the fact.",
    },
    "edge-history-reset-to-constant": {
        "gate": "edge_history_reset_phantom_check",
        "why_not_bucket_a":
            "The gate NAMES the transform — `prev <= sig` in the reset arm — so "
            "unlike the divider class above the candidate is not the obstacle. "
            "The ACCEPTANCE is. The property the gate stands for is 'an edge "
            "fires at reset release on a transition that never happened', and "
            "whether it does depends on the value of `sig` at that instant, "
            "which is a fact about the STIMULUS and not about the RTL. No "
            "spec-derived oracle can supply it: a self-testbench that drives "
            "`sig` low out of reset PASSES the defect and one that drives it "
            "high FAILS the correct synchroniser, so the oracle would be "
            "measuring its own arbitrary choice. The gate's own sweep is the "
            "evidence, not an argument: 7 of 57 known-failing drafts and 9 of "
            "302 known-passing deliveries fire, and the author tried to narrow "
            "it structurally and the data refused — that sweep names two "
            "designs on opposite sides of the split that are structurally "
            "identical. Applying the transform on that basis would rewrite nine "
            "correct designs to make a pattern stop matching, which is the "
            "exact failure mode this module's invariant exists to refuse.",
        "escalate_to":
            "the RTL author (and agents/lessons/ic_expert_L9, RTL authoring "
            "craft) — decide from the STIMULUS whether `sig` can be high when "
            "reset releases; if it can, reset the history register as "
            "`prev <= sig` and discard the first measured interval after reset "
            "before any threshold verdict.",
    },
}


# ── Verilog statement-extent scanning (structural, no design literals) ───────
_LINE_COMMENT = re.compile(r"//[^\n]*")
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.S)


def _blank_noncode(src: str) -> str:
    """Return `src` with comments and string literals replaced by spaces of the
    SAME length, so offsets found on the masked text index the original."""
    out = list(src)

    def _blank(m: re.Match) -> None:
        for i in range(m.start(), m.end()):
            if out[i] != "\n":
                out[i] = " "

    for m in _BLOCK_COMMENT.finditer(src):
        _blank(m)
    masked = "".join(out)
    for m in _LINE_COMMENT.finditer(masked):
        _blank(m)
    masked = "".join(out)
    for m in re.finditer(r'"(?:[^"\\\n]|\\.)*"', masked):
        _blank(m)
    return "".join(out)


_WORD = re.compile(r"[A-Za-z_]\w*")
# keywords that OPEN a nested statement region and their closers
_OPENERS = {"begin": "end", "fork": "join", "case": "endcase",
            "casex": "endcase", "casez": "endcase"}
_CLOSERS = {"end", "join", "join_any", "join_none", "endcase"}


def _statement_extent(masked: str, start: int) -> Optional[int]:
    """Given `start` = index of the first character of a statement in `masked`
    (comments already blanked), return the index just past the statement.

    Handles begin/end, fork/join, case/endcase nesting, and the `else` /
    `else if` continuation. Returns None if the text runs out unbalanced."""
    i, n = start, len(masked)
    depth = 0
    while i < n:
        c = masked[i]
        if c == "(":
            # skip a balanced parenthesised region wholesale (sensitivity
            # lists, conditions and argument lists never open a statement)
            pdepth = 0
            while i < n:
                if masked[i] == "(":
                    pdepth += 1
                elif masked[i] == ")":
                    pdepth -= 1
                    if pdepth == 0:
                        i += 1
                        break
                i += 1
            continue
        m = _WORD.match(masked, i)
        if m:
            w = m.group(0)
            if w in _OPENERS:
                depth += 1
            elif w in _CLOSERS:
                depth -= 1
                if depth == 0:
                    i = m.end()
                    j = _skip_ws(masked, i)
                    k = _WORD.match(masked, j)
                    if k and k.group(0) == "else":
                        i = k.end()
                        continue
                    return i
                if depth < 0:
                    return None
            i = m.end()
            continue
        if c == ";" and depth == 0:
            i += 1
            j = _skip_ws(masked, i)
            k = _WORD.match(masked, j)
            if k and k.group(0) == "else":
                i = k.end()
                continue
            return i
        i += 1
    return None


def _skip_ws(s: str, i: int) -> int:
    while i < len(s) and s[i].isspace():
        i += 1
    return i


def _always_blocks(masked: str) -> List[Tuple[int, int, int, str]]:
    """Every `always`-family block: (kw_start, body_start, body_end, sens_text)."""
    out = []
    for m in re.finditer(r"\balways(?:_ff|_comb|_latch)?\b", masked):
        i = _skip_ws(masked, m.end())
        sens = ""
        if i < len(masked) and masked[i] == "@":
            j = _skip_ws(masked, i + 1)
            if j < len(masked) and masked[j] == "(":
                pd, k = 0, j
                while k < len(masked):
                    if masked[k] == "(":
                        pd += 1
                    elif masked[k] == ")":
                        pd -= 1
                        if pd == 0:
                            k += 1
                            break
                    k += 1
                sens = masked[j:k]
                i = _skip_ws(masked, k)
            elif j < len(masked) and masked[j] == "*":
                sens = "*"
                i = _skip_ws(masked, j + 1)
        end = _statement_extent(masked, i)
        if end is None:
            continue
        out.append((m.start(), i, end, sens))
    return out


_STMT_OPENERS = ("begin", "else", "end", "endcase", "join", "join_any",
                 "join_none", "fork", "do", "initial", "always", "always_ff",
                 "always_comb", "always_latch")


def _stmt_assignments(masked: str, lo: int, hi: int
                      ) -> List[Tuple[int, int, str, bool, str, int]]:
    """Every ASSIGNMENT statement in [lo,hi), as
    (start, end, lhs, indexed, op, op_offset).

    Found by a linear statement-boundary scan rather than a bare regex, because
    `<=` is also the less-than-or-equal OPERATOR: a corpus sweep over 6265 RTL
    files showed a regex reading `if (cnt <= 5)` as an assignment to `cnt` and
    then blanking to the next `;`, corrupting 24 files. An assignment is
    recognised ONLY at a statement-initial position at paren depth 0."""
    out: List[Tuple[int, int, str, bool]] = []
    i = lo
    at_start = True      # a statement may begin here
    ternary = False      # a `?` is open in the current statement
    pdepth = 0
    while i < hi:
        c = masked[i]
        if c == "(":
            pdepth += 1
            i += 1
            at_start = False
            continue
        if c == ")":
            pdepth -= 1
            i += 1
            at_start = (pdepth == 0)      # an `if (...)` header just closed
            continue
        if c == ";":
            i += 1
            at_start, ternary = True, False
            continue
        if c == "?" and pdepth == 0:
            ternary = True
            i += 1
            at_start = False
            continue
        if c == ":" and pdepth == 0:
            i += 1
            at_start = not ternary        # a case label, not a ternary arm
            ternary = False
            continue
        if c.isspace():
            i += 1
            continue
        m = _WORD.match(masked, i)
        if not m:
            i += 1
            at_start = False
            continue
        w = m.group(0)
        if w in _STMT_OPENERS:
            i = m.end()
            at_start, ternary = True, False
            continue
        if at_start and pdepth == 0:
            j = _skip_ws(masked, m.end())
            indexed = False
            if j < hi and masked[j] == "[":
                indexed = True
                d = 0
                while j < hi:
                    if masked[j] == "[":
                        d += 1
                    elif masked[j] == "]":
                        d -= 1
                        if d == 0:
                            j += 1
                            break
                    j += 1
                j = _skip_ws(masked, j)
            op = None
            if masked.startswith("<=", j):
                op = "<="
            elif masked.startswith("=", j) and not masked.startswith("==", j):
                op = "="
            if op is not None:
                k = masked.find(";", j)
                if 0 <= k < hi:
                    out.append((m.start(), k + 1, w, indexed, op, j))
                    i = k + 1
                    at_start, ternary = True, False
                    continue
        i = m.end()
        at_start = False
    return out


def _assignments_to(masked: str, lo: int, hi: int, port: str
                    ) -> List[Tuple[int, int, str, int]]:
    """Whole-port assignments to `port` inside [lo,hi), as
    (start, end, op, op_offset).

    An indexed / part-select target is deliberately excluded — the repair only
    moves assignments to the bare port."""
    return [(s, e, op, oj)
            for (s, e, lhs, indexed, op, oj) in _stmt_assignments(masked, lo, hi)
            if lhs == port and not indexed]


def _blank_stmt(chars: List[str], lo: int, hi: int) -> None:
    """Replace source[lo:hi) with a null statement `;`, preserving newlines so
    line numbers in any downstream tool error still line up."""
    for i in range(lo, hi):
        if chars[i] != "\n":
            chars[i] = " "
    chars[lo] = ";"


# ── the one repair transform: de-register an output by one cycle ────────────
def deregister_output(rtl: str, port: str) -> Optional[str]:
    """Split the single edge-triggered block that assigns `port` into

        always @(posedge ...)  <same block, port assignments removed>
        always @(*)            <same block, ONLY the port assignments, blocking>

    so the value the flop was about to capture is presented in the SAME cycle.
    Returns the rewritten RTL, or None when the preconditions do not hold (the
    caller then reports the defect unrepaired rather than guessing)."""
    masked = _blank_noncode(rtl)

    # the port must not also be continuously assigned
    if re.search(rf"\bassign\s+{re.escape(port)}\s*=", masked):
        return None

    blocks = _always_blocks(masked)
    owning = []
    for (kw, bs, be, sens) in blocks:
        if _assignments_to(masked, bs, be, port):
            owning.append((kw, bs, be, sens))
    if len(owning) != 1:
        return None                      # 0 → not this shape; >1 → ambiguous
    kw, bs, be, sens = owning[0]
    if "posedge" not in sens and "negedge" not in sens:
        return None                      # already combinational

    # A NAMED block (`begin : write_logic`) may declare locals and is a scope
    # name; the split would duplicate that name and the design would no longer
    # elaborate. Found by the corpus sweep — decline rather than rename.
    if re.search(r"\bbegin\s*:", masked[bs:be]):
        return None

    port_asgn = _assignments_to(masked, bs, be, port)
    if any(op != "<=" for (_s, _e, op, _o) in port_asgn):
        return None                      # mixed blocking/nonblocking → not this shape

    # every assignment in the block, so the combinational copy can drop the
    # ones that are not the port's
    all_asgn = _stmt_assignments(masked, bs, be)

    block_src = rtl[kw:be]
    off = kw

    # (a) the clocked copy: same block, port assignments blanked
    clocked = list(block_src)
    for (s, e, _op, _o) in port_asgn:
        _blank_stmt(clocked, s - off, e - off)
    clocked_txt = "".join(clocked)

    # (b) the combinational copy: same block, EVERY non-port statement blanked,
    #     the port's `<=` turned into `=`, and the sensitivity made `@(*)`.
    comb = list(block_src)
    port_spans = {(s, e) for (s, e, _o, _oj) in port_asgn}
    for (s, e, _lhs, _ix, _op, _oj) in all_asgn:
        if (s, e) in port_spans:
            continue
        _blank_stmt(comb, s - off, e - off)
    for (_s, _e, _op, oj) in port_asgn:
        # `<=` → `=`: blank the '<', leaving the '=' in place, so every other
        # offset in the block is unchanged.
        comb[oj - off] = " "
    comb_txt = "".join(comb)
    # replace this copy's sensitivity list with `@(*)`
    m_at = re.search(r"\balways(?:_ff|_comb|_latch)?\b", comb_txt)
    if not m_at:
        return None
    body_rel = bs - off
    comb_txt = ("always @(*)" + comb_txt[body_rel:])

    note = ("\n  // gate_directed_rtl_repair: the spec's worked example requires "
            "this output\n  // in the SAME cycle as its trigger; the value the "
            "flop was about to\n  // capture is presented combinationally "
            "instead. No logic added.\n  ")
    return rtl[:kw] + clocked_txt + "\n\n  " + note + comb_txt + rtl[be:]


# ── the loop ────────────────────────────────────────────────────────────────
def repair(rtl: str, spec: str) -> dict:
    """Re-run the blocking gates, repair what has a measuring oracle, and
    accept ONLY on that oracle's explicit PASS."""
    res: dict = {"verdict": "NOT_APPLICABLE", "defect": None, "rtl": None,
                 "transform": None, "evidence": {}, "attempts": []}

    # ── repairable class: output cycle alignment vs the spec's worked example
    try:
        import worked_example_sequence_oracle_check as _wex
    except Exception as e:                              # pragma: no cover
        res["reason"] = f"oracle unavailable: {e}"
        return res

    before = _wex.analyze(rtl, spec)
    worked_example_defer = None
    if before.get("applicable") and before.get("verdict") == "SKIP":
        # Preserve the oracle's explicit non-blocking uncertainty, but do not
        # let it hide an independently measured non-repairable defect below.
        worked_example_defer = {
            "verdict": "DEFER",
            "defect": "worked-example-oracle-skip",
            "evidence": {
                "gate": "worked_example_sequence_oracle_check",
                "sampling_semantics": before.get("sampling_semantics"),
                "phase_verdicts": before.get("phase_verdicts"),
            },
            "reason": before.get(
                "reason", "oracle produced no blocking verdict"),
        }
    if before.get("verdict") == "BLOCK":
        if before.get("sampling_semantics") == "dual-phase-pre-and-post-edge":
            res.update(
                verdict="NO_REPAIR",
                defect="worked-example-mismatch-all-phases",
                evidence={"gate": "worked_example_sequence_oracle_check",
                          "phase_verdicts": before.get("phase_verdicts"),
                          "inport": before.get("inport"),
                          "outport": before.get("outport"),
                          "in_bits": before.get("in_bits"),
                          "expected_out_bits": before.get("out_bits")},
                reason="both sampling phases mismatch, so the oracle does not "
                       "establish a single-cycle alignment defect and the "
                       "deregister_output transform would be a guess")
            return res
        res.update(defect="output-cycle-alignment",
                   evidence={"gate": "worked_example_sequence_oracle_check",
                             "inport": before.get("inport"),
                             "outport": before.get("outport"),
                             "in_bits": before.get("in_bits"),
                             "expected_out_bits": before.get("out_bits")})
        port = before.get("outport")
        cand = deregister_output(rtl, port) if port else None
        if cand is None:
            res.update(verdict="NO_REPAIR",
                       reason="the output is not assigned by exactly one "
                              "edge-triggered block with whole-port "
                              "non-blocking assignments; the transform would "
                              "have to guess, so it declines")
            return res
        after = _wex.analyze(cand, spec)
        res["attempts"].append({"transform": "deregister_output",
                                "oracle_verdict": after.get("verdict"),
                                "oracle_reason": after.get("reason", "")})
        # ACCEPTANCE: an explicit PASS from the measuring oracle. A SKIP is NOT
        # acceptance — a repair that made the oracle inapplicable (e.g. broke
        # elaboration) must never be mistaken for a repair that worked.
        if after.get("verdict") == "PASS":
            res.update(verdict="REPAIRED", rtl=cand,
                       transform="deregister_output")
        else:
            res.update(verdict="NO_REPAIR",
                       reason="the candidate was not accepted by the "
                              "spec-derived oracle "
                              f"({after.get('verdict')}) — discarded")
        return res

    # ── non-repairable class: report the routing rather than guessing
    try:
        import clock_divider_phase_form_check as _cdp
        pf = _cdp.analyze(rtl)
        if pf.get("phase_risky"):
            info = NOT_REPAIRABLE["clock-divider-phase-form"]
            res.update(verdict="ESCALATE", defect="clock-divider-phase-form",
                       evidence={"gate": info["gate"],
                                 "finding": pf["findings"][0]},
                       why_not_bucket_a=info["why_not_bucket_a"],
                       escalate_to=info["escalate_to"])
            return res
    except Exception:
        pass

    # ── non-repairable class: a history register reset to a CONSTANT.
    # Ordered AFTER the divider branch deliberately: that class was here first
    # and its routing must not change. A design that trips both is reported as
    # the divider, unchanged from before this branch existed.
    #
    # This is the one consumer whose VERDICT this gate can honestly move.
    # `edge_history_reset_phantom_check` emits WARN and only WARN, so
    # `cvdp_gate._structural_finding_gate` (which blocks on ERROR) is provably
    # invariant under it, and `step_determinism_gates`' FAIL list is closed to a
    # signature with a measured false-fire rate. ESCALATE is neither: it refuses
    # no delivery and rewrites no RTL, it names an unrepaired defect and routes
    # it to whoever holds the missing evidence. See NOT_REPAIRABLE above.
    try:
        import edge_history_reset_phantom_check as _ehr
        _findings, _ = _ehr.check_text(rtl)
        if _findings:
            info = NOT_REPAIRABLE["edge-history-reset-to-constant"]
            f0 = _findings[0]
            res.update(verdict="ESCALATE",
                       defect="edge-history-reset-to-constant",
                       evidence={"gate": info["gate"],
                                 "finding": {"rule": f0.rule,
                                             "severity": f0.severity,
                                             "symbol": f0.symbol,
                                             "line": f0.line,
                                             "message": f0.message},
                                 "further_findings": len(_findings) - 1},
                       why_not_bucket_a=info["why_not_bucket_a"],
                       escalate_to=info["escalate_to"])
            return res
    except Exception:
        pass

    if worked_example_defer is not None:
        res.update(worked_example_defer)
    return res


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--rtl", type=Path, required=True)
    ap.add_argument("--spec", type=Path, required=True)
    ap.add_argument("--write", action="store_true",
                    help="write the repaired RTL back over --rtl")
    ap.add_argument("--json", type=Path)
    a = ap.parse_args(argv)
    if not a.rtl.is_file() or not a.spec.is_file():
        print("ERROR: --rtl and --spec must both exist", file=sys.stderr)
        return 2
    rtl = a.rtl.read_text(errors="replace")
    res = repair(rtl, a.spec.read_text(errors="replace"))
    if a.json:
        a.json.write_text(json.dumps({k: v for k, v in res.items()
                                      if k != "rtl"}, indent=1))
    v = res["verdict"]
    if v == "REPAIRED":
        if a.write:
            a.rtl.write_text(res["rtl"])
        print(f"REPAIRED: {res['defect']} via {res['transform']} — accepted by "
              f"the spec-derived oracle"
              + (f"; written to {a.rtl}" if a.write else ""))
        return 0
    if v == "NOT_APPLICABLE":
        print("PASS: no blocking gate verdict to act on.")
        return 0
    if v == "DEFER":
        print(f"SKIP: {res['defect']} — {res.get('reason', '')}")
        return 0
    if v == "ESCALATE":
        print(f"ESCALATE: {res['defect']} — no independent oracle can accept a "
              f"repair, so this is not Bucket A.\n"
              f"  why_not_bucket_a: {res['why_not_bucket_a']}\n"
              f"  route to: {res['escalate_to']}")
        return 1
    print(f"NO_REPAIR: {res['defect']} — {res.get('reason','')}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
