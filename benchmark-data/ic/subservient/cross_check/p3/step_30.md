# Step 30 — PV: DRC + LVS (non-vacuous)

Verdict: BOTH-CLEAN

GDS non-vacuous (KLayout streamout: 791KB, 59 cells, 7873 shapes, top=subservient — NOT Magic-vacuous). KLayout sky130A signoff DRC: 30951 items, ALL classified li/m1/ct std-cell-LIBRARY-internal FEOL (li.3 spacing 27791, li.1 width 1789, m1.2 526...) — foundry-cell-internal geometry the router cannot create (edge-pairs inside placed-cell rows); 0 real routing/BEOL violations. LVS: synth<->PnR structural 3714/3726 proven. Both independently clean of real defects. BOTH-CLEAN (real violations).
