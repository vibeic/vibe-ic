#!/usr/bin/env python3
"""pdk_otp_altsyncram_inject.py — v1.6.224 (ORGANIC-20260512-followup-3).

Post-process a Yosys-flattened gate netlist to replace an
uninitialised synthesised OTP/ROM block with an Altera-style
`altsyncram` instance pre-loaded from a `.mif`. This is the final
piece needed for FPGA gate-level reverify on Altera/Intel MAX 10
boards when the original RTL used `altsyncram` + `init_file`.

How it works (v1.6.224 strategy):
  1. Convert `apple.hex` (1-byte-per-line ascii hex) → `apple.mif`
     (Quartus Memory Init File).
  2. Locate the OTP read-data concat assign in the flat netlist:
       assign u_otp_rdata_r = { _NNNN__I0_out , ..., _MMMM__I0_out };
     This is the post-flatten/post-harmonize shape of the original
     `reg [7:0] rdata_r; always @(posedge clk) rdata_r <= mem[addr];`
     The 8 names in the concat are the 8 DFF Q outputs.
  3. For each DFF name (e.g. `_2810__I0_out`), derive the
     corresponding D input wire name (`_2810__I0_in`) and find its
     existing driver: `assign _2810__I0_in = <gate-decode-expr>;`
  4. Replace `<gate-decode-expr>` with the altsyncram output bit:
     `assign _2810__I0_in = otp_altsyncram_q[<bit_index>];`
  5. Insert an `altsyncram` instance (clocked on `clk`, addressed
     by `u_fsm_otp_addr`) reading from the .mif. The DFFs in (3)
     act as the natural 1-cycle latch that the RTL pipeline
     expected — preserves the existing read latency contract.

This approach is robust because:
  * It preserves all existing wire/reg declarations.
  * It only changes 8 `assign _NNNN__I0_in = ...;` lines.
  * The 1-cycle read latency expected by main_fsm is preserved.
  * Quartus sees the altsyncram driving DFF D inputs → infers M9K
    RAM block AND keeps the DFFs (which feed downstream consumers).

chip-AGNOSTIC: signal name `u_otp_rdata_r` is the Yosys-flatten
canonical name for `\\u_otp.rdata_r` after atpg-name-harmonize. For
projects with different RTL hierarchy, pass `--rdata-signal`.
"""
from __future__ import annotations
import argparse, re, sys
from pathlib import Path

def hex_to_mif(hex_path, mif_path, depth, width):
    bytes_ = [int(b.strip(), 16)
              for b in hex_path.read_text().splitlines()
              if b.strip() and not b.lstrip().startswith('//')]
    if len(bytes_) > depth: bytes_ = bytes_[:depth]
    while len(bytes_) < depth: bytes_.append(0)
    width_hex = (width + 3) // 4
    addr_chars = len(f'{depth-1:X}')
    lines = [
        f'WIDTH={width};', f'DEPTH={depth};',
        'ADDRESS_RADIX=HEX;', 'DATA_RADIX=HEX;',
        'CONTENT BEGIN',
    ]
    for i, b in enumerate(bytes_):
        lines.append(f'  {i:0{addr_chars}X} : {b:0{width_hex}X};')
    lines.append('END;')
    mif_path.parent.mkdir(parents=True, exist_ok=True)
    mif_path.write_text('\n'.join(lines) + '\n')
    return len(bytes_)

