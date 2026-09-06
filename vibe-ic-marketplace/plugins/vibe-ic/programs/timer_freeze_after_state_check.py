#!/usr/bin/env python3
"""timer_freeze_after_state_check.py — Static heuristic for the
"counter must freeze after state transition" RTL anti-pattern.

# What it catches

A module declares a one-shot state-bit input/wire (typical names: `awake`,
`active`, `enable`, `started`, `live`, `on`, `running`) AND has a
free-running counter (`cnt <= cnt + ...`, `count <= count + ...`,
`timer <= timer + ...`, ...). The state bit MUST have control over whether
that counter advances: there must be some value of it in which the counter
does not move. Either polarity satisfies that — `if (!<state>)` gating the
increment, or a `<state>`-keyed branch in which the counter holds or is
reset while the increment sits in a sibling branch.

If the counter increments unconditionally inside an `always` block whose
module imports a state bit, this checker FLAGs the site for review.

v1.17.71+ — TWO MEASURED DEFECTS FIXED, both false positives on correct RTL:

  1. The freeze had to be an ASSIGNMENT (`<counter> <= <const>`). A freeze
     implemented as a HOLD — the counter simply not assigned in the
     state-keyed branch — is the same freeze and was unrecognised. The
     finding message named `if (!<state>)` as a remedy that the code then
     rejected.
  2. `_enclosing_block_text` searched back a fixed 1500 characters for the
     enclosing `always` and, failing to find one, analysed the 1500-character
     slice as if it were a block. MEASURED on `u_hawaii_adc_readout.v`: for
     both flagged counters the slice began mid-statement and did not contain
     the freeze branch at all. The block is now bounded by its own `always`
     and its own `end`, at any distance.

Fixing (1) means the check no longer asserts that ASSERTION means freeze.
It cannot: the token list holds both `awake` (assert = stop the idle timer)
and `enable` (assert = run), whose polarities are opposite, and the two
shapes are structurally identical. What it asserts now is the property the
v052 specimen actually violated — a counter free-running with respect to a
state bit its module imports. That specimen is still flagged; see
`tests/test_timer_freeze_after_state_check.py`.

# Why this matters

Bug specimen (hardware-caught 2026-04-24): v052 `wake_ctrl.v` had a tITO
idle-timeout counter that kept incrementing after the IC went `awake=1`
on receiving the 0x74 wake command. Every 5 ms (`TITO_CYC` cycles) the
counter rolled over and emitted `wake_req`, which `gen_wake` translated
into a periodic 24-µs LOW pulse on `ID_BUS`. Sim missed it because no
testbench waited >1 tITO with `awake=1`. Hardware caught it on first
power-on. This rule would have flagged the offending `else cnt <= cnt + 24'd1;`
because the enclosing module imports `awake` but the increment is
ungated.

# Static heuristic — known limits

This is grep + simple control-flow inspection, not a formal analyzer:

  - False positives: counters that legitimately don't gate on state
    (e.g. an internal POR debouncer that runs regardless of `awake`).
    Add `// timer_freeze_check: ok-unconditional` on the increment line
    to whitelist.
  - False negatives: counters whose freeze logic is split across multiple
    `always` blocks, or counters reset by an external `cmd_valid` event
    that incidentally only fires while not-awake.

Each finding requires manual review. The intended use is "fail loud
before the next FPGA bring-up cycle, not silently FAIL a CI gate".

# CLI

    python3 timer_freeze_after_state_check.py --rtl-dir <path> [--json out.json]

Exit codes:
    0 — no findings
    1 — at least one ungated counter in a stateful module
    2 — argument or I/O error
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, asdict
from pathlib import Path
from typing import Iterable, List, Optional, Tuple


# ---------------------------------------------------------------------------
# Tunables (regex tokens — kept narrow on purpose; widen via flag if needed)
# ---------------------------------------------------------------------------
_STATE_TOKENS = (
    "awake", "woken", "active", "enable", "enabled", "started", "live",
    "running", "armed", "ready_lock", "on_state",
)
_COUNTER_NAME_RE = re.compile(
    r"\b(\w*(?:cnt|count|counter|timer|tick|cycle|delay|wait)\w*)\b",
    re.IGNORECASE,
)
# Match an unconditional self-increment: `<name> <= <name> + ...;`
# (allowed widths/values: any digit, any apostrophe-prefixed literal, any
# named macro, any simple expression — we anchor on the `<= same_name +`
# shape).
_INC_LINE_RE = re.compile(
    r"\b(\w+)\s*<=\s*\1\s*\+\s*[^;]+;",
)
_NONBLOCK_INC_LINE_RE = re.compile(
    r"\b(\w+)\s*=\s*\1\s*\+\s*[^;]+;",
)
_WHITELIST_COMMENT = "timer_freeze_check: ok-unconditional"


@dataclass
class Finding:
    file: str
    module: str
    line: int
    counter: str
    state_bit: str
    snippet: str
    reason: str

    def as_dict(self) -> dict:
        return asdict(self)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _list_rtl_files(rtl_dir: Path) -> List[Path]:
    out: List[Path] = []
    for ext in (".v", ".sv"):
        out.extend(sorted(rtl_dir.rglob(f"*{ext}")))
    return out


def _read_rtl_files(rtl_dir: Path) -> Tuple[List[Tuple[Path, str]], List[Path]]:
    """Read every globbed RTL file, partitioned into readable and unreadable.

    #492 — `audit` used to call `read_text` straight off the glob. A path the
    glob yields is not necessarily a path that can be read: a DANGLING SYMLINK
    matches `*.v` and then raises `FileNotFoundError`. That escaped as an
    uncaught traceback, and an uncaught traceback exits 1 — which this repo's
    convention reads as FAIL. So an unreadable file in a user's RTL directory
    produced a FAIL that was really a crash, and a crash is not a verdict about
    the design. That is the same false-certificate family as the rc-2 defect
    #492 is about, pointed the other way. MEASURED: 6 dangling `.v` symlinks
    exist in this repo's own tracked tree (generated netlists under
    `steps/*/netlist.v`), so this is the normal layout of several projects here,
    not an exotic input.

    Returning the two lists SEPARATELY is what keeps the denominator honest.
    The report's `files_scanned` is the count of files actually read; files that
    could not be read are counted under `files_unreadable` instead of silently
    padding the number. A gate that discloses a denominator must not include
    files it never opened.
    """
    readable: List[Tuple[Path, str]] = []
    unreadable: List[Path] = []
    for fpath in _list_rtl_files(rtl_dir):
        try:
            readable.append((fpath, fpath.read_text(errors="replace")))
        except OSError:
            unreadable.append(fpath)
    return readable, unreadable


def _strip_line_comments(text: str) -> str:
    """Remove `// ...` and `/* ... */` so they don't affect regex matches.
    Preserves newlines so line numbers stay correct."""
    text = re.sub(r"/\*.*?\*/", lambda m: "\n" * m.group(0).count("\n"),
                  text, flags=re.DOTALL)
    text = re.sub(r"//[^\n]*", "", text)
    return text


def _modules_in(text: str) -> List[Tuple[str, int, int]]:
    """Return [(module_name, start_line, end_line), ...] for each module
    in the (comment-stripped) file. Uses 1-based line numbers."""
    out: List[Tuple[str, int, int]] = []
    line_starts = [0]
    for m in re.finditer(r"\n", text):
        line_starts.append(m.end())
    line_starts.append(len(text))

    def offset_to_line(off: int) -> int:
        # Binary search would be nicer but linear is fine for typical files.
        for i in range(len(line_starts) - 1):
            if line_starts[i] <= off < line_starts[i + 1]:
                return i + 1
        return len(line_starts)

    pat_mod = re.compile(r"\bmodule\s+(\w+)\b")
    pat_end = re.compile(r"\bendmodule\b")
    cursor = 0
    while cursor < len(text):
        m = pat_mod.search(text, cursor)
        if not m:
            break
        e = pat_end.search(text, m.end())
        if not e:
            break
        out.append((m.group(1), offset_to_line(m.start()),
                    offset_to_line(e.end())))
        cursor = e.end()
    return out


def _module_imports_state(mod_text: str) -> Optional[str]:
    """Return the matched state-bit token if the module declares one as
    an INPUT — i.e., something the module reacts to but doesn't own.

    Owner / producer signals (declared `output reg`) and internal helpers
    (declared `reg`/`wire` inside the module body) are excluded — those
    follow a different "I'm the state machine, I drive my own counter"
    pattern that legitimately doesn't need the `else if (state) freeze`
    branch this checker enforces. v052 false-positive examples that
    motivated this filter:

      - gen_wake.v: `reg active` is owned by the module; the `cnt+1`
        runs inside `else` of `if (!active)` so the counter naturally
        freezes when the module deasserts active itself.
      - mac.v: `output reg awake` — mac.v PRODUCES awake, doesn't
        consume it as a guard.
    """
    # Stop the lookahead at `,` / `;` / `)` so we don't false-pair an
    # earlier `input` keyword with a later `output reg <token>` declaration
    # in the same module-port list.
    decl_re = re.compile(
        r"\binput\b[^;,)]*?\b(" + "|".join(_STATE_TOKENS) + r")\b",
        re.IGNORECASE,
    )
    m = decl_re.search(mod_text)
    return m.group(1) if m else None


def _match_paren(text: str, i: int) -> int:
    """`text[i]` is `(`; return the offset just past its matching `)`,
    or -1 if unbalanced."""
    depth = 0
    for j in range(i, len(text)):
        if text[j] == "(":
            depth += 1
        elif text[j] == ")":
            depth -= 1
            if depth == 0:
                return j + 1
    return -1


_WS_RE = re.compile(r"\s*")
_KW_IF = re.compile(r"\bif\b")
_KW_ELSE = re.compile(r"\belse\b")
_KW_BEGIN = re.compile(r"\bbegin\b")
_KW_END = re.compile(r"\bend\b")
_KW_CASE = re.compile(r"\bcase[xz]?\b")
_KW_ENDCASE = re.compile(r"\bendcase\b")
_KW_FORK = re.compile(r"\bfork\b")
_KW_JOIN = re.compile(r"\bjoin(?:_any|_none)?\b")
_KW_ALWAYS = re.compile(r"\balways(?:_ff|_comb|_latch)?\b")


def _skip_ws(text: str, i: int) -> int:
    return _WS_RE.match(text, i).end()


def _block_end(text: str, i: int, opener: re.Pattern, closer: re.Pattern) -> int:
    """`i` is the offset of an opening keyword match (`begin`, `case`, `fork`).
    Return the offset just past its matching closer, counting nesting."""
    depth = 0
    pos = i
    while pos < len(text):
        mo = opener.search(text, pos)
        mc = closer.search(text, pos)
        if mc is None:
            return len(text)
        if mo is not None and mo.start() < mc.start():
            depth += 1
            pos = mo.end()
            continue
        depth -= 1
        pos = mc.end()
        if depth == 0:
            return pos
    return len(text)


def _statement_span(text: str, i: int) -> int:
    """`i` is the first offset of a statement. Return the offset just past it.

    Understands `begin`/`end`, `case`/`endcase`, `fork`/`join`, a nested
    if/else chain (dangling `else` binds to the nearest `if`, as in Verilog),
    and otherwise runs to the next `;` outside parentheses.
    """
    i = _skip_ws(text, i)
    if i >= len(text):
        return len(text)
    if _KW_BEGIN.match(text, i):
        return _block_end(text, i, _KW_BEGIN, _KW_END)
    if _KW_CASE.match(text, i):
        return _block_end(text, i, _KW_CASE, _KW_ENDCASE)
    if _KW_FORK.match(text, i):
        return _block_end(text, i, _KW_FORK, _KW_JOIN)
    if _KW_IF.match(text, i):
        _branches, end = _parse_chain(text, i)
        return end
    depth = 0
    for j in range(i, len(text)):
        c = text[j]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
        elif c == ";" and depth <= 0:
            return j + 1
    return len(text)


def _parse_chain(text: str, i: int) -> Tuple[List[Tuple[Optional[str], int, int]], int]:
    """Parse the if/else-if/else chain whose leading `if` starts at `i`.

    Returns `([(condition_or_None, body_start, body_end), ...], chain_end)`.
    A chain with no explicit final `else` is given a VIRTUAL empty final
    branch: reaching it means every condition was false, and in it the
    counter provably does not advance. That virtual branch is what makes
    `if (!<state>) <increment>` — the remedy this checker's own finding
    message has always named — recognisable as a freeze.
    """
    branches: List[Tuple[Optional[str], int, int]] = []
    pos = i
    end = i
    while True:
        mi = _KW_IF.match(text, pos)
        if not mi:
            break
        p = _skip_ws(text, mi.end())
        if p >= len(text) or text[p] != "(":
            break
        k = _match_paren(text, p)
        if k < 0:
            break
        cond = text[p + 1:k - 1]
        bs = _skip_ws(text, k)
        be = _statement_span(text, bs)
        branches.append((cond, bs, be))
        end = be
        p2 = _skip_ws(text, be)
        me = _KW_ELSE.match(text, p2)
        if not me:
            break
        p3 = _skip_ws(text, me.end())
        if _KW_IF.match(text, p3):
            pos = p3
            continue
        b2 = _statement_span(text, p3)
        branches.append((None, p3, b2))
        end = b2
        break
    if branches and branches[-1][0] is not None:
        branches.append((None, end, end))   # virtual empty `else`
    return branches, end


def _chains_in(text: str) -> List[List[Tuple[Optional[str], int, int]]]:
    """Every if/else chain in `text`, at any nesting depth.

    A chain HEAD is an `if` that is not itself the `if` of an `else if`;
    scanning every head therefore reaches nested chains too, without
    recursion.
    """
    out: List[List[Tuple[Optional[str], int, int]]] = []
    for m in _KW_IF.finditer(text):
        before = text[:m.start()].rstrip()
        if _KW_ELSE.search(before[-6:]) and before.endswith("else"):
            continue
        branches, _end = _parse_chain(text, m.start())
        if branches:
            out.append(branches)
    return out


def _advances_counter(body: str, counter: str) -> bool:
    """True if `body` contains a self-increment of `counter` anywhere."""
    pat = re.compile(
        rf"\b{re.escape(counter)}\s*(?:<=|=)\s*{re.escape(counter)}\s*\+"
    )
    return bool(pat.search(body))


def _enclosing_always_block(text: str, inc_offset: int) -> Tuple[str, int]:
    """Return `(block_text, offset_of_inc_within_block)` for the `always`
    block that encloses `inc_offset`.

    The previous implementation searched back a FIXED 1500 characters and,
    when no `always` was found inside that window, used the 1500-character
    point itself as the block start. MEASURED on `u_hawaii_adc_readout.v`:
    for both counters the window began mid-statement, so the slice handed to
    the gating test was not a block at all and did not contain the freeze
    branch. A truncated block can only ever produce a verdict about the
    truncation. There is no cap now: the enclosing `always` is found however
    far back it is, and the block runs to its own `end`, so a freeze branch
    that sits after the increment is visible too.
    """
    starts = [m.start() for m in _KW_ALWAYS.finditer(text, 0, inc_offset)]
    if not starts:
        return text, inc_offset
    bs = starts[-1]
    be = _statement_span(text, _skip_ws(text, _KW_ALWAYS.match(text, bs).end()))
    # The always header may carry a sensitivity list before the statement.
    hdr = _skip_ws(text, _KW_ALWAYS.match(text, bs).end())
    if hdr < len(text) and text[hdr] == "@":
        p = _skip_ws(text, hdr + 1)
        if p < len(text) and text[p] == "(":
            p = _match_paren(text, p)
            if p > 0:
                be = _statement_span(text, p)
        elif p < len(text) and text[p] == "*":
            be = _statement_span(text, p + 1)
    if be <= inc_offset:
        be = min(len(text), inc_offset + 200)
    return text[bs:be], inc_offset - bs


def _counter_is_gated_by_state(
    block_text: str, state_token: str, counter_name: str, inc_offset: int,
) -> bool:
    """True when the state bit has CONTROL over whether `counter_name`
    advances at `inc_offset`.

    The property, stated once: there is an if/else chain in the enclosing
    `always` block that contains the increment, and that chain has ANOTHER
    branch which (a) can only be reached once the state token has been
    tested, and (b) does not advance the counter. In that branch the counter
    is frozen — whether it is frozen by being assigned a constant, or frozen
    by simply not being assigned at all.

    Reaching branch *i* of a chain requires `!c1 && ... && !c(i-1) && ci`, so
    branch *i* is state-constrained as soon as ANY condition up to and
    including its own names the token. The chain always ends in an explicit
    or virtual `else`, so a lone `if (!<state>) <increment>` is recognised:
    its virtual else is state-constrained and cannot advance the counter.

    This subsumes both shapes the check accepted before —

        else if (<state>) ... <counter> <= <const>;      (v0.64)
        if      (<state>) ... <counter> <= <const>;      (v0.119.29)

    — because in each the state-keyed branch does not advance the counter.
    It additionally recognises the FREEZE-BY-HOLD form, in which the
    state-keyed branch assigns the counter nothing at all:

        end else if (!enable) begin
            dout_valid <= 1'b0;          // counters simply HOLD
        end else begin
            ... <counter> <= <counter> + 1'b1; ...
        end

    MEASURED on `u_hawaii_adc_readout.v` (ihp-sg13g2, 2026-09-06): the hold
    form above freezes `bit_count` and `ch_count` correctly — proven by
    simulation, not by assertion: with the branch removed a testbench that
    drops `enable` mid-frame sees `bit_count` run 4 -> 12; with the branch
    present it holds at 4 and no payload bit is emitted. The check flagged
    the CORRECT design and named, as its remedy, the `if (!<state>)` guard
    the code had never implemented.

    WHAT THIS GIVES UP, stated plainly. The old shapes required the freeze
    branch to be keyed POSITIVELY on the token, which encodes "assertion
    means freeze" — true of the `awake` specimen this check was born from,
    and false of `enable`, which is in the same token list and conventionally
    means the opposite. No STRUCTURAL discriminator between the two exists:
    `if (!awake) X; else cnt <= cnt+1;` and the ADC's hold form are the same
    shape, so no rule can accept one and reject the other. This check
    therefore no longer asserts a polarity; it asserts that the counter is
    not free-running with respect to a state bit the module imports, which is
    what the v052 specimen actually violated — its increment is control-
    INDEPENDENT of `awake` and is still flagged.
    """
    tok_re = re.compile(rf"\b{re.escape(state_token)}\b", re.IGNORECASE)
    for branches in _chains_in(block_text):
        constrained: List[bool] = []
        seen = False
        for cond, _bs, _be in branches:
            if cond is not None and tok_re.search(cond):
                seen = True
            constrained.append(seen)
        holder = None
        for idx, (_cond, bs, be) in enumerate(branches):
            if bs <= inc_offset < be:
                holder = idx
                break
        if holder is None:
            continue
        for idx, (_cond, bs, be) in enumerate(branches):
            if idx == holder or not constrained[idx]:
                continue
            if _advances_counter(block_text[bs:be], counter_name):
                continue
            return True
    return False


def _line_of_offset(text: str, off: int) -> int:
    return text.count("\n", 0, off) + 1


# ---------------------------------------------------------------------------
# Core audit
# ---------------------------------------------------------------------------
def audit(rtl_dir: Path) -> List[Finding]:
    findings: List[Finding] = []
    readable, _unreadable = _read_rtl_files(rtl_dir)

    for fpath, raw in readable:
        # We need the original line numbers for reporting AND we need the
        # whitelist comment intact, so check whitelist on raw text.
        # Comment-strip before regex matching to avoid commented-out code.
        text = _strip_line_comments(raw)

        modules = _modules_in(text)
        for mod_name, start_ln, end_ln in modules:
            # Slice module text by line range.
            lines = text.splitlines(keepends=True)
            mod_text = "".join(lines[start_ln - 1:end_ln])
            state_tok = _module_imports_state(mod_text)
            if not state_tok:
                continue

            # Find every counter self-increment inside this module.
            for inc_re in (_INC_LINE_RE, _NONBLOCK_INC_LINE_RE):
                for m in inc_re.finditer(mod_text):
                    counter = m.group(1)
                    if not _COUNTER_NAME_RE.search(counter):
                        continue

                    # Whitelist marker on the original raw line?
                    inc_line_in_module = mod_text[:m.start()].count("\n") + 1
                    abs_line = start_ln + inc_line_in_module - 1
                    raw_line = raw.splitlines()[abs_line - 1] \
                        if abs_line - 1 < len(raw.splitlines()) else ""
                    if _WHITELIST_COMMENT in raw_line:
                        continue

                    block, rel = _enclosing_always_block(mod_text, m.start())
                    if _counter_is_gated_by_state(
                            block, state_tok, counter, rel):
                        continue

                    findings.append(Finding(
                        file=str(fpath),
                        module=mod_name,
                        line=abs_line,
                        counter=counter,
                        state_bit=state_tok,
                        snippet=raw_line.strip(),
                        reason=(
                            f"module imports `{state_tok}` but counter "
                            f"`{counter}` advances in EVERY state of "
                            f"`{state_tok}`: no branch of the if/else chain "
                            f"holding the increment is keyed on it, so "
                            f"nothing freezes the counter. Gate the "
                            f"increment on `{state_tok}`, or freeze the "
                            f"counter in a `{state_tok}`-keyed branch — "
                            f"holding it there counts, it need not be "
                            f"assigned a constant"
                        ),
                    ))
    return findings


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def _build_report(findings: List[Finding], rtl_dir: Path) -> dict:
    # #492 — `files_scanned` used to be `len(_list_rtl_files(...))`, i.e. the
    # GLOB count, computed independently of what `audit` managed to read. That
    # decoupling is what let the disclosed denominator include a file the gate
    # never opened. It is now the count of files actually read, with the
    # unreadable ones disclosed separately rather than folded in.
    readable, unreadable = _read_rtl_files(rtl_dir)
    return {
        "program": "timer_freeze_after_state_check",
        "version": "1.1.0",
        "rtl_dir": str(rtl_dir),
        "summary": {
            "files_scanned": len(readable),
            "files_unreadable": len(unreadable),
            "unreadable_files": [str(p) for p in unreadable],
            "findings_count": len(findings),
            "pass": len(findings) == 0,
        },
        "findings": [f.as_dict() for f in findings],
    }


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(
        description="Static heuristic for ungated counters in stateful modules.",
    )
    ap.add_argument("--rtl-dir", required=True,
                    help="Directory of .v / .sv files to scan recursively")
    ap.add_argument("--json", default=None,
                    help="Optional path for JSON report output")
    args = ap.parse_args(argv)

    rtl_dir = Path(args.rtl_dir)
    if not rtl_dir.is_dir():
        print(f"ERROR: not a directory: {rtl_dir}", file=sys.stderr)
        return 2

    findings = audit(rtl_dir)
    report = _build_report(findings, rtl_dir)
    out = json.dumps(report, indent=2, ensure_ascii=False)

    if args.json:
        Path(args.json).parent.mkdir(parents=True, exist_ok=True)
        Path(args.json).write_text(out)

    print(out)
    # #492 — NOT CHECKED is not PASS. `files_scanned` counts files actually
    # read, so zero means nothing was examined and there is no evidence for any
    # verdict. Returning 0 here would certify a check that looked at nothing —
    # the exact shape this gate's own umbrella exists to make visible, and the
    # one the conversion in flow_compliance_check would otherwise have created:
    # a project whose RTL is symlinked in with the target missing still
    # satisfies the umbrella's `any(d.glob("*.v"))` selection. rc 2 is this
    # repo's "NOT CHECKED / VACUOUS" code, matching `phase1_k5_quality_check`.
    # #492 — NOT CHECKED is not PASS. `files_scanned` counts files actually
    # read, so zero means nothing was examined and there is no evidence for any
    # verdict. Returning 0 here would certify a check that looked at nothing —
    # the exact shape this gate's own umbrella exists to make visible, and the
    # one the conversion in flow_compliance_check would otherwise have created:
    # a project whose RTL is symlinked in with the target missing still
    # satisfies the umbrella's `any(d.glob("*.v"))` selection. rc 2 is this
    # repo's "NOT CHECKED / VACUOUS" code, matching `phase1_k5_quality_check`.
    if report["summary"]["files_scanned"] == 0:
        print(f"SKIP: timer_freeze_after_state_check — no readable RTL under "
              f"{rtl_dir} ({report['summary']['files_unreadable']} unreadable); "
              f"nothing examined, no verdict", file=sys.stderr)
        return 2
    return 0 if report["summary"]["pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
