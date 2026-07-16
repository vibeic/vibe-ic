# spm — clean-room validation on commercial foundry commercial_pdk (commercial NDA PDK)

**IC**: `spm` — 32-bit serial/parallel modulo-2^N integer multiplier (`p = (x·y) mod 2^N`; x parallel, y serial, p serial, LSB-first)
**PDK**: **commercial foundry commercial_pdk 180 nm — commercial / NDA.** This report carries NUMBERS ONLY, never PDK/deck/device content.
**Plugin**: vibe-ic **v1.4.30** (repo `/home/reyerchu/vibe-ic` HEAD `5e37ed518`, run from repo source — task said "v1.4.31"; newest on `main` is v1.4.30).
**Toolchain**: `ghcr.io/vibeic/vibeic-eda:0.2.17` (yosys 0.66-vibeic / OpenROAD / OpenSTA 3.1.0 / KLayout 0.30.9 / native `svrfdrc` / netgen / ngspice / iverilog+cocotb / FasterCap 6.0.7).
**§4.05 blind**: only the design INPUT (L1-L23 spec docs) + the commercial PDK were read. No golden/oracle leak. RTL authored from spec.

> **This design is NOT silicon-proven.** Every verdict is a tool/geometry result on the layout, never a fabricated-and-measured result.

---

## 1. Headline

**Verdict: FAIL — does NOT cleanly converge on the newest plugin+image. Two sign-off floors surfaced, both isolated and reported.**

Score (flow_compliance_check `--strict`): **Overall FAIL**. Canonical steps **executed-PASS = 32/39**; **FAIL = 2** — both inside **Step 31 Physical Verification (DRC + LVS)**. Every other dimension passes: Phase 1 (spec→L1-L23), Phase 2 (RTL→synth→sim→LEC), and Phase 3 backend Steps 22-30 (parasitic extraction, multi-corner STA, IR, EM, antenna, SI/MCF crosstalk-delay, post-layout SPICE) all **PASS**.

What was measured: whether spm — reported `PASS_WITH_WAIVERS` on commercial_pdk in an earlier campaign (v1.3.82 / image 0.2.16) — still reaches a clean tapeout sign-off on v1.4.30 / image 0.2.17 from clean-room staging. **It does not:** the raw foundry Calibre deck run through the shipped `svrfdrc` engine false-fires ~12-15 FEOL rules on foundry-qualified std-cell interiors, and LVS misses by exactly one power net. Neither is a design defect; both are engine/tool floors the earlier campaign masked with **unshipped local svrf patches**.

| Dimension | Engine | Result |
|---|---|---|
| Phase 1 spec→L1-L23 | phase1_one_shot_runner | **PASS** |
| Phase 2 RTL→synth | AI spec-to-rtl + yosys | **PASS_WITH_WAIVERS** (599 cells) |
| Functional (unit + professional cocotb) | iverilog + cocotb | **PASS** (streaming scoreboard) |
| LEC (RTL≡netlist, Step 13) | yosys equiv | **PASS** (rc=0) |
| STA multi-corner (Step 23) | OpenSTA on real commercial_pdk Liberty | **PASS** |
| IR / EM / Antenna (24/25/26) | OpenROAD | **PASS** |
| SI / MCF crosstalk-delay (27) | OpenSTA + FasterCap | **PASS** |
| Parasitic extract (22) / SPICE (30) | analytical SPEF / ngspice | **PASS** |
| **DRC sign-off (Step 31)** | native `svrfdrc` on foundry Calibre deck | **FAIL — floor #1** (see §4) |
| **LVS sign-off (Step 31)** | netgen + KLayout NetlistComparer | **FAIL — floor #2** (see §4) |

---

## 2. Shape

**Shape A — full canonical runner**, the intended path (open-benchmark methodology §2).

Entry point:
```
python3 /home/reyerchu/vibe-ic/vibe-ic-marketplace/plugins/vibe-ic/programs/vibe_ic_one_shot_runner.py \
    /home/reyerchu/vibe-ic/benchmark-data/ic/spm/clean_run_v1431_commercial_pdk \
    --pdk custom:pdk --ic-name spm --top-name spm --container vibeic-eda --no-dashboard
```
`--pdk custom:pdk` routes PDK detection to `<run>/input/pdk/` (custom commercial PDK; matches the prior spm commercial_pdk invocation). Digital std cells + sign-off decks staged by SYMLINK under `input/pdk/`, git-ignored (NDA).