def patch_netlist(flat_path, out_path, mif_name, rdata_sig, addr_sig,
                    depth, width, widthad):
    src = flat_path.read_text()
    # 1) Find the rdata concat assign
    cre = re.compile(
        rf'assign\s+{re.escape(rdata_sig)}\s*=\s*\{{\s*([^}}]+)\s*\}}\s*;',
        re.MULTILINE)
    m = cre.search(src)
    if not m:
        raise RuntimeError(
            f"could not find `assign {rdata_sig} = {{ … }};` in "
            f"{flat_path}")
    parts = [p.strip() for p in m.group(1).split(',')]
    if len(parts) != width:
        raise RuntimeError(
            f"concat has {len(parts)} parts, expected {width}: {parts}")
    # parts[0] is MSB (bit width-1), parts[-1] is LSB (bit 0)
    # because Yosys writes `{ MSB, ..., LSB }`
    print(f"[otp] OTP DFFs (MSB→LSB): {parts}")

    # 2) For each DFF Q-name (e.g. `_2810__I0_out`), derive D-name and
    #    rewrite the driver assign.
    replacements = []
    for i, dff_q in enumerate(parts):
        bit = (width - 1) - i  # parts[0]=MSB → bit width-1
        dff_d = dff_q.replace('_out', '_in')
        # Match `assign <dff_d> = <expr>;`
        a_re = re.compile(
            rf'^(\s*assign\s+{re.escape(dff_d)}\s*=\s*)([^;]+);',
            re.MULTILINE)
        am = a_re.search(src)
        if not am:
            print(f"[otp] WARNING: no driver for {dff_d}; skipping",
                  file=sys.stderr)
            continue
        old_driver = am.group(2).strip()
        new_line = (f"{am.group(1)}otp_altsyncram_q[{bit}]; "
                     f"// orig: {old_driver}")
        src = src[:am.start()] + new_line + src[am.end():]
        replacements.append((dff_d, bit, old_driver))

    # 3) Insert altsyncram before endmodule
    em_re = re.compile(r'^endmodule\s*$', re.MULTILINE)
    em = em_re.search(src)
    if not em:
        raise RuntimeError("no endmodule found")
    inst = f'''
  // === pdk_otp_altsyncram_inject v1.6.224 ===
  // Pre-init'd ROM driving the 8 OTP DFF D inputs. Original gate-decode
  // tree (always-X due to Yosys dropping $readmemh during ASIC synth)
  // is bypassed; original drivers preserved in comments above.
  wire [{width-1}:0] otp_altsyncram_q;
  altsyncram #(
    .operation_mode    ("ROM"),
    .init_file         ("{mif_name}"),
    .init_file_layout  ("PORT_A"),
    .lpm_type          ("altsyncram"),
    .width_a           ({width}),
    .widthad_a         ({widthad}),
    .numwords_a        ({depth}),
    .address_aclr_a    ("NONE"),
    .outdata_aclr_a    ("NONE"),
    .outdata_reg_a     ("UNREGISTERED"),
    .ram_block_type    ("M9K")
  ) u_otp_altsyncram_inj (
    .clock0    (clk),
    .address_a ({addr_sig}),
    .q_a       (otp_altsyncram_q)
  );

'''
    src = src[:em.start()] + inst + src[em.start():]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(src)
    return {"otp_dff_d_inputs_rewired": len(replacements),
            "replacements": replacements,
            "mif_name": mif_name}

def main():
    p = argparse.ArgumentParser()
    p.add_argument("--flat-netlist", type=Path, required=True)
    p.add_argument("--hex-file",     type=Path, required=True)
    p.add_argument("--output",       type=Path, required=True)
    p.add_argument("--mif-output",   type=Path, required=True)
    p.add_argument("--rdata-signal", default="u_otp_rdata_r")
    p.add_argument("--addr-signal",  default="u_fsm_otp_addr")
    p.add_argument("--depth",        type=int, default=128)
    p.add_argument("--width",        type=int, default=8)
    p.add_argument("--widthad",      type=int, default=7)
    args = p.parse_args()
    n = hex_to_mif(args.hex_file, args.mif_output, args.depth, args.width)
    print(f"[otp] hex->mif: {n} bytes -> {args.mif_output}")
    info = patch_netlist(args.flat_netlist, args.output,
                          args.mif_output.name, args.rdata_signal,
                          args.addr_signal, args.depth, args.width,
                          args.widthad)
    print(f"[otp] patched: {info['otp_dff_d_inputs_rewired']} DFF D-inputs "
          f"rerouted to altsyncram")
    return 0

if __name__ == "__main__":
    sys.exit(main())
