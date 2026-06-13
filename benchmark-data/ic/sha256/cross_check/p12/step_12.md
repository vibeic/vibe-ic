# Step 12 — Post-DFT netlist (OURS)

**Verdict: BOTH-CLEAN** (scan chain stitched; post-DFT netlist produced and resynthesized)

## What ran
The `eda_dft` flow (step 11) re-synthesizes the design after scan insertion
("Resynthesizing with yosys… Done. CHAIN_DONE") and emits the stitched netlist +
`atpg.tv.json` + `coverage.yml` under
`/home/reyerchu/AI_IC_design/_sha256_xc_p12/dft/`.

## Result (OURS)
- Post-DFT (scan-inserted) netlist produced; internal chain length 1584,
  boundary 75, total 1659.
- ATPG vectors written (`atpg.tv.json`, 60 compacted), coverage metadata
  (`coverage.yml`).
- No errors in scan stitch or resynthesis (CHAIN_DONE + ATPG_DONE).

## REF comparison
REF carries a `phase3/stage3/dft/` with `dft_scan.ys` (audited PASS in
`eco_audit.json`: "contains -sv, -flatten, hilomap") and a
`phase2/stage2/synth/post_dft_netlist.v` (1.16 MB). So REF *has* a post-DFT
netlist artifact, but its archived ATPG coverage was 0 % (step 11). OURS
produced an equivalent post-DFT netlist AND achieved 94 % coverage on it.

→ Both have a clean post-DFT netlist; OURS additionally has working ATPG on it.
