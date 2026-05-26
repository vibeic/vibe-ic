# Step 35 — Foundry Handoff (mask layers + scribe / WAT)

## What ran
Compared OUR vs REF `phase3/stage4/foundry_handoff/` package
(mask_spec.json, wat_plan.json, scribe_line_layout.gds, corner_test_vectors.json,
README.txt) and OUR `reports/phase3/foundry_handoff_audit.json`.

## Side-by-side
| artifact | OURS | REF |
|---|---|---|
| mask_spec.json | present (schema 1.0, TODO_mask_layers template) | present (same schema) |
| wat_plan.json | present (same 6 keys: structures/yield/acceptance TODO) | present (identical keys) |
| scribe_line_layout.gds | present (137 B placeholder) | present |
| corner_test_vectors.json | present | present |
| README.txt | present | present |
| foundry_handoff audit | PASS (all required artifacts present) | PASS |

## Verdict: BOTH-CLEAN / IN-RANGE (handoff kit present, items are TODO-templated)
Both flows emit the identical foundry-handoff package shape: a mask_spec +
wat_plan + scribe-line GDS + corner test vectors + README. The mask-layer index
and WAT structures are TODO-templated on BOTH sides (the open-source handoff-kit
assembler ships a template that the foundry shuttle fills against the final
routing stack) — this is the same state on OURS and REF, not an OURS-specific gap.
OUR foundry_handoff_audit gate is PASS. Equivalent handoff readiness.
