---
name: vibe-ic-phase2
description: Run Phase 2 (L1-L27 → RTL → SOF → <half-duplex-tester> byte[6]=0xF2) via design_one_shot_runner. AI-monitored + bounded RTL repair/retry.
argument-hint: <project-dir> [--top-name chip_top] [--skip-hardware] [--max-rtl-repair-retries 3]
---
> **Missing arg?** When `$ARGUMENTS` is empty, prompt the user first:
> `/vibe-ic-phase2 <project-dir>` (e.g. `/vibe-ic-phase2 1st_benchmark_example/phase2_v0119.48-vendor`).
> The AI must NOT guess the path; a concrete project path is required before continuing.


# /phase2 — Phase 2 (RTL → SOF → on-board verify) entry

**Prerequisite**: `<project>/generated_docs/L1..L13.json` must exist (produced by `/phase1` or `/phase1`).

Main execution (**program-driven**):

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/programs/design_one_shot_runner.py $ARGUMENTS
```

The runner runs: rig_topology skeleton → detect_ic_class → rtl_gen → reference_tb → yosys → qsf/sdc → otp_image_check → fpga_compile → fpga_burn → md905_verify → phase2_manifests → final_audit.

After the run completes, the AI must:

1. Read `<project>/reports/phase23_one_shot.json`, find the verdict and per-step status
2. For every FAIL step:
   - **`rtl_gen`** FAIL → check `aid_class_rtl_gen.py` stderr; usually L8/L9 fields missing → return to `/phase1` to fill in
   - **`reference_tb`** FAIL → iverilog parse / sim error; bounded RTL repair/retry loop (runner auto-retries up to 3 times); if retries are exhausted, modify `aid_class_rtl_gen.py` template
   - **`fpga_compile`** FAIL → check `fpga/compile.log`; common: QSF init_file SEARCH_PATH, SystemVerilog patterns Quartus does not accept → fix RTL template / qsf_gen
   - **`fpga_burn`** FAIL → parse `error_code` and `failed_gates` (pre-burn structural-gate audit); close-loop each gate (call `programs/<gate>.py` to capture detail → patch RTL/L doc → re-run)
   - **`md905_verify`** FAIL → `<unparsed>` = driver did not see frame; first verify the SOF was burned in + <half-duplex-tester> connected to PIN_V10; if `expected ≠ observed` it is a real hardware bug and requires RTL repair (not a metal-layer ECO)
3. All PASS → hint: `/phase3`

**Helper skills:** `spec-to-rtl` / `cdc-check` / `rtl-review` / `formal-verify` / `bringup-plan`

**Rule:** `flow_compliance_check.py --phase 2 --strict-structural` Overall: PASS is required for Phase 2 to be considered complete. `PASS_WITH_WAIVERS` requires a corresponding `waivers.json` entry tagged `review_required: true`.

---

## ⚠ Anti-fabrication 5 hard rules (v1.6.30)

Any violation ⇒ verdict-FAIL: (1) no symlinks under `phase2/stage1/fpga/**` / `phase3/stage4/**` / `phase3/mixed_signal/**` / `analog/hardmacro/**` (exceptions via `.canonical_symlink_allowlist`); (2) every `provenance.jsonl` entry must carry `outputs: sha256:<64hex>`; (3) `reports/` root may only contain `final_summary.md` + `chip_specific_summary.md`; (4) any sub-gate FAIL inside a step ⇒ verdict FAIL; (5) `final_summary.md` must include the canonical artefact SHA256 table. Full version: `commands/_anti_fabrication_rules.md`.
