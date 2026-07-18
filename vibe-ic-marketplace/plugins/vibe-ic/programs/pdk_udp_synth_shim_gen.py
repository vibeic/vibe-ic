#!/usr/bin/env python3
"""pdk_udp_synth_shim_gen.py — v1.6.218 (ORGANIC-20260512-followup).

Convert a foundry std-cell behavioural-Verilog library into a
synthesisable shim by:
  1. Replacing each `primitive udp_NAME ... endprimitive` with a
     `module udp_NAME ... endmodule` whose body implements the same
     truth table in pure synthesisable Verilog.
  2. Stripping every `specify ... endspecify` block (timing-only).
  3. Inserting `assign d<X> = <X>;` continuous assigns for the
     `wire d<X>` signals that the cell uses (these were previously
     only driven via `$setuphold(..., d<X>, <X>)` inside specify
     and are otherwise undriven — root cause of "Q stays X" in
     iverilog and "Stuck at GND" in Quartus).
  4. Stripping `reg NOTIFIER;` declarations + tying `NOTIFIER` ports
     low at every UDP instantiation.

Output: a synth-equivalent .v file that:
  - keeps all cell-port names IDENTICAL to the source (so the
    gate-level netlist instantiates them unchanged)
  - synthesises cleanly under Quartus 23.1+ and Yosys 0.34+
  - simulates correctly under iverilog (no specify timing issues)

Use case: FPGA-reverify of post-PnR gate-level netlist when the
foundry library is HSPICE/Spectre/ELDO-targeted (e.g. a commercial
180nm foundry library). The original specify-heavy library is fine for
SPICE / formal LEC against gate netlist + .lib timing, but useless
for FPGA emulation of the gate-level chip.

chip-AGNOSTIC; works on any foundry library that uses the standard
Verilog UDP idiom.
"""
from __future__ import annotations
import argparse, re, sys
from pathlib import Path

# ─────────────────── UDP truth-table → synthesisable Verilog ───────────────────

