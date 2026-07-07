# subservient — clean-run spec->GDSII (plugin v1.3.35, 8HD-d / sky130A)
Blind clean-room RV32I SoC (multi-cycle CPU + internal RF + byte-wide external SRAM + GPIO),
§4.05 from L2/L3/L8. Not a copy of SERV RTL; a faithful RV32I ISA with micro-arch freedom.
## Result: functional + physical PASS, timing FAIL (pipelining residual)
| Pillar | Result |
|---|---|
| RV32I functional (self-test) | PASS — executes ADDI/ADD/SW/LW/BEQ + GPIO write; x3=8, mem[8]=42, x7=42, o_gpio=1 |
| yosys synth | PASS (6264 cells) |
| PnR (OpenROAD) | PASS (126 spares, density 0.020) |
| GDS streamout | PASS — subservient.gds 76 MB |
| DRC | 0 violations |
| LVS (netgen power-aware) | circuits match uniquely |
| STA @ target clk (sky130_fd_sc_hd) | FAIL setup -98 ns (hold +0.31 MET) |
## Timing finding (same class as spm/sha256)
The single-cycle multi-cycle-FSM datapath computes the full 32-bit ALU (incl. barrel
shifters SLL/SRL/SRA), branch comparators, and byte-address arithmetic combinationally in
one clock. Closure needs pipelining the execute stage (register ALU operands / split
shift). Functional correctness + DRC/LVS unaffected.
## Tool substitution
VCS->iverilog 12; DC->yosys; PnR/DRC/LVS/STA->OpenROAD/klayout/netgen (iic-osic-tools, sky130A).
