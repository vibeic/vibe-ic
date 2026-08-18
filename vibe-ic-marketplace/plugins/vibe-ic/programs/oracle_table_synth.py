#!/usr/bin/env python3
"""oracle_table_synth.py — deterministic SOLVER from a prompt-disclosed oracle.

WHY (§4.2 absorption, "let bucket-② become bucket-①"): when a VerilogEval prompt
embeds a COMPLETE combinational oracle — a truth table, a don't-care-free K-map,
or an FSM next-state-BIT over a sequential encoding — the answer is fully
determined by the prompt, blind. `kmap_truth_table_oracle_check.build_oracle`
already PARSES that oracle into an exhaustive (inputs -> bit) table for its emit
GATE. This module turns that SAME parse into a SOLVER: it EMITS the RTL that
implements the table directly (a `case` over the inputs), so the problem is
program-GENERATED (zero authoring variance) instead of AI-authored-then-gated.

The existing `kmap_grid_synth` / `waveform_truth_table_synth` solvers cover the
K-map/waveform SOP cases; this one additionally covers the truth-table and
binary-encoded FSM-next-state-bit cases the gate parses but those solvers miss
(e.g. Prob069_truthtable1, Prob135_m2014_q6b).

§4.05 NO-LEAK: returns None (SKIP — leaves the author's sample untouched) whenever
the oracle is not unambiguously complete, inheriting build_oracle's conservative
envelope verbatim. A fired synth is exhaustively faithful to the parsed table;
DON'T-CARE input combinations absent from the table fall through to `default`.

API: synth(prompt_text, top="TopModule") -> RTL string | None
"""
from __future__ import annotations
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import kmap_truth_table_oracle_check as _O  # noqa: E402


def _normalize_in_specs(in_field):
    return [(x, 1) if isinstance(x, str) else tuple(x) for x in in_field]


def synth(prompt_text: str, top: str = "TopModule"):
    oracle = _O.build_oracle(prompt_text)
    if not oracle:
        return None
    _kind, in_field, out_name, table = oracle
    in_specs = _normalize_in_specs(in_field)
    if not in_specs or not table:
        return None
    total_w = sum(w for _, w in in_specs)
    decls = []
    for nm, w in in_specs:
        decls.append(f"input [{w-1}:0] {nm}" if w > 1 else f"input {nm}")
    decls.append(f"output reg {out_name}")
    cat = "{" + ", ".join(nm for nm, _ in in_specs) + "}"
    lines = [
        f"// program-SOLVED from the prompt's own oracle ({_kind}); deterministic, no AI.",
        f"module {top}(",
        "    " + ",\n    ".join(decls),
        ");",
        "    always @(*) begin",
        f"        {out_name} = 1'b0;",
        f"        case ({cat})",
    ]
    for key in sorted(table):
        bits = "".join(format(val, f"0{w}b") for (_, w), val in zip(in_specs, key))
        lines.append(f"            {total_w}'b{bits}: {out_name} = 1'b{table[key]};")
    lines += [
        f"            default: {out_name} = 1'b0;",
        "        endcase",
        "    end",
        "endmodule",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--prompt", required=True)
    ap.add_argument("--top", default="TopModule")
    a = ap.parse_args()
    rtl = synth(Path(a.prompt).read_text(errors="replace"), a.top)
    if rtl is None:
        print("SKIP: no complete prompt-disclosed oracle", file=sys.stderr)
        sys.exit(1)
    print(rtl)
