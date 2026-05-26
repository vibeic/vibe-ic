# Step 36 — Foundry handoff

**What ran:** Compared OURS `phase3/stage4/foundry_handoff/` package against REF.

| Artefact | OURS | REF |
|---|---|---|
| README.txt | present (skeleton v1.6.36) | present (skeleton v1.6.36) |
| mask_spec.json | present, TODO/placeholder fields (pdk=unknown, cell_count=-1, die_area=null) | present, identical placeholder shape (pdk="pdk") |
| wat_plan.json | present (skeleton) | present |
| scribe_line_layout.gds | present (137 B placeholder) | present |
| corner_test_vectors.json | present | present |
| GDS referenced | `sha256.gds` (1.4 MB abstract) + 0-byte `sha256.magic_merged.gds` | `sha256.gds` |

**Verdict: IN-RANGE / DIFFERENT-BUT-OK (both skeleton) — with one honest defect on OURS.** OURS and REF ship the identical auto-generated handoff *skeleton*: both have TODO/placeholder mask-layer tables and null process/die fields that the foundry-interface engineer fills before tape-out. At the package-completeness level they are equivalent.

**Honest defects flagged on OURS handoff:**
1. `mask_spec.json` points `gds_path` at the 1.4 MB abstract GDS and the package contains a **0-byte `sha256.magic_merged.gds`** — the handoff should be re-pointed at the regenerated 25.9 MB full-geometry magic GDS (`phase3/stage4/gds/sha256_magic.gds`) produced in Step 30 before any real foundry submission.
2. `cell_count=-1`, `die_area_um2=null`, `pdk="unknown"` placeholders should be back-filled (cell_count=12,148; die=810,000 um²; pdk=sky130A) — REF has the same null placeholders, so this is not a regression vs REF, just an incomplete-but-expected skeleton.

**Evidence:** OURS + REF `phase3/stage4/foundry_handoff/{README.txt,mask_spec.json,wat_plan.json}`, `reports/phase3/foundry_handoff_audit.json`.
