---
name: vibe-ic-phase3
description: Run Phase 3 (synth → PnR → GDS → DRC → LVS) via phase3_one_shot_runner. AI-monitored + close-loop.
argument-hint: <project-dir> [--top-name chip_top] [--die-um 1500x1500] [--util 0.4] [--pdk auto|sky130A|<custom>]
---
> **Missing arg?** When `$ARGUMENTS` is empty, prompt the user first:
> `/vibe-ic-phase3 <project-dir>` (e.g. `/vibe-ic-phase3 1st_benchmark_example/phase2_v0119.48-vendor`).
> The AI must NOT guess the path; a concrete project path is required before continuing.


# /phase3 — Phase 3 (silicon backend)

**Prerequisite**: at least one of `<project>/rtl/*.sv` and `<project>/input/pdk/{liberty,lef}/` is present (PDK can be auto-detected or fall back to sky130A). `/phase2` complete is best.

Main execution (**program-driven**):

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/programs/phase3_one_shot_runner.py $ARGUMENTS
```

The runner automatically:
1. PDK detect (input/pdk/liberty + lef → custom; fallback sky130A)
2. macro detect (input/pdk_local/<vendor>/{lib,LEF,PA_GDS,Verilog})
3. Calibre / Assura DRC + LVS deck detect
4. yosys synth (macro libs as blackbox)
5. OpenROAD floorplan + place + CTS + global_route → DEF + sta.rpt
6. KLayout DEF→GDS (merge macro PA-GDS)
7. KLayout DRC (when .lydrc or deck is available)
8. Netgen LVS (when reference netlist is available)

After the run completes, the AI must:

1. Read `<project>/reports/phase3_one_shot.json` and inspect the verdict
2. For every FAIL step:
   - **`synth`** FAIL → check `phase3/synth/synth.log`; common: vendor primitive missing black-box (need to add macro `read_liberty -lib`), `SIMULATION` define not effective (runner already set), `assertions.sv` leaking into synth (runner already filters)
   - **`pnr`** FAIL → check `phase3/pnr/openroad.log`; common: site name detected wrong, metal_prefix detected wrong, CTS buffer not in liberty, die size too small (util > 80% requires enlarging die), missing TRACKS (runner already adds `make_tracks`), SDC ref FPGA-only port → close-loop fix `_detect_pdk` heuristic
   - **`gds`** FAIL → check KLayout stream-out log; usually LEF conflict (multiple LEF variants for the same macro) → fix `lef_by_macro` selection logic
   - **`drc` / `lvs`** WAIVED is legal (commercial deck must be run offline); but if .lydrc should exist yet was not found, hint to fix the path
3. All PASS / PASS_WITH_WAIVERS → hint: tapeout review

**Helper skills:** `synthesis-driver` / `pnr-orchestrate` / `drc-orchestrate` / `lvs-orchestrate` / `gds-export` / `tapeout-checklist`

**Rule:** Phase 3 PASS requires synth + pnr + gds all PASS (DRC/LVS may be WAIVED → must be run offline for sign-off before tapeout).

---

## ⚠ Anti-fabrication 5 hard rules (v1.6.30)

Any violation ⇒ verdict-FAIL: (1) no symlinks under `phase3/stage4/**` (including `gds/`, `foundry_handoff/`) / `phase3/mixed_signal/**` / `analog/hardmacro/**` — `chip_gds_canonical_real_file_check` v1.6.30 made recursive, broken symlinks split into a separate `BROKEN_SYMLINK` rule; exceptions via `.canonical_symlink_allowlist`; (2) every `provenance.jsonl` entry must carry `outputs: sha256:<64hex>`; (3) `reports/` root may only contain `final_summary.md` + `chip_specific_summary.md`; (4) any sub-gate FAIL inside a step ⇒ verdict FAIL; (5) `final_summary.md` must include the canonical artefact (GDS / netlist / LEF / Liberty / sign-off) SHA256 table. Full version: `commands/_anti_fabrication_rules.md`.
