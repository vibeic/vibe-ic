# LDO Topology — LDO_TOP_T2 (folded-cascode error-amp, PMOS pass device)

Source: bmurmann/EE628, `5_Design/4_Layout/Team 2`, subckt `LDO_TOP_T2` (DRC + LVS clean).
PDK: IHP SG13G2 (high-voltage devices, `sg13_hv_*`).

## Architecture
- **Error amplifier**: folded-cascode differential pair (XM14/XM16 PMOS mirror load,
  XM17/XM18 NMOS input pair, XM19 tail). Senses feedback divider vs `Vref`.
- **Pass device**: large PMOS `XM10` (W=1.414 mm, L=0.45 u) from `VDD_IO` to `vdda`.
- **Bias generator**: constant-gm self-bias (XM4/XM5/XM13/XM20) producing `vbn`/`vbp`.
- **Startup circuit**: XM6/XM1/XM9 kick the self-bias loop out of the zero-current state.
- **Compensation**: Miller cap `XC2` (cap_cmim 60u×60u) + series R `XR1` zero (`Verr`→`net4`).
- **Output cap**: `XC1` cap_cmim 70u×75u, MF=6 (large on-die decoupling for `vdda`).
- **Feedback divider**: rhigh poly resistors set `vdda = Vref·(1+R1/R4)`; here `Vref` ≈ `vdda`
  target (unity-style sense → 0.6 V).

## Pin list (Team2.readme)
| pin     | dir   | function                         |
|---------|-------|----------------------------------|
| VDD_IO  | in    | unregulated input supply         |
| Vref    | in    | error-amp reference (0.6 V)      |
| vdda    | inout | regulated output = analog supply |
| vssa    | in    | analog ground                    |

## Why this topology
Folded-cascode gives high DC loop gain (good line/load regulation) with a single
high-swing output node; PMOS pass device gives low dropout. Verified: line reg
≈0.14 mV/V, load reg ≈0.5 mV/mA across TT/FF/SS (real ngspice PSP103 sim).
