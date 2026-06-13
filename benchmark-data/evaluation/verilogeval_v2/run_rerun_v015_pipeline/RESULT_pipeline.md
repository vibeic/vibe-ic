# VerilogEval-v2 through the FULL Vibe-IC Phase1→Phase2 pipeline (v0.1.5)

## What this run answers
"Does routing VerilogEval through the actual plugin (program-first: PM-Agent →
deterministic phase1_engine → L1-L13 contract → gated generation) beat the bare
blind-agent path?" — i.e. does the plugin's machinery improve the score.

## Method (program-first, still blind)
Per problem, 8 parallel agents ran the real pipeline, reading ONLY the prompt:
1. **PM Agent** (Claude, prompt-only) → `input/phase1_structured.yaml` (ic_name, class_path, L1 description, **L9 ports** from the interface).
2. **phase1_engine `run-all`** (deterministic) → `generated_docs/L*.json` — the structured spec contract.
3. **`spec_self_consistency_check`** (deterministic, pre-RTL) on the prompt.
4. Blind RTL generation targeting the L9 contract.
5. **Phase-2 gates** (deterministic): `iverilog -g2012` compile + `spec_conformance_check --spec <prompt>` (port/width/reset vs the *prompt-derived* contract — never the hidden test). Fix flagged ERRORs, re-gate.
Ref/test never read. One blind shot + gate-directed fixes.

## Result vs bare-blind (same v0.1.5)
| Path | pass@1 |
|---|---|
| bare blind agent (`run_rerun_v015/`) | 143/156 = 91.67% |
| **full plugin pipeline (this run)** | **145/156 = 92.95%** |

## Honest verdict: the +2 is run-to-run variance, NOT a systematic plugin gain
Diffing the two fail sets:
- pipeline **fixed** (pass here, failed bare-blind): Prob070, 092, 116, 133, 146, 149 — mostly K-map don't-care / FSM problems where *this run's* blind shot happened to pick the reference interpretation.
- pipeline **broke** (fail here, passed bare-blind): Prob031, 078, 089, 145.

Different problems flip in each direction → the spread is the **same ±2% blind
single-shot noise** seen across all four runs (91.03 / 91.67 / 92.95 / 93.59%).
The generation step is fundamentally a blind LLM shot; that dominates.

Notably **Prob031_dff is a case where the pipeline actively HURT**: the prompt's
interface bullets declare `input q` while the body says "a D flip-flop" (q should
be the output). Following the plugin's L9 contract *strictly* (the disciplined
thing) reproduced the garbled `input q` and failed; the looser bare-blind agent
had ignored the bad interface and passed. Rigid contract-adherence to a defective
spec can backfire.

## What the gates DID do (genuine, just not score-moving here)
- `spec_self_consistency_check` flagged **Prob099** (garbled Y1/Y3-vs-Y2/Y4) from
  the prompt alone, pre-RTL — the one structural defect.
- `spec_conformance_check` + `iverilog` caught real structural issues mid-run and
  the agents fixed them before scoring: `output reg` for procedurally-assigned
  outputs (Prob023), and `port-extra`/`reset-not-found` advisories.
- But VerilogEval's *scoreable* failures are dominantly **functional** (K-map
  don't-care choice, FSM/reset/edge timing). No deterministic gate can judge those
  from the spec alone — you'd need the hidden testbench. So the plugin's
  determinism cannot move this pass-rate.

## Conclusion
VerilogEval-v2 is **structurally the wrong benchmark to show the plugin's value**.
It measures blind single-module functional correctness — a property of the
underlying model, flat at ~92% regardless of plugin version or whether the plugin
pipeline is used. The plugin's program-determinism (structuring, contract gating,
spec-lint, and downstream synth/PnR/DRC/LVS) shows measurable, version-over-version
value where most of the work IS deterministic: the full-flow IC benchmarks
(`benchmark_clean/`) and phase1 doc→L1-L13 extraction — not here.
