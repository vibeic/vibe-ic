# VerilogEval-v2 — clean-room pass@1 · authoring model = **Kimi K3**

- **pass@1 = 147/156 = 94.23%** (raw); excl. dataset defects 147/155 = 94.84%; advisory excl. suspected-defect golden 147/154 = 95.45%.
- **Author = Kimi K3** (Moonshot subscription `api.kimi.com/coding`, model `kimi-k3`), NOT Claude. Shape C.
- Same gate (`gates_atomic.py`, sole emit) + same official scorer (`score_iverilog_tb.py`, `Mismatches: 0`) + same dataset as the Claude Fable 5 reference (`../RESULT.md`, 153/156). Blind (§4.05), clean-room.
- **vs Claude Fable 5: 147 vs 153 (−6 problems).** See `../LLM_AUTHORING_COMPARISON.md`.
- Fails (9): Prob099 (dataset defect, golden fails own TB), Prob062 (suspected-defect golden), Prob058/133/149/155 no_sample + Prob093/152/154 functional_mismatch — hard multi-state FSM/complex tail (Kimi weaker than Fable-5 here).
- Harness: Python per-problem author calling Kimi K3 → plugin gate → host scorer. Deterministic port-parse (program-first) + Kimi RTL body (AI-backup). Model-substitution + tool-substitution disclosed.
