# spm pilot — systematic lessons for vibe-ic flow enhancement

> User request (2026-05-29): "learn Caravel MPW Precheck progress table
> and process (tier 1-5, phase a/b/c) applied by spm golden sample, to
> see if our vibe-ic flow can be enhanced."

This document mines the spm pilot for **patterns that should be runner
features**, not per-IC hand work. Doctrine: 把修法寫進工具，而非寫進
prompt — every "we discovered we needed X" lesson becomes a plugin
program / runner step, with pytest.

## Part A — What spm pilot actually did

### Tier 1-5 process (per-design sign-off ladder, applied by spm)

| Tier | What it checks | spm initial state | Fix shipped | Plugin program |
|---|---|---|---|---|
| **Tier 1 DRC** | Full SKY130A KLayout deck (not basic) | 1780 violations (basic deck masked them) | density 0.45→0.30 | `phase3_one_shot_runner.py` v0.1.45 |
| **Tier 1.5** | Geographic DRC distribution map | uniform li-rule cluster | (diagnostic only) | — |
| **Tier 2 PDN** | OpenROAD `pdngen` + IR-drop analysis | **zero SPECIALNETS** (silicon-DOA) | global_connection + met1 follow-pin + met4/5 stripes | `phase3_one_shot_runner.py` v0.1.47 |
| **Tier 2 EM/decap** | filler + decap count | **zero decap, zero fill** | `filler_placement decap_3/4/6/8/12 + fill_1/2/4/8` | `phase3_one_shot_runner.py` v0.1.48 |
| **Tier 3 Antenna** | Magic + KLayout antenna deck | 0 violations | — | `eda_antenna` MCP tool |
| **Tier 3 Caravel wrapper** | user_project_wrapper.v + pin map | not authored | 111-line hand wrapper | `caravel_integration/` template |
| **Tier 3 ESD/pad-ring** | sky130 ESD diodes per cell row | clean | — | manual scope |
| **Tier 4 LVS device** | Netgen device-class compare | 261=261 PASS | — | `eda_lvs` (existing) |
| **Tier 4.5 LVS net** | Netgen net-level compare | 531 vs 1340 INCONCLUSIVE | Netgen supplement TCL (14 globals + flatten) | `lvs_netgen_setup_emit.py` v0.1.49 |
| **Tier 5 Latch-up** | tapcell well-tie density | **zero tap cells** (silicon-failing) | `tapcell -distance 14 -tapcell_master sky130_fd_sc_hd__tapvpwrvgnd_1` | `phase3_one_shot_runner.py` v0.1.46 |

### Phase A/B/C (Caravel integration ladder, applied by spm)

| Phase | What it does | spm result | Plugin asset |
|---|---|---|---|
| **Phase A** | Caravel clone + RTL + LEF + config | 30 min (vs 1-day budget) — already signoff-clean core | `caravel_integration/README.md` integration plan |
| **Phase B** | OpenLane wrapper-level PnR | 1m 52s — 2.8 MB wrapper GDS | OpenLane workflow (existing) |
| **Phase C initial** | eFabless `mpw_precheck` Docker | 5 of 7 FAIL initial | (process step) |
| **Phase C cleanup** | mechanical fix-ups | **5/7 → 2/7 FAIL** | (process step) |
| **Phase C flatten experiment** | option 1 remediation | empirically validates 2/7 floor | (experiment doc) |
| **Phase C waiver** | path 3 (real chipignite path) | `signoff_waiver_emit.py` + `signoff_waiver_md_emit.py` | v0.1.49 |

### The 4 silicon-critical bugs spm pilot surfaced

These were ALREADY landed in v0.1.45-48 + pytest-pinned in v0.1.49:

1. **v0.1.45 density default 0.45 → 0.30** (DRC 1780 → 0 on identical die)
2. **v0.1.46 tapcell insertion** (latch-up risk → 384 tap cells @ 14 µm)
3. **v0.1.47 pdngen + global_connect** (silicon-DOA → working SPECIALNETS)
4. **v0.1.48 filler_placement decap + fill** (0 cells → 2079 decap + 150 fill)

