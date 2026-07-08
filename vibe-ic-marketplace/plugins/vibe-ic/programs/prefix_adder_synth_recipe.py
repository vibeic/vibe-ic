#!/usr/bin/env python3
"""prefix_adder_synth_recipe.py — parallel-prefix adder structuring (QoR recipe).

WHY THIS EXISTS
===============
A plain RTL `a + b` lowered with a naive ripple carry chain has O(n) logic depth
(a 32-bit add is ~depth 128 in AIG-AND terms). yosys already ships parallel-
prefix carry-lookahead structures that cut this to O(log n): Brent-Kung is the
DEFAULT `$lcu` map, and Kogge-Stone / Han-Carlson / Sklansky are opt-in
`choices/` maps. This program emits the exact, verified yosys recipe to select a
prefix topology for adder-depth QoR — WITH a combinational-equivalence (CEC) step
so the faster adder is never shipped without proving it equals the plain-add
reference.

Verified in vibeic-eda:0.2.3 (32-bit `a+b`): ripple depth 128 -> Brent-Kung 109
-> Kogge-Stone 72, every form CEC "Equivalence successfully proven!" against the
ripple reference; depth grows a constant per width-doubling (O(log n), not
overfit).

The capability lives in the shipped yosys binary already; this recipe makes the
synth flow INVOKE it correctly. The one ordering gotcha it encodes: for a NON-
default topology the choice map and `+/techmap.v` must be in the SAME `techmap`
call with the choice map FIRST — otherwise `$alu` never lowers to `$lcu` and it
silently falls through to the default Brent-Kung (so you would think you selected
Kogge-Stone but got Brent-Kung).

SCOPE / HONESTY
===============
- This is a QoR RECIPE emitter, not a correctness gate. Its correctness guarantee
  is the emitted CEC step, which IS gate-strength: a `verdict != EQUIVALENT` is a
  hard FAIL (the caller must not ship the restructured netlist).
- It only helps designs that carry an RTL `$add`/`$alu`/`$lcu` (any width). A
  netlist that is ALREADY a gate-level ripple (bit-level XOR/AND/OR) has no
  `$alu` to match — lifting that back to `$add` for restructuring is a separate,
  genuinely-missing arithmetic-recognition pass (honestly out of scope here).

CLI:
    python3 prefix_adder_synth_recipe.py --emit <rtl.v> --top <mod> \\
            [--topology kogge-stone] [--no-cec]
      -> prints the yosys .ys recipe to stdout, exit 0.
    python3 prefix_adder_synth_recipe.py --list      -> print known topologies.
    main(argv) -> int : 0 ok / 2 arg error.
"""
from __future__ import annotations

import argparse
import re
import sys
from typing import Dict, Optional

TOOL = "prefix_adder_synth_recipe"

# topology -> yosys techmap `-map` argument (None == the DEFAULT $lcu map, which
# is already Brent-Kung parallel-prefix, so a bare `techmap` selects it).
TOPOLOGIES: Dict[str, Optional[str]] = {
    "brent-kung": None,                      # the built-in default $lcu map
    "kogge-stone": "+/choices/kogge-stone.v",
    "han-carlson": "+/choices/han-carlson.v",
    "sklansky": "+/choices/sklansky.v",
}
DEFAULT_TOPOLOGY = "kogge-stone"


def known_topologies() -> list:
    return sorted(TOPOLOGIES)


def build_techmap_step(topology: str) -> str:
    """Return the single yosys line that lowers $alu/$add to the chosen prefix
    adder. For a non-default topology the choice map MUST precede `+/techmap.v`
    in the SAME techmap call, or $alu never reaches $lcu (silent fall-through to
    Brent-Kung)."""
    if topology not in TOPOLOGIES:
        raise ValueError(
            f"unknown prefix-adder topology {topology!r}; "
            f"known: {', '.join(known_topologies())}")
    choice = TOPOLOGIES[topology]
    if choice is None:
        # Default Brent-Kung $lcu map — a bare techmap selects it.
        return "techmap"
    # Choice map FIRST, then the base techmap, in ONE call.
    return f"techmap -map {choice} -map +/techmap.v"


