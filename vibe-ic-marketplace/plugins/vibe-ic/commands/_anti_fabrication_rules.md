# v1.6.30 Anti-fabrication Rules — shared appendix

Codified after the v10627 / v10627-vendor false-PASS comparison. Inlined
into every phase2 / phase2 / phase3 / phase23 / vibe-ic-all command so
that any fresh agent invoking those commands sees the same hard rules.

---

## 5 hard rules (any one violated ⇒ verdict-FAIL)

1. **Real file, no symlink** in canonical deliverable trees:
   `phase3/stage4/**`, `phase3/mixed_signal/**`,
   `phase2/stage1/fpga/**`, `analog/hardmacro/**`.
   Foundry-shipped references that *must* be symlinks: declare in
   `<project>/.canonical_symlink_allowlist` (one path per line).

2. **Provenance entries carry SHA256** of every output:
   `provenance.jsonl` rows must include
   `"outputs": {"<rel>": "sha256:<64hex>", ...}`.
   Synthetic timestamps (every entry on `:00` second boundary, regular
   gaps) will be flagged by `provenance_output_hash_completeness_check`
   (roadmap). Empty is honest; fabricated is dishonest.
   An output the publish step did not ship is DISCLOSED, never deleted
   (#414): keep the row and its digest and add
   `outputs_relocated_at_publish` / `outputs_pruned_at_publish` +
   `outputs_pruned_reason`. Deleting the row to quiet the gate restores
   the dangling pointer those keys exist to remove.

3. **`reports/` root holds only 2 markdown files** —
   `final_summary.md` + `chip_specific_summary.md` (produced by
   `final_report_generate.py`).
   Retry verdicts, run logs, agent notes route through
   `_pl.report_path()` into `reports/orchestrator/logs/` or
   `reports/audit/`. Loose files at `reports/` root fail
   `reports_subfolder_taxonomy_check`.

4. **Step-internal gate FAIL ⇒ verdict FAIL.**
   No `Overall: PASS` while a sub-gate (cdc / formal / lint / etc.)
   inside any step is FAIL. Bubble up.

5. **Final report carries a SHA256 attestation table** of every
   canonical artefact (SOF / GDS / synth-netlist / LEF / Liberty /
   sign-off reports). Without that table, "PASS" is unverifiable and
   counts as incomplete.

---

## v1.6.30+ deterministic gates already enforce parts of these

- `analog_artefact_substance_check` — 14-marker case-insensitive panel
  catches `placeholder hardmacro`, `TODO implement`, `behavioral stub`,
  `__STUB__`, `do not tape out`, `methodology_stub` and similar. Also
  per-extension size thresholds.
- `chip_gds_canonical_real_file_check` — recursive globs across
  `phase3/stage4/gds/**`, `phase3/mixed_signal/**`,
  `phase3/stage4/foundry_handoff/**`. `BROKEN_SYMLINK` is its own rule.
- `canonical_path_symlink_forbid_check` (v1.6.51) — generalisation of
  the GDS gate above to all 5 canonical-deliverable trees and all file
  extensions (rule 1). Allowlist via `.canonical_symlink_allowlist`.
- `metadata_content_substance_check` (v1.6.51) — substance for the
  4 whitelisted phase1 metadata JSON files. Closes the v1.6.26
  taxonomy-by-location loophole.
- `provenance_output_hash_completeness_check` (v1.6.31) — rule 2.
  Every provenance.jsonl entry must declare `outputs:
  sha256:<64hex>` and the declared hash must match the on-disk
  file. Synthetic-timestamp pattern flagged as ATTEST_TIMING_SUSPICIOUS.
  #434: an absence the row DISCLOSES is a third outcome —
  PROVENANCE_OUTPUT_NOT_VERIFIABLE_HERE, severity DISCLOSED, counted on
  the verdict line — but only after the gate follows a relocation to a
  file with the SAME digest, or finds the not-shipped claim explained,
  true, and backed by the run's own digest. Presence and hash are
  decided before any disclosure is read, so a marker can never silence
  a PROVENANCE_HASH_MISMATCH. `--require-outputs-present` restores the
  ERROR for run directories, where nothing has been published yet.
- `agent_report_sha256_attestation_check` (v1.6.33) — rule 5.
  AGENT_REPORT.md must carry a SHA256 attestation table for every
  canonical artefact.
- `step_internal_fail_bubble_up_check` (v1.6.44) — rule 4.
- `reports_subfolder_taxonomy_check` + `top_level_outputs_in_canonical_check`
  — taxonomy whitelist enforcement (rule 3).
- `migrate_to_canonical_taxonomy.py` — resume semantics; identical-
  content collisions drop redundant src; real conflicts block AND
  preserve src for manual resolution.

All 5 hard rules now have a deterministic gate. Backlog items
`community/backlogs/ORGANIC-20260508-*.yaml` (canonical-symlink-forbid,
metadata-content-substance, provenance-output-hash-completeness) are
closed by v1.6.31 + v1.6.51.
