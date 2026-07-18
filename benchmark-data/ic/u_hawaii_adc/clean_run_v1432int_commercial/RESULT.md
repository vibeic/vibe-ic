# u_hawaii_adc — commercial-180nm real-node analog RE-VERIFY (clean_run_v1432int_commercial)

**Purpose.** Clean-room A/B re-verify of the analog PDK-consume PLUGIN fix
(composed-shim corner selection + MC-lib ranking + multi-terminal PMOS +
15-corner N/P-skew grid) end-to-end on the REAL commercial-180 nm device models,
driven through the runner and simulated on the **0.2.20-int** container's
`ngspice-46+`. Baseline for the A/B is the committed
`clean_run_v1432_commercial` (Pillar-5 PASS, both blocks 15/15 real PVT corners +
native Monte-Carlo 100 % yield).

- IC: 6× incremental delta-sigma modulator + 1 on-chip LDO (analog in, serial
  digital out; 1.2 V core from an on-chip LDO off 1.8 V IOVDD).
- PDK: a commercial 180 nm PDK, staged out-of-repo under `input/pdk/` (rung-1
  `project_custom_pdk`; symlinks, git-excluded). Name/SKU/foundry omitted per NDA.
- Image: fresh throwaway container off `:0.2.20-int` (image id `fa8cb8…`),
  separate from the long-running 0.2.19 container (left untouched). Tools
  dispatched into it via `--container`; the plugin runs from the working tree
  (the analog-consume fix is a plugin change on main, NOT image-gated).
- Input: ONLY `input/docs/{L1_DATASHEET, L5_ANALOG_SPEC, L9_CONSTRAINTS}.md`.

## NDA discipline (ABSOLUTE)
- RESULTS-ONLY, NDA-EXCLUDED. No PDK name / SKU / foundry / rule-id / model
  parameter / library / section token appears here. Only metric VALUES, PASS/FAIL,
  and tool return codes are reported. Model libs, decks, and logs are git-excluded;
  the tools read the models by PATH — only tool OUTPUT is reported.
- NEVER "silicon-proven". Simulated results against released device + statistical
  models; foundry sign-off is a separate human-owned gate.
- **HV LDMOS models are reduced-fidelity** (per the ngspice-shim WARNING). This IC
  uses ONLY the LV (1.8 V) CMOS core devices — no HV path is claimed. The HV
  reduced-fidelity caveat is disclosed and does not affect these results.

---

## /benchmark-verify — six-pillar verdict (numbers-only)
Pillar-5 (analog closed-loop) is the focus and is **FAIL**: the analog corner-sweep
gate produced **no scoreable output** (rc=2, `corner_results.json` not written, so
`analog_corner_sweep_check` did not run). Corners executed **0/15** for BOTH
blocks; MC not reached. Other pillars unchanged from baseline scope (table below).

---

## HEADLINE VERDICT — Pillar 5 **FAIL** in this run (REGRESSION vs baseline)

The plugin analog-consume path, at current `main` HEAD on the 0.2.20-int
`ngspice`, against the currently-staged commercial PDK, **does NOT reproduce the
baseline flagship**. The corner sweep returns **rc=2 ("no successful sim") for
BOTH blocks — 0/15 corners executed, no Monte-Carlo reached.**