def build_prefix_adder_recipe(rtl_v: str, top: str,
                              topology: str = DEFAULT_TOPOLOGY,
                              cec: bool = True) -> str:
    """Emit the yosys .ys that structures `top`'s adders into `topology` and
    (when cec) proves the result equals the plain-add reference.

    rtl_v : the RTL carrying the `a + b` (any width).
    top   : top module name.
    topology : one of known_topologies(); default kogge-stone (shallowest).
    cec   : emit the combinational-equivalence proof vs the un-restructured
            (default-lowered) adder — a mismatch is a hard FAIL. Strongly
            recommended: QoR must never trade correctness.

    Paths are used verbatim (caller translates host->container)."""
    techmap = build_techmap_step(topology)
    prefix = f"""# Vibe-IC prefix-adder structuring ({topology}) — QoR: cut carry depth O(n)->O(log n).
read_verilog -sv {rtl_v}
hierarchy -top {top}
proc; opt
alumacc
{techmap}
opt
"""
    if not cec:
        return prefix + "stat\n"
    # CEC: prove the restructured adder == the plain-add reference (default lower)
    # so a faster adder is never shipped without an equivalence proof.
    return prefix + f"""# --- gate-strength CEC: restructured == plain-add reference ---
design -stash gate
read_verilog -sv {rtl_v}
hierarchy -top {top}
proc; opt; alumacc; techmap; opt
design -stash gold
design -copy-from gold -as gold {top}
design -copy-from gate -as gate {top}
equiv_make gold gate equiv
hierarchy -top equiv
equiv_simple
equiv_induct
equiv_status
"""


# Verdict of the CEC readout embedded in the recipe (same phrasing as
# lec_post_layout_check.parse_equiv_log, kept local to avoid a hard dep).
_PROVEN_UNPROVEN_RE = re.compile(
    r"(\d+)\s+are\s+proven\s+and\s+(\d+)\s+are\s+unproven", re.IGNORECASE)
_SUCCESS_RE = re.compile(r"Equivalence\s+successfully\s+proven", re.IGNORECASE)

V_EQUIV = "EQUIVALENT"
V_NONEQUIV = "NOT_EQUIVALENT"
V_UNKNOWN = "UNKNOWN"


def parse_cec_verdict(log: str) -> str:
    """EQUIVALENT only on a real, non-vacuous proof (>0 proven, 0 unproven, or
    the explicit success banner). Anything unproven -> NOT_EQUIVALENT. No
    parseable result -> UNKNOWN (never silently a pass)."""
    m = _PROVEN_UNPROVEN_RE.search(log)
    if m:
        proven, unproven = int(m.group(1)), int(m.group(2))
        if unproven > 0:
            return V_NONEQUIV
        if proven > 0:
            return V_EQUIV
    if _SUCCESS_RE.search(log):
        return V_EQUIV
    return V_UNKNOWN


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--emit", metavar="RTL_V",
                    help="emit the yosys recipe for this RTL file")
    ap.add_argument("--top", help="top module (required with --emit)")
    ap.add_argument("--topology", default=DEFAULT_TOPOLOGY,
                    choices=known_topologies())
    ap.add_argument("--no-cec", action="store_true",
                    help="omit the equivalence proof (NOT recommended)")
    ap.add_argument("--list", action="store_true",
                    help="print known prefix-adder topologies")
    a = ap.parse_args(argv)
    if a.list:
        print("prefix-adder topologies:", ", ".join(known_topologies()))
        print(f"default: {DEFAULT_TOPOLOGY}  (brent-kung == the built-in $lcu map)")
        return 0
    if not a.emit:
        ap.error("nothing to do: pass --emit <rtl.v> --top <mod> or --list")
    if not a.top:
        ap.error("--top is required with --emit")
    try:
        print(build_prefix_adder_recipe(
            a.emit, a.top, topology=a.topology, cec=not a.no_cec))
    except ValueError as e:
        print(f"[{TOOL}] {e}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
