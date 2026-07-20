# Convergence diff — forward (blind, plain-language) vs original edge_llm_accel

Sanctioned cross-check, run by the orchestrator AFTER authoring was frozen. The
forward design was produced blind (proven by zero original-fingerprint leakage in
all forward deliverables); this diff is the honest comparison of where the
plain-language front door + expert expansion LANDED vs the pre-existing design.

## Observable-contract comparison

| Dimension | Original `edge_llm_accel` | Forward `edge_llm_matmul_accel` (blind) | Same? |
|---|---|---|---|
| Product intent | INT4 GEMM accel, offload LLM attention/FC | **identical intent** | ✅ converged |
| ic_class | digital_arithmetic_primitive | digital_arithmetic_primitive | ✅ |
| Number format | signed INT4 (W4A4) | signed INT4 (W4A4) | ✅ |
| Compute tile | 64×64 (DIM=64), 4096 MACs | **16×16, 256 MACs** | ✖ diverged |
| Accumulator | 20-bit (ACCW=20) | **32-bit** | ✖ (forward safer) |
| Requant OUTPUT | dequant → INT16 (no round/saturate-to-INT) | **INT8 requant, round-half-up + saturate** (real in RTL) | ✖ (forward genuinely better) |
| Requant SCALE granularity | single per-tensor scale | **L2/L15 CLAIM per-channel, but L4 regmap has ONE `SCALE` reg + RTL applies it globally → actually single global (per-tensor)** | ⚠️ DOC over-claim; RTL == original's limitation |
| Arbitrary M/K/N | not addressed (one tile) | HW = one 16×16 tile per START, K clamped ≤16/pass, **M/N masking + K-tile accumulation deferred to SOFTWARE** | ⚠️ "arbitrary sizes" is software-tiling, HW is a single-tile engine |
| On-chip memory | 20-bank × 2048×39 ≈ 195 KB, hold | **~64 KB streaming buffers (32/16/16)** | ✖ |
| Host interface | bare 20-bank scratchpad, `(i%32)%20` addr, start/busy/done | **Wishbone B4 slave, 9 regs, IRQ, SRAM windows** | ✖ (forward standard bus) |
| PDK | nangate45 (educational, `tapeout_capable=false`) | **sky130A (real, Efabless-manufacturable)** | ✖ (forward tapeout-capable) |
| Clock | 100 MHz | 50 MHz | ✖ |
| Peak | 819 GOP/s (4096 MAC @100MHz) | ~25.6 GOP/s (256 MAC @50MHz) | ✖ (forward smaller/lower-power) |

## Golden-reuse verdict: N/A (documented, not skipped)

The original V2 golden (`verify/tb_v2_top.v`) is bound to the 64×64 array, the
specific 20-bank memory map + beat/word framing formulas, per-tensor scale, and
INT16 duplicated-word output. The forward RTL has a different port list (Wishbone
slave), a different tile (16×16), per-channel Q1.15 → INT8, and a different memory
architecture. Therefore the original V2 golden **cannot be compiled or matched
against the forward RTL** — reusing it is not meaningful. The forward design is
verified instead by its OWN independent from-scratch golden (Stage 4), which is the
same METHODOLOGY (independent software sum-of-products reference) applied to the
forward contract.

## F2 residual: original-specific, does NOT carry over

The original's F2 (16/4096 weight nibbles, row 63 cols 48–63, alias word 0 via a
beat-0 read-pipe framing skew; input-deterministic only under a reset-per-run +
≥2-idle-cycle usage contract) is an artifact of the original's 64×64 array + its
2-cycle scratchpad read latency + its specific beat framing. The forward design
loads operands over Wishbone into addressed SRAM windows with a different FSM and
no beat-framing skew, so **F2 has no analogue to reproduce here**. Whether the
forward design has any residual of its own is answered by Stage 4's independent
golden including saturation-boundary and tiled cases — a clean Stage-4 bit-true
pass means no such residual; any failure it finds is a NEW forward-specific finding,
not F2.

## Honest reading

The blind plain-language front door converged to the SAME product and the SAME core
datapath character (signed-INT4 systolic GEMM + requant), and DIVERGED on every free
implementation parameter. GENUINE improvements that are REAL in the forward RTL: a
proper INT8 requant with round-half-up + saturation (the original only dequantized to
INT16); a safe 32-bit accumulator; a real tapeout-capable PDK (sky130A vs the
original's educational nangate45); and a standard Wishbone bus. But two claims must be
read with honesty caveats found in this cross-check: (1) the L2/L15 docs claim
**per-output-channel** scale, yet the L4 regmap exposes a SINGLE `SCALE` register and
the RTL applies it globally — so on the requant-granularity axis the forward design
did NOT actually beat the original's per-tensor limitation; it documented an
improvement it did not build (a real cross-layer inconsistency the Phase-1 consistency
gate did not catch). (2) "Arbitrary M/K/N" is a software-tiling claim: the hardware is
a single 16×16-tile engine (K ≤16/pass, M/N masking + cross-tile accumulation left to
host software). Net: plain language pins the intent; expert fill-to-floor produced a
mostly-better but not uniformly-better design, and — like the original — it carries at
least one doc-vs-RTL gap that honest verification (not the auto-gates) surfaces.
