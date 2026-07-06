# VerilogEval-Human code-complete — TRUE BLIND run (plugin v1.3.27)

Run directory: `benchmark-data/evaluation/verilogeval_human/run_fresh_v1.3.26_blind`
Dataset: `/home/reyerchu/AI_IC_design/_extbench/verilog-eval/dataset_code-complete-iccad2023` (upstream official)
Date: 2026-07-06
Plugin: v1.3.27

## What "blind" means here (the honest number)

This run measures the plugin's **true one-shot capability with NO reference-answer
access** — the number a real user gets. It is NOT the earlier `run_fresh_v1.3.26`
convergence number (156/156), which was reached by an agent that READ the hidden
`_ref.sv`/`_test.sv` to converge. That convergence number is a process artifact,
not a capability measurement, and must not be published as one.

The blind pipeline, per **open-benchmark-methodology** Shape C:

1. **Deterministic layer** — `gates_atomic.py` → `spec_artifact_registry.generate()`
   emits host-verified RTL for every prompt whose structure is a recognized
   artifact (truth table, K-map, one-hot/Moore FSM table, DFF/edge family, …).
   This layer reads ONLY the prompt. **129/156** solved here.
2. **AI-backup layer** (`spec-to-rtl`) — for the 27 prompts the deterministic
   layer SKIPs, a FRESH agent with no prior context authored RTL reading **only
   `<prob>_prompt.txt`** (§4.05: the `_test.sv`/`_ref.sv` were never opened).
   **24/27** of these passed the official testbench.

The hidden official testbench is invoked ONLY by the scorer, never by the author —
that is legitimate scoring, not a blindness violation.

## Result

| Metric | Value |
|---|---|
| Total | 156 |
| PASS (blind) | **153** |
| FAIL | 3 |
| pass@1 (blind) | **153 / 156 = 98.08 %** |
| — deterministic layer | 129 |
| — blind AI-backup layer | 24 |
| Genuine §4 FLOOR (spec-ambiguity / prompt-vs-golden) | 3 |
| pass@1 excluding §4 floor | **153 / 153 = 100.00 %** |

## Enhancement captured into the plugin this round (Bucket A)

**`dff_edge_synth.py`: unstated clock edge on a plain D-FF defaults to posedge**
(shipped as v1.3.27). `_synth_dff` hard-SKIPped when the prompt did not NAME the
clock edge, though the edge-detect branch of the same module already applied the
universal "unstated edge → posedge" convention. This regressed the plain-DFF
family the docstring claims to solve. Fix: default an unstated edge to posedge
(zero-exception HDL convention); a CONTRADICTORY edge still SKIPs (§4.05 no-leak).
Effect: **Prob031_dff** and **Prob048_m2014_q4c** moved from AI-authored to
**deterministic** (both official-TB 0-mismatch), lifting the deterministic floor
127 → 129. General, benchmark-agnostic, no oracle read.

A second candidate — **FSM reset-by-convention** (would have recovered Prob136
deterministically) — was implemented, verified, and then **deliberately reverted**:
`full_moore_fsm_synth` force-OVERWRITES the author's sample, and inferring an
unstated reset state (first-listed) + unstated sync/async (default sync) is a
strong-but-not-universal convention. Overwriting a deliberate §4.05 no-leak
guardrail for a +1 benchmark gain is exactly the pressure the no-leak rule exists
to resist. Prob136 is already solved correctly by the blind AI-backup layer, so
the change added no capability. Kept the guardrail; classified Prob136 Bucket B.

## The 3 residual fails — genuine §4 FLOOR, NOT fixable without cheating

Each was RCA'd against the oracle in convergence mode (§3.9 oracle-for-RCA). In all
three the **prompt under-determines the answer** and only the hidden reference's
arbitrary choice disambiguates it — encoding that choice into the plugin would be
peeking at the oracle (cheating), so it is deliberately NOT done.

| Problem | Blind sample | Reference | Why it is a floor |
|---|---|---|---|
| `Prob062_bugs_mux2` | `out = sel ? b : a` | `out = sel ? a : b` | "Find the bug and fix this mux." The buggy code `(~sel&a)|(sel&b)` reads as sel=0→a / sel=1→b, so the intent-preserving fix is `sel ? b : a`. The reference instead flips the polarity to `sel ? a : b`. The prompt states no sel polarity; only the hidden ref picks one. **Spec-ambiguity.** |
| `Prob093_ece241_2014_q3` | `mux_in[2] = c\|~d` (binary ordering) | `mux_in[2] = ~d` (Gray ordering) | The prompt maps "ab=00→mux_in[0], ab=01→mux_in[1], **and so in**" [sic — truncated typo]. The mux_in ordering (binary 10→2,11→3 vs Gray 11→2,10→3) is left undefined; the TB compares mux_in directly, so the exact per-bit mapping is fixed only by the hidden ref. **Spec-ambiguity / prompt typo.** |
| `Prob149_ece241_2013_q4` | rising→dfr=1 (follows prompt) | falling→dfr=1 | The prompt says dfr opens when "the previous level was **lower** than the current level" (rising). The golden asserts dfr while **falling** (previous higher). The blind agent followed the prompt text literally; the golden contradicts its own prompt. **Prompt-vs-golden discrepancy.** |

## Tool-substitution disclosure

Official VerilogEval mandates Synopsys VCS / Cadence Xcelium. This run uses
**Icarus Verilog 12** on the host as the functional-simulation substitute. No PPA
(Design Compiler) scoring is performed. Scorer runs from the design directory so
the TB's relative `$readmem*` paths resolve.

## Artifacts

- Per-problem verdicts: `pass_at_1.json` (regenerate via `score_verilogeval.py`)
- Blind samples: `samples/<Prob>_sample01.sv`
- Deterministic gate logs: `work/<Prob>/gates.json`
- Converged (reference-read) twin for comparison: `../run_fresh_v1.3.26/`
