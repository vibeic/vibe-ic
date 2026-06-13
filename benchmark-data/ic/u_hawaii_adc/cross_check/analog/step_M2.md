# Step M2 — mixed-signal functional cosim (A+D)  ·  Verdict: EQUIVALENT
OURS: REAL iverilog/vvp cosim drives the modulator behavioural model with the digital clock/reset window (incremental OSR=256) and reads the 1-bit bitstream + sinc^2 decimation -> ENOB=14.74. This IS the A+D functional check for an analog-front-end (analog loop + digital window/decimation).
REF: EE628 idsm2 system model — same incremental 2nd-order architecture. Equivalent.
