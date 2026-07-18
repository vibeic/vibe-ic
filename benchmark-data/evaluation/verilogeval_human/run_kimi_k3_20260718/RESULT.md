# VerilogEval-Human — clean-room pass@1 · authoring model = **Kimi K3**

- **pass@1 = 149/156 = 95.51%** (raw); advisory excl. suspected-defect golden 149/155 = 96.13%.
- **Author = Kimi K3** (Moonshot subscription `api.kimi.com/coding`, model `kimi-k3`), NOT Claude. Shape C.
- Same gate (`gates_atomic.py`, sole emit) + same official scorer (`score_iverilog_tb.py`, `Mismatches: 0`) + same dataset (`dataset_code-complete-iccad2023`) as the Claude Fable 5 reference (`../RESULT.md`, 153/156). Blind (§4.05), clean-room.
- **vs Claude Fable 5: 149 vs 153 (−4 problems).** See `../LLM_AUTHORING_COMPARISON.md`.
- Fails (7): Prob062 (suspected-defect golden), Prob093/099/149/155 functional_mismatch + Prob133/154 no_sample — hard multi-state FSM tail.
- Note: authored in two passes (initial single-shot 137/156, then a resume recovered the FSM tail that had been HTTP-403 quota-truncated → 149). Harness: Python per-problem author calling Kimi K3 → plugin gate → host scorer.
