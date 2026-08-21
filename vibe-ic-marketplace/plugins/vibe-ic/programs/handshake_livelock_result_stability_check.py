#!/usr/bin/env python3
"""handshake_livelock_result_stability_check.py — v0.3.22 (ORGANIC #523).

Two STRUCTURAL, zero-false-positive checks for a multi-cycle valid/ready
datapath (an N-cycle operation that raises an output `*_valid` and is drained by
a consumer `*_ready`). Both target bugs that PASS the author's own testbench but
hang / corrupt under a standard always-ready consumer — the field agent saw a
fresh author re-make BOTH every clean-room round, and the valid/ready prose
lessons proved unreliable (the #517/#518 prose-is-not-enough lesson).

GATING (this is what makes the checks zero-false-positive on the existing
correct corpus): a file is examined ONLY when its module exposes BOTH an OUTPUT
port whose name contains `valid` AND an INPUT port whose name contains `ready`
(the res_valid / res_ready multi-cycle handshake). Streaming / register-mapped /
bus designs (spm bit-serial multiplier, sha256 register-file core, subservient
Wishbone SoC) do not expose that port pair, so they SKIP — they can never fire.

CHECK 1 — LOAD-GUARD LIVELOCK (`handshake-load-livelock`, ERROR)
    A clocked load/kick-off arm that (a) starts an iteration counter (assigns it
    a constant start value) and self-sets a busy flag to 1, and (b) is guarded
    by a valid-like trigger input (opn_valid / req_valid / start / ...), BUT
    whose guard carries NO busy-exclusion term. The exact discriminator that
    separates a CORRECT design from the bug: the correct radix2_div guards the
    load with `~start_cnt` (a flag it self-sets to 1 in the very same arm) — so
    once loaded the guard blocks re-loading. The buggy author drops that term
    and guards only with `opn_valid & ~res_valid`; because an always-ready
    consumer makes `res_valid` a single-cycle pulse, `~res_valid` is true for
    the whole multi-cycle op → the counter re-loads to its start value every
    cycle → it never reaches its terminal value → `res_valid` never rises →
    the consumer hangs. A negation of a pulse output (`~res_valid`/`~done`) is
    NOT a busy-exclusion; a negation of a self-set/held busy flag, a
    `state == IDLE` guard, or a counter-idle compare IS.

CHECK 2 — RESULT-REGISTER INSTABILITY (`handshake-result-unstable`, ERROR)
    A result/data OUTPUT port driven (comb or registered) by a working
    shift/accumulate register that has a FREE-RUNNING assignment — one reached
    on a clocked path with NO busy / state / counting / load guard (i.e. it
    keeps shifting when the machine is idle / after completion). A standard
    consumer latches the data the cycle AFTER it sees `*_valid`; by then a
    free-running working register has moved on → the consumer reads a corrupted
    value. The correct radix2_div drives `result` from its shift register `SR`
    too, but EVERY `SR` assignment sits under a `start_cnt`-guarded branch, so
    `SR` freezes when idle — that is NOT free-running and does NOT fire.

DELIBERATELY CONSERVATIVE: when the handshake gate is absent, when no iteration
counter is found, or when the structure is not confidently parseable, the file
SKIPs. An under-flag (miss) is acceptable; a false flag on a correct handshake
design is not — it would block a good design (#511 no-leak is load-bearing here).

chip-AGNOSTIC: pure Verilog structure parsing — no chip / signal / opcode literal.

EXIT CODES
----------
    0  clean OR not-an-analysable-handshake (SKIP)  — also 0 with --warn-only
    1  a structural defect found
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
    symbol: str
    detail: str


def _strip_comments(text: str) -> str:
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.DOTALL)
    text = re.sub(r"//[^\n]*", "", text)
    return text


# ---- handshake port gate ---------------------------------------------------
# An OUTPUT port containing 'valid' AND an INPUT port containing 'ready'. We scan
# explicit port direction declarations (ANSI header or body `input/output`).
_PORT_DECL_RE = re.compile(
    r"\b(input|output|inout)\b\s*(?:wire|reg|logic)?\s*(?:\[[^\]]*\]\s*)?"
    r"([A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*)\s*[,;)]")


def _ports_by_dir(body: str) -> Tuple[set, set]:
    inputs, outputs = set(), set()
    for m in _PORT_DECL_RE.finditer(body):
        d = m.group(1)
        names = [n.strip() for n in m.group(2).split(",")]
        for n in names:
            if d == "input":
                inputs.add(n)
            elif d == "output":
                outputs.add(n)
    return inputs, outputs


def has_handshake_ports(body: str) -> Tuple[bool, set, set]:
    inputs, outputs = _ports_by_dir(body)
    out_valid = {n for n in outputs if "valid" in n.lower()}
    in_ready = {n for n in inputs if "ready" in n.lower()}
    return (bool(out_valid) and bool(in_ready)), out_valid, in_ready


# ---- clocked-block extraction ----------------------------------------------
def _clocked_blocks(body: str) -> List[str]:
    """Return the bodies of `always @(posedge ...)` blocks (begin..matching end
    or single statement). Best-effort balanced begin/end scan."""
    out = []
    for m in re.finditer(r"always\s*@\s*\(\s*posedge\b[^)]*\)\s*", body):
        i = m.end()
        # skip to first token
        rest = body[i:]
        mb = re.match(r"\s*begin\b", rest)
        if not mb:
            # single statement up to ';'
            semi = rest.find(";")
            if semi != -1:
                out.append(rest[:semi + 1])
            continue
        # balanced begin/end
        depth = 0
        j = i + mb.start()  # start at 'begin'
        tokens = re.finditer(r"\bbegin\b|\bend\b", body[j:])
        start_body = None
        for tk in tokens:
            if tk.group(0) == "begin":
                if depth == 0:
                    start_body = j + tk.end()
                depth += 1
            else:
                depth -= 1
                if depth == 0:
                    out.append(body[start_body:j + tk.start()])
                    break
    return out


# counter reg: appears as `R <= R + ...` (increment) somewhere.
def _counter_regs(text: str) -> set:
    regs = set()
    for m in re.finditer(r"\b([A-Za-z_]\w*)\s*<=\s*\1\s*\+", text):
        regs.add(m.group(1))
    return regs


# valid-like trigger input (NOT a result/pulse output).
_TRIGGER_RE = re.compile(
    r"\b(opn_?valid|op_?valid|in_?valid|i_?valid|s_?valid|valid_in|"
    r"start(?:_i|_in)?|req(?:_i|_valid)?|load(?:_i|_en)?|go|kick|launch)\b",
    re.IGNORECASE)
_PULSE_OUT_RE = re.compile(
    r"^(res_?valid|out_?valid|o_?valid|result_?valid|done|o_?done|"
    r"data_?valid|dout_?valid)$", re.IGNORECASE)
# names that, when negated, count as a genuine busy-exclusion.
_BUSY_NAME_RE = re.compile(
    r"(busy|counting|in_?progress|inflight|active|running|started|start_?cnt|"
    r"load_?done|processing|calc|comput|state_?busy|ongoing)", re.IGNORECASE)
_IDLE_GUARD_RE = re.compile(
    r"\b(?:state|st|cs|fsm|c_?state|cur_?state)\w*\s*==\s*\w*"
    r"(idle|reset|wait|ready)\w*", re.IGNORECASE)


def _consume_stmt(s: str, i: int) -> int:
    """Return the end index (exclusive) of the procedural statement starting at
    or after `i`: a balanced begin..end, a case..endcase, or a single stmt to
    the next ';'."""
    m = re.compile(r"\S").search(s, i)
    if not m:
        return len(s)
    j = m.start()
    if re.match(r"begin\b", s[j:]):
        depth = 0
        for tk in re.finditer(r"\bbegin\b|\bend\b", s[j:]):
            if tk.group(0) == "begin":
                depth += 1
            else:
                depth -= 1
                if depth == 0:
                    return j + tk.end()
        return len(s)
    if re.match(r"case\b", s[j:]):
        mm = re.search(r"\bendcase\b", s[j:])
        return j + mm.end() if mm else len(s)
    semi = s.find(";", j)
    return semi + 1 if semi != -1 else len(s)


def _split_case_arms(sel: str, case_body: str) -> List[Tuple[str, str]]:
    """Split a case body into (guard, arm_body) where guard is `sel==LABEL`."""
    out: List[Tuple[str, str]] = []
    label_re = re.compile(r"(\bdefault\b|[A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*)"
                          r"\s*:(?!:)")
    depth = 0
    pending = None
    pstart = None
    for tk in re.finditer(r"\bbegin\b|\bend\b|\bcase\b|\bendcase\b|"
                          r"(\bdefault\b|[A-Za-z_]\w*(?:\s*,\s*[A-Za-z_]\w*)*)"
                          r"\s*:(?!:)", case_body):
        w = tk.group(0)
        if w.startswith("begin"):
            depth += 1
            continue
        if w.startswith("end") and not w.startswith("endcase"):
            depth -= 1
            continue
        if w.startswith("case") or w.startswith("endcase"):
            continue
        if depth == 0 and ":" in w:
            if pending is not None:
                out.append((f"{sel}=={pending}", case_body[pstart:tk.start()]))
            pending = tk.group(1).strip()
            pstart = tk.end()
    if pending is not None:
        out.append((f"{sel}=={pending}", case_body[pstart:]))
    return out


def _top_level_clauses(block: str) -> List[Tuple[str, str]]:
    """Return the TOP-LEVEL (guard, body) clauses of a procedural block,
    correctly skipping over nested begin/end so inner if/else are absorbed into
    their parent's body. case is expanded into per-label (sel==LABEL, body)
    clauses. A plain statement is returned as ('', stmt)."""
    clauses: List[Tuple[str, str]] = []
    i, n = 0, len(block)
    while True:
        m = re.compile(r"\S").search(block, i)
        if not m:
            break
        i = m.start()
        mif = re.match(r"(else\s+if|if|case|else)\b", block[i:])
        if not mif:
            j = _consume_stmt(block, i)
            clauses.append(("", block[i:j]))
            i = j
            continue
        kw = re.sub(r"\s+", " ", mif.group(1))
        after = i + mif.end()
        if kw in ("if", "else if", "case"):
            p = block.find("(", after)
            if p == -1:
                break
            depth = 0
            guard = ""
            q = p + 1
            for c in range(p, n):
                if block[c] == "(":
                    depth += 1
                elif block[c] == ")":
                    depth -= 1
                    if depth == 0:
                        guard = block[p + 1:c]
                        q = c + 1
                        break
            if kw == "case":
                mm = re.search(r"\bendcase\b", block[q:])
                end = q + mm.end() if mm else n
                cbody = block[q:(q + mm.start()) if mm else n]
                clauses.extend(_split_case_arms(guard.strip(), cbody))
                i = end
            else:
                j = _consume_stmt(block, q)
                clauses.append((guard, block[q:j]))
                i = j
        else:  # bare else
            j = _consume_stmt(block, after)
            clauses.append(("", block[after:j]))
            i = j
    return clauses


def _leaf_regions(block: str, pg: str = "") -> List[Tuple[str, str]]:
    """Recursively descend if/else/case → list of (combined_guard, leaf_body),
    where combined_guard is the conjunction of all enclosing guards."""
    out: List[Tuple[str, str]] = []
    for guard, body in _top_level_clauses(block):
        combined = (pg + " " + guard).strip()
        if re.search(r"\bif\s*\(|\bcase\s*\(", body):
            inner = body
            mb = re.match(r"\s*begin\b", inner)
            if mb:
                inner = inner[mb.end():]
                inner = re.sub(r"\bend\b\s*$", "", inner.rstrip())
            out.extend(_leaf_regions(inner, combined))
        else:
            out.append((combined, body))
    return out


def _is_reset_guard(guard: str) -> bool:
    return re.search(r"\b(rst|reset|n?rst_?n?|areset|por)\b", guard,
                     re.IGNORECASE) is not None


def _guard_has_busy_exclusion(guard: str, self_set_flags: set) -> bool:
    # negation of a self-set flag (start_cnt-style)
    for f in self_set_flags:
        if re.search(rf"[~!]\s*{re.escape(f)}\b", guard):
            return True
    # negation of a busy-named signal
    for m in re.finditer(r"[~!]\s*([A-Za-z_]\w*)", guard):
        if _BUSY_NAME_RE.search(m.group(1)):
            return True
    # state == IDLE-style
    if _IDLE_GUARD_RE.search(guard):
        return True
    # counter-idle compare: cnt == 0 / count == 0 / !cnt
    if re.search(r"\b\w*(cnt|count)\w*\s*==\s*0", guard, re.IGNORECASE):
        return True
    return False


def _self_set_flags(arm_body: str) -> set:
    """Regs assigned a logic-1 in this arm (candidate busy flags)."""
    out = set()
    for m in re.finditer(r"\b([A-Za-z_]\w*)\s*<=\s*1'b1\b", arm_body):
        out.add(m.group(1))
    for m in re.finditer(r"\b([A-Za-z_]\w*)\s*<=\s*1\s*;", arm_body):
        out.add(m.group(1))
    return out


def _check_livelock(block: str, counters: set) -> List[Finding]:
    findings: List[Finding] = []
    arms = _top_level_clauses(block)
    for guard, abody in arms:
        if not guard:
            continue
        if _is_reset_guard(guard):
            continue
        # does this arm kick off a counter (assign a counter a constant start)?
        starts_counter = False
        for c in counters:
            if re.search(rf"\b{re.escape(c)}\s*<=\s*\d+'?[bdh]?\d*\s*;", abody) \
                    or re.search(rf"\b{re.escape(c)}\s*<=\s*\d+\s*;", abody):
                # exclude pure increment `c <= c + 1`
                if not re.search(rf"\b{re.escape(c)}\s*<=\s*{re.escape(c)}\s*\+",
                                 abody):
                    starts_counter = True
        if not starts_counter:
            continue
        # is the arm guarded by a valid-like trigger input?
        trig = None
        for m in _TRIGGER_RE.finditer(guard):
            # ensure the matched token is not the negated pulse-output
            tok = m.group(0)
            if _PULSE_OUT_RE.match(tok):
                continue
            trig = tok
            break
        if trig is None:
            continue
        self_flags = _self_set_flags(abody)
        if _guard_has_busy_exclusion(guard, self_flags):
            continue
        findings.append(Finding(
            "handshake-load-livelock", "ERROR", trig,
            f"load arm guarded by trigger '{trig}' starts an iteration counter "
            f"but its guard '{guard.strip()[:80]}' has no busy-exclusion "
            f"(no ~busy/~start_cnt/state==IDLE/cnt==0). Under an always-ready "
            f"consumer the valid pulse re-arms the load every cycle → counter "
            f"never reaches terminal → livelock / hang."))
    return findings


_RESULT_NAME_RE = re.compile(
    r"(result|product|quotient|remainder|accum|data_?out|dout|"
    r"sum|q_?out|res_?data|odata|o_?data)", re.IGNORECASE)


def _result_ports(inputs: set, outputs: set) -> set:
    out = set()
    for n in outputs:
        ln = n.lower()
        if re.search(r"(valid|ready|done|busy|error|err|ack)", ln):
            continue
        if _RESULT_NAME_RE.search(ln) and len(n) >= 3:
            out.add(n)
    return out


def _driver_regs(body: str, port: str) -> set:
    """Source regs that drive `port` (one hop): assign port = f(...) or
    port <= reg, plus an intermediate `assign port = g(W)` chain (one level)."""
    regs = set()
    # assign port = expr ;
    for m in re.finditer(rf"\bassign\s+{re.escape(port)}\s*=\s*([^;]+);", body):
        ids = set(re.findall(r"\b([A-Za-z_]\w*)\b", m.group(1)))
        regs |= ids
    # port <= expr ;
    for m in re.finditer(rf"\b{re.escape(port)}\s*<=\s*([^;]+);", body):
        regs |= set(re.findall(r"\b([A-Za-z_]\w*)\b", m.group(1)))
    # one-hop through intermediate wires: assign W = h(X)
    chained = set()
    for w in list(regs):
        for m in re.finditer(rf"\bassign\s+{re.escape(w)}\s*=\s*([^;]+);", body):
            chained |= set(re.findall(r"\b([A-Za-z_]\w*)\b", m.group(1)))
    return regs | chained


def _is_shift_accum_reg(block: str, reg: str) -> bool:
    # W <= {..W..}  OR  W <= W +/- ..  OR  W <= {W[..], ..}
    if re.search(rf"\b{re.escape(reg)}\s*<=\s*\{{[^;]*\b{re.escape(reg)}\b",
                 block):
        return True
    if re.search(rf"\b{re.escape(reg)}\s*<=\s*{re.escape(reg)}\s*[-+]", block):
        return True
    return False


_BUSY_TOK_RE = re.compile(
    r"(busy|counting|in_?progress|inflight|active|running|start|cnt|count|"
    r"state|st_|_st|fsm|idle|valid|load|enable|\ben\b|go|phase|step|round|"
    r"stage|\bcs\b|done|finish|complete|last|term)", re.IGNORECASE)


def _has_free_running_assign(block: str, reg: str) -> bool:
    """True iff `reg` is assigned in a leaf region whose COMBINED enclosing guard
    carries NO busy / state / counting / load / valid token (and is not a reset
    region) — i.e. it keeps updating while the machine is idle / after done."""
    for guard, body in _leaf_regions(block):
        if not re.search(rf"\b{re.escape(reg)}\s*<=", body):
            continue
        if _is_reset_guard(guard):
            continue
        if not _BUSY_TOK_RE.search(guard):
            return True
    return False


def _check_result_stability(body: str, block_all: str,
                            inputs: set, outputs: set) -> List[Finding]:
    findings: List[Finding] = []
    for port in sorted(_result_ports(inputs, outputs)):
        for reg in sorted(_driver_regs(body, port)):
            if reg == port:
                continue
            if not _is_shift_accum_reg(block_all, reg):
                continue
            if _has_free_running_assign(block_all, reg):
                findings.append(Finding(
                    "handshake-result-unstable", "ERROR", port,
                    f"result/data output '{port}' is driven by working register "
                    f"'{reg}', which has a free-running (non-busy-gated) "
                    f"shift/accumulate assignment → it keeps changing after "
                    f"'{port}' is presented. A consumer that latches the cycle "
                    f"AFTER valid reads a corrupted value. Latch the result in a "
                    f"dedicated register only on the completion cycle."))
                break
    return findings


def check_text(text: str) -> Tuple[List[Finding], str]:
    body = _strip_comments(text)
    ok, out_valid, in_ready = has_handshake_ports(body)
    if not ok:
        return ([], "SKIP-no-valid-ready-handshake")
    blocks = _clocked_blocks(body)
    if not blocks:
        return ([], "SKIP-no-clocked-block")
    block_all = "\n".join(blocks)
    counters = _counter_regs(block_all)
    findings: List[Finding] = []
    if counters:
        for blk in blocks:
            findings.extend(_check_livelock(blk, counters))
    inputs, outputs = _ports_by_dir(body)
    findings.extend(_check_result_stability(body, block_all, inputs, outputs))
    # de-dup
    seen = set()
    uniq = []
    for f in findings:
        key = (f.rule, f.symbol)
        if key not in seen:
            seen.add(key)
            uniq.append(f)
    return (uniq, "CHECKED")


def check_paths(paths: List[Path]) -> Tuple[List[Tuple[Path, Finding]], str]:
    out: List[Tuple[Path, Finding]] = []
    any_checked = False
    for f in paths:
        if not f.is_file():
            continue
        try:
            findings, status = check_text(f.read_text(errors="replace"))
        except OSError:
            continue
        if status == "CHECKED":
            any_checked = True
        for fd in findings:
            out.append((f, fd))
    return out, ("CHECKED" if any_checked else "SKIP-no-handshake")


def _expand(targets: List[str]) -> List[Path]:
    out: List[Path] = []
    for t in targets:
        p = Path(t)
        if p.is_dir():
            out.extend(sorted(q for q in p.rglob("*")
                              if q.suffix in (".v", ".sv") and q.is_file()))
        else:
            out.append(p)
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(
        description="Multi-cycle valid/ready handshake structural check (#523).")
    ap.add_argument("targets", nargs="+", help="RTL file(s) / dir(s) / globs")
    ap.add_argument("--json", default=None, help="write JSON findings here")
    ap.add_argument("--warn-only", action="store_true",
                    help="exit 0 even on ERROR findings (advisory mode)")
    args = ap.parse_args(argv)

    paths = _expand(args.targets)
    if not paths:
        print("ERROR: no targets", file=sys.stderr)
        return 2
    pairs, status = check_paths(paths)
    findings = [{"file": str(fp), **asdict(fd)} for fp, fd in pairs]
    summary = {
        "status": status,
        "n_findings": len(findings),
        "n_error": sum(1 for f in findings if f["severity"] == "ERROR"),
        "findings": findings,
    }
    out = json.dumps(summary, indent=2, ensure_ascii=False)
    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(out + "\n")
    print(out)
    if args.warn_only:
        return 0
    if status == "SKIP-no-handshake":
        # The JSON already said SKIP; the exit code said success (#564).
        # `n_error` is 0 because nothing was examined, not because a handshake
        # was checked and found stable, and rc 0 is what the P0 umbrella
        # aggregates.
        #
        # Measured over 60 corpus projects: 4 answer CHECKED (real work), 31
        # answer SKIP-no-handshake, 25 already exit 2 via the no-targets path.
        # So this gate can distinguish; only this branch could not.
        print("VACUOUS_PASS: handshake_livelock_result_stability_check "
              "examined nothing (reason: no handshake found in any target) — "
              "n_error 0 is not a stability result", file=sys.stderr)
        return 2
    return 1 if summary["n_error"] > 0 else 0


if __name__ == "__main__":
    sys.exit(main())