---

## 3. Score trajectory

| Stage | Action | Result |
|---|---|---|
| single-shot (runner, no RTL) | runner WAIVES `rtl_gen` for class `digital_arithmetic_primitive` → asks AI to author RTL | phase2 FAIL "rtl/ missing" (expected handoff) |
| close-loop 1 — RTL authoring | AI authored a carry-save serial/parallel multiplier from L2/L3 spec (LSB-first, latency-1, sync active-high reset); **exhaustively self-verified: N=8 all 65 536 pairs = 0 err; N=32 directed corners + 4000 random = 0 err** | phase2 PASS_WITH_WAIVERS; synth/LEC/cocotb PASS |
| single-shot phase3 (initial staging) | first backend run | **DRC {'PASS':4477,'FAIL':56}** — traced to missing LEF/DEF layermap (see below) |
| close-loop 2 — staging fix | restored the foundry LEF/DEF streamout layermap (`KF_common_layermap_for_SOC_encounter.txt`) into `input/pdk/lef/` — my lef curation had dropped it | **DRC 56→15 FAIL** (fuse/thick-oxide/HV garbage cleared; VIA1/2/3 now on foundry numbers 10/12/14) |
| isolation — DRC | ran current deck+`svrfdrc` on the PRIOR clean GDS: 0.2.16 → **12 FAIL**, 0.2.17 → **12 FAIL** (identical) | residual DRC is a **standing svrfdrc floor**, not my GDS, not a 0.2.17 regression |
| final | flow_compliance `--strict` | **Overall FAIL** — Step 31 DRC + LVS; all other 30 steps PASS/skip-clean |

---

## 4. Residual triage (every FAIL → category + evidence)

### FLOOR #1 — DRC sign-off (Category C: tool/engine fidelity floor — FORK)
- **Symptom**: raw foundry Calibre commercial_pdk D4.20 deck (224 layers, 4533 rules) via native `svrfdrc` → `{'PASS':4518,'FAIL':15}` on this run's GDS; dominant fails (rule-IDs/layer-tokens genericized — NDA): an **HV-poly spacing** rule fires **14 744×**, the **N+ and P+ implant-enclosure-of-active** rules fire **1113× each**, a **contact-spacing** rule **1902×**, plus **metal1/upper-metal spacing** rules.
- **Why it is a FALSE-POSITIVE, not a real DRC defect**: (a) spm is a pure **low-voltage** digital multiplier — it contains **zero HV/thick-oxide poly**, so the HV-poly derived layer should be EMPTY and its spacing rule must be 0; 14 744 hits proves the **HV-poly-layer derivation itself mis-fires**. (b) All failing rules are **FEOL** (poly/active/implant/contact); in a flattened digital GDS every FEOL shape comes from the placed **foundry-qualified std cells**, which are silicon-proven DRC-clean — implant-enclosure violations inside them cannot be real.
- **In-container reproduction (proven-negative, isolates the engine)**:
  ```
  # identical deck + identical PRIOR clean GDS, only the image version differs
  docker run --rm --entrypoint /bin/bash -v /home/reyerchu:/home/reyerchu \
      ghcr.io/vibeic/vibeic-eda:0.2.16 -lc "svrfdrc <deck> <prior_spm.gds> <out> --cell=spm"
  #   0.2.16 → {'PASS':4521,'FAIL':12}
  #   0.2.17 → {'PASS':4521,'FAIL':12}   (identical — NOT a 0.2.17 regression)
  ```
  The prior campaign's SPM_SIGNOFF_FINAL claims `{'PASS':4533}` (0 FAIL) at **15911 derivations**; the shipped-image raw deck produces **15897 derivations** (−14) + 12-15 FAIL on the very same GDS. The 14-derivation delta means the prior "0" ran a **different (patched) deck / engine**. This corroborates the recorded fact that the earlier svrf fork fixes were **local/unpushed and the binary was reverted to stock** — i.e. the shipped `svrfdrc` in 0.2.16 **and** 0.2.17 reproduces the false-positives; the prior clean number depended on patches never baked into a shipped image.
