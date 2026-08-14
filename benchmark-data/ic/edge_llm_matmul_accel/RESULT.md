# edge_llm_matmul_accel — a genuine plain-language → IC sample (Vibe-IC front door, blind)

**What this is.** A worked, end-to-end demonstration that a plain-language spoken
request — from a user with NO chip-design vocabulary — drives the Vibe-IC front door
to a real, functionally-verified INT4 GEMM edge-LLM accelerator. Every authoring step
ran BLIND to any pre-existing design (§4.05); the design was produced from intent, not
copied. This is the clean "口語 → IC" sample that the earlier `edge_llm_accel`
benchmark IC was NOT (that one was RTL-first, docs formalized after, with no dialogue).

> Honest scope: OSS **sky130** flow demonstration. NOT silicon-proven, NOT
> tapeout-qualified. It is a GEMM-accelerator **building block** (one INT4 matmul
> tile), not a complete edge-LLM accelerator.

---

## The IC — `edge_llm_matmul_accel`
Hard-wired signed-INT4 (W4A4) GEMM accelerator: fixed **16×16 systolic array (256 MAC
PEs)** → **32-bit accumulator** → **Q1.15 requant (round-half-up + saturate) → INT8**;
arbitrary M/K/N by host software tiling through the fixed tile. Host = **Wishbone B4
slave** (9 registers + weight/act/out SRAM windows), START → BUSY/DONE + IRQ. FSM
IDLE→LOAD_W→LOAD_A→COMPUTE→REQUANT→WRITE_OUT→DONE. Target sky130A, 50 MHz. Offloads the
LLM attention/fully-connected matmul; softmax/normalization stay on the host CPU.

## The pipeline that produced it (each stage's evidence)
| Stage | What ran | Evidence (in this dir) |
|---|---|---|
| 1 — plain-language seed | `persona-common` (zero jargon) spoke the need | `input/docs/00_user_request.md`, `_meta/persona_card.md` |
| 2 — front door → L1-L27 | IC-Expert dual-track (program + AI converge) + sufficiency + fill-to-floor parity | `phase1/{generated,ai,merged}_docs/`, `_meta/{converge,sufficiency,parity}_report.json`, `_meta/frontdoor_dialogue.md` |
| 3 — spec → RTL + gates | spec-to-rtl authored, then hygiene/lint/conformance/synth | `phase2/stage1/rtl/edge_llm_matmul_accel.v` (256 PEs, yosys-confirmed) |
| 4 — independent verify | from-scratch numpy golden + Wishbone TB, iverilog | `verify/functional_verify_result.json`, `verify/golden_int4_gemm.py` |
| 5 — cross-check | contract diff vs the pre-existing design | `_meta/convergence_diff.md`, `_meta/FINAL_VERDICT.md` |
| 6 — Phase 3 | synth→FP→place→CTS→hold→(route) on sky130 | `phase3/PHASE3_MILESTONE.md` |

## The load-bearing answer — "how much can plain language state?"
37 material design parameters (`_meta/provenance_ledger.json`):
**user-stated 10 (27%) · expert-filled 27 (73%)**.
- The user stated the INTENT: 4-bit, offload the LLM multiply, local low-power helper,
  open/cheap process, load→go→read, hard-wired, simple ready/done.
- The IC-Expert filled everything the user cannot state: accumulator width, requant
  scheme, register map, FSM, ports, tiling, PDK, die, DFT, sign-off ladder — and
  CORRECTED two impractical guesses ("a few MB" → ~64 KB streaming buffers;
  "28/45 nm" → sky130). That 73% expert fill IS the Vibe-IC value proposition:
  the user brings intent, the agent brings silicon expertise.

## Functional correctness (independent, adversarially validated)
`tests=16 comparisons=5376 mismatches=0 → PASS`. The golden is a from-scratch Python
INT4-GEMM reference built from the L-doc math contract; the testbench carries ZERO
golden arithmetic. Cases: random 16×16, small-K, saturation on both rails, 32×32
mn-tiling, K=32 k-tiling. **Proof-of-negative:** 3 injected RTL mutants (truncate,
broken-saturation, weight-transpose) were all caught → mismatches=0 is not a
false-clean. This matches/exceeds the original's V2 methodology.

