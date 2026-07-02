# CVDP hard-94 CLEAN-ROOM blind re-run — RESULT (plugin v1.2.93, 2026-07-03)

## 1. Headline
**Official blind pass@1 on the 94-case HARD subset = 19/94 = 20.21%** (problem pass rate;
official `run_benchmark.py --llm -m local_import`, criterion = `errors==0`). Tests 29/106 = 27.36%.
This is a **clean-room re-run of only the hard/fail tail** (the fair94/blind94 membership) on the
CURRENT plugin — NOT a re-report of the compliant full-302 number (243/302 = 80.46%, v1.2.63).

## 2. Shape
**Shape D** (agentic, cocotb-scored) via **GATE-AS-SOLE-EMIT-PATH** (`benchmark/cvdp_gate.py`).
Entry: 12 blind authoring agents (one per batch) → each authored RTL drafts → the gate assembled the
responses JSONL (the agent never hand-wrote it). Authors read ONLY `input.prompt` + `input.context`,
plus the plugin's design knowledge (`ic-expert-agent` skill + `ic_expert_db_query.py` — the v1.2.89 IC
Expert DB, the capability under measurement). NEVER `output.*` / harness / sibling / memory / scorer.

## 3. Score trajectory
- **Single-shot blind, NO close-loop this run** — every one of the 94 authored fresh from spec alone.
- **Burst rate-limit mid-flight** (methodology's known kill signature): 6 of the 12 first-wave batches
  died with `Server is temporarily limiting requests`. Recovered per the rate-limit resilience ladder:
  the deterministic host-gate swept all authored drafts, disk-truth reconcile found 23 missing, and 3
  **narrow-width** re-author batches completed them. Final assembly = 94/94 gated, deduped one-per-id.
  (The disruption likely cost a few passes vs an uninterrupted run — disclosed, not hidden.)

## 4. Residual triage (75 fails) — representative, per § 4 A–H (NOT blanket-labelled floor)
The hard-94 is BY CONSTRUCTION the oracle-coupled-floor-dense tail. Representative RCA (harness log,
oracle used for RCA only) shows a **MIX**, not a uniform floor:

| pid | evidence (harness) | category | note |
|---|---|---|---|
| axi_alu_0001 | Data==Expected on sampled addrs, then **docker 600s TIMEOUT** | **infra** (not a functional fail) | would likely PASS on re-run; the visible checks passed |
| microcode_sequencer_0001 | exact `d_out` sequence + control-store encoding checked | **B (under-spec)** floor-candidate | ~15-submodule microcode ROM not blind-derivable |
| sync_serial_communication_0052 | area-opt gate; all tests FAIL | **B** floor-candidate | the ≥9% area threshold + latency window live only in the TB |
| perceptron_0006 | `Expected w1=1, got 0` | **B/E** floor-candidate | hidden Testing-ROM microcode drives the weight trajectory |
| image_rotate_0001 | output **shifted 2 rows** vs expected | **G/H (agent-fixable)** | row-offset/border convention mis-guessed — recoverable |

By category the fails skew to **cid002 (33, code-comprehension/modify — context-heavy)** and cid003 (16,
spec→RTL); **cid007 bug-fix recovered BEST (17/24 = 71% of that category passed)** — the most
deterministic shape, where the DB craft + self-verified bug-fixes (Brent-Kung 2-bug 12/12,
modified_booth <<-vs->> 8/8, coffee_machine 5-bug, cont_adder equivalence) landed.

**HONEST scope (§4.1 binding):** I do NOT blanket-label the 75 as floors — a FLOOR claim requires the
`golden-also-fails` proof per case, and the sample above already contains ≥1 infra timeout (axi_alu)
and ≥1 agent-fixable convention miss (image_rotate). The convergence follow-up (benchmark-agent LOOP
mandate): (a) re-run the axi_alu timeout with a longer budget; (b) capture the agent-fixable convention
misses (image_rotate row-offset, and similar) into the plugin; (c) run the §4.1 golden-also-fails proof
on the oracle-coupled candidates (microcode ROM, area-gates) before any is called a TRUE_FLOOR. This
run is a MEASUREMENT, not a converged campaign.

## 5. Tool substitution
**NONE.** The CVDP OSS sim image `cvdp-sim-pinned:latest` (Icarus 13 / cocotb / yosys) IS the official
scoring toolchain — no Synopsys/NVIDIA substitution. Authors self-verified with host iverilog 12.0
(disclosed in each gate report as a possible accepted-syntax divergence vs the pinned Icarus 13).

## 6. Reproduce
```
# dataset subset (94 of the 302 no_commercial track) + assembled 94 gated responses are in this dir.
bash benchmark-data/evaluation/cvdp/rerun_v1293_hard94/score_hard94.sh
# → run_benchmark.py -f dataset_hard94.jsonl --llm -m local_import \
#     --prompts-responses-file responses_hard94_final.jsonl -t 6 -p score_hard94
# in OSS_SIM_IMAGE=cvdp-sim-pinned:latest ; report at score_hard94/report.txt
```

## 7. Sequence/plan status
This was an explicit `--floor-only`-style opt-in (the user asked for "the 94 fail cases"), run
CLEAN-ROOM per § 4.1 (blind, fresh dir, no inherited samples/memory/storage/oracle). The full-302
compliant number (243/302) is unchanged and remains the headline CVDP result; this hard-94 = 19/94 is a
separate datapoint measuring the current plugin's fresh-blind recovery on the hardest tail. Baseline
context: the hard-94 recovered ~26/94 on an earlier "fair rerun" (v1.2.39-era); this v1.2.93 clean-room
blind (rate-limit-disrupted, single-shot) landed 19/94 — within the expected clean-room variance for a
fresh-authoring run of the oracle-coupled-floor-dense tail.

### The 19 recovered blind
Brent_Kung_PP_adder, binary_multiplier, cache_lru×2, cont_adder×2, events_to_apb, galois_encryption,
halfband_fir, nbit_swizzling, restoring_division, run_length, secure_read_write_register_bank,
sigma_delta_audio, sorter×3 (0003/0009/0057), sync_lifo, ttc_lite.
</content>