UDP_SYNTH = {
  # name : (ports, body)
  "udp_dff": ('''module udp_dff (out, in, clk, clr_, set_, NOTIFIER);
  output out;
  input  in, clk, clr_, set_, NOTIFIER;
  reg    out;
  always @(posedge clk or negedge clr_ or negedge set_)
    if (!set_)      out <= 1'b1;
    else if (!clr_) out <= 1'b0;
    else            out <= in;
endmodule'''),

  "udp_edff": ('''module udp_edff (out, in, clk, clr_, set_, en, NOTIFIER);
  output out;
  input  in, clk, clr_, set_, en, NOTIFIER;
  reg    out;
  always @(posedge clk or negedge clr_ or negedge set_)
    if (!set_)      out <= 1'b1;
    else if (!clr_) out <= 1'b0;
    else if (en)    out <= in;
endmodule'''),

  "udp_edfft": ('''module udp_edfft (out, in, clk, clr_, set_, en, NOTIFIER);
  output out;
  input  in, clk, clr_, set_, en, NOTIFIER;
  reg    out;
  always @(posedge clk or negedge clr_ or negedge set_)
    if (!set_)      out <= 1'b1;
    else if (!clr_) out <= 1'b0;
    else if (en)    out <= in;
endmodule'''),

  "udp_jkff": ('''module udp_jkff (out, j, k, clk, clr_, set_, NOTIFIER);
  output out;
  input  j, k, clk, clr_, set_, NOTIFIER;
  reg    out;
  always @(posedge clk or negedge clr_ or negedge set_)
    if (!set_)             out <= 1'b1;
    else if (!clr_)        out <= 1'b0;
    else if ( j &&  k)     out <= ~out;
    else if ( j && ~k)     out <= 1'b1;
    else if (~j &&  k)     out <= 1'b0;
endmodule'''),

  "udp_mux2": ('''module udp_mux2 (out, in0, in1, sel);
  output out;
  input  in0, in1, sel;
  assign out = sel ? in1 : in0;
endmodule'''),

  "udp_mux4": ('''module udp_mux4 (out, in0, in1, in2, in3, sel_0, sel_1);
  output out;
  input  in0, in1, in2, in3, sel_0, sel_1;
  assign out = sel_1 ? (sel_0 ? in3 : in2)
                     : (sel_0 ? in1 : in0);
endmodule'''),

  # 1-bit data, scalar select: select asserts in0 vs in1 vs hold.
  # Conservative: if s_sel=0 → out=in, else out=s_in (latch-passthrough).
  "udp_mux": ('''module udp_mux (out, in, s_in, s_sel);
  output out;
  input  in, s_in, s_sel;
  assign out = s_sel ? s_in : in;
endmodule'''),

  # udp_bmx: 5-input mux with two-of-three encoding
  # primitive udp_bmx (out, x2, a, s, m1, m0)
  # used inside MUX cells to select between paths; treat as
  # priority encoder: x2 dominates, then s-controlled a/m1/m0.
  "udp_bmx": ('''module udp_bmx (out, x2, a, s, m1, m0);
  output out;
  input  x2, a, s, m1, m0;
  assign out = s ? (m1 ? a : m0) : x2;
endmodule'''),

  # udp_outrf: read-write tristate output cell
  # primitive udp_outrf (out, in, rwn, rw); when rw=1 drive in, else hi-Z
  "udp_outrf": ('''module udp_outrf (out, in, rwn, rw);
  output out;
  input  in, rwn, rw;
  assign out = rw ? in : 1'bz;
endmodule'''),

  # SR latches: active-high reset/set with NOTIFIER ignored.
  "udp_rslat_out": ('''module udp_rslat_out (out, r, s, NOTIFIER);
  output out;
  input  r, s, NOTIFIER;
  reg    out;
  always @(*)
    if (r)        out <= 1'b0;
    else if (s)   out <= 1'b1;
endmodule'''),

  "udp_rslat_out_": ('''module udp_rslat_out_ (out_, r, s, NOTIFIER);
  output out_;
  input  r, s, NOTIFIER;
  reg    out_;
  always @(*)
    if (r)        out_ <= 1'b1;
    else if (s)   out_ <= 1'b0;
endmodule'''),

  # Active-low SR latches.
  "udp_rslatn_out": ('''module udp_rslatn_out (out, r_, s_, NOTIFIER);
  output out;
  input  r_, s_, NOTIFIER;
  reg    out;
  always @(*)
    if (!r_)        out <= 1'b0;
    else if (!s_)   out <= 1'b1;
endmodule'''),

  "udp_rslatn_out_": ('''module udp_rslatn_out_ (out_, r_, s_, NOTIFIER);
  output out_;
  input  r_, s_, NOTIFIER;
  reg    out_;
  always @(*)
    if (!r_)        out_ <= 1'b1;
    else if (!s_)   out_ <= 1'b0;
endmodule'''),

  # Scan-enabled DFF (DFT). se=1 → in=si (scan-in path); se=0 → in=in (functional)
  # en=enable; clr_=active-low async reset.
  "udp_sedff": ('''module udp_sedff (out, in, clk, clr_, si, se, en, NOTIFIER);
  output out;
  input  in, clk, clr_, si, se, en, NOTIFIER;
  reg    out;
  always @(posedge clk or negedge clr_)
    if (!clr_)      out <= 1'b0;
    else if (en)    out <= se ? si : in;
endmodule'''),

  # Scan DFF with async set AND reset.
  "udp_sedffsr": ('''module udp_sedffsr (out, in, clk, clr_, set_, si, se, en, NOTIFIER);
  output out;
  input  in, clk, clr_, set_, si, se, en, NOTIFIER;
  reg    out;
  always @(posedge clk or negedge clr_ or negedge set_)
    if (!set_)      out <= 1'b1;
    else if (!clr_) out <= 1'b0;
    else if (en)    out <= se ? si : in;
endmodule'''),

  # Test scan DFF (same semantics as udp_sedff in synth).
  "udp_sedfft": ('''module udp_sedfft (out, in, clk, clr_, si, se, en, NOTIFIER);
  output out;
  input  in, clk, clr_, si, se, en, NOTIFIER;
  reg    out;
  always @(posedge clk or negedge clr_)
    if (!clr_)      out <= 1'b0;
    else if (en)    out <= se ? si : in;
endmodule'''),

  # Transparent latch (hold=0 → passthrough; hold=1 → freeze)
  "udp_tlat": ('''module udp_tlat (out, in, hold, clr_, set_, NOTIFIER);
  output out;
  input  in, hold, clr_, set_, NOTIFIER;
  reg    out;
  always @(*)
    if (!set_)      out <= 1'b1;
    else if (!clr_) out <= 1'b0;
    else if (!hold) out <= in;
endmodule'''),

  # tlatrf: gated-latch with read-write enables ww (write) + wwn (write enable n)
  "udp_tlatrf": ('''module udp_tlatrf (out, in, ww, wwn, NOTIFIER);
  output out;
  input  in, ww, wwn, NOTIFIER;
  reg    out;
  always @(*)
    if (ww && !wwn) out <= in;
endmodule'''),

  # tlatrf2: dual-write latch (two write ports, second wins)
  "udp_tlatrf2": ('''module udp_tlatrf2 (out, in1, w1w, in2, w2w, NOTIFIER);
  output out;
  input  in1, w1w, in2, w2w, NOTIFIER;
  reg    out;
  always @(*)
    if (w2w) out <= in2;
    else if (w1w) out <= in1;
endmodule'''),

  # xgen: tristate gate (en=1 drive in, else hi-Z when e=1)
  "udp_xgen": ('''module udp_xgen (out, in, en, e);
  output out;
  input  in, en, e;
  assign out = en ? in : (e ? 1'bz : 1'b0);
endmodule'''),
}

