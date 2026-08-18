#!/usr/bin/env python3
"""deterministic_rtl_dispatcher.py — Phase-2 program-first RTL router.

since v0.1.9.

The "program-first, Claude-as-backup" entry point for Phase 2. Given ONE
structured design spec, it auto-detects whether the design falls into a
mechanically-derivable class and, if so, routes to the matching DETERMINISTIC
generator — emitting correct RTL with no LLM. If no deterministic generator
applies, it returns a clear `fall-back-to-LLM` verdict so the caller knows the
body-synthesis genuinely needs the reasoning engine.

This wires the VerilogEval-driven generator family into one automatic path:
  - `gates`        present → gate_netlist_rtl_gen   (logic-gate netlist)
  - `transitions`  present → fsm_table_rtl_gen      (FSM state table; needs `kind`)
  - `rows`         present → truth_table_rtl_gen    (truth table / K-map)
  - `op` ∈ {reverse,split,concat,sign_extend,zero_extend} → vector_op_rtl_gen
  - else                  → NO deterministic generator → fall back to LLM.
A spec may force a class with `"generator": "<name>"`.

chip-AGNOSTIC. Deterministic: same spec → same route → byte-identical RTL.

CLI:
    python3 deterministic_rtl_dispatcher.py <spec.json|spec.yaml> [-o out.sv] [--explain]

Exit codes:
    0 = deterministic RTL generated     2 = file/parse error
    1 = a matched generator rejected the spec (invalid)
    3 = no deterministic generator applies → caller should use LLM generation
"""
from __future__ import annotations
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from fsm_table_rtl_gen import generate as _fsm_gen           # noqa: E402
from truth_table_rtl_gen import generate as _tt_gen          # noqa: E402
from gate_netlist_rtl_gen import generate as _gate_gen       # noqa: E402
from vector_op_rtl_gen import generate as _vec_gen           # noqa: E402

_VECTOR_OPS = {"reverse", "split", "concat", "sign_extend", "zero_extend"}

# name → (generate fn, human label)
_GENERATORS = {
    "gate_netlist": (_gate_gen, "gate-netlist"),
    "fsm_table": (_fsm_gen, "FSM-table"),
    "truth_table": (_tt_gen, "truth-table"),
    "vector_op": (_vec_gen, "vector-op"),
}


def classify(spec: dict) -> str | None:
    """Return the generator name for `spec`, or None if no deterministic
    generator applies (→ LLM fallback). Detection is by spec SHAPE, with a
    fixed precedence so a route is never ambiguous."""
    forced = spec.get("generator")
    if forced:
        if forced not in _GENERATORS:
            raise ValueError(f"unknown forced generator '{forced}'")
        return forced
    if "gates" in spec:
        return "gate_netlist"
    if "transitions" in spec:
        return "fsm_table"
    if "rows" in spec:
        return "truth_table"
    if str(spec.get("op", "")).lower() in _VECTOR_OPS:
        return "vector_op"
    return None


def dispatch(spec: dict) -> tuple[str | None, str]:
    """Return (generator_name_or_None, rtl_or_empty)."""
    name = classify(spec)
    if name is None:
        return None, ""
    gen, _ = _GENERATORS[name]
    return name, gen(spec)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("spec")
    ap.add_argument("-o", "--out")
    ap.add_argument("--explain", action="store_true",
                    help="report the detected class only; do not generate")
    a = ap.parse_args()
    p = Path(a.spec)
    if not p.is_file():
        print(f"deterministic_rtl_dispatcher: spec not found: {p}", file=sys.stderr)
        return 2
    try:
        text = p.read_text()
        spec = (__import__("yaml").safe_load(text)
                if p.suffix.lower() in (".yaml", ".yml") else json.loads(text))
        if not isinstance(spec, dict):
            raise ValueError("spec must be a mapping")
        name = classify(spec)
    except (ValueError, KeyError) as e:
        print(f"deterministic_rtl_dispatcher: invalid spec: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        print(f"deterministic_rtl_dispatcher: {e}", file=sys.stderr)
        return 2

    if name is None:
        print("deterministic_rtl_dispatcher: NO deterministic generator applies "
              "for this spec — fall back to LLM generation.", file=sys.stderr)
        return 3

    label = _GENERATORS[name][1]
    if a.explain:
        print(f"deterministic_rtl_dispatcher: route → {name} ({label})")
        return 0
    try:
        rtl = dispatch(spec)[1]
    except (ValueError, KeyError) as e:
        print(f"deterministic_rtl_dispatcher: {name} rejected spec: {e}", file=sys.stderr)
        return 1

    if a.out:
        Path(a.out).write_text(rtl)
        print(f"deterministic_rtl_dispatcher: {label} → wrote {a.out} "
              f"({rtl.count(chr(10))} lines)")
    else:
        sys.stdout.write(rtl)
        sys.stderr.write(f"deterministic_rtl_dispatcher: route → {name} ({label})\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
