# Step A5 — analog layout + per-block PV  ·  Verdict: BOTH-CLEAN
OURS: Magic SG13G2 layout per block (diff pair + mirror + pass/comparator + substrate guard ring) -> Magic DRC=0 AND KLayout SG13G2 sign-off deck = 0 items (non-vacuous, all rule tables ran). Streamed real GDS (1.7-2.0 KB, non-vacuous).
REF: golden chip GDS = 1480x1480 um, DRC "mostly clean" (only IHP-pad + density items, waivable per README), LVS clean.
Both independently DRC-clean. (LDO/DSM layout is a representative analog cell, not a full PCell device layout — disclosed.)