Each one's fix is a NONFATAL-guarded Tcl block in `phase3_one_shot_runner.py`,
unit-tested via `_build_tapcell_tcl()` / `_build_pdn_tcl()` /
`_filler_masters_for_pdk()` pure helpers (v0.1.49 regression tests).

### Phase C cleanup — 5 mechanical fix-ups that worked

| Initial FAIL | Fix | Time |
|---|---|---|
| Default (README) | Write spm-specific README replacing stock template | 5 min |
| SPDX (16 dev files) | Add `// SPDX-License-Identifier: Apache-2.0` headers | 10 min |
| GPIO-Defines (33 placeholders) | Fill `USER_CONFIG_GPIO_*_INIT` per pin map | 15 min |
| Documentation ("blacklist") | Patch precheck-self bug (denylist/allowlist) | 5 min |
| Junk files | Delete `*.bak`, `*.orig`, `*.lef.spm` | 1 min |

Floor after cleanup: **2 of 7** (Consistency LAYOUT + XOR — both
hard-macro signoff limitations, requiring waiver entry).

## Part B — Patterns to vibe-ic flow enhancement

Each row below is a **specific deliverable** the vibe-ic plugin should
gain so the spm pattern is reusable for any future hard-macro Caravel
submission.

### B1. Tier-1-5 sign-off ladder as a plugin runner

**Problem today**: vibe-ic `phase3_one_shot_runner.py` runs PnR, but
the 5-tier sign-off ladder (full DRC + PDN-IR + antenna + LVS device +
LVS net + latch-up) is currently per-IC manual work. spm did each tier
by hand and discovered the 4 silicon-critical bugs that way.

**Enhancement**: NEW `programs/signoff_ladder_run.py`:
```
signoff_ladder_run.py --project <p> --pdk sky130A [--include-tier 4.5]
  Tier 1   eda_drc_klayout (full deck, not basic) + zero-violation gate
  Tier 1.5 geographic DRC heatmap (diagnostic JSON)
  Tier 2   pdn_verify_check.py (SPECIALNETS > 0)
           + eda_ir_drop (IR-drop budget gate)
           + decap_count_check.py (>= per-area threshold)
  Tier 3   eda_antenna both Magic + KLayout
           + esd_diode_per_row_check.py
           + caravel_wrapper_lint.py (next item B3)
  Tier 4   eda_lvs (device class, count + cell pin lists)
  Tier 4.5 eda_lvs setup_supplement (lvs_netgen_setup_emit.py)
  Tier 5   tapcell_density_check.py (cells/mm^2 vs PDK threshold)
```

Each tier emits a JSON verdict (PASS / FAIL / WARN / WAIVED). The
runner aggregates into `reports/signoff_ladder.json` with the
canonical `PASS_WITH_WAIVERS` rollup vibe-ic-d already understands.

**Doctrine win**: the next spm-style IC doesn't have to discover bugs
serially. The runner runs all 9 sub-checks and surfaces ALL gaps in
one pass.

### B2. Phase A/B/C as a sub-runner

**Problem today**: phase A/B/C (Caravel integration + OpenLane wrapper
PnR + mpw_precheck) is hand-driven via `caravel_integration/README.md`
instructions. Easy to miss steps; hard to verify.

**Enhancement**: NEW `programs/caravel_integration_runner.py`:
```
caravel_integration_runner.py --project <p> --core-gds <gds>
  --core-lef <lef> --pin-map <yaml> [--shuttle chipignite-MPW-X]

  Phase A:
    - git clone caravel_user_project (cached locally)
    - install core GDS + LEF + Verilog stubs
    - emit user_project_wrapper.v from pin-map YAML  (B3 program)
    - generate openlane/user_project_wrapper/config.json
  Phase B:
    - docker run efabless/openlane:2023.07.19-1
    - flow.tcl wrapper PnR
    - assert: WNS >= 0, TritonRoute violations = 0
  Phase C:
    - docker run efabless/mpw_precheck:latest
    - parse 7-check JSON output
    - run phase_c_cleanup_emit.py (B4) on each FAIL
    - emit final waiver entries (signoff_waiver_emit.py)
```