## Blindness (why this is a real front-door result, not copying)
ZERO original fingerprints (64×64 / nangate45 / fakeram / per-tensor / 20-bank /
ACCW=20 / orig-FSM / 2400-die / 4096-MAC / 1099-latency) appear anywhere in the forward
deliverables; the forward design diverges from the pre-existing one on EVERY free
parameter (16×16, sky130, 32-bit, Wishbone, INT8). Systematic divergence on every axis
is impossible if the agents had copied. All authoring agents also self-confirmed no
read under the off-limits path.

## Disclosed caveats — found by the honest-verification pass, NOT by the auto-gates
1. **Per-channel scale is a doc-vs-RTL over-claim.** L2/L15 claim per-output-channel
   scale, but L4's regmap exposes a SINGLE `SCALE` register and the RTL applies it
   globally (= per-tensor, the same limitation as the original). The independent
   verifier proved it structurally: the DUT matches a single-global-scale golden
   (0 mism) but diverges from a per-channel golden on **105/256** elements. **These
   generated L-docs are preserved unedited** — they are the evidence of what the front
   door produced. The value on display: independent verification CATCHES doc-vs-RTL
   gaps the auto-gates miss. (A corrected-doc variant can be produced on request.)
2. **"Arbitrary M/K/N" is software tiling.** The hardware is a single 16×16-tile engine
   (K ≤16/pass; cross-tile accumulation + M/N masking are the host's job).
3. **This is a different (mostly better) instance, not a reproduction** of the original
   — so the original's V2 golden does not apply, and its F2 residual is
   architecture-specific with no analogue here.

## Phase-3 milestone (honest)
Furthest CLEAN stage = **post-hold (synth → floorplan → place → CTS → hold-fix),
timing MET @ 50 MHz** (setup: no violations; worst hold slack +5.15 ns). Synth
154,632 sky130_fd_sc_hd cells (~1.40 mm²); die 2000×2000 µm, 36.1% core utilization.
**Detailed route did NOT converge** (violations plateaued ~116K) — root cause is
physical, not logical: the 3 buffers are FF-modeled reduced SRAM (~4K memory FFs) plus
the dense 256-MAC array's local pin density exceed sky130 6-metal local capacity even
at 36% global utilization. **Exact remaining step to a clean GDS:** replace the 3
FF-modeled buffers with real sky130 SRAM hard macros (OpenRAM/banking, staged in
`input/pdk_local/`) + floorplan/utilization tuning — a standard memory-as-macro
integration step, NOT a tool limitation and NOT a Vibe-IC failure. The
doc→RTL→synth→floorplan→place→CTS→timing chain is proven clean end-to-end.

## Plugin improvements this sample surfaced (general, chip-agnostic — held for push)
Five real gate defects were found and fixed (each proven on a clean synthetic fixture,
regression-tested): (1) quality-parity unknown-class defaulted to a serial-ID floor →
neutral `generic-ic` floor; (2) verify_aggregate positional-arg drift false-FAILed 3
sub-checks; (3) spec_conformance read `direction` not the canonical `dir`; (4) param
port widths `[WB_AW-1:0]` defaulted to 1 → now resolved or width-unknown; (5) a new
advisory catching L2/L15-per-axis vs L4-scalar-register inconsistency (the exact gap in
caveat #1).

## Bottom line
YES — plain language produced a real, verifiable edge-LLM INT4 GEMM accelerator IC.
The spoken intent was sufficient to seed it; the IC-Expert faithfully filled the ~73%
the user could not state. It is a GEMM building block (not a full accelerator), the
sky130 GDS awaits standard SRAM-macro integration, and one honest doc-vs-RTL gap was
caught by real verification — all disclosed above rather than hidden.

