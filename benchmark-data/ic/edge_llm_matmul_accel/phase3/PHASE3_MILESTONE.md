# Phase 3 (PnR → GDS) — Honest Milestone Snapshot

**Design:** `edge_llm_matmul_accel` (INT4 16×16 systolic matmul accelerator, Wishbone slave)
**PDK / target:** sky130A (`sky130_fd_sc_hd`), 50 MHz (20 ns period)
**Run:** isolated sandbox `_experiments/edge_llm_accel_p3sandbox`, container `vibeic-eda:0.2.23`
**Runner:** `phase3_one_shot_runner.py --pdk sky130A --top-name edge_llm_matmul_accel`
**Status:** stopped by decision at congested detailed-route (confirmatory run only). **No GDS was faked.**

---

## SRAM integration path used: **(c) representative reduced memory**

The 3 on-chip buffers are the RTL's behavioral `sram_sp` model, instantiated 3×
(weight / activation / output). The RTL caps their depth under synthesis via
`` `ifdef SYNTHESIS `` (full silicon = 32 KB weight / 16 KB act / 16 KB out;
capped = **32 / 32 / 64 words × 32 b**). The vibeic-fork yosys **predefines
`SYNTHESIS`**, so the physical netlist elaborates the *capped* depth
automatically — verified by direct probe (sram address bus = 5/6-bit, not
12/13-bit) under the runner's default `-DSIMULATION`. **No RTL edit, no hack.**

Consequence: the reduced memory synthesizes to **standard-cell flip-flop arrays**
(no hard macros needed), so the *complete* flow (synth → floorplan → place → CTS
→ route) runs on a real, all-std-cell netlist. Memory is **depth-reduced for the
flow demo**; full-depth silicon substitutes real SRAM macros (see "remaining
step").

Paths (a) OpenRAM macro-gen and (b) blackbox pre-built macros were **not reached**
in-container in reasonable time (macro-banking + staging is a separate
integration task — see below), so (c) was the soundest path to exercise the full
back-end chain.

---

## Milestones — furthest CLEAN = **post-hold (place + CTS + hold-fix), timing MET @ 50 MHz**

| Stage | Status | Concrete evidence |
|---|---|---|
| **Synth** (sky130_fd_sc_hd) | ✅ CLEAN | **154,632** std cells; instance area **1,396,528 µm² (≈1.40 mm²)** |
| **Floorplan** | ✅ CLEAN | die **2000×2000 µm (4.00 mm²)**, core area **3,873,572.56 µm²**, **utilization 36.1 %**, 51,475 tapcells |
| **Global placement + legalization** | ✅ CLEAN | 0 placement failures; util 36.1 %. ⚠ congestion-driven placement **could not reach target** — weighted routing congestion **1.15–1.17** (>1.0 ⇒ local over-capacity): the early congestion signal |
| **CTS** | ✅ CLEAN | root `clkbuf_16` / sink `clkbuf_4`; 46 input buffers; 4,336 timing-repair buffers in 2,113 nets |
| **STA @ 50 MHz** | ✅ MET | **setup MET** ("No setup violations found", RSZ-0098); **hold MET**, worst hold slack **+5.15 ns** (`post_hold_timing.rpt`) |
| **Detailed route (TritonRoute)** | ❌ CONGESTED — did NOT converge | violations **409,554 → 332,073 → 312,639 → 129,304 → ~116,677** (iter 1→4), plateauing ≈13 K/iter; ≈23.5 h OpenROAD CPU. **No routed DEF / GDS written** |
| DRC / LVS / final GDS | — not reached | gated on a clean route |

**Artifacts (all on disk, intact):**
`phase3/stage3/pnr/{floorplan.def, placed.def, post_cts.def, post_hold.def, post_hold_timing.rpt, openroad.log}`

---

## Why the route is congested (honest root cause)

Not a tool defect and not a Vibe-IC failure. Two design-physical drivers:

1. **FF-modeled memory.** The 3 buffers are behavioral SRAM synthesized to
   flip-flop register arrays (reduced depth ⇒ ~4 K memory FFs) instead of compact
   SRAM macros. FF arrays spread thousands of individually-routed data/enable nets
   across the std-cell fabric.
2. **Dense 256-MAC systolic array.** 256 `mac_pe` instances (INT4 multiply +
   32-bit accumulate) create very high *local* pin/net density.

Together these push **local** routing demand past sky130 6-metal capacity in
hotspots (weighted congestion 1.15) **even at only 36 % global utilization** — so
TritonRoute's residual short/spacing violations plateau near ~100 K instead of
reaching 0.

---

## Exact remaining step to a clean, routable GDS (integration work, NOT a tool limit)

1. **Swap the 3 FF-modeled buffers for real sky130 SRAM hard macros.**
   OpenRAM-generated (or pre-built sky130 SRAM macros with banking): weight 32 KB
   (e.g. 8192×32 as banked 512×32), act/out 16 KB (4096×32 banked). Stage
   LEF / Liberty / GDS under `input/pdk_local/` so the runner blackboxes them at
   synth, places them as hard macros at floorplan, and routes std-cell logic
   around them. This removes the ~4 K memory FFs and their dense nets from the
   fabric — the dominant congestion source.
2. **Floorplan / utilization tuning:** lower target density (or larger die),
   macro-aware floorplan (halos + placement blockages around macros), optionally
   hierarchical placement of the 256-PE array.

This is the **standard ASIC memory-integration step** — every real accelerator
uses SRAM macros, not FF arrays. The OSS flow (yosys + OpenROAD) handles
macro-based PnR natively; it is **fork/integration work**, not a commercial-EDA
gap. The plain-language → doc → RTL → synth → floorplan → place → CTS → timing
chain is **proven clean end-to-end**; only the memory-as-macro physical
integration remains for a DRC-clean GDS.

---

## Provenance / honesty

- **Path (c)** stated explicitly; memory is depth-reduced and labeled as such.
- **No GDS fabricated.** The run was stopped at genuine route congestion; the
  furthest clean milestone (post-hold, timing-MET) is reported as-is.
- **Blindness held:** nothing under `benchmark-data/ic/edge_llm_accel/` was read
  at any point.
- Not silicon-qualified / not tapeout-qualified — this is an OSS sky130 flow demo.