- **Proposed fix (fork, not plugin; I report, orchestrator lands)**: fork `github.com/vibeic/klayout` branch `vibeic/svrf-native-drc`, the SVRF derivation engine (`src/plugins/tools/svrf_drc/db_plugin/` → `db::SVRFEngine`). The HV/thick-oxide poly-recognition derivation and the P/N-active + P+/N+ implant-recognition derivations over-fire on foundry-qualified LV std-cell geometry. Diff the derivation results against a real Calibre golden on the foundry cell GDS (a proven-negative corpus) to localize the mis-derived SVRF construct(s), fix in `db::SVRFEngine`, re-bake the image. This is the documented deck-fidelity residual class (over-fire on foundry-qualified std-cell interiors) at full-chip scale. LIVE-NOW vs image-rebake: **needs image re-bake** (the fix is in the baked `libklayout_bd.so` + `svrfdrc` buddy).

### FLOOR #2 — LVS sign-off (Category C: extraction/compare floor — PLUGIN/FORK)
- **Symptom**: netgen terminal verdict **MISMATCH** — Circuit 1 (layout) 3180 devices / **1675 nets** vs Circuit 2 (schematic) 3180 devices / **1674 nets**; **all devices match** (pmos/nmos counts equal both sides), off by **exactly one net** → "Top level cell failed pin matching". KLayout `NetlistComparer` (the OR-path) also **MISMATCH** (NMOS 1590 / PMOS 1589; 5 power-only decaps dropped each side). `power_shorts=0`.
- **Category**: this is the documented spm power-net LVS near-miss (memory: solved previously via **bulk-normalize (NMOS.B→VSS / PMOS.B→VDD) + power-aware extraction + drop-2-filler-decaps + KLayout NetlistComparer MATCH**). All 3180 devices matching with a single unmatched net is a substrate/power-net labeling/merge artifact, not a functional netlist error (LEC already proved RTL≡gate-netlist, rc=0).
- **In-container reproduction**: `reports/phase3/lvs.rpt` (netgen), `phase3/stage3/extracted/spm_klayout_compare.json` (KLayout), `reports/phase3/lvs_verdict.json` (`klayout_compare_verdict=MISMATCH`, `power_only_dropped={layout:5,source:5}`). The filler decap cells (several drive strengths) flatten as unmatched subcells.
- **Proposed fix (I report, orchestrator lands)**: the power-aware LVS path (`lvs_power_aware_netlist_emit.py` + `lvs_power_aware_extract_tcl.py` bulk-normalize) that produced the earlier device-level MATCH is **not driving the off-by-one net to closure on this clean-room GDS** — the single unmatched net is almost certainly a power/substrate tie whose layout label vs schematic pin is not reconciled after decap drop. Localize which net (VSS/substrate) is unpaired in the KLayout compare and extend the bulk-normalize / power-pin-seed step so the OR-path (netgen **or** KLayout) reaches MATCH, as the prior campaign did. Whether this is a staging-provided device layermap gap or a plugin extraction gap should be confirmed by the orchestrator against a known-good spm LVS setup. LIVE-NOW candidate (plugin-side extraction TCL); no image re-bake needed if plugin-only.

### Staging note (my error, FIXED — not a plugin/fork floor)
Floor #1's initial 56→15 delta was **my staging mistake**: I curated `input/pdk/lef/` to a single metal-stack tech LEF (to remove `rglob("*tech*.lef")` ambiguity) and inadvertently dropped `KF_common_layermap_for_SOC_encounter.txt`, so `_discover_lefdef_layermap()` (phase3_one_shot_runner.py:2126) returned None → streamout fell back to legacy via-numbering (VIA1/2/3 on GDS 36-44 instead of 10/12/14) → the deck read them as thick-oxide/fuse/HV markers → 41 extra false rule-fires. Restoring the layermap fixed it. **Plugin-robustness observation (secondary, worth landing)**: when a custom PDK ships a foundry Calibre deck but no discoverable LEF/DEF layermap, the streamout logs `LEFDEF_MAP not applied — legacy numbering` and silently produces a mis-mapped GDS that guarantees a confusing wall of false DRC. A louder WARN / capability-gap (deck present + layermap absent → hard advisory) would prevent this failure mode.

