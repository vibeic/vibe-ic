# VerilogEval-v2 spec-to-RTL — TRUE BLIND run (plugin v1.3.27)

Run directory: `benchmark-data/evaluation/verilogeval_v2/run_blind_v1.3.27`
Dataset: `/home/reyerchu/AI_IC_design/_extbench/verilog-eval/dataset_spec-to-rtl` (upstream official)
Date: 2026-07-06
Plugin: v1.3.27 · Shape **C**

## Why this run exists (verification of the earlier convergence number)

The sibling run `../run_fresh_v1.3.26/` reported **155/156** — but that is a CONVERGENCE number:
its RESULT.md discloses that the hidden `_test.sv`/`_ref.sv` were read during the convergence RCA
to re-author 5 failing problems. That is a legitimate process number, NOT a capability measurement.
This run measures the **true blind** capability: what the plugin produces reading ONLY the prompts.

Independent audit of the prior 155/156:
- ✅ Reproduces exactly under the official v2 scorer (155/156).
- ✅ `Prob099_m2014_q6c` is a genuine upstream dataset defect (prompt declares Y1/Y2/Y3/Y4, the TB
  instantiates only Y2/Y4, the ref declares Y1/Y3 — mutually inconsistent, cannot compile).
- ✅ Honestly disclosed as a convergence (reference-read) number.
- ⚠️ The true blind number was never measured → **measured here**.

## Method (§4.05-blind, Shape C)

- **Deterministic layer** — `gates_atomic.py` → `spec_artifact_registry.generate()`, prompt-only:
  **130 fired / 129 PASS** (the 1 fired-but-failing is Prob099, the dataset defect).
- **AI-backup layer** — for the 26 prompts the deterministic layer SKIPs, three fresh agents with
  no prior context authored RTL reading **only `<prob>_prompt.txt`** (the `_test.sv`/`_ref.sv` were
  never opened). 24/26 passed the official testbench.

## Result

| Metric | Value |
|---|---|
| Total | 156 |
| PASS (blind) | **153** |
| pass@1 (blind) | **153 / 156 = 98.08 %** |
| — deterministic layer | 129 |
| — blind AI-backup layer | 24 |
| Genuine floor (spec-ambiguity ×2 + dataset defect ×1) | 3 |
| pass@1 excluding floor/defect | **153 / 153 = 100.00 %** |

**The true blind VE-v2 number (153/156) equals the true blind VE-Human number (153/156)** — the two
prompt formats of the same 156 problems converge to the same capability, which cross-validates both
measurements.

## The 3 residual fails — §4 FLOOR (RCA'd in convergence mode, not fixable without cheating)

| Problem | §4 category | Why |
|---|---|---|
| `Prob062_bugs_mux2` | spec-ambiguity | "Fix this mux." The buggy code's intent is `sel ? b : a`; the reference flips it to `sel ? a : b`. The prompt states no sel polarity — only the hidden ref picks one. |
| `Prob093_ece241_2014_q3` | spec-ambiguity / prompt typo | The prompt's mux_in ordering clause is truncated ("and so in" [sic]); binary vs Gray column mapping is undefined and only the hidden ref fixes it. |
| `Prob099_m2014_q6c` | dataset defect | prompt Y1–Y4 / TB Y2,Y4 / ref Y1,Y3 — mutually inconsistent; cannot compile. |

Notably `Prob149_ece241_2013_q4` (the water-level FSM that is a floor in VE-Human) **PASSED blind
here**: the AI-backup applied the reset-equivalence anchor ("low for a long time ⇒ all four outputs
asserted, including dfr") which pins dfr's polarity to match the golden — a genuine blind recovery.

## Enhancement captured this round (shared with VE-Human)

`dff_edge_synth.py` unstated-edge → posedge fix (shipped v1.3.27) also raises the VE-v2 deterministic
layer. No VE-v2-specific Bucket A was extracted; the FSM reset-by-convention idea was deliberately
NOT shipped (would weaken a §4.05 no-leak guardrail — see the VE-Human blind RESULT).

## Tool-substitution disclosure

Official VerilogEval mandates Synopsys VCS / Cadence Xcelium; this run uses **Icarus Verilog 12**
for the functional pass@1. No PPA scoring. Scorer runs from the design directory.

## Artifacts

- Per-problem verdicts: `score_verilogeval.py --run run_blind_v1.3.27 --dataset <spec-to-rtl>`
- Blind samples: `samples/<Prob>_sample01.sv`
- Convergence twin (reference-read, for comparison): `../run_fresh_v1.3.26/` (155/156)