### Why this is an A/B regression (git ordering)
The baseline commit (`432ecbd0…`) is an **ancestor of** the analog-consume fix
commits (`4340632f…` → `a6b5a797…`) — i.e. the committed baseline's 15/15 + MC
flagship was produced by the **pre-fix raw-lib path** (each corner selected a raw
process-corner section lib that sits in the SAME directory as its siblings, so
`ngspice`'s relative `.lib` includes resolved). The fix then landed AFTER the
baseline and changed the resolver to **prefer the enhanced composed corner shim**
(the shim carrying the 15 N/P-skew sections). At HEAD that shim is now selected
— and it fails to consume the models (see root cause).

## A/B focus table (as requested)

| Metric | Baseline (pre-fix raw-lib path) | Re-verify @HEAD (post-fix composed-shim path) |
|---|---|---|
| delta_sigma corners executed | **15 / 15** | **0 / 15** (rc=2) |
| delta_sigma native MC yield | **100 %** (n=50, σ 0.247 dB) | not reached |
| ldo corners executed | **15 / 15** | **0 / 15** (rc=2) |
| ldo native MC yield | **100 %** (n=50, σ 0.056 mV) | not reached |
| corner-sweep return code | **rc=0** (real_ngspice_commercial180) | **rc=2** (UNSCOREABLE — worse than the old rc=1) |
| `analog_corner_sweep_check` gate | PASS (2/2 blocks, 15/15, MC 100 %) | not produced (no `corner_results.json` written) |
| **Pillar 5** | **PASS** | **FAIL** |

Composed-shim / project_custom_pdk SELECTION did fire (the deck header carried the
native-custom-PDK marker `source=project_custom_pdk rung=1`, and the resolver
correctly preferred the composed shim). But CONSUMPTION failed at the `ngspice`
include-resolution step — so the answer to "did the selection consume the real
models, rc=0?" is **NO: rc=2**.

## Root cause (single, precise, reproducible for BOTH blocks)
The resolver ranks the **enhanced composed corner shim highest** (it carries the
most corner sections — the 15-skew grid added by the fix). The plugin then runs
`ngspice` with `sim_cwd = the shim's own directory`. But that shim `.include`s its
sibling process-corner libs by **bare relative name**, and those bare libs are
**NOT co-located in the shim's directory** — they live in the raw-lib directory.
From `cwd = shim-dir`, `ngspice` cannot find the bare include →
`ERROR, library file … not found → fatal → exit(1)` on EVERY corner → the driver
reports "no successful sim" → rc=2, no `corner_results.json`, no MC.

The pre-fix baseline avoided this because it selected a raw corner lib that is
itself co-located with its siblings; the post-fix shim is staged in a directory
that holds only the alternate (suffixed) variants of those sibling libs.

## Isolation proof — the models, the shim, and 0.2.20-int ngspice are all SOUND
Re-running the **same shim-based LDO deck** (the exact deck the plugin emitted)
from the **raw-lib directory** (where the shim's bare sibling includes DO exist)
on the 0.2.20-int `ngspice` produced a clean measurement:

- **LDO Vout = 1.19878 V** (feedback node 0.599 V) — matches the baseline LDO
  Vout (≈ 1.1998 V).

So the defect is **purely** the `sim_cwd` / co-location mismatch in the plugin
path — not the models, not the composed shim's electrical content, not the
0.2.20-int simulator.

## Second, narrower residual (delta_sigma only)
Even with the include resolved (running the delta_sigma OTA deck from the raw-lib
directory so the lib loads), the OTA transient/AC measures still failed —
`measure … : out of interval` and `no such vector as gain` — i.e. no settle /
no gain vector was produced against the enhanced composed section. The LDO deck
does NOT show this. So beyond the cwd fix, the delta_sigma OTA template needs
attention to bias/converge against the composed-shim corner section; the LDO path
is clean once the cwd is right.

---

## Six-pillar summary (this re-verify)

| Pillar | Status | Note |
|---|---|---|
| 1 · Functional coverage | **FAIL (analog)** | Neither analog block closed on the real node this run — corner sweep rc=2. |
| 2 · 56-step output vs OSS ref | Spec-level only | No 180 nm-fab golden die; cross-check stays spec-level (as baseline). |
| 3 · Code coverage ≥90% | N/A | Digital readout is node-independent; not re-exercised in this analog-core run. |
| 4 · FPGA digital verify | WAIVED | No board contract for this analog IC. |
| **5 · Analog closed-loop** | **FAIL** | **0/15 corners both blocks, no MC — the focus pillar; a regression vs the baseline PASS.** |
| 6 · Design-for-ECO (spare) | N/A | Analog blocks have no digital PnR spare-cell surface. |

Runner phases this run: phase1 **PASS** (24/24 L-docs, coverage 100 %), phase2
**PASS_WITH_WAIVERS**, analog **FAIL** (A4 waived to the skill layer, then the
skill-layer corner sweep returned rc=2), phase3 **FAIL** (backend unauthored —
same scope boundary as baseline).

## Residual triage (honest — DONE vs BLOCKED)
- **DONE:** Phase 1 (100 %), Phase 2 (PASS_WITH_WAIVERS), PDK resolved as rung-1
  `project_custom_pdk` (commercial 180 nm), composed-shim SELECTION fired, and the
  models + shim + 0.2.20-int ngspice proven sound (LDO 1.199 V isolation run).
- **BLOCKED (regression):** the analog-consume corner sweep + native MC —
  `sim_cwd` = shim-dir defect blocks BOTH blocks (rc=2); delta_sigma additionally
  needs OTA-template convergence against the composed section.
- **Not attempted (scope, as baseline):** analog A5–A9 and the digital-readout
  backend / full-chip PnR.

## Backlog for the analog-consume-fix owner (chip-AGNOSTIC)
1. **[HIGH] Composed-shim `sim_cwd` / include-root defect.** When the resolver
   selects a composed corner shim, run `ngspice` from (or add to the include path)
   the directory that actually holds the shim's bare-name sibling corner libs —
   not blindly the shim's own directory. Rank/select a shim as usable only if its
   bare relative includes resolve from the chosen cwd (a "runnable-in-place"
   check), or co-locate the sibling libs. This alone recovers the LDO to
   real-node PASS.
2. **[MED] delta_sigma OTA template vs composed section.** After (1), the
   delta_sigma OTA transient/AC still yields no settle/gain vector against the
   composed corner section (LDO is unaffected) — the OTA deck needs bias/tstop
   attention for the composed-shim path.

## Provenance / reproduce
- Image: `ghcr.io/vibeic/vibeic-eda:0.2.20-int` (id `fa8cb8…`), throwaway
  container; tools dispatched via `--container`; plugin from working-tree `main`.
- Entry: `vibe_ic_one_shot_runner … --pdk auto` (Shape-A), then per-block
  `analog_real_corner_sweep.py --block {delta_sigma,ldo}` (the designed
  skill-layer fall-through after the runner WAIVES A4).
- Run artifacts (decks / `*.ngspice.log`, absent `corner_results.json`) are
  git-excluded for NDA hygiene; only this RESULT.md + `.gitignore` are committed.
