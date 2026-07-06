# CVDP cache_lru family — enhancement-driven convergence (v1.3.33) — NEGATIVE RESULT

**Goal:** distill a general cache-replacement-policy lesson to recover the `cache_lru`
family, then A/B blind-verify the functional lift. **Outcome: net lift = 0 → NOT shipped.**

## A/B verdicts (official cocotb harness; scores/direct_verdicts.txt)

| cache_lru | BASE (no lesson) | ENH (with lesson) |
|---|---|---|
| 0001 | FAIL | FAIL |
| 0008 | PASS | PASS |
| 0011 | PASS | PASS |
| 0016 | PASS | PASS |
| 0019 | PASS | PASS |
| 0022 | PASS | PASS |

**Net clean-blind FAIL→PASS = 0/6.** Base == enh on every problem.

## Honest triage
- 5/6 already PASS blind WITHOUT the lesson — the family prompts are spec-complete
  enough that careful blind authoring produces functionally-correct RTL (static
  inspection: base 0022 already gates `if(access & ~hit)`; base 0016 already has the
  at-MAX-decrement). This is author-care, not a knowledge gap a lesson closes.
- 0001 stays FAIL even WITH the lesson → the lesson is not the right fix there; the
  fail is a harder authoring/spec-reading miss (golden stripped, harness self-consistent
  → not a dataset floor). Left as an honest unconverged residual.
- The lesson only lifted retrieval COVERAGE (4/6→6/6) = process, not verdict outcome.
  Per benchmark-enhancement-capture, ship only on demonstrated functional lift → NO-SHIP
  (PR #109 closed).

## Harness note (tool-substitution)
Official scorer = Icarus 13 in `cvdp-sim-pinned:latest` (OSS substitute for NVIDIA
cvdp-sim). `score_one.py --dataset <subset>` still drives `run_benchmark.py -f` over the
FULL 302-problem set → ~7 min/call and 420s timeouts; a direct per-problem cocotb
invocation (scores/direct_verdicts.txt, 1–2 s/problem, same TB) was used for the A/B.
This score_one full-scan inefficiency is itself a harness backlog item.

## Bottom line for the CVDP number
No change. Projected v1.3.33 ≈ 243/302 (the cache_lru family adds 0). The value of this
run is the HONEST negative: it rules out a whole "cache-policy lesson" hypothesis and
records why, instead of shipping a no-op lesson that inflates nothing.
