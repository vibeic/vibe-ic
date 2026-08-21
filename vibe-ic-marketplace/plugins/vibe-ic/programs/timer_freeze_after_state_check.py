#!/usr/bin/env python3
"""timer_freeze_after_state_check.py — Static heuristic for the
"counter must freeze after state transition" RTL anti-pattern.

# What it catches

A module declares a one-shot state-bit input/wire (typical names: `awake`,
`active`, `enable`, `started`, `live`, `on`, `running`) AND has a
free-running counter (`cnt <= cnt + ...`, `count <= count + ...`,
`timer <= timer + ...`, ...). Once the state bit goes high, the counter
MUST freeze — either by gating the increment with `if (!<state>)` or by
a sibling `else if (<state>)` branch that holds the counter at zero.

If the counter increments unconditionally inside an `always` block whose
module imports a state bit, this checker FLAGs the site for review.

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


def _enclosing_block_text(
    text: str, inc_offset: int, search_back: int = 1500,
) -> str:
    """Return the text from the start of the enclosing `always` block (or
    `inc_offset - search_back`, whichever is later) up to the increment's
    statement end."""
    start = max(0, inc_offset - search_back)
    block_start_re = re.compile(r"\balways\b")
    candidates = list(block_start_re.finditer(text, start, inc_offset))
    blk_start = candidates[-1].start() if candidates else start
    return text[blk_start:inc_offset + 200]


def _counter_is_gated_by_state(
    block_text: str, state_token: str, counter_name: str,
) -> bool:
    """True only if the enclosing always block has an EXPLICIT freeze
    branch for `counter_name` keyed on `state_token`:

        else if (<state>...) ... <counter> <= <constant>;

    The branch may include intermediate begin/end + statements, but the
    counter-reset must appear within the same `else if` chain.

    Why this strict shape: v052 wake_ctrl.v had `if (!awake && cmd_op !=
    CMD_74)` in the OUTER conditional but the counter `cnt + 1` was
    inside a nested `else`, unprotected. A loose "block contains
    `!<state>`" check would have called that gated and missed the bug.
    Requiring an explicit freeze branch catches the right pattern at the
    cost of false-flagging single-line `if (!<state>) cnt <= cnt+1;`
    designs (those need to add the branch or whitelist with the
    `// timer_freeze_check: ok-unconditional` comment)."""
    # v0.119.29: also accept the freeze branch as a PRIMARY `if (state)`
    # (not just `else if (state)`). The agent on v0.119.27 vendor wrote
    # ```
    #   if (state) cnt <= '0;
    #   else cnt <= cnt + 1;
    # ```
    # which is logically equivalent to the `else if (state)` form the
    # earlier strict regex required. Both shapes correctly freeze the
    # counter in the named state.
    pat_freeze_else = (
        rf"else\s+if\s*\(\s*{state_token}\b[^)]*\)\s*"
        r"(?:begin\s*)?"
        rf"(?:[^;{{}}]*;)*?\s*\b{counter_name}\s*<=\s*[0-9'hbd_]+\s*;"
    )
    pat_freeze_primary = (
        rf"\bif\s*\(\s*{state_token}\b[^)]*\)\s*"
        r"(?:begin\s*)?"
        rf"(?:[^;{{}}]*;)*?\s*\b{counter_name}\s*<=\s*[0-9'hbd_]+\s*;"
    )
    flags = re.IGNORECASE | re.DOTALL
    if re.search(pat_freeze_else, block_text, flags):
        return True
    if re.search(pat_freeze_primary, block_text, flags):
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

                    block = _enclosing_block_text(mod_text, m.start())
                    if _counter_is_gated_by_state(block, state_tok, counter):
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
                            f"`{counter}` self-increments without an "
                            f"`if (!{state_tok})` guard or sibling "
                            f"`else if ({state_tok})` freeze branch"
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
        "version": "1.0.0",
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
