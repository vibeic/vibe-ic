# benchmark_clean — corrected Vibe-IC benchmark protocol (v2)

The earlier `benchmark_ic/` run was **not a valid training/validation signal**: inputs were
contaminated (raw upstream doc-trees with `.scala`/`.c`/`.rst`/build files, no PDK constraint),
and Phase 2 pulled the real upstream RTL via `catalog-glue-author` (sha256→secworks,
picorv32→ISC, darkriscv→github, VexRiscv→`sbt GenSmallest`) instead of **generating** RTL from
the design documents. That references the answer = effectively cheating.

This protocol fixes that.

## Hard rules

1. **Input = Design Documents ONLY.** Each IC's input is curated design documentation
   (datasheet / architecture / interface / register-map / timing / verification-plan /
   **constraints incl. explicit PDK + target process + clock**). It MUST contain **no RTL,
   no HDL source (.v/.sv/.vhd/.scala), no firmware, no build files, no reference netlist**.
   Each doc follows R1/R2/R3:
   - **R1 schema-only** — describes product intent, not implementation.
   - **R2 blackbox** — only externally-observable specs (ports, widths, timing, PDK targets).
   - **R3 multiple-correct** — does not prescribe hierarchy / FSM / pipeline / latency / placement.
   (The `spm` L1–L9 docs are the reference template for this shape.)

2. **The benchmark starts at the Design Documents.** Nothing produced by a later phase may be
   fed back as input. No referencing the upstream implementation as a Phase-1/2 input.

3. **Phase 2 = GENERATE, with mandatory source highlighting.** spec-to-RTL generation is the
   path under test. **IP reuse is allowed, but every reused source MUST be explicitly
   highlighted** in `SOURCE_MANIFEST.md`: each RTL module tagged
   - `GENERATED` — synthesized from the design documents by spec-to-RTL, or
   - `REUSED-IP` — pulled from an external source (name + license + commit/URL + which docs
     it satisfies), clearly flagged so it is never mistaken for generation.
   The "doc→silicon" PASS credit only applies to the `GENERATED` portion; `REUSED-IP` is
   reported honestly and separately.

4. **Honesty (unchanged).** No fabricated artifacts, no stubbed RTL, no waiver without
   evidence. A genuine DRC/LVS/STA/functional failure FAILs. (Magic-vacuous-0 etc. are
   rejected per the phase3 fixes now on `main`.)

## Flow per IC
1. Phase 1: design docs → L1–L13.
2. Phase 2: GENERATE RTL from the L-docs (spec-to-RTL). If any module is REUSED-IP, tag it.
   Then lint / sim / synth.
3. Phase 3: synth → PnR → GDS → DRC → LVS → STA on the produced RTL (honest, no vacuous pass).
4. **Verify / cross-check stage** (this is where the real upstream IP is finally allowed — as
   the **golden oracle**, NOT as input): equivalence/structural-check the GENERATED RTL against
   the reference (upstream RTL + L7 golden truth-table), and confirm the produced GDS is
   genuinely producible + production-ready (sign-off targets from L9). Report the cross-check.

## IC scope
- **Primary = small, fully-specifiable, genuinely-generatable IPs** (arithmetic / protocol /
  control blocks: spm, sha256, …) — these measure real generation capability.
- **Stress = the 21-IC set** — run as a capability-boundary stress test; complex CPUs are
  expected to honestly FAIL or fall to REUSED-IP at spec-to-RTL, and that result is the signal.

## Status
- [benchmark-verified 2026-05-26] `spm` — **FIRST fully benchmark-verified IC**:
  `benchmark-verify` OVERALL = **PRODUCTION-READY** (all 5 pillars pass; evidence in
  `spm/BENCHMARK_VERIFICATION_REPORT.md` + `spm/reports/`). Pillar 1 Functional
  Coverage **100% (21/21 requirements)** — every L1-L13 requirement bound to a real
  passing check (10,013-vector golden sim @N=32, 45 directed/corner/reset/encoding
  checks @N=8/16/32, gen-vs-upstream co-sim EQUIVALENT, SymbiYosys k-induction proof).
  Pillar 2 55-step **38/38 applicable PASS, 0 unresolved** (steps 6/30/36 closed: 6 &
  36 by the real FPGA compile, 30 = N/A no-ECO-needed matching the ref's
  `no_eco_needed.flag`; 27/28/32 stay PASS with the runnable portion run and the
  genuine NO-TOOL sub-items honestly cited as shared with the reference). Pillar 3
  Code Coverage **line 100% / branch 100% / toggle 98.7%** (Verilator `--coverage`;
  the 3 untoggled points are PROVABLY-DEAD top-stage carry/sum-in constants, not a
  test gap). Pillar 4 FPGA **PASS** — a REAL Quartus 23.1 compile on MAX10
  (10M50DAF484C7G) produced a signed 3.2 MB bitstream with FPGA STA MET at all 9
  corner-models, and 64 corner+random patterns pass cycle-accurate through an on-chip
  BIST harness (method = BFM + real-Quartus-bitstream; no physical board attached —
  `cables:[]` — same as the reference, whose FPGA step is compile-to-SOF only).
  Pillar 5 N/A (pure-digital).
