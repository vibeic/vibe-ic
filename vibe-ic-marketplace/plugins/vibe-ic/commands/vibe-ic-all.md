---
name: vibe-ic-all
description: Run the complete Vibe-IC flow (Phase 1 → Phase 2 → Analog → Phase 3) via vibe_ic_one_shot_runner. Auto-detects Path A vs B. AI-monitored + close-loop.
argument-hint: <project-dir> [--top-name chip_top] [--skip-hardware] [--skip-analog] [--skip-phase3] [--ic-name <name>] [--die-um WxH] [--util 0.4] [--pdk auto|sky130A|<custom>]
---
> **Missing arg?** When `$ARGUMENTS` is empty, prompt the user first:
> `/vibe-ic-all <project-dir>` (e.g. `/vibe-ic-all 1st_benchmark_example/phase2_v0119.48-vendor`).
> The AI must NOT guess the path; a concrete project path is required before continuing.


# /vibe-ic-all — Whole Vibe-IC flow (Phase 1 → 2 → Analog → 3)

Main execution (**program-driven**):

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/programs/vibe_ic_one_shot_runner.py $ARGUMENTS
```

This runner is the **top-level chain**:
1. Auto-detect Path A (NL prompt) vs Path B (vendor docs) → run `phase1_one_shot_runner` if needed
2. `design_one_shot_runner` (= phase1 + phase2)
3. `analog_one_shot_runner` (only runs if analog blocks are declared; analog FAIL does not block digital)
4. `phase3_one_shot_runner` (synth → PnR → GDS → DRC → LVS)

**Halt rules:**
- Phase 1 FAIL → do not enter Phase 2
- Phase 2 FAIL → do not enter Analog / Phase 3
- Analog FAIL → recorded but **does not block** Phase 3
- Phase 3 FAIL → overall FAIL, but report is still emitted

**Flag-to-sub-phase skip mapping:**
- `--skip-phase1` ≡ force Path B
- `--skip-analog` ≡ skip A1..A8
- `--skip-phase3` ≡ equivalent to `/vibe-ic-phase2`
- `--skip-hardware` ≡ skip fpga compile/burn/<half-duplex-tester> (forwarded to phase2)

After the run completes, the AI must:

1. Read `<project>/reports/vibe_ic_one_shot.json` — inspect `phases[]`, `halted_at`, and overall `verdict`
2. For the `halted_at` phase → jump to the corresponding `/vibe-ic-phase<X>` close-loop rules
3. **Acceptance** (per CLAUDE.md SOLE ACCEPTANCE CRITERION):
   - `Overall: PASS` — production tapeout-ready
   - `Overall: PASS_WITH_WAIVERS` — every deferred step in waivers.json must carry evidence + ticket id + `review_required: true`
   - `Overall: FAIL` — not complete, keep working
4. Individual phase / gate PASS does NOT mean the whole flow is complete

**Purpose:** one command runs full spec → silicon-ready GDS (including the NL-prompt entry point and analog integration).

---

## ⚠ Anti-fabrication 5 hard rules (v1.6.30, span Phase 1→2→Analog→3)

Any violation ⇒ verdict-FAIL: (1) no symlinks under `phase3/stage4/**` / `phase3/mixed_signal/**` / `phase2/stage1/fpga/**` / `analog/hardmacro/**` (exceptions via `.canonical_symlink_allowlist`); (2) every `provenance.jsonl` entry must carry `outputs: sha256:<64hex>`; (3) `reports/` root may only contain `final_summary.md` + `chip_specific_summary.md`; (4) any sub-gate FAIL inside a step / phase ⇒ verdict FAIL; (5) `final_summary.md` must include the SHA256 table of every canonical artefact across the flow (L1-L27 / SOF / GDS / netlist / LEF / Liberty / each sign-off report). Full version: `commands/_anti_fabrication_rules.md`.
