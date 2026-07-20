# FINAL VERDICT — "扶正" edge_llm_accel into a genuine plain-language → IC sample

Experiment: run the vibe-IC forward front door BLIND (a zero-jargon persona speaks a
plain-language need → IC-Expert dual-track Phase-1 → L1-L27 → Phase-2 RTL →
independent bit-true verification), to test whether a spoken intent can produce a real
edge-LLM INT4 GEMM accelerator IC. Original edge_llm_accel artifacts were OFF-LIMITS
throughout authoring (§4.05).

## What was produced
`edge_llm_matmul_accel` — a hard-wired signed-INT4 (W4A4) GEMM accelerator: fixed
16×16 systolic array (256 MAC PEs, yosys-confirmed), 32-bit accumulator, Q1.15 requant
→ INT8 saturating output, Wishbone B4 slave (9 regs + SRAM windows), FSM
IDLE→LOAD_W→LOAD_A→COMPUTE→REQUANT→WRITE_OUT→DONE, ~64 KB streaming SRAM, sky130A,
50 MHz. Offloads LLM attention/FC matmul; softmax/norm stay on host.

## Evidence ladder (all passed)
- **Blindness**: 0 original fingerprints (64×64 / nangate45 / fakeram / per-tensor /
  20-bank / ACCW=20 / orig-FSM / 2400-die / 4096-MAC / 1099-latency) across ALL forward
  deliverables; both authoring agents self-confirmed no oracle read. The design diverged
  from the original on every free parameter → copying is ruled out by the outputs.
- **Phase-1**: sufficiency=sufficient (exit 0), fill-to-floor parity pass (exit 0,
  non-degenerate), consistency 15/15, 100% input capture.
- **Phase-2**: iverilog + verilator-lint + rtl_hygiene + spec_conformance (15/15 ports)
  + yosys synth (~227k cells) ALL rc=0. Smoke sim: 256 outputs bit-exact.
- **Independent functional verification** (separate agent, from-scratch numpy golden,
  TB carries zero golden arithmetic): `tests=16 comparisons=5376 mismatches=0 → PASS`.
  Cases: random 16×16, small-K, saturation both rails, 32×32 mn-tiling, K=32 k-tiling.
  **Proof-of-negative**: 3 injected RTL mutants (truncation / broken-saturation /
  weight-transpose) all caught → not a false-clean.

## Provenance — "how much can plain language state?" (the load-bearing answer)
37 material design parameters: **10 user-stated (27%)**, 8 card-deferred-expert-filled,
**19 expert-floor-fill (73% expert)**. User could state the INTENT (4-bit, offload the
LLM multiply, local low-power helper, open cheap process, load→go→read, hard-wired).
Expert had to fill the entire numeric contract (accumulator width, requant scheme,
regmap, FSM, ports, tiling, PDK, die, DFT, sign-off) AND correct two impractical user
guesses ("a few MB"→~64 KB streaming; "28/45nm"→sky130).

## Honest caveats (found by the cross-check + independent verify — NOT by the auto-gates)
1. **Per-channel scale is a DOC-only over-claim.** L2/L15 say per-output-channel scale;
   L4 regmap has ONE `SCALE` reg and the RTL applies it globally = single per-tensor
   scale, the SAME limitation as the original. A real cross-layer inconsistency the
   Phase-1 consistency gate did not catch. (Per-channel is achievable only by the host
   reprogramming SCALE between tiles = software.)
2. **"Arbitrary M/K/N" is software-tiling.** Hardware is a single 16×16-tile engine
   (K ≤16/pass; cross-tile accumulation + M/N masking deferred to host software;
   K>16 lossless only when per-pass requant is identity).
3. **Not a bit-identical reproduction of the original**; it's a different (mostly
   better) valid instance. Original's V2 golden cannot apply (different ports/math);
   original's F2 residual is architecture-specific and has no analogue here.
4. Genuine improvements that ARE real in the forward RTL: INT8 requant with
   round-half-up + saturation; 32-bit accumulator; tapeout-capable sky130A; standard
   Wishbone bus.

## Plugin-improvement candidates captured (chip-agnostic)
- phase1_quality_parity_check class-resolver defaults unknown class → `cable-side-id-ic`
  (wrong opcode/CRC/OTP floors); needs a neutral default / GEMM-accel class.
- phase1_verify_aggregate passes `<project>` positionally to 3 checks that want a
  docs-dir / `--gates` → false FAILs inside the aggregate while passing standalone.
- spec_conformance_check reads `direction`; L-docs emit `dir` → mis-flagged ports.
- parse_rtl_ports defaults parameterized port widths ([WB_AW-1:0]) to 1.
- Phase-1 consistency gate missed the L2/L15(per-channel) vs L4/RTL(global) scale
  inconsistency — a semantic cross-layer check gap.

## Bottom line
YES — this is a genuine end-to-end "plain-language → working IC" demonstration, blind
and bit-true, which the ORIGINAL edge_llm_accel was not (that one was RTL-first, docs
formalized after, no dialogue). "口語就能做出一顆 IC" is true in the load-bearing sense:
the plain-language INTENT is sufficient to seed a real, verifiable edge-LLM INT4 GEMM
accelerator, and the IC-Expert faithfully fills the ~73% the user cannot state — which
IS the vibe-IC value proposition. It is a GEMM-accelerator building block (like the
original), not a complete edge-LLM accelerator, and it carries one honest doc-vs-RTL
gap that only real verification surfaced. Phase-3 PnR→GDS is running as confirmation.
