#!/usr/bin/env python3
r"""spec_context_sibling_detect.py — PROGRAM-FIRST context-sibling collision advisory.

GENERAL CORE (benchmark-AGNOSTIC). A CVDP completion/modify task often ships the
existing design as SEPARATE `input.context` RTL files (one module per file). The
harness may compile some of those sibling files ALONGSIDE the author's emitted
file. If the author inlines a verbatim copy of such a sibling INTO the emitted
file, that module is then declared twice → iverilog `module <X> already declared`
(exit 1/2) → every test dies at elaboration (the CVDP scrambler / elevator_control
extraction-gap: the draft inlined `intra_block` / `floor_to_seven_segment` +
`Binary2BCD` which the harness also compiled).

⚠️ WHY THIS IS AN ADVISORY, NOT A GATE STRIP (load-bearing honesty): whether a
context sibling is ACTUALLY compiled separately lives in the hidden harness
`VERILOG_SOURCES` (§4.05 off-limits). A blind auto-strip based on
`input.context` membership OVER-FIRES: 8/302 PASSING drafts legitimately inline a
context-provided submodule that the harness does NOT compile separately (it MUST
be inlined). So this module does NOT strip anything — it emits a precise
REQUIREMENT into the AI-backup hand-off telling the author to (a) emit only the
target module(s), (b) never inline a verbatim copy of a context sibling the
prompt marks 'provided/excluded/existing', and (c) use the prompt prose to decide
which siblings are provided (do not emit) vs which must be implemented.

Reads ONLY the prompt + the `input.context` file keys (both design INPUT) —
never the harness/oracle/golden (§4.05).

Usage:
    from spec_context_sibling_detect import detect_context_siblings
    r = detect_context_siblings(prompt, context_keys)     # -> dict

    python3 spec_context_sibling_detect.py --prompt @f.md --context rtl/a.sv,rtl/b.sv
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

_RTL_EXTS = (".sv", ".svh", ".v", ".vh")

# a sibling the prompt marks as PROVIDED / EXCLUDED / not-to-be-emitted. Kept
# tight (module/file-referring phrasing) so a stray "test cases are provided
# below" does NOT match.
_EXCLUDED_RE = re.compile(
    r"excluded\s+from|do\s+not\s+(?:modify|edit|change|include|redefine|re-?implement)"
    r"|(?:should|must)\s+not\s+be\s+(?:modified|changed|redefined|included)"
    r"|existing\s+(?:module|file|design|submodule)|as\s+a\s+black\s*box"
    r"|provided\s+(?:module|submodule|as\s+a\s+separate|separately|below\s+as)"
    r"|kept?\s+(?:un)?changed|left?\s+unchanged|untouched|separate\s+file"
    r"|instantiate\s+the\s+provided",
    re.IGNORECASE,
)


def _stems_from_keys(context_keys) -> List[str]:
    out: List[str] = []
    keys = context_keys.keys() if isinstance(context_keys, dict) else (context_keys or [])
    for k in keys:
        if not isinstance(k, str):
            continue
        base = k.rsplit("/", 1)[-1]
        ext = next((e for e in _RTL_EXTS if base.lower().endswith(e)), None)
        if not ext:
            continue
        stem = base[: -len(ext)]
        if stem and stem not in out:
            out.append(stem)
    return out


def detect_context_siblings(prompt: str,
                            context_keys) -> Dict[str, Any]:
    """Return the context-sibling collision advisory.

    Returns a dict::

        {
          "has_siblings": bool,           # >=2 context RTL files provided
          "sibling_modules": [str, ...],  # RTL file stems the context provides
          "prose_excluded": [str, ...],   # siblings the prompt marks provided/excluded
          "requirement": str|None,        # ready-to-inject author directive
        }
    """
    p = prompt or ""
    stems = _stems_from_keys(context_keys)
    has = len(stems) >= 2
    # Flag a sibling as excluded = the stem that is the GRAMMATICAL SUBJECT of the
    # exclusion phrase, i.e. the one whose name ENDS nearest-BEFORE the phrase
    # ("...the `intra_block` module, which should be excluded" → intra_block, NOT
    # the `inter_block` target that appears earlier in the same sentence). Picking
    # every stem in a window would wrongly flag the target as 'do not emit'.
    excluded: List[str] = []
    WIN = 80
    for m in _EXCLUDED_RE.finditer(p):
        best: Optional[str] = None
        best_gap = WIN + 1
        for s in stems:
            for sm in re.finditer(r"\b" + re.escape(s) + r"\b", p):
                gap = m.start() - sm.end()
                if 0 <= gap < best_gap:
                    best, best_gap = s, gap
        if best and best not in excluded:
            excluded.append(best)

    requirement = None
    if has:
        bits = [
            f"input.context provides {len(stems)} separate RTL modules "
            f"({', '.join(stems)}); the harness may compile some ALONGSIDE your "
            f"file. Emit ONLY the target module(s) you are asked to modify — do "
            f"NOT inline a verbatim copy of a context-provided sibling that is "
            f"compiled separately (a duplicate `module` definition triggers an "
            f"iverilog 'already declared' elaboration error, exit 1/2).",
            "Use the prompt prose to decide which siblings are provided "
            "(instantiate but do not define) vs which you must implement — a "
            "sibling described as 'excluded from the review' / 'existing' / "
            "'provided'/'kept unchanged' must NOT be redefined in your file.",
        ]
        # `prose_excluded` (below) is a HEURISTIC soft hint only — it is NOT put
        # into the imperative requirement, because reliably separating the target
        # module from the excluded sibling when both are named next to the
        # exclusion phrase is not decidable by proximity alone.
        requirement = " ".join(bits)

    return {
        "has_siblings": has,
        "sibling_modules": stems,
        "prose_excluded": excluded,
        "requirement": requirement,
    }


def main(argv: Optional[List[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--prompt", required=True, help="prompt text or @file")
    ap.add_argument("--context", default="", help="comma-list of context file paths")
    a = ap.parse_args(argv)
    prompt = a.prompt
    if prompt.startswith("@"):
        prompt = Path(prompt[1:]).read_text()
    keys = [c for c in a.context.split(",") if c]
    print(json.dumps(detect_context_siblings(prompt, keys), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
