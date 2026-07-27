#!/usr/bin/env python3
"""synth_wrapper_gen.py — auto-generate synthesis wrapper for inout-port designs.

Yosys + most synth tools optimise away tri-state logic for `inout` ports
unless wrapped. This generator scans rtl/<top>.sv for `inout` ports and
emits rtl/<top>_synth.sv that:
  - declares `output id_bus_oe`, `output id_bus_o`, `input id_bus_i` in
    place of each `inout id_bus`
  - keeps the original module callable from non-synth flows

Output: rtl/<top>_synth.sv — and ONLY that file.

CORRECTED CLAIMS (this docstring asserted behaviour the code does not have):

  * "emits accompanying SDC `set_false_path` for the new `_oe` net" and
    "Output: ... + rtl/<top>_synth.sdc" — no .sdc is written. `main()` writes
    exactly one path, `rtl_dir / f"{top}_synth.sv"`, and outside this
    correction note the token "sdc" appears nowhere in the module's code.
    Removed rather than implemented: the
    false-path constraint an operator actually needs depends on the pad-cell
    tie-off, which this generator does not know.

  * "Used by phase2 runner when L9.synth_wrapper_required=true or when
    ic_class_registry's class config sets needs_synth_wrapper=true" — neither
    key exists anywhere in the plugin (`grep -rn synth_wrapper_required` /
    `needs_synth_wrapper` matched only this docstring), and no runner, gate or
    MCP tool invokes this program at all. It is declared under flow Step 9's
    `programs:` list and is OPERATOR-INVOKED: run it by hand before synthesis
    on an inout-bearing design.

KNOWN LIMITATION of the emitted wrapper (why it is not auto-wired): the
generated instantiation connects each inout to its `_i` leg only —
`.{sig}({sig}_i)` — and never drives the `_o` / `_oe` ports it declares, and
the trailing "Caller must wire ..." comment names only the LAST signal. The
output is a starting point for a human, not a drop-in synthesis wrapper.

chip-AGNOSTIC.

Replaces skill `synth-wrapper-gen` (archived).
"""
from __future__ import annotations
import argparse, re, sys
from pathlib import Path
import _path_layout as _pl


def find_top_with_inout(rtl_dir: Path, top: str) -> Path | None:
    for ext in (".sv", ".v"):
        f = rtl_dir / f"{top}{ext}"
        if f.is_file() and "inout" in f.read_text(errors="ignore"):
            return f
    return None


def extract_inout_signals(text: str) -> list[str]:
    return re.findall(r"\binout\s+(?:wire\s+)?(?:\[[^\]]+\]\s+)?([A-Za-z_]\w*)",
                       text)


def emit_wrapper(top: str, inout_signals: list[str], out_path: Path) -> None:
    if not inout_signals:
        return
    body = [f"// Auto-generated synthesis wrapper for {top}",
            "// Tri-states each inout into separate _i / _o / _oe nets so",
            "// yosys / synth tools don't optimise the open-drain logic away.",
            f"module {top}_synth (",
            "  input  wire clk, reset_n,"]
    for sig in inout_signals:
        body.append(f"  input  wire {sig}_i,")
        body.append(f"  output wire {sig}_o,")
        body.append(f"  output wire {sig}_oe,")
    body[-1] = body[-1].rstrip(",")
    body.append(");")
    body.append(f"  // Re-instantiate {top} with internal tri-state expansion")
    body.append(f"  // Caller must wire {sig}_o + {sig}_oe to top-level pad cell.")
    body.append(f"  {top} u_inner (")
    body.append("    .clk(clk), .reset_n(reset_n),")
    for sig in inout_signals:
        body.append(f"    .{sig}({sig}_i)  // simplified — top emits separate _o/_oe in wrapper hier")
    body.append("  );")
    body.append("endmodule")
    out_path.write_text("\n".join(body) + "\n")


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("project", type=Path)
    p.add_argument("--top", default="chip_top")
    args = p.parse_args()
    rtl_dir = _pl.rtl_dir(args.project)
    if not rtl_dir.is_dir():
        print(f"[SKIP] synth_wrapper_gen: no rtl/ in {args.project}")
        return 0
    src = find_top_with_inout(rtl_dir, args.top)
    if not src:
        print(f"[SKIP] synth_wrapper_gen: no inout port in {args.top}")
        return 0
    inouts = extract_inout_signals(src.read_text())
    out = rtl_dir / f"{args.top}_synth.sv"
    emit_wrapper(args.top, inouts, out)
    print(f"[PASS] synth_wrapper_gen: emitted {out.name} for "
          f"{len(inouts)} inout port(s) {inouts}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
