#!/usr/bin/env python3
r"""spec_named_signal_detect.py — PROGRAM-FIRST named-signal-preservation advisory.

GENERAL CORE (benchmark-AGNOSTIC). CVDP prompts introduce signals by a backtick-
quoted identifier (`` `interrupt_idx` ``, `` `parity` ``, `` `door_open_counter` ``).
A WHITE-BOX testbench then force/peeks those signals by their EXACT spec name
through the module hierarchy (`dut.interrupt_idx`). If the author renames the
signal (append `_w`/`_reg`/`_sig`), folds it into an expression, or optimizes it
away, the TB crashes with `AttributeError: <module> contains no child object
named <name>` BEFORE any functional check — this sank both `sync_serial`
(top-level `parity` net) and `interrupt_controller` (INTERNAL `interrupt_idx`
index register).

The existing verbatim-net-name lesson covers TOP-LEVEL connecting nets; this
detector extends the same discipline to ANY spec-named signal — including
INTERNAL/intermediate ones (an index / counter / state / flag) — because a
white-box TB can peek an internal register just as easily as a port. It injects
an ADVISORY hand-off requirement (never a gate/strip): preserving a spec-named
identifier verbatim is always-safe. Reads ONLY the prompt (§4.05).

Usage:
    from spec_named_signal_detect import detect_named_signals
    r = detect_named_signals(prompt)     # -> dict

    python3 spec_named_signal_detect.py --prompt @file.md   # CLI, JSON out
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# a backtick-quoted signal-like identifier: snake_case / has a digit or underscore
# (so `interrupt_idx`, `parity`, `door_open_counter`, `slv_reg0` match, while a
# backtick-quoted module name like `AXI4-Lite` or a prose word does not).
_TICK_ID_RE = re.compile(r"`([a-zA-Z][A-Za-z0-9_]*)`")
# words that are types/keywords/directives, not user signals
_NOT_A_SIGNAL = frozenset({
    "module", "endmodule", "input", "output", "inout", "wire", "reg", "logic",
    "parameter", "localparam", "always", "assign", "posedge", "negedge",
    "verilog", "systemverilog", "clk", "clock", "rst", "reset",
})


def detect_named_signals(prompt: str) -> Dict[str, Any]:
    """Return whether the prompt names signals in backticks + the preserve-verbatim
    advisory.

    Returns a dict::

        {
          "has_named_signals": bool,       # >=3 distinct backtick-named signals
          "named_signals": [str, ...],     # the identifiers (dedup, order-preserved)
          "requirement": str|None,         # ready-to-inject author directive
        }
    """
    p = prompt or ""
    seen: List[str] = []
    for m in _TICK_ID_RE.finditer(p):
        nm = m.group(1)
        if nm.lower() in _NOT_A_SIGNAL:
            continue
        # signal-ish: has an underscore/digit OR is a short lowercase identifier
        if ("_" in nm or any(c.isdigit() for c in nm) or
                (nm.islower() and 2 <= len(nm) <= 20)):
            if nm not in seen:
                seen.append(nm)

    has = len(seen) >= 3
    requirement = None
    if has:
        sample = ", ".join(seen[:12]) + ("…" if len(seen) > 12 else "")
        requirement = (
            "PRESERVE SPEC-NAMED SIGNALS VERBATIM: the prompt names signals in "
            "backticks (" + sample + "). Declare EACH one as a real named net/reg "
            "with EXACTLY that identifier — do NOT rename (no _w/_reg/_sig suffix), "
            "fold it into an expression, or optimize it away. This applies to "
            "INTERNAL/intermediate signals (index, counter, state, flag), not only "
            "ports: a white-box testbench may force/peek any of them by the exact "
            "spec name through the hierarchy, and a missing/renamed one crashes "
            "every test with a 'no child object named <name>' error before any "
            "functional check.")

    return {
        "has_named_signals": has,
        "named_signals": seen,
        "requirement": requirement,
    }


def main(argv: Optional[List[str]] = None) -> int:
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--prompt", required=True, help="prompt text or @file")
    a = ap.parse_args(argv)
    prompt = a.prompt
    if prompt.startswith("@"):
        prompt = Path(prompt[1:]).read_text()
    print(json.dumps(detect_named_signals(prompt), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
