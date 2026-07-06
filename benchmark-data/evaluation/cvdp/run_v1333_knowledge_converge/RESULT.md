# CVDP knowledge-heavy convergence probe — run_v1333_knowledge_converge

## 1. Headline

**Measured**: clean-blind pass@1 (per authored RTL) over 17 CVDP `no_commercial`
records across four knowledge-heavy classes (Hamming ECC, GF multiplier, scrambler,
64b/66b encoder), scored by the **official cocotb/iverilog harness** (docker
`cvdp-sim-pinned:latest`, Icarus 13).

**Base (current plugin, no targeted lesson): 14/17 PASS.**
- Hamming: **5/5 PASS** — spec-complete, **no headroom** (abandoned per base-first gate).
- GF multiplier: **4/4 PASS** — spec-complete, **no headroom** (abandoned).
- 64b/66b encoder: **3/4 PASS** (0009 FAIL).
- scrambler: **2/4 PASS** (0009, 0018 FAIL).

**Result: NO class had a recoverable real-knowledge-gap base-fail.** All three
base-fails are **dataset FLOORS** (under-specification / description↔TB
inconsistency), proven by an independent disciplined re-authoring pass that still
failed. **Demonstrated FAIL→PASS lift: 0/3.** No general lesson shipped (an
unverified lift must not become a PR).

This is a clean **negative result**, the same shape as the prior `cache_lru`
probe but with a richer characterization: the *easy* knowledge-heavy prompts are
fully spec-complete (base already solves them); the *hard* residual fails are
floors, not headroom.

## 2. Shape

**Shape C** (atomic per-record, blind AI author → deterministic host gate → official
cocotb scorer). Entry disclosure: this is the **blind-author** CVDP entry (AI reads
`input.prompt` + `input.context` only; the official harness scores). Per § 5.1 this
is NOT the Phase-1 runner-chain number; it measures blind authoring gated by the
official scorer. Golden solutions are **stripped** (empty `output`) in this open
slice, so a §4.1 golden-also-fails FLOOR-proof is not runnable; the FLOOR evidence
below uses the strongest available substitutes (unmodified-context replay +
convergent independent re-derivation).

## 3. Score trajectory

| Stage | What changed | scrambler_0009 | scrambler_0018 | 64b66b_0009 |
|---|---|---|---|---|
| Base (blind, current plugin) | single blind author, self-check on worked example | FAIL 0/36 | FAIL (0/1) | FAIL 5/13 |
| Enhanced (blind + discipline) | added general craft: "self-verify against the COMPLETE stated behavior (every parameter value in the stated range, every table row, cycle-by-cycle timing), build your own iverilog TB, iterate to green — do NOT stop at the one worked example" | FAIL 0/36 | FAIL (0/1) | FAIL 5/13 |

The enhanced authors each built exhaustive self-check testbenches (scrambler_0009:
6 param combos incl. (8,4)/(16,5)/(8,7) green; scrambler_0018: 1100-cycle
equivalence TB; 64b66b_0009: 20/20 table-rows+examples green) **and still failed
the hidden scorer** — the residual is not authoring effort, it is missing spec.

## 4. Residual triage (A–H, § 4)

Base pass counts already prove **Hamming (5/5) and GF-multiplier (4/4) are
spec-complete → 0 headroom** (Category: N/A, no fail). The three fails:

