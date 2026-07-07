# sha256 — clean-run spec→GDSII (plugin v1.3.35, 8HD-d / iic-osic-tools)

Blind IC-Expert-Agent authoring of a full NIST FIPS-180-4 SHA-256/224 MMIO accelerator
from L2/L4/L5 docs (register file + message schedule + 64 K-constants + compression;
K-constants and init vectors are public NIST standard, not an oracle read).

## Result: functional + physical PASS, timing FAIL (pipelining residual)
| Pillar | Result |
|---|---|
| Functional (NIST "abc" vector) | PASS — digest ba7816bf 8f01cfea 414140de 5dae2223 b00361a3 96177a9c b410ff61 f20015ad (exact) |
| yosys synth | PASS (8921 cells) |
| PnR (OpenROAD) | PASS (179 spares, density 0.020) |
| GDS streamout | PASS — sha256.gds 105 MB, grid-snapped |
| DRC | 0 violations |
| LVS (netgen, power-aware) | circuits match uniquely |
| STA @ 100 MHz (sky130_fd_sc_hd) | FAIL setup -75 ns (hold +0.31 ns MET) |

## Timing finding (same class as spm's systolic lesson)
The single-cycle SHA-256 round places a 4-5 deep cascaded 32-bit adder chain
(T1 = h + Sigma1(e) + Ch(e,f,g) + K[t] + W[t]) in the register-to-register path
(~85 ns) and busts the 10 ns clock. Closure requires pipelining the round (register
the K+W term ahead + split the T1/T2 computation across 2 cycles so each cycle carries
<=2-3 adds). Functional correctness and DRC/LVS are unaffected.

## Tool substitution
VCS->iverilog 12; Design Compiler->yosys; PnR/DRC/LVS/STA->OpenROAD/klayout/netgen in
hpretl/iic-osic-tools (sky130A).