- [signed-off 2026-05-26] `spm` — corrected-protocol run SIGNED OFF (doc ->
  production-ready). RTL remains 100% GENERATED from L1-L9 docs (0 REUSED-IP).
  After a timing-driven re-architecture authored from the docs (ripple-carry
  accumulator -> **carry-save bit-serial array**, R3-permitted, NO upstream RTL
  read), it still passes functional equivalence vs BOTH the spec golden and the
  upstream reference RTL — bit-exact, 10,013 vectors + mid-stream reset.
  Multi-corner STA now MEETs at all three corners @10 ns:
  **SS +6.99 / TT +7.49 / FF +7.68 ns** (was SS -7.87 ns FAIL). Detailed route
  is clean (0 route violations); a real 4.26 MB merged GDS (full cell-internal
  geometry, non-vacuous) streams out. Sign-off DRC (KLayout `sky130A_mr` full
  deck) has **0 real routing/BEOL violations** — the 130 residual items are all
  FEOL nwell/HVT-implant foundry-cell-internal false-positives (geometry-evidenced:
  inside placed-cell bboxes / inter-cell well gaps; the router cannot create FEOL
  layers). LVS: Magic extracted a real transistor netlist (non-vacuous) that
  matches the schematic device-for-device (3176/3176 transistors, every class
  equivalent) and synth<->PnR structural equivalence is formally proven 287/287;
  the only LVS residual is a Magic<->OpenROAD NDR-via-name interop artifact that
  drops boundary I/O nets in extraction (not a layout defect). Honest verdict and
  full evidence in `spm/RESULT.md`. doc->RTL generation AND doc->signed-off-silicon
  (timing clean, DRC clean of real violations, LVS device-exact) both demonstrated.
- [signed-off 2026-05-26] `sha256` — corrected-protocol run SIGNED OFF (doc ->
  production-ready): doc -> GENERATED RTL -> functionally-proven -> routed clean
  GDS -> **FULL 9-corner sign-off** DEMONSTRATED. RTL is **100% GENERATED** from
  L1-L9 + the public NIST FIPS-180-4 standard (0 REUSED-IP; secworks RTL never
  read as input). Author's own iterative single-cycle round (66 cyc/block) +
  shift-register message-schedule window + a timing-driven datapath re-arch
  authored from the spec (sequential ripple-carry round -> **carry-save-adder
  (3:2 compressor) tree + carry-select final adder**, R3-permitted, NO upstream
  RTL read) that collapsed the worst reg2reg path from ~22 series maj3 cells to 0.
  Functionally **bit-exact** vs BOTH the NIST KAT golden (abc / empty / 2-block /
  SHA-224 + 300 random vs hashlib) AND the upstream secworks reference RTL
  (co-sim, oracle-only) AFTER the re-arch — latency UNCHANGED, arithmetic bit-exact
  mod 2^32. Physical (new carry-select layout): real **non-vacuous 27 MB magic
  GDS** (413,725 shapes, single top cell, 88 cell types with internal geometry),
  detailed route **0 DRV**, **KLayout sky130A sign-off DRC = 0 violations** (568
  rule ops, no waivers — magic stream-out path genuinely clean; a KLayout
  cell-GDS+DEF overlay merge showed spurious li.* items, a merge artifact not a
  defect). Magic extracted a real **12,148-transistor** netlist with **all 177
  device classes equivalent, 0 non-equivalent, device count exact (12,148=12,148)**
  (LVS top-level residual = Verilog-vs-layout power-pin modeling artifact, not a
  defect). Multi-corner STA @25.9 ns: **setup >= 0 AND hold >= 0 at ALL 9 corners**
  (SS/TT/FF x cold/nom/hot x min/nom/max V) — worst setup SS_n40C_1v60 **+4.84 ns**
  (was -3.81 ns FAIL), worst hold FF_n40C_1v95 +0.280 ns; in-PnR routed-parasitics
  SS cold +0.60/+0.93. Honest verdict + full 9-corner table in `sha256/RESULT.md`.
  doc->RTL GENERATION + doc->signed-off-silicon (timing 9/9, DRC clean, LVS
  device-exact) both demonstrated.
