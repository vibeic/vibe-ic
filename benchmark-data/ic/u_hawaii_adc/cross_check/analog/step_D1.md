# Step D1 — L1-L13 doc / spec cross-check vs golden  ·  Verdict: MATCH
OURS (generated L1-L13 from input/docs): mixed-signal incremental delta-sigma ADC; 6x delta_sigma modulators + 1 LDO; PDK IHP SG13G2; IOVDD=1.8 V, CORE=1.2 V; die core 1300x1300 um; top pins IN1-6/OUT1-6/CK4-6/dout/IOVDD/CORE/VLDO/VREF/VHI/VLO.
REF (golden UHEE628_S2024, verify-stage only): top_cell UHEE628_S2024, die 1480x1480 um (= 1300 core + seal ring, matches L9 "~1480x1480 with seal ring"), 171 cells, 58 layers; extracted .cir top pins = CK4/5/6, IN1-6, OUT1-6, dout, IOVDD, AVDD, CORE(x multiple), VLO, VHI, VLDO, VREF, RES — device class sg13_lv_nmos/pmos.
Field/semantic diff: ports, supply rails, PDK, die-with-seal-ring, channel count (6 modulators + LDO), converter type ALL agree. Same spec.