### B3. Caravel wrapper emit from pin-map YAML

**Problem today**: spm's `user_project_wrapper.v` (111 lines) is hand-
authored. Every future hard-macro project needs the same shape: the
canonical Caravel golden ports + the per-design pin assignments + tie-
offs for unused IOs.

**Enhancement**: NEW `programs/caravel_wrapper_emit.py`:
```yaml
# pin_map.yaml
project_name: spm
core_module: spm
pin_assignments:
  - core_port: clk           # in spm
    caravel_pin: wb_clk_i    # in wrapper
  - core_port: rst
    caravel_pin: wb_rst_i
  - core_port: x[31:0]
    caravel_pin: io_in[33:2]
  - core_port: y
    caravel_pin: io_in[34]
  - core_port: p
    caravel_pin: io_out[35]
unused_tie_offs:
  io_in[1:0]: management_reserved
  io_in[37:36]: tie_0
  io_out[34:0]: tie_0
  io_out[37:36]: tie_0
```

Emits the 111-line canonical wrapper.v deterministically + the
matching openlane config.json + the `USER_CONFIG_GPIO_N_INIT` settings
in user_defines.v.

**Doctrine win**: takes spm-pilot's 111-line hand-authored wrapper
(generic shape) and makes it a deterministic emit from a 30-line YAML.

### B4. Phase C cleanup automation

**Problem today**: spm's Phase C cleanup (5 mechanical fix-ups) was
hand-driven and took ~30 min. Every Caravel hard-macro project will
hit the same 5 mpw_precheck FAILs initially.

**Enhancement**: NEW `programs/mpw_precheck_cleanup.py`:
```
mpw_precheck_cleanup.py --project <p> --pin-map <yaml> --shuttle X

  Reads precheck output JSON, applies known cleanup pattern per FAIL:
    Default (README) → emit project-specific README from template
                        + pin-map data
    SPDX             → add SPDX-License-Identifier headers to dev files
                        (catalog the file types: .tcl, .yaml, .py, .c, .v)
    GPIO-Defines     → fill USER_CONFIG_GPIO_*_INIT per pin-map
                        (default unused = USER_STD_INPUT_NOPULL)
    Documentation    → patch precheck-self bug (denylist/allowlist/
                        secondary) if present
    Junk files       → rm *.bak, *.orig, *.lef.spm
```

Each cleanup is deterministic. Re-runs precheck after each batch.
Emits the `2/7 FAIL` floor with N/A rationale for the remaining
Consistency LAYOUT + XOR (hard-macro signoff limit).

### B5. Hard-macro 2/7 FAIL floor handler