### DFT / DT1 (disclosed skip, not a FAIL)
Step 11 DFT insertion = **SKIPPED-CONDITION** ("OSS ATPG engine-limited pdk=generic" at phase2; not recovered in phase3). The prior campaign reported 96.12% stuck-at via Fault ATPG — this run does not reach it. Disclosed capability-gap, not a design defect; flagged for the orchestrator (DT1 producer #146 present but the arithmetic-primitive class self-skips DFT here).

---

## 5. Tool substitution (per §3)

**The PDK, sign-off decks, std cells, SPICE models are the REAL commercial commercial foundry commercial_pdk — NO substitution.** DRC ran the **foundry's own Calibre `.rule` deck** (not an OSS re-write); STA/SPICE ran the **real commercial_pdk Liberty / device models**. Only the **execution ENGINES** are OSS substitutes for the licensed foundry tools:

| Sign-off task | Licensed reference | OSS substitute used (this run) |
|---|---|---|
| Synthesis | Synopsys DC | yosys 0.66-vibeic (on real commercial_pdk `.lib`) |
| Place & route | Cadence Innovus / ICC2 | OpenROAD |
| STA | Synopsys PrimeTime | OpenSTA 3.1.0 (real commercial_pdk Liberty) |
| DRC | Siemens Calibre | native `svrfdrc` running **Calibre's own deck** (engine substitute only) |
| LVS | Calibre LVS | netgen + KLayout NetlistComparer (real commercial_pdk CDL/`.device`) |
| RC extraction | Synopsys StarRC | analytical SPEF + FasterCap 6.0.7 BEM |
| Logic sim | Synopsys VCS | iverilog + cocotb |

No analog/mixed-signal track (spm is pure digital → A1-A9 / M1-M4 N/A). No fabricated or keyword-matched numbers anywhere.

---

## 6. Reproduce

```bash
# 1. stage (NDA scratch outside git; symlinks into input/pdk, git-ignored):
#    input/pdk/{liberty,lef,gds,calibre,spice} → real commercial_pdk assets
#    input/pdk/lef must include KF_common_layermap_for_SOC_encounter.txt (LEF/DEF layermap)
#    input/pdk/bridge = fresh copy (mutable signoff_config.json)
# 2. run (Shape A):
python3 /home/reyerchu/vibe-ic/vibe-ic-marketplace/plugins/vibe-ic/programs/vibe_ic_one_shot_runner.py \
    /home/reyerchu/vibe-ic/benchmark-data/ic/spm/clean_run_v1431_commercial_pdk \
    --pdk custom:pdk --ic-name spm --top-name spm --container vibeic-eda --no-dashboard
# 3. score:
python3 .../programs/flow_compliance_check.py <run> --strict
python3 .../programs/run_output_completeness_check.py <run>
# DRC-floor isolation (proven-negative):
docker run --rm --entrypoint /bin/bash -v /home/reyerchu:/home/reyerchu \
    ghcr.io/vibeic/vibeic-eda:0.2.16 -lc "svrfdrc <deck> <prior_clean_spm.gds> <out> --cell=spm"  # → 12 FAIL (== 0.2.17)
```
Dataset / run dir: `/home/reyerchu/vibe-ic/benchmark-data/ic/spm/clean_run_v1431_commercial_pdk/` (input/pdk NDA-excluded). Authored RTL: `phase2/stage1/rtl/spm.v`. Deck/GDS numbers only; no PDK content committed.

---

## 7. Sequence / plan status

- **Phase 1 / 2 / analog / mfg**: Phase 1 + Phase 2 executed to PASS_WITH_WAIVERS. Analog (A1-A9) + mixed-signal (M1-M4) **intentionally N/A** (pure-digital IC). Manufacturing Steps 40-44 **awaiting silicon** by design (not silicon-proven).
- **FPGA (Steps 6/39)**: ENV_UNAVAILABLE waiver (no DE10-class board contract for this IC class) — deferred, review_required.
- **Out-of-scope for this validation (reported, orchestrator lands — I do NOT patch plugin/fork)**: FLOOR #1 (svrfdrc SVRF-engine derivation fidelity — image re-bake), FLOOR #2 (LVS power-net off-by-one closure — plugin/fork), the LEF/DEF-layermap-absent robustness WARN (plugin), and DT1/DFT recovery for the arithmetic-primitive class.
- **Convergence status**: this IC **does not converge to a clean sign-off** on v1.4.30 + vibeic-eda:0.2.17 from clean-room staging. The earlier `PASS_WITH_WAIVERS` is **not reproducible** with the shipped image + raw foundry deck; it depended on unshipped local svrf patches. Everything except DRC + LVS converges cleanly.

_Generated by the IC-Expert flow; numbers only; NDA-safe; NOT silicon-proven._
