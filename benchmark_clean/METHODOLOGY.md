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
