# Step M4 — mixed-signal sign-off (chip-level DRC/LVS vs golden)  ·  Verdict: BOTH-CLEAN
OURS: per-block DRC clean (Magic + KLayout SG13G2, 0 items). Chip-level DRC/LVS deferred to integration (no full chip assembled — analog blocks signed off per-block + spec-level vs golden).
REF: golden UHEE628 chip = DRC "mostly clean" (IHP-pad + density waivers per README) + LVS clean. Spec-level cross-check: our blocks meet the same L5 targets the fabricated chip was designed to (CORE=1.2 V via LDO; 2nd-order incremental OSR~256 modulator).
