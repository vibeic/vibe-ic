# Step A1 — analog spec extract  ·  Verdict: IN-RANGE
OURS: phase3/analog/{ldo,delta_sigma}/spec.json GENERATED from L5 (Vout=1.2/PSRR>=40/Iq<=50uA; ENOB>=14/OSR=256/order=2).
REF (golden, verify-stage): UHEE628 top pins (CORE=1.2, IOVDD=1.8, VLDO/VREF, IN1-6/OUT1-6/CK4-6) confirm the same product intent.
Cross-check is SPEC-LEVEL (upstream publishes NO per-block sub-netlist). Targets match the chip's design intent.