# ─────────────────── Transform stages ───────────────────

_PRIM_RE = re.compile(
    r"^[ \t]*primitive\s+(udp_\w+)\s*\([^)]*\)\s*;.*?^endprimitive[^\n]*\n",
    re.MULTILINE | re.DOTALL)
_SPECIFY_RE = re.compile(r"^[ \t]*specify\b.*?^[ \t]*endspecify[^\n]*\n",
                         re.MULTILINE | re.DOTALL)
_NOTIFIER_DECL_RE = re.compile(r"^([ \t]*)reg\s+NOTIFIER\s*;\s*\n", re.MULTILINE)
_MODULE_RE = re.compile(r"^module\s+(\w+)\s*\(", re.MULTILINE)
# Find `wire d<X>;` declarations inside a module so we can add
# `assign d<X> = <X>;` if a port <X> exists.
_DWIRE_RE = re.compile(r"^[ \t]*wire\s+d([A-Z]\w*)\s*;", re.MULTILINE)

def _replace_udps(src: str, scaffold_unknown: bool = False
                   ) -> tuple[str, list[str], list[dict]]:
    """Returns (rewritten_src, seen_udp_names, unknown_udps_metadata).

    v1.6.229 — when `scaffold_unknown=True`, emit a TODO module shell
    for every UDP not in UDP_SYNTH so Quartus/iverilog can at least
    parse the file (the body is empty so the cell will produce X
    until the human fills in the truth table). The metadata list lets
    callers persist a JSON report of UDPs that need human attention.
    """
    seen: list[str] = []
    unknowns: list[dict] = []
    def _sub(m):
        name = m.group(1)
        seen.append(name)
        if name in UDP_SYNTH:
            return UDP_SYNTH[name] + "\n"
        # capture full UDP body for the JSON unknowns report so a
        # human can write a synth template by reading the truth table
        body = m.group(0)
        port_match = re.match(r"^[ \t]*primitive\s+\w+\s*\(([^)]*)\)\s*;",
                                body)
        ports = port_match.group(1) if port_match else ""
        unknowns.append({"name": name, "ports": ports,
                          "raw_lines": body.count("\n"),
                          "raw_snippet": body[:400]})
        if scaffold_unknown:
            # Emit synth scaffold with empty body — caller must fill in
            return (f"// === SCAFFOLD: no synth template for {name} ===\n"
                     f"// TODO: write a synthesisable module body that\n"
                     f"// implements the original UDP truth table.\n"
                     f"// Original primitive body preserved below as comment:\n"
                     + "\n".join("// " + ln for ln in body.splitlines())
                     + f"\nmodule {name} ({ports});\n"
                     f"  // STUB BODY — outputs X until truth table is written\n"
                     f"endmodule\n")
        return f"// PASS-THROUGH (no synth template for {name})\n{body}\n"
    return _PRIM_RE.sub(_sub, src), seen, unknowns

def _strip_specify(src: str) -> str:
    return _SPECIFY_RE.sub("", src)

def _strip_notifier_regs(src: str) -> str:
    """Replace `reg NOTIFIER;` with `supply0 NOTIFIER;` so Quartus has
    a defined low-tied wire for NOTIFIER ports on synthesised UDP shims."""
    return _NOTIFIER_DECL_RE.sub(r"\1supply0 NOTIFIER;\n", src)

def _module_blocks(src: str):
    """Yield (module_name, body_text, start, end) tuples for every
    `module ... endmodule` block."""
    pos = 0
    while True:
        m = _MODULE_RE.search(src, pos)
        if not m: return
        # Find matching endmodule
        end = src.find("\nendmodule", m.end())
        if end < 0: return
        yield m.group(1), src[m.start():end+10], m.start(), end+10
        pos = end + 10

