## Verification intent (drives L7 / Pillar 5)
- DC operating point + line/load regulation (LDO); SNDR/ENOB transient + input sweep (modulator).
- Multi-corner: TT/SS/FF × −40/27/125 °C.
- **Tool disclosure:** IHP SG13G2 ships sectioned ngspice corner libraries for every device
  class (`cornerMOShv.lib` / `cornerMOSlv.lib` / `cornerRES.lib` / `cornerCAP.lib`, tt/ss/ff/sf/fs
  with `_mismatch` and `_stat` variants); corner sims bind those sections directly. Results are
  SIMULATED, not silicon sign-off, and say so — they are NOT LEVEL=1 standins.
  CORRECTED 2026-08-11 (vibe-ic#904).
- Golden cross-check (verify stage only): the fabricated UHEE628_S2024 GDS + KLayout-extracted
  SG13G2 netlist (chip-level; per-block sub-netlist is NOT published upstream → cross-check is
  spec-level + chip-GDS-DRC level, not per-block device-LVS).
