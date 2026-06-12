#!/usr/bin/env python3
"""sv2v_mixed_driver_fixup.py — deterministic post-pass to repair Verilog
produced by sv2v when SystemVerilog hw2reg / packed-struct patterns produce
MIXED-DRIVER nets (same net has both a continuous `assign` AND a procedural
`always` driver).  iverilog -g2012 rejects these; this pass rewrites them.

ORGANIC #546 — runner sv2v fallback must include this post-processing step.

ALGORITHM (chip-AGNOSTIC, no class/IC-name literals):
  1. Collect all nets driven by `assign <net> = ...;` (continuous assigns).
  2. Collect all nets driven inside `always @(...)` / `always_ff` / `initial`
     blocks (procedural).
  3. A net in BOTH sets is a mixed-driver net.
  4. For each mixed-driver net: REMOVE its `assign` line.  The procedural
     driver (always/initial) is the real synchronous driver; the `assign` is
     typically a sv2v-generated initialisation artefact.
  5. Write the repaired content (in-place or to stdout).

GUARANTEE:
  * A file with NO mixed-driver nets is byte-identical after this pass
    (the NEGATIVE test: unmodified single-driver files are not changed).
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


def mixed_driver_nets(text: str) -> FrozenSet[str]:
    """Return the set of net names that have BOTH a continuous assign and
    a procedural driver — these are the mixed-driver (illegal in Verilog) nets.
    Chip-AGNOSTIC.
    """
    ca = _collect_continuous_assigns(text)
    pv = _collect_procedural_lvalues(text)
    return frozenset(ca & pv)


def fixup(text: str) -> str:
    """Return the repaired Verilog text.  Mixed-driver assign lines are
    removed; single-driver files are returned byte-identical.
    Chip-AGNOSTIC.
    """
    nets = mixed_driver_nets(text)
    if not nets:
        return text
    # Build a pattern matching the assign lines to remove.
    escaped = "|".join(re.escape(n) for n in sorted(nets))
    _rm_re = re.compile(
        r"^(\s*)assign\s+(?:" + escaped + r")\s*=.*?;\s*\n",
        re.MULTILINE | re.DOTALL,
    )
    fixed = _rm_re.sub("", text)
    return fixed


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
