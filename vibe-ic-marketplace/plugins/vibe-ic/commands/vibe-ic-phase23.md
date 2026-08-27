---
name: vibe-ic-phase23
description: Chain /vibe-ic-phase2 → /vibe-ic-phase3 via phase23_one_shot_runner (true chained orchestrator — delegates to design_one_shot_runner.py + phase3_one_shot_runner.py, not monolithic). AI-monitored + close-loop.
argument-hint: <project-dir> [--top-name chip_top] [--skip-hardware] [--max-rtl-repair-retries 3] [--skip-phase2|--skip-phase3]
---
> **Missing arg?** When `$ARGUMENTS` is empty, prompt the user first:
> `/vibe-ic-phase23 <project-dir>` (e.g. `/vibe-ic-phase23 1st_benchmark_example/phase2_v0119.48-vendor`).
> The AI must NOT guess the path; a concrete project path is required before continuing.


# /vibe-ic-phase23 — Phase 2 + Phase 3 true chain

Main execution (**program-driven**):

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/programs/phase23_one_shot_runner.py $ARGUMENTS
```

This runner is a **thin-shell chain**:
1. Delegates to `design_one_shot_runner.py` to run Phase 2 (rig_topology skeleton → phase1 → rtl_gen → reference_tb → yosys → qsf/sdc → otp_check → fpga compile/burn → <half-duplex-tester> → manifests → final_audit @phase 2)
2. If Phase 2 verdict==FAIL, **auto-halt** without entering Phase 3 (unless `--skip-phase3` is the user-specified alias usage)
3. Phase 2 PASS / PASS_WITH_WAIVERS → delegates to `phase3_one_shot_runner.py` to run Phase 3 (synth/PnR/GDS/DRC/LVS)
4. Aggregates JSON reports from both phases → `<project>/reports/phase23_one_shot.json`

After the run completes, the AI must (combine `/vibe-ic-phase2` + `/vibe-ic-phase3` monitoring rules):

1. Read `<project>/reports/phase23_one_shot.json` — inspect `phase2.verdict` / `phase3.verdict` / overall `verdict`
2. Phase 2 FAIL → close-loop per `/vibe-ic-phase2` rules; Phase 3 FAIL → per `/vibe-ic-phase3` rules
3. **Acceptance gate** (per CLAUDE.md SOLE ACCEPTANCE CRITERION):
   - `Overall: PASS` — production tapeout-ready
   - `Overall: PASS_WITH_WAIVERS` — every deferred step in waivers.json must carry evidence + ticket id + `review_required: true`
   - `Overall: FAIL` — not complete, keep working
4. Individual gate PASS does NOT mean Phase 2+3 is complete

**Flag mapping:**
- `--skip-phase3` ≡ exactly equivalent to `/vibe-ic-phase2`
- `--skip-phase2` ≡ exactly equivalent to `/vibe-ic-phase3` (precondition: rtl/ + generated_docs/ already prepared)

**Helper skills:** same as `/vibe-ic-phase2` + `/vibe-ic-phase3`, plus `tapeout-checklist`, `flow-orchestrate`.

---

## ⚠ Anti-fabrication 5 hard rules (v1.6.30)

Any violation ⇒ verdict-FAIL: (1) no symlinks under `phase3/stage4/**` / `phase3/mixed_signal/**` / `phase2/stage1/fpga/**` / `analog/hardmacro/**` (exceptions via `.canonical_symlink_allowlist`); (2) every `provenance.jsonl` entry must carry `outputs: sha256:<64hex>`; (3) `reports/` root may only contain `final_summary.md` + `chip_specific_summary.md`; (4) any sub-gate FAIL inside a step ⇒ verdict FAIL; (5) `final_summary.md` must include the canonical artefact SHA256 table. Full version: `commands/_anti_fabrication_rules.md`.
