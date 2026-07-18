# Authoring-LLM comparison — same Vibe-IC harness, different author

The Vibe-IC clean-room benchmark harness is **model-agnostic**: the deterministic gate
(`gates_atomic.py` = sole emit path) + the official upstream scorer (`score_iverilog_tb.py`,
`Mismatches: 0`) stay fixed; only the **authoring LLM** is swapped. This isolates *authoring-model*
quality from harness quality. All runs below are clean-room, blind (§4.05 — prompt only, never the
testbench / golden / sibling solutions).

## VerilogEval pass@1 by authoring model

| Benchmark | Claude Fable 5 | Kimi K3 | Δ (Claude − Kimi) |
|---|---|---|---|
| **VerilogEval-v2** (156)    | **153/156 = 98.08%** | 147/156 = 94.23% | **+6 problems / +3.85 pts** |
| **VerilogEval-Human** (156) | **153/156 = 98.08%** | 149/156 = 95.51% | **+4 problems / +2.57 pts** |
| RTLLM v2.0 (50)             | 49/50 = 98% | *in progress (quota-limited)* | — |

excl. dataset defects: VE-v2 Claude 153/155=98.71% · Kimi 147/155=94.84%; VE-Human Claude 153/155=98.71% · Kimi 149/155=96.13%.

## Read-out
**Claude (Fable 5) is currently the stronger RTL author** under the identical Vibe-IC harness,
leading Kimi K3 by ~3–4 points on VerilogEval. Kimi K3's residual misses concentrate on the hard
multi-state FSM tail (lemmings / gshare / ps2 / one-hot FSM) — the same class where the harness's
deterministic solvers do not fire, so the authoring model carries the load. On the easy/combinational
and single-register problems the two models are near-parity; the gap opens on sequential/FSM depth.

## Provenance / reproduce
- **Claude Fable 5** runs: `verilogeval_v2/RESULT.md`, `verilogeval_human/RESULT.md` (plugin v1.3.88,
  26 batch authoring agents).
- **Kimi K3** runs (2026-07-18): `verilogeval_v2/run_kimi_k3_20260718/`, `verilogeval_human/run_kimi_k3_20260718/`
  (`pass_at_1.json`). Authored via a Python harness that calls the Kimi K3 subscription
  (`api.kimi.com/coding`, model `kimi-k3`) per problem → the SAME `gates_atomic.py` gate → the SAME
  `score_iverilog_tb.py` scorer. Deterministic port-parse builds the port contract; Kimi authors the
  RTL body (program-first + AI-backup).

**Honesty note:** the gate's deterministic Tier-1 solvers fire regardless of authoring model, so both
columns include that shared program layer; the *difference* between the columns is attributable to the
authoring LLM on the problems the solvers do not cover. These are authoring-model comparison numbers,
NOT a change to Vibe-IC's headline (which stays the Claude Fable 5 reference).
