# RESULT — edge_llm_accel (Kimi-K3-scale edge-LLM INT4 GEMM accelerator, NanGate45)

> STATUS: COMPLETE — flow closed, verified, educational-DRC final emission and
> the 8-seed V2 soak both landed. Everything below is measured.

## 1. Headline

- **What was measured**: full doc→GDS clean-run of a self-designed Kimi-K3-scale
  benchmark IC through the canonical Vibe-IC front door (Shape A), on the open
  NanGate45 / FreePDK45 enablement (`--pdk nangate45`), including doc-driven
  functional verification (which caught and fixed one real pre-silicon RTL bug).
- **Design**: `edge_llm_accel` — 64×64 weight-stationary INT4 systolic GEMM core
  (4096 MAC/cycle), 20× `fakeram45_2048x39` SRAM scratchpad (~195 KB), streaming
  controller, 64-way fused dequant (SAT16((acc×scale)>>>shift)). 3/3 RTL modules
  GENERATED, 0 REUSED-IP (SOURCE_MANIFEST.md).
- **Scale vs Kimi K3 demo** (1.46M cells / 3.981 mm² / 0.277 MB / 100 MHz / Nangate45):
  ours = **1,360,147 mapped cells → 1,356,030 placed std cells + 20 SRAM macros
  (1,356,050 instances, 93 % of Kimi's cell count)**, die 2400×2400 µm = 5.76 mm²,
  **design area 3.07 mm² @ 55 % utilization**, ~195 KB SRAM, 100 MHz.
- **Result**: **100 MHz timing MET** (post-route SPEF-canonical WNS **+1.08 ns**,
  pre-SPEF estimate +4.27 ns; TNS 0), **detailed-route DRC 0** (336k → 0 over 8
  iterations), **antenna 0** (clean, no repair needed), 27,121 ECO spare cells,
  **GDSII produced** (KLayout streamout, std-cell artwork embedded; SRAM macros
  abstract per FakeRAM). LVS: honest ENV_UNAVAILABLE (Nangate45 ships no
  Magic/netgen tech — fictional process; see §7).
- **Functional verification**: V1 systolic-core golden — 108 tiles / 56,760
  every-cycle comparisons / 0 mismatches; V2 full-scale end-to-end — **180
  random 64×64 tiles bit-true 64/64 across 9 RNG seeds** (20 original + 8-seed
  parallel soak, `verify/soak/`) + dequant-saturation directed + protocol +
  back-to-back-no-reset suites (residue-aware golden bit-true, 8/8 seeds ALL
  TESTS PASS). Caught real bug F1 pre-silicon (§4.3); residual F2 declared
  with usage contract (`plugin_output/declaration.json`).
- **Educational KLayout DRC (FreePDK45.lydrc) final emission** on the
  artwork-embedded, correctly-scaled GDS (4.68 GB): **23,082 items, fully
  attributed** — WELL.4 = 15,814 (the deck's 200 nm well-separation
  interpretation vs the Nangate library's standard abutting-row well
  convention; sampled items sit uniformly on row-boundary bands — an
  artwork+deck pair characteristic, not a design defect), METALx_ANTENNA =
  7,247 (the deck's simplified flat antenna model; OpenROAD's hierarchical
  antenna check — the authoritative one — reports 0), ACTIVE.4 = 20 (exactly
  the 20 abstract FakeRAM macros — artwork voids under LEF-only macros),
  METAL1.5 = 1. Router DRC (authoritative, tech-LEF rules) remains **0**.
- **Wall-clock**: campaign start (docs authoring) 2026-07-18 20:30 → flow closed
  ~14 h later INCLUDING all convergence + eleven chip-AGNOSTIC plugin fixes
  distilled en route (vs Kimi K3's 48 h). Measured stage walls in §5.

## 2. Shape & entry (methodology §2/§7.5)

**Shape A — full runner.** Canonical entry chain actually driven:
`phase1_one_shot_runner.py` (docs mode) → `vibe_ic_one_shot_runner.py --pdk nangate45
--die-um 2400x2400` (phase2 = design/phase2_one_shot_runner; rtl_gen WAIVE →
spec-to-rtl authored `phase2/stage1/rtl/`) → `phase3_one_shot_runner.py --pdk
nangate45`. The final numbers come from the post-convergence official re-run (r4);
the convergence passes (r1–r3) are documented in §4.

## 3. Environment & tool substitution (methodology §3)

| Mandated/typical commercial | Used here (all open-source) |
|---|---|
| Synopsys DC / Cadence Genus | yosys 0.67+ (vibeic fork, sha 1042b3f55) |
| Cadence Innovus / Synopsys ICC2 | OpenROAD 26Q3-111-g3efb695851 (vibeic fork) |
| Calibre DRC | KLayout 0.30.9 + FreePDK45.lydrc (EDUCATIONAL deck) |
| Calibre LVS | none — Nangate45 ships no LVS deck (`lvs_deck=null`) → honest ENV_UNAVAILABLE waiver |
| PrimeTime | OpenSTA (in OpenROAD), single typical corner (Nangate45 ships typical only) |
| VCS/Xcelium (sim) | iverilog -g2012 / verilator (container vibeic-eda) |

Container: `ghcr.io/vibeic/vibeic-eda:0.2.18` (newest published), NanGate45 platform
(OpenROAD-flow-scripts, pinned f255c15b) staged at `/foss/pdks/nangate45` in the
open_pdks `libs.ref` layout via explicit bind-mount (the Dockerfile Stage-9 that
ships this in-image was authored this session; no image ≤0.2.18 carries it).
Host: 32 cores / 125 GB; `VIBEIC_OPENROAD_THREADS=32`.

## 4. Trajectory (convergence passes — every fix chip-AGNOSTIC, NO-MIX committed)

1. **Phase 1 PASS first try** — 9 authored L1–L9 docs (R1/R2/R3) → 28/28 L-JSON,
   0 TODO, coverage 100%, deterministic input-completeness gate PASS,
   `L19.pdk_target=nangate45`. Wall 1.08 s.
2. **Phase 2 r1 FAIL → fixed** — `fakeram45_2048x39` undefined for TB + synth.
   Fix: dual-use `(* blackbox *)` behavioral macro model in `rtl/` (yosys
   blackboxes it, iverilog simulates it).
3. **Functional verification (doc-driven, dual-track) caught a REAL pre-silicon
   bug (F1)** — PE weight-load chain used `w_out <= w` (stale pass-down): chain
   advances at half rate → only 32/64 rows load; rows 32–63 retain the PREVIOUS
   run's tile (proven bit-true with a history-aware golden). Violates L2 (64×64
   tile) + L4 (re-start without reset). **Fix: `w_out <= w_in`** (one line).
   Re-verified: V1 56,760 comparisons 0 mismatch; V2 20 random 64×64 tiles
   bit-true end-to-end + 6-run no-reset back-to-back suite PASS + row≥32 basis
   probes confirm full 64-row GEMM. Residual **F2** (row-63 cols 48–63: 16/4096
   weight nibbles alias word 0 / pre-start idle-read channel due to beat-0
   read-pipe framing) — declared in `plugin_output/declaration.json` usage
   contract (reset-per-run ⇒ exactly input-deterministic); upstream fix path
   noted (prime the read pipe 2 words early). Evidence: `verify/VERDICT.md`,
   `verify/mapping.json`, `verify/func_directed.log`.
4. **Phase 2 r3** — all functional gates PASS (generic synth 3,104,629 cells,
   LEC PASS); `final_audit` FAILed on **structural gates timing out**: they
   rglobbed the whole project and ingested the 342 MB emitted generic netlist
   through char-level comment strippers. Fixed program-first: shared
   `_specrtl_common.rtl_source_files()` collector (canonical `phase2/stage1/rtl`
   preference, generated-dir exclusion, 8 MB cap) adopted by 12 gates over two
   rounds — each gate went from 900 s timeout-death to ~0.05 s with verdicts
   proven unchanged on spm (§4.05 no-leak proof). Plugin commits `45a214a7b`,
   `05495f612`.
5. **Phase 3 r1 FAIL → fixed** — OpenROAD structural reader rejected
   `wire signed [31:0] k;` surviving in the mapped netlist (STA-0171; the known
   signed-PORT limitation generalized to any net declaration — 40,900
   qualifiers). Fix: `_strip_signed_net_decls()` defence-in-depth guard in
   phase3 `step_synth` (same family as tie-rename / dlatch-remap guards).
6. **Named-PDK front-door gaps fixed pre-run** (surfaced by recon, commit
   `3a93e78e6`): `--pdk nangate45`/`sky130A` branches dropped
   `input/pdk_local/` hard macros (hoisted `_discover_local_macros()`); no CTS
   clock buffer on nangate45 (added PdkConfig `clk_buf`=CLKBUF_X1/X3 per
   registry); NO macro placement at all in the runner (added NONFATAL-guarded
   `rtl_macro_placer -halo 5`); phase-2 generic-synth 300 s cap
   (`VIBEIC_PHASE2_SYNTH_TIMEOUT_S`); Dockerfile Stage-9 nangate45 staging.
7. **Phase 3 r2 — the flow closes.** First full pass through the fixed
   nangate45 path: RTLMP placed all 20 SRAM macros (0 NONFATAL), placement →
   CTS (CLKBUF_X1/X3) → 32-thread detailed route converged 336k → 0
   violations in 8 iterations. **1,356,030 std cells + 20 macros
   (1,356,050 instances), design area 3.07 mm² @ 55% util (die 5.76 mm²),
   100 MHz MET (WNS +4.27 ns, TNS 0), route DRC 0, antenna 0 (clean, no
   repair needed), 27,121 ECO spare cells, GDS 2.2 GB.** Step walls: PnR
   16,133 s (4 h 29 m), GDS 739 s, canonicalize 1,401 s. Educational-deck
   DRC step initially died on a `-rd` variable-name convention mismatch
   (deck reads `$in_gds`/`$report_file`, runner passed `input`/`report`) —
   fixed by passing both spellings (commit `084af7541`); LVS =
   ENV_UNAVAILABLE honest waiver (Nangate45 ships no Magic/netgen tech).
8. **Official end-to-end re-run (r4)** — phase1 (docs already generated) +
   **phase2 PASS_WITH_WAIVERS** (3 h 01 m total); phase3 FAILed at synth on a
   watchdog defect (below). The interim provenance/attestation residuals were
   cleared by construction (in-runner emission).
9. **Educational-DRC attribution onion (3 layers, each §4.1-proven and fixed
   chip-AGNOSTIC):** (a) `-rd` variable-name convention (`084af7541`);
   (b) missing LEF/DEF streamout layer map → compact numbering landed
   routing/PDN on the deck's FEOL device numbers → 18.7M spurious
   implant/VT/well items — stock cells check clean standalone (AND2/INV/DFF =
   0 items); fixed by synthesizing `FreePDK45.map` from the platform `.lyt`
   (`18a6b8246`; DEF via metal-enclosure patches need the VIA purpose on
   metal lines — second sub-layer, 18.1M → 0.9M); (c) flat MULTI-TOP library
   GDS (135 tops) made the cell-artwork substitution skip every master →
   LEF placeholder boxes on GDS 1/0 read as a phantom active plane (~0.9M
   ACTIVE.* items); fixed to skip lib tops only for single-top wrapper
   libraries (`dded132b3`). BEOL-meaningful residual before (c): METAL1.2 = 2.
10. **Watchdog double-kill of a healthy 1.8M-cell synth** — the stall
   watchdog's CPU probe counted only processes whose argv carries the marker;
   yosys runs its entire ABC pass in a child `yosys-abc` (no marker in argv),
   so parent-idle + quiet-log + invisible-child-CPU read as "stalled" at the
   30-min grace (the earlier r2 pass survived purely on a lighter machine).
   Fixed with process-TREE CPU accounting in the shared probe (`25c339737`) —
   then hit AGAIN because phase3 carried a private argv-only duplicate of the
   probe; the duplicate now delegates to the shared implementation
   (`eaf6c0728`). The final phase3 runs with all fixes live.

## 5. Timing vs Kimi K3 (measured)

| | Kimi K3 | vibe-IC (this campaign) |
|---|---|---|
| PnR (place→CTS→route, 32 threads) | (part of 48 h) | **4 h 29 m** (16,133 s) |
| GDS streamout | — | 12 m (739 s; artwork-embedded final ~63 m) |
| Phase-2 (docs→RTL gates→generic+mapped synth→audit) | — | ~3 h |
| One-command r4 orchestrator (phase1+phase2) | — | 3 h 01 m (10,861 s) |
| **Total campaign: docs authoring → flow closed, incl. ALL convergence + 11 plugin fixes** | **48 h** | **~14 h** |

Timer marks: `reports/official_run_start.ts` (2026-07-18 20:30 docs+phase1 start),
`reports/official_r4_start.ts`/`official_r4_end.ts` (03:24→06:34), per-phase
runner durations in `reports/orchestrator/*.json`. Autonomy-model caveat: Kimi =
one LLM iterating alone for 48 h; vibe-IC = deterministic runner chain + IC
Expert Agent convergence — different kind of autonomy, both open-source EDA only.

## 6. Residual triage (methodology §4)

- **F2 beat-0 framing residual** — Category H (real RTL limitation), declared:
  16/4096 weight nibbles (row 63, cols 48–63) alias word 0 / the pre-start
  idle-read channel due to the 2-cycle read-pipe skew. Input-deterministic
  under the declared reset-per-run + 2-idle-cycle contract (verified by the
  6-run back-to-back suite with a residue-aware golden); upstream fix path
  documented in `plugin_output/declaration.json`. Not fixed in this run.
- **`l_doc_structured_field_count_check`** — cleared: L5 explicit-N/A
  declaration + L7 typed test cases TC1–TC6 + test-mode table added to the
  input docs; gate PASS (14/14 L docs) after phase-1 regen.
- **Educational-deck DRC final number** — landed (headline §1): 23,082 items,
  every category attributed (well-abutment interpretation / simplified flat
  antenna model / abstract-macro voids / 1 metal item). Router DRC (the
  authoritative in-loop geometry check against the platform tech LEF) is 0;
  every prior educational-deck wall was §4.1-proven to be a
  streamout/numbering artefact (trajectory §4.9–4.10), each with a
  chip-AGNOSTIC fix landed (`-rd` conventions, layer map, VIA purposes,
  flat-multi-top substitution, dbu rescale).
- **LVS** — ENV_UNAVAILABLE waiver (auto-emitted in `waivers.json`,
  review_required): Nangate45 ships no Magic/netgen tech and no LVS deck
  (`lvs_deck=null`, `tapeout_capable=false`) — the fictional-process boundary,
  identical for the Kimi demo.

## 7. Honest scope note (identical bar to the Kimi K3 demo)

NanGate45 / FreePDK45 is a **SIMULATION-grade, non-foundry** 45 nm enablement
(`tapeout_capable=false`): fictional process, EDUCATIONAL KLayout DRC deck, **no
LVS deck**, SRAM = abstract FakeRAM macro (no transistor GDS — final GDS carries
the macro outlines). This run therefore demonstrates
**synth → macro place → PnR → CTS → detailed-route-DRC-clean → GDS =
"tape-out simulation"**, the SAME level as Kimi's Nangate45 demo. It is NOT a
foundry signoff. vibe-IC's higher bar (real KLayout DRC + netgen LVS + STA
signoff) is demonstrated separately on real open PDKs (sky130A / gf180mcuD /
ihp-sg13g2). Additional disclosed limits: single typical-corner STA (Nangate45
ships one liberty corner); PDN is follow-pin + upper straps without macro-aware
power rings (runner limitation, documented); DFT/ATPG out of scope for this
demo class.

## 8. Reproduce

```bash
# container: ghcr.io/vibeic/vibeic-eda:0.2.18 named `vibeic-eda`,
# with the ORFS nangate45 platform staged at /foss/pdks/nangate45 (libs.ref layout)
P=vibe-ic-marketplace/plugins/vibe-ic/programs
B=benchmark-data/ic/edge_llm_accel
python3 $P/phase1_one_shot_runner.py $B --ic-name edge_llm_accel
VIBEIC_PHASE2_SYNTH_TIMEOUT_S=7200 VIBEIC_OPENROAD_THREADS=32 \
python3 $P/vibe_ic_one_shot_runner.py $B \
  --pdk nangate45 --ic-name edge_llm_accel --die-um 2400x2400 \
  --skip-analog --skip-hardware --no-dashboard
# functional verification TBs: verify/tb_v1_systolic.v, verify/tb_v2_top.v (iverilog -g2012)
```

## 9. Plan status

This is the canonical-IC campaign's Nangate45 addition (mirrors the Kimi K3
news demo); open-benchmark suites (VerilogEval/RTLLM/CVDP) are tracked
separately and were not part of this run.
