#!/usr/bin/env python3
"""Rewrite Fault-cut netlist so escaped identifiers with embedded dots
are converted into plain alphanumeric names that iverilog hierarchical
probes can actually find.

Originally written in v052; generalised in v0.63. Behaviour is identical
but inputs/outputs are now argparse-driven and an optional --name-map
JSON records every rewrite for traceability.

Fault v0.6 emits boundary-cut names like `\\__uuf__._5339_.d ` (backslash-
prefixed, space-terminated, with an embedded dot). When Fault's TB then
references `uut.__uuf__._5339_.d` as a dotted path, iverilog treats the
escape + dot differently and the probe fails with 'Could not find
variable'.

Fix: replace every identifier of form
   \\__uuf__._NNNN_         -> UUF_NNNN
   \\__uuf__._NNNN_.d       -> UUF_NNNN_d
both in port declarations and in instance connections. Similar rules
for bare scan-register-node escapes and boundary-scan register names.
"""
import argparse
import json
import os
import re
import sys
from _atomic_artefact import writing as atomic_writing  # vibe-ic#1082 (helper from PR #1094)


def rewrite(txt, collect_map=None):
    before_uuf = txt.count("__uuf__")

    # 0) Handle bus indices inside escaped identifiers.
    txt = re.sub(r"\\?__uuf__\._(\d+)_\[(\d+)\]",
                 lambda m: f"UUF_{m.group(1)}_{m.group(2)}", txt)

    # 1) Clean __uuf__._N_.d and __uuf__._N_
    txt = re.sub(r"\\\\?__uuf__\._(\d+)_\.d\s",
                 lambda m: f"UUF_{m.group(1)}_d ", txt)
    txt = re.sub(r"\\\\?__uuf__\._(\d+)_\s",
                 lambda m: f"UUF_{m.group(1)} ", txt)
    txt = re.sub(r"\\\\?__uuf__\._(\d+)_\.d\b",
                 lambda m: f"UUF_{m.group(1)}_d", txt)
    txt = re.sub(r"\\\\?__uuf__\._(\d+)_(?![a-zA-Z0-9_.])",
                 lambda m: f"UUF_{m.group(1)}", txt)
    txt = re.sub(r"__uuf__\._(\d+)_\.d\b",
                 lambda m: f"UUF_{m.group(1)}_d", txt)
    txt = re.sub(r"__uuf__\._(\d+)_(?![a-zA-Z0-9_.])",
                 lambda m: f"UUF_{m.group(1)}", txt)

    # 0b) Same for bare `\_NNNN_[K]` (scan cells with bus indices)
    txt = re.sub(r"\\_(\d+)_\[(\d+)\]",
                 lambda m: f"SRN_{m.group(1)}_{m.group(2)}", txt)

    # 2) Clean bare escape-IDs like `\_2962_.d ` (no __uuf__ prefix)
    txt = re.sub(r"\\_(\d+)_\.d\s",
                 lambda m: f"SRN_{m.group(1)}_d ", txt)
    txt = re.sub(r"\\_(\d+)_\.d\b",
                 lambda m: f"SRN_{m.group(1)}_d", txt)

    # 3) Clean boundary-scan identifiers.
    txt = re.sub(
        r"\\__BoundaryScanRegister_(input|output)__(\d+)__([A-Za-z0-9_.]*?)\s",
        lambda m: f"BSR_{('in' if m.group(1)=='input' else 'out')}_{m.group(2)}"
                  f"{('_' + m.group(3).replace('.', '_')) if m.group(3) else ''} ",
        txt,
    )
    txt = re.sub(
        r"\\__BoundaryScanRegister_(input|output)__(\d+)__([A-Za-z0-9_.]*?)\b",
        lambda m: f"BSR_{('in' if m.group(1)=='input' else 'out')}_{m.group(2)}"
                  f"{('_' + m.group(3).replace('.', '_')) if m.group(3) else ''}",
        txt,
    )

    # 4) CATCH-ALL for escaped identifiers containing dots
    def repl_escaped_dotty(m):
        ident = m.group(1)
        ident = ident.replace(".", "_").replace("[", "_").replace("]", "")
        return ident + " "

    txt = re.sub(r"\\([A-Za-z_][A-Za-z0-9_.\[\]]*)\s", repl_escaped_dotty, txt)

    after_uuf = txt.count("__uuf__")
    return txt, before_uuf, after_uuf


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Rewrite Fault-ATPG scan-cut netlist's "
                    "`\\__uuf__._NNNN_.B` style escape identifiers to "
                    "plain alphanumeric, so iverilog hierarchical probes "
                    "work. Required for any Yosys -> Fault ATPG flow.")
    ap.add_argument("--scan-cut", required=True,
                    help="Input scan-cut Verilog netlist (Fault output)")
    ap.add_argument("--out", required=True,
                    help="Output flattened Verilog path")
    ap.add_argument("--name-map",
                    help="Optional JSON path to record counters "
                         "(before/after __uuf__, remaining backslashes)")
    args = ap.parse_args(argv)

    with open(args.scan_cut) as f:
        txt = f.read()

    out_txt, before_uuf, after_uuf = rewrite(txt)

    pat1 = r'\\_\d+_\.d'
    pat2 = r'\\__BoundaryScanRegister'
    r1 = len(re.findall(pat1, out_txt))
    r2 = len(re.findall(pat2, out_txt))
    r3 = len(re.findall(r"\\[A-Za-z_]", out_txt))
    print(f"__uuf__  : before={before_uuf}  after={after_uuf}")
    print(f"remaining backslash-SRN-d:  {r1}")
    print(f"remaining backslash-BSR:    {r2}")
    print(f"remaining backslash-id:     {r3}")

    os.makedirs(os.path.dirname(os.path.abspath(args.out)) or ".", exist_ok=True)
    with atomic_writing(args.out) as f:
        f.write(out_txt)
    print(f"wrote {args.out}")

    if args.name_map:
        os.makedirs(os.path.dirname(os.path.abspath(args.name_map)) or ".",
                    exist_ok=True)
        with open(args.name_map, "w") as f:
            json.dump({
                "__uuf___before": before_uuf,
                "__uuf___after": after_uuf,
                "remaining_backslash_srn_d": r1,
                "remaining_backslash_bsr": r2,
                "remaining_backslash_id": r3,
                "input": os.path.abspath(args.scan_cut),
                "output": os.path.abspath(args.out),
            }, f, indent=2)
        print(f"wrote {args.name_map}")

    return 0


if __name__ == "__main__":
    sys.exit(main())
