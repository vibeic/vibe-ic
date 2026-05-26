# Step A4 — corner sweep  ·  Verdict: IN-RANGE
OURS: REAL ngspice 9-corner (TT/SS/FF x -40/27/125C). LDO Vout 1.199-1.201 V, PSRR>=74 dB, Iq~6 uA, dropout<=0.044 V. DSM OTA DC gain 48.3-72.5 dB (>48.2 dB floor) all corners. all_corners_pass=true.
DISCLOSURE: SG13G2 has NO public ngspice corner lib -> LEVEL=1 standin = MODELED, not silicon sign-off.
REF: golden is fabricated silicon (DRC/LVS clean per README) but publishes no per-block corner data -> spec-level compare: our blocks meet the same L5 targets the chip was designed to.