**Problem today**: spm discovered the floor is 2/7 (Consistency LAYOUT
+ XOR, both blackbox-macro hard-limits). The pilot also empirically
ruled out path 1 (flatten — multi-bterm power wall) and path 2 (LEF
with -include_obs — doesn't move wrapper GDS XOR). The practical path
is **path 3 (waiver)**.

**Enhancement**: this is ALREADY in v0.1.49 with `signoff_waiver_emit.py`
+ `signoff_waiver_md_emit.py`. Need to AUTO-INVOKE them from B2's
Phase C step when the 2 FAILs remain after B4.

Wiring: `caravel_integration_runner.py` Phase C, after cleanup:
- IF remaining FAIL set == `{"Consistency","XOR"}`: auto-emit the
  pair of waivers via signoff_waiver_emit + the SPM_CHIPIGNITE_WAIVER.md
  template per signoff_waiver_md_emit.
- IF remaining FAIL set != `{"Consistency","XOR"}`: STOP and require
  human triage (something other than the known floor).

### B6. Open-source LVS net-level supplement (already shipped)

`programs/lvs_netgen_setup_emit.py` (v0.1.49). Demonstrated to apply
cleanly to spm Tier 4.5; doesn't close THIS specific net-level gap
(interconnect-naming gap dominates), but the rule is deterministic
and the program ships correct. Future designs whose gap IS power-net
globalisation will close fully.

### B7. Silicon-critical NONFATAL guard checks (regression tests)

ALREADY shipped in v0.1.49 — `_build_tapcell_tcl()`,
`_build_pdn_tcl()`, `_filler_masters_for_pdk()` are pure helpers with
11 pytest cases pinning the silicon-critical Tcl block presence.

**Add to ladder run**: the signoff_ladder_run from B1 should also
deliberately probe for these in the OpenROAD Tcl that the runner
emits, so the chain "runner emits → ladder verifies" is end-to-end
checked.

## Part C — Summary of recommended new programs

| New program | Pattern | Effort | Closes |
|---|---|---|---|
| `signoff_ladder_run.py` | B1 — chip-level 5-tier ladder | 300 LOC + 30 pytest | Replaces per-IC manual tier discovery |
| `caravel_integration_runner.py` | B2 — Phase A/B/C orchestrator | 200 LOC + 20 pytest | Replaces 3-step hand workflow |
| `caravel_wrapper_emit.py` | B3 — pin-map YAML → wrapper.v | 250 LOC + 25 pytest | Generalises spm's 111-line wrapper |
| `mpw_precheck_cleanup.py` | B4 — auto-fix 5 mechanical FAILs | 200 LOC + 20 pytest | Replaces 30-min hand cleanup |
| (already shipped: lvs_netgen_setup_emit + signoff_waiver_emit/md) | | | |

Total new code: **~950 LOC + ~95 pytest cases** to make the spm
golden-sample reproducible end-to-end without per-IC hand work.

## Part D — How this closes the doctrine loop

The spm pilot is the **operational evidence** for "把修法寫進工具":

- 4 silicon-critical bugs discovered serially by hand → captured as 4
  Tcl-block emitters in `phase3_one_shot_runner.py` + 11 regression
  pytest cases ← already done, v0.1.49
- LVS net-level open-source gap → captured as `lvs_netgen_setup_emit.py`
  + 33 pytest cases ← already done, v0.1.49
- mpw_precheck waiver shape → captured as `signoff_waiver_emit.py` +
  `signoff_waiver_md_emit.py` + 33+26 pytest cases ← already done, v0.1.49

What spm pilot did NOT yet capture as plugin program:
- **The 5-tier ladder** (B1) — currently lives in TIER_RESULT_*.md prose
- **Phase A/B/C orchestrator** (B2) — currently lives in
  `caravel_integration/README.md` prose
- **Caravel wrapper emit** (B3) — the 111-line wrapper is hand-authored
- **Precheck cleanup** (B4) — the 5 fix-ups are hand-driven

These 4 are the **next round** of capturing-spm-as-tool, and would let
the doctrine principle apply to the ENTIRE end-to-end Caravel shuttle
submission, not just the per-step pieces.

## Part E — Suggested next batch

1. **B3 first** (smallest, highest reuse): `caravel_wrapper_emit.py`
   takes a 30-line pin-map YAML and emits the 111-line wrapper
   verbatim. Every future Caravel IC starts with this. Cost ~250 LOC.

2. **B4 second** (closes the 30-min hand cleanup): `mpw_precheck_cleanup.py`
   reads precheck JSON output, applies known fix-up per FAIL. Cost
   ~200 LOC. The 5 specific fix-ups are already documented; this is
   pure tool-encoding.

3. **B1 + B2 third** (the orchestrator wrapper): `signoff_ladder_run.py`
   + `caravel_integration_runner.py` — these are the runner-level
   pieces that compose B3 + B4 with existing PnR + the eFabless Docker
   images. Cost ~500 LOC.

After all four ship: a future user with a clean spm-class core can
type ONE command:
```bash
python3 caravel_integration_runner.py my_project \
    --core-gds my_project.gds --pin-map my_pinmap.yaml \
    --shuttle chipignite-MPW-X
```

…and get a chipignite-ready submission in ~30 minutes wall time. The
spm pilot's 2-day discovery becomes a reproducible runner.
