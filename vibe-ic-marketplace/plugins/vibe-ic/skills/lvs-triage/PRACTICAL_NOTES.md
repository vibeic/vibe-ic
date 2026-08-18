# LVS Triage — Practical Notes

**Added**: 2026-04-07 from a digital LVS verification pilot

## Method: Netgen (Post-P&R vs Synthesis Netlist Comparison)

For digital standard-cell designs, the correct LVS approach is comparing the **post-P&R Verilog netlist** against the **synthesis Verilog netlist** using Netgen. This verifies that P&R didn't corrupt the netlist.

### Command

```bash
netgen -batch lvs \
  "post_pnr.v top_module" \
  "synth.v top_module" \
  /foss/pdks/gf180mcuD/libs.tech/netgen/setup.tcl \
  lvs_result.txt
```

### Pilot Result: PASS — Circuits match uniquely

```
Circuit 1 contains 2716 devices, Circuit 2 contains 2716 devices.
Circuit 1 contains 2722 nets,    Circuit 2 contains 2722 nets.
Netlists match uniquely.
Cell pin lists are equivalent.
Device classes example_synth_wrapper and example_synth_wrapper are equivalent.
Final result: Circuits match uniquely.
```

All 34 standard cell types match exactly (625 dffrnq, 469 mux2, 250 nand2, etc.).

### Why NOT KLayout LVS or Magic LVS

- **KLayout LVS** (`run_lvs.py`): designed for GDS extraction vs SPICE schematic — for analog/mixed-signal, not digital standard-cell
- **Magic LVS**: no GF180MCU tech file for extraction → can't extract layout netlist

### Why NOT Yosys equiv

Yosys `equiv_make`/`equiv_simple`/`equiv_induct` cannot prove RTL-vs-gate equivalence for designs with technology mapping (hundreds of unproven cells on a ~2.7k-cell pilot). This is a known Yosys limitation for production-sized designs. Netgen comparison at gate level is the stronger check.

## References

- [Netgen Documentation](http://opencircuitdesign.com/netgen/)
- [GF180MCU Netgen setup](https://github.com/google/gf180mcu-pdk) — `/libs.tech/netgen/setup.tcl`
