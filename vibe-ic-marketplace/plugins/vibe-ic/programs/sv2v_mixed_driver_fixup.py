#!/usr/bin/env python3
"""sv2v_mixed_driver_fixup.py — deterministic post-pass to repair Verilog
produced by sv2v when SystemVerilog hw2reg / packed-struct patterns produce
MIXED-DRIVER nets (same net has both a continuous `assign` AND a procedural
`always` driver).  iverilog -g2012 rejects these; this pass rewrites them.

ORGANIC #546 — runner sv2v fallback must include this post-processing step.

ALGORITHM (chip-AGNOSTIC, no class/IC-name literals):
  0. Partition the flattened file into per-module scopes (`module`/`macromodule`
     … `endmodule`, nesting-aware, comment/string-safe).  ALL detection and
     removal below is done INDEPENDENTLY within each module scope.
  1. Collect all nets driven by `assign <net> = ...;` (continuous assigns)
     WITHIN a module.
  2. Collect all nets driven inside `always @(...)` / `always_ff` / `initial`
     blocks (procedural) WITHIN the SAME module.
  3. A net in BOTH sets IN THE SAME MODULE is a mixed-driver net.
  4. For each mixed-driver net: REMOVE its `assign` line — but ONLY inside the
     module that has the conflict.  The procedural driver (always/initial) is
     the real synchronous driver; the `assign` is typically a sv2v-generated
     initialisation artefact.
  5. Write the repaired content (in-place or to stdout).

WHY MODULE SCOPING IS MANDATORY (#200):
  sv2v emits every module into ONE flattened file.  A port name that is
  `output reg` (procedural) in module A and `assign`-driven in a DIFFERENT
  module B is TWO different nets — B's continuous assign is its ONLY, legal
  driver.  A file-wide intersection cross-matches them and deletes B's
  legitimate driver (this silently broke ibex: instr_req_o / data_req_o lost
  their only driver).  Cross-module same-name nets are NEVER cross-matched.

GUARANTEE:
  * A file with NO mixed-driver nets is byte-identical after this pass
    (the NEGATIVE test: unmodified single-driver files are not changed).
  * A net driven both ways only across DIFFERENT modules is left untouched;
    only a genuine same-module mixed driver has its `assign` removed.
  * Only full-line `assign <net> = ...;` statements are removed.  Multi-line
    assigns, `assign {a, b} = ...`, or `assign` inside always blocks are
    NOT touched (regex is anchored + requires the net name to be a plain
    identifier, not a concatenation).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path
from typing import FrozenSet, List, Optional, Set

# Match a standalone assign statement covering the entire line:
#   assign  <net_name>  = ... ;
# Captures the net name (group 1).  Intentionally does NOT match
#   assign {a,b} = ...   (concatenation lhs)
#   assign a.b = ...     (hierarchical)
#   assign a[7:0] = ...  (slice — leave alone)
_ASSIGN_RE = re.compile(
    r"^(\s*)assign\s+([A-Za-z_][A-Za-z0-9_]*)\s*=",
    re.MULTILINE,
)

# Match a procedural (always/initial) block: capture every net that appears
# as an lvalue inside `<net> =` or `<net> <=` assignments.
# We scan the block for `<ident> =` or `<ident> <=` patterns.
_PROC_BLOCK_RE = re.compile(
    r"always\b[^;]*?begin\b(.*?)end\b",
    re.DOTALL | re.IGNORECASE,
)
_INITIAL_BLOCK_RE = re.compile(
    r"initial\b[^;]*?begin\b(.*?)end\b",
    re.DOTALL | re.IGNORECASE,
)
_PROC_LV_RE = re.compile(
    r"\b([A-Za-z_][A-Za-z0-9_]*)\s*(?:<=|=)\s",
    re.MULTILINE,
)

# ORGANIC #575 — begin-less single-statement always/initial bodies
# (`always @(posedge clk) if (we) q <= d;`) carry procedural drivers too.
_PROC_KW_RE = re.compile(
    r"\b(?:always(?:_ff|_comb|_latch)?|initial)\b",
    re.IGNORECASE,
)


def _word_at(text: str, i: int, word: str) -> bool:
    """True when `word` starts at offset i as a whole identifier token."""
    end = i + len(word)
    if not text.startswith(word, i):
        return False
    return end >= len(text) or not (text[end].isalnum() or text[end] == "_")


def _beginless_proc_bodies(text: str) -> List[str]:
    """Yield the single-statement bodies of begin-less always/initial blocks.

    After the keyword and its optional event control `@(...)` / `@*`, if the
    next token is NOT `begin`, the body is one statement: capture up to its
    terminating `;`, extending across `else` continuations so the else-branch
    lvalue of `if (c) a <= x; else a <= y;` is harvested as well.
    """
    bodies: List[str] = []
    n = len(text)
    for m in _PROC_KW_RE.finditer(text):
        i = m.end()
        while i < n and text[i].isspace():
            i += 1
        if i < n and text[i] == "@":
            i += 1
            while i < n and text[i].isspace():
                i += 1
            if i < n and text[i] == "(":
                depth = 1
                i += 1
                while i < n and depth:
                    if text[i] == "(":
                        depth += 1
                    elif text[i] == ")":
                        depth -= 1
                    i += 1
            elif i < n and text[i] == "*":
                i += 1
        while i < n and text[i].isspace():
            i += 1
        if i >= n or _word_at(text, i, "begin"):
            continue  # block-shaped: handled by the begin/end regexes
        start = i
        while True:
            semi = text.find(";", i)
            if semi == -1:
                i = n
                break
            i = semi + 1
            j = i
            while j < n and text[j].isspace():
                j += 1
            if _word_at(text, j, "else"):
                i = j + 4
                continue
            break
        bodies.append(text[start:i])
    return bodies


def _collect_continuous_assigns(text: str) -> Set[str]:
    return {m.group(2) for m in _ASSIGN_RE.finditer(text)}


def _collect_procedural_lvalues(text: str) -> Set[str]:
    lvalues: Set[str] = set()
    for m in _PROC_BLOCK_RE.finditer(text):
        body = m.group(1)
        lvalues.update(v.group(1) for v in _PROC_LV_RE.finditer(body))
    for m in _INITIAL_BLOCK_RE.finditer(text):
        body = m.group(1)
        lvalues.update(v.group(1) for v in _PROC_LV_RE.finditer(body))
    for body in _beginless_proc_bodies(text):
        lvalues.update(v.group(1) for v in _PROC_LV_RE.finditer(body))
    return lvalues


# ──────────────────────────────────────────────────────────────────────
# #200 — module-scope partitioning
# ──────────────────────────────────────────────────────────────────────
# A "segment" is a maximal run of characters belonging to the same innermost
# module scope.  scope_id is an int identifying a module instance, or None for
# text outside any module (between modules, `define`s, etc.).  The concatenation
# of every segment's slice reconstructs the file byte-for-byte, so untouched
# scopes (and all out-of-module text) are preserved exactly.
_MOD_START_KW = frozenset({"module", "macromodule"})
_MOD_END_KW = "endmodule"


def _module_segments(text: str):
    """Partition `text` into (scope_id, start, end) segments where scope_id is
    the innermost enclosing module (None = outside any module).  Comment- and
    string-safe so `module`/`endmodule` inside `//`, `/* */`, or "..." are not
    mistaken for real boundaries.  Nesting-aware (SV nested modules degrade to
    correct innermost attribution; sv2v output is flat, which is the exact
    top-level-per-module case)."""
    n = len(text)
    events = []  # (pos, kind, kw_end)  kind in {"start", "end"}
    i = 0
    while i < n:
        c = text[i]
        # line comment
        if c == "/" and i + 1 < n and text[i + 1] == "/":
            j = text.find("\n", i + 2)
            i = n if j == -1 else j
            continue
        # block comment
        if c == "/" and i + 1 < n and text[i + 1] == "*":
            j = text.find("*/", i + 2)
            i = n if j == -1 else j + 2
            continue
        # string literal
        if c == '"':
            i += 1
            while i < n:
                if text[i] == "\\":
                    i += 2
                    continue
                if text[i] == '"':
                    i += 1
                    break
                i += 1
            continue
        # identifier / keyword — the preceding char is guaranteed a
        # non-identifier here, so this is a whole-word left boundary.
        if c.isalpha() or c == "_":
            k = i + 1
            while k < n and (text[k].isalnum() or text[k] == "_"):
                k += 1
            word = text[i:k]
            if word == _MOD_END_KW:
                events.append((i, "end", k))
            elif word in _MOD_START_KW:
                events.append((i, "start", k))
            i = k
            continue
        i += 1

    segments = []
    cursor = 0
    stack = [None]  # innermost scope; None = outside any module
    next_id = 1
    for pos, kind, kw_end in events:
        if kind == "start":
            if pos > cursor:
                segments.append((stack[-1], cursor, pos))
            stack.append(next_id)
            next_id += 1
            cursor = pos  # the `module` keyword belongs to the new scope
        else:  # end — the `endmodule` keyword belongs to the closing scope
            if kw_end > cursor:
                segments.append((stack[-1], cursor, kw_end))
            if len(stack) > 1:
                stack.pop()
            cursor = kw_end
    if cursor < n:
        segments.append((stack[-1], cursor, n))
    return segments


def _scope_texts(text: str):
    """Return {scope_id: [segment_text, ...]} for every real module scope."""
    by_scope = {}
    for sid, a, b in _module_segments(text):
        if sid is None:
            continue
        by_scope.setdefault(sid, []).append(text[a:b])
    return by_scope


def _scope_mixed_nets(seg_texts) -> Set[str]:
    """Mixed-driver nets within ONE module scope: nets driven both by a
    continuous assign AND procedurally, both inside the same module."""
    ca: Set[str] = set()
    pv: Set[str] = set()
    for s in seg_texts:
        ca |= _collect_continuous_assigns(s)
        pv |= _collect_procedural_lvalues(s)
    return ca & pv


def mixed_driver_nets(text: str) -> FrozenSet[str]:
    """Return the set of net names that have BOTH a continuous assign and a
    procedural driver INSIDE THE SAME MODULE — these are the mixed-driver
    (illegal in Verilog) nets.  A same-named net that is assign-driven in one
    module and procedurally-driven in a DIFFERENT module is NOT mixed and is
    never reported.  Chip-AGNOSTIC.
    """
    result: Set[str] = set()
    for texts in _scope_texts(text).values():
        result |= _scope_mixed_nets(texts)
    return frozenset(result)


def _remove_assigns(seg_text: str, nets: Set[str]) -> str:
    """Remove full-line `assign <net> = ...;` statements for `nets` from a
    single scope segment.  Conservative: only plain-identifier lvalue assigns.

    The statement terminator tolerates a trailing line comment
    (`assign x = 0;  // note`).  Without that, the non-greedy `.*?;` under
    DOTALL would treat the comment as "no newline yet" and keep extending
    across newlines to the NEXT `;`, swallowing subsequent legitimate
    statements — another way this pass could delete valid code."""
    if not nets:
        return seg_text
    escaped = "|".join(re.escape(n) for n in sorted(nets))
    _rm_re = re.compile(
        r"^(\s*)assign\s+(?:" + escaped + r")\s*="
        r".*?;[^\S\n]*(?://[^\n]*)?\r?\n",
        re.MULTILINE | re.DOTALL,
    )
    return _rm_re.sub("", seg_text)


def fixup(text: str) -> str:
    """Return the repaired Verilog text.  Mixed-driver assign lines are removed
    PER MODULE SCOPE; single-driver files are returned byte-identical.  A net
    driven both ways only across DIFFERENT modules is left untouched — only a
    genuine same-module conflict has its `assign` removed.  Chip-AGNOSTIC.
    """
    segments = _module_segments(text)
    # Compute the mixed-driver set for each module scope independently.
    by_scope = {}
    for sid, a, b in segments:
        if sid is None:
            continue
        by_scope.setdefault(sid, []).append(text[a:b])
    scope_nets = {sid: _scope_mixed_nets(t) for sid, t in by_scope.items()}
    if not any(scope_nets.values()):
        return text  # byte-identical guarantee for clean files
    out: List[str] = []
    for sid, a, b in segments:
        seg = text[a:b]
        nets = scope_nets.get(sid) if sid is not None else None
        if nets:
            seg = _remove_assigns(seg, nets)
        out.append(seg)
    return "".join(out)


def fixup_file(path: Path) -> bool:
    """Apply fixup() to `path` in-place.  Returns True if the file was
    modified, False if it was already clean (no mixed drivers)."""
    original = path.read_text(errors="replace")
    repaired = fixup(original)
    if repaired == original:
        return False
    path.write_text(repaired)
    return True


# ──────────────────────────────────────────────────────────────────────
# CLI entry-point
# ──────────────────────────────────────────────────────────────────────
def main(argv: Optional[List[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(
        description="Repair sv2v mixed-driver assigns (#546)")
    ap.add_argument("files", nargs="+", metavar="FILE",
                    help="Verilog files to fix in-place")
    ap.add_argument("--dry-run", action="store_true",
                    help="Print nets that would be removed, don't write")
    args = ap.parse_args(argv)
    rc = 0
    for f_str in args.files:
        p = Path(f_str)
        if not p.is_file():
            print(f"ERROR: {p}: not found", file=sys.stderr)
            rc = 1
            continue
        text = p.read_text(errors="replace")
        nets = mixed_driver_nets(text)
        if nets:
            if args.dry_run:
                print(f"{p}: mixed-driver nets: {sorted(nets)}")
            else:
                p.write_text(fixup(text))
                print(f"{p}: removed {len(nets)} mixed-driver assign(s): "
                      f"{sorted(nets)[:5]}"
                      f"{'...' if len(nets) > 5 else ''}")
    return rc


if __name__ == "__main__":
    sys.exit(main())
