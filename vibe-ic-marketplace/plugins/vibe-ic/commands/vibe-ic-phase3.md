---
name: vibe-ic-phase3
description: Run a bounded backend Flow109 row through the sole public entry in Default mode. AI-monitored + close-loop.
argument-hint: <project-dir> --route ic|ip --flow109-manifest <manifest.json> --entry-step <D-id> --exit-step <D-id> [--top-name <top>] [--pdk <pdk>]
---
> **Missing arg?** When `$ARGUMENTS` is empty, prompt the user first:
> `/vibe-ic-phase3 <project-dir> --route ic|ip --flow109-manifest <manifest.json> --entry-step <D-id> --exit-step <D-id>`.
> The AI must NOT guess the path; a concrete project path is required before continuing.


# /vibe-ic-phase3 — bounded Flow109 backend entry

**Prerequisite**: every input declared by the selected current Flow109 row must
exist and bind the current project. The manifest must select that row for the
owner-declared IC/IP route.

Main execution (**program-driven**):

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/programs/vibe_ic_one_shot_runner.py $ARGUMENTS \
  --flow 109 --execution-mode default
```

Do not call a backend owner directly. The public entry admits only the exact
current row/window and retains its Flow109 request and attempt. D50 is the
current path-delay ATPG responsibility at position 72, but it has no registered
dispatch today; requesting D50 must refuse before native work. Never replace
that refusal with a former path-ATPG entry. Use another backend ID only after
confirming both its current position and dispatch in `flow/flow109.json`.

After the run completes, the AI must:

1. Read `<project>/reports/flow109/attempts/` and every selected
   `<project>/reports/flow109/components/<D-id>.json`.
2. For a selected registered owner that emits the corresponding artifact, use
   its exact FAIL evidence:
   - **`synth`** FAIL → check `phase3/synth/synth.log`; common: vendor primitive missing black-box (need to add macro `read_liberty -lib`), `SIMULATION` define not effective (runner already set), `assertions.sv` leaking into synth (runner already filters)
   - **`pnr`** FAIL → check `phase3/pnr/openroad.log`; common: site name detected wrong, metal_prefix detected wrong, CTS buffer not in liberty, die size too small (util > 80% requires enlarging die), missing TRACKS (runner already adds `make_tracks`), SDC ref FPGA-only port → close-loop fix `_detect_pdk` heuristic
   - **`gds`** FAIL → check KLayout stream-out log; usually LEF conflict (multiple LEF variants for the same macro) → fix `lef_by_macro` selection logic
   - **`drc` / `lvs`** WAIVED is legal (commercial deck must be run offline); but if .lydrc should exist yet was not found, hint to fix the path
3. A selected-row PASS permits only the next dependency-valid Flow109 request;
   it is not tapeout or whole-flow acceptance.

**Helper skills:** `synthesis-driver` / `pnr-orchestrate` / `drc-orchestrate` / `lvs-orchestrate` / `gds-export` / `tapeout-checklist`

**Rule:** the selected Flow109 attempt and every selected component must be
current and terminal. Missing signoff remains NOT_MEASURED; a row-local PASS is
never promoted to backend or whole-flow PASS by this command.

---

## ⚠ Anti-fabrication 5 hard rules (v1.6.30)

Any violation ⇒ verdict-FAIL: (1) no symlinks under `phase3/stage4/**` (including `gds/`, `foundry_handoff/`) / `phase3/mixed_signal/**` / `analog/hardmacro/**` — `chip_gds_canonical_real_file_check` v1.6.30 made recursive, broken symlinks split into a separate `BROKEN_SYMLINK` rule; exceptions via `.canonical_symlink_allowlist`; (2) every `provenance.jsonl` entry must carry `outputs: sha256:<64hex>`; (3) `reports/` root may only contain `final_summary.md` + `chip_specific_summary.md`; (4) any sub-gate FAIL inside a step ⇒ verdict FAIL; (5) `final_summary.md` must include the canonical artefact (GDS / netlist / LEF / Liberty / sign-off) SHA256 table. Full version: `commands/_anti_fabrication_rules.md`.
