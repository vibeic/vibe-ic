# Step A9 — mixed-signal cosim  ·  Verdict: EQUIVALENT
OURS: REAL iverilog/vvp cosim of the 2nd-order incremental DSM + sinc^2 decimator -> ENOB=14.737 bits @ OSR=256 (>=14 target) over +/-0.75 FS, after 2-pt gain/offset cal (linear converter). Validated against a Python float reference model (ENOB 14.6-14.7). MODELED.
REF: upstream system model is the EE628 idsm2 Simulink (figures) -> same architecture (2nd-order incremental, OSR~256). Behaviour equivalent at the system level.