- **scrambler_0018 — Category A (description↔TB inconsistency) FLOOR.** Prompt asks
  ONLY for a LINT review ("remove unused signals; fix mixing of blocking/non-blocking
  assignments") and explicitly excludes functional change ("intra_block … excluded
  from consideration"). Yet the hidden functional TB's reference model expects
  `out_data==0` during the wait window while the design emits data at `counter=1`.
  **Evidence:** the *unmodified context RTL* fails identically (`ctx` arm = FAIL, same
  `counter:1 … != 0x0`), and a spec-faithful enhanced fix proven **bit-identical to
  the original over 1100 cycles** also fails identically. No lint-scope change can
  satisfy a TB that requires an output-gating change the prompt never states.

- **scrambler_0009 — Category B (under-specification) FLOOR.** The hidden TB sweeps
  `OUT_DATA_WIDTH ∈ {8,16}` and `WAIT_CYCLES = [4] + random(5..16)` × 3 stimuli (36
  cases). The prompt gives exactly ONE worked example (`OUT=16, WAIT=5`). The exact
  **output-onset latency as a function of `WAIT_CYCLES` and `OUT_DATA_WIDTH`** is
  never stated. The enhanced author matched the prompt's visible table cycle-for-cycle
  yet **all 36 cases fail — including `WAIT=4, OUT=16`** — i.e. the hidden TB's onset
  model does not even match the prompt's own worked-example table. Not derivable blind
  without over-fitting the hidden oracle.

- **64b66b_encoder_0009 — Category B/A (under-specification + example↔table
  contradiction) FLOOR.** The mixed/control-mode encoding needs a **complete
  control-character codec**; the prompt gives 16 example rows + 3 worked examples, but
  the hidden TB's `all_control_symbols_test` / `random_data_control_test` exercise
  control inputs those rows do not cover. Additionally the enhanced author flagged a
  genuine internal contradiction: control-only payload is written as eight 7-bit codes
  (`C7…C0`, 56b tight-packed) in the table but Example 2 shows a byte-repeated pattern
  (`0x1E1E1E…`) — mutually exclusive for non-uniform inputs. Enhanced author verified
  **20/20** of everything derivable from the prompt and still failed the same 8/13
  hidden subtests. Data-only + reset + mixed-octet subtests PASS; the control codec
  subtests are unsatisfiable blind.

No Category F/G/H (agent-fixable) fail survived: the one candidate general lesson
("self-verify against complete stated behavior") was applied and produced **0/3
lift**, because the residual is spec-absent, not effort-absent.

## 5. Tool substitution

Scoring uses the **official OSS harness** — Icarus Verilog 13 + cocotb (docker
`cvdp-sim-pinned:latest`). **No commercial-tool substitution** (CVDP's sim image is
fully OSS by design). Golden RTL is stripped from the open slice (empty `output`),
disclosed in § 2.

## 6. Reproduce

```
RUN=benchmark-data/evaluation/cvdp/run_v1333_knowledge_converge
# records/ carry each problem's harness (src/*, .env); drafts/<arm>/<pid>/rtl/*.sv are the authored RTL
python3 $RUN/score.py base <pid...>   # stages harness + draft into docker cvdp-sim-pinned:latest, runs pytest test_runner.py
python3 $RUN/score.py enh  <pid...>
# verdicts: $RUN/scores/{base,enh,ctx}_verdicts.txt ; per-run logs: $RUN/direct/<arm>_<pid>/pytest.log
# dataset: /home/reyerchu/AI_IC_design/_extbench/cvdp_open_v110/cvdp_v1.1.0_nonagentic_code_generation_no_commercial.jsonl
```

## 7. Sequence / plan status

Candidate classes attacked in the assigned order: (1) Hamming, (2) GF-multiplier,
(3) scrambler, (4) 64b/66b. Base-first abandon gate abandoned Hamming and
GF-multiplier immediately (spec-complete). scrambler and 64b/66b each carried a
real base-fail, all triaged to FLOOR after a disciplined re-authoring pass failed to
lift them. **No version-less PR filed** — per the anti-pattern rule, an UNVERIFIED
gap (0/3 lift) must not become a PR, and a dataset floor is not a plugin gap. The
"self-verify against complete stated behavior" discipline is recorded here as an
unshipped candidate craft-lesson (Bucket B, `why_not_bucket_a`: multi-parameter /
full-table functional correctness cannot be decided by a regex) — but it is **not**
shipped because it produced no measurable lift on this dataset (the residual is
floor, so the lesson is unfalsifiable here).