def _add_dwire_assigns(src: str) -> str:
    """For each cell module body, find `wire dX;` and add `assign dX = X;`
    if X is a port (i.e., listed in the module header). This fixes the
    iverilog 'Q stays X' issue caused by dX being driven only via
    $setuphold inside the now-removed specify block."""
    out_chunks = []
    last_end = 0
    for name, body, s, e in _module_blocks(src):
        # Identify ports in module header
        header_end = body.find(");")
        if header_end < 0:
            out_chunks.append(src[last_end:e]); last_end = e; continue
        header = body[:header_end]
        port_chars = set(re.findall(r"\b([A-Z]\w*)\b", header))
        # Find `wire dX;` in body
        dwire_names = [m.group(1) for m in _DWIRE_RE.finditer(body)]
        if not dwire_names:
            out_chunks.append(src[last_end:e]); last_end = e; continue
        # Build assigns
        assigns = []
        for dname in dwire_names:
            if dname in port_chars:
                assigns.append(f"  assign d{dname} = {dname};")
        if assigns:
            # Insert assigns AFTER the last `wire dX;` declaration
            last_dwire_pos = max(m.end() for m in _DWIRE_RE.finditer(body))
            new_body = body[:last_dwire_pos] + "\n" + "\n".join(assigns) + "\n" + body[last_dwire_pos:]
            out_chunks.append(src[last_end:s])
            out_chunks.append(new_body)
            last_end = e
        else:
            out_chunks.append(src[last_end:e]); last_end = e
    out_chunks.append(src[last_end:])
    return "".join(out_chunks)

# Quartus disagrees with `1'bz` in assign for non-tristate cells;
# in synth shim for FPGA we emit 1'b0 placeholder for udp_xgen/udp_outrf.
def _drop_tristate_for_fpga(src: str, drop: bool) -> str:
    if not drop: return src
    return src.replace("1'bz", "1'b0")

# `celldefine` / `enable_portfaults` / `suppress_faults` directives are
# simulator-only; Quartus warns CRITICAL_WARNING on them.
def _strip_specials(src: str) -> str:
    for d in ["`celldefine", "`endcelldefine", "`suppress_faults",
              "`nosuppress_faults", "`enable_portfaults",
              "`disable_portfaults", "`delay_mode_path",
              "`delay_mode_distributed"]:
        src = src.replace(d, f"// stripped: {d}")
    return src

# ─────────────────── Main ───────────────────

def main(argv=None):
    import json as _json
    p = argparse.ArgumentParser()
    p.add_argument("input_v", type=Path, help="Source behavioural .v")
    p.add_argument("output_v", type=Path, help="Synth shim output .v")
    p.add_argument("--fpga", action="store_true",
                    help="FPGA-friendly: drop tristate (1'bz → 1'b0)")
    p.add_argument("--scaffold-unknown", action="store_true",
                    help="v1.6.229 — for UDPs not in UDP_SYNTH, emit a "
                         "synth scaffold (empty module body + commented "
                         "original truth table) instead of a PASS-"
                         "THROUGH that breaks Quartus parsing.")
    p.add_argument("--unknowns-json", type=Path, default=None,
                    help="v1.6.229 — emit a JSON list of every UDP "
                         "without a synth template, so future plugin "
                         "iterations can absorb them.")
    args = p.parse_args(argv)

    src = args.input_v.read_text()
    n_specify_before = len(_SPECIFY_RE.findall(src))
    n_prim_before = len(_PRIM_RE.findall(src))

    src, seen, unknowns = _replace_udps(src, args.scaffold_unknown)
    src = _strip_specify(src)
    src = _strip_notifier_regs(src)
    src = _add_dwire_assigns(src)
    src = _strip_specials(src)
    src = _drop_tristate_for_fpga(src, args.fpga)

    unknown_names = sorted({u["name"] for u in unknowns})
    header = (f"// === pdk_udp_synth_shim_gen v1.6.229 ===\n"
               f"// Source: {args.input_v}\n"
               f"// Primitives encountered: {n_prim_before} "
               f"({sorted(set(seen))})\n"
               f"// Unknowns (need synth template): {len(unknown_names)} "
               f"{unknown_names}\n"
               f"// Specify blocks stripped: {n_specify_before}\n"
               f"// FPGA mode: {args.fpga}\n"
               f"// Scaffold mode: {args.scaffold_unknown}\n\n")
    args.output_v.parent.mkdir(parents=True, exist_ok=True)
    args.output_v.write_text(header + src)
    if args.unknowns_json:
        args.unknowns_json.parent.mkdir(parents=True, exist_ok=True)
        args.unknowns_json.write_text(_json.dumps(
            {"source": str(args.input_v),
             "unknown_count": len(unknown_names),
             "unknowns": unknowns}, indent=2))
    print(f"[shim] in={args.input_v.name}  out={args.output_v.name}  "
          f"udps={n_prim_before}  unknowns={len(unknown_names)}  "
          f"specify_stripped={n_specify_before}  fpga={args.fpga}  "
          f"scaffold={args.scaffold_unknown}")
    return 0

if __name__ == "__main__":
    sys.exit(main())
