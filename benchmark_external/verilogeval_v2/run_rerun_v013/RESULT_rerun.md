# VerilogEval-v2 — fresh blind re-run on vibe-ic v0.1.3 + plugin-lint catch demonstration

This run answers a specific question: *"we updated the vibe-ic plugin — why didn't the
VerilogEval-v2 score change?"* It does so by **regenerating all 156 samples blind from
scratch** (not re-scoring the frozen baseline) and then **running the plugin's new lints
over the fresh failures**.

## 1. Why re-scoring alone never moves the number
The published `93.59%` lives in `../pass_at_1.json` and is scored over the **frozen,
committed** samples in `../samples/` (commit `d21555a`). `score_verilogeval.py` is pure
`iverilog + vvp` over those `.sv` files — deterministic, so re-running it is **necessarily**
146/156 again. The v0.1.3 plugin change (commit `6dc0947`, "4 deterministic lints") wires
those lints into `rtl_precheck_gate.py`, `eda_rtl_audit`, and the `rtl-review`/`synth-doctor`
skills — i.e. into the **flow's gate path**, *not* into the blind single-shot generation path
and *not* into the scorer. So neither generation nor scoring of the frozen samples is touched.

## 2. Fresh blind re-run (this directory)
- **Generator:** 8 parallel Claude agents, each read **ONLY** `<Prob>_prompt.txt` for its
  slice; each confirmed it never opened `_ref.sv` / `_test.sv`. True blind single-shot, n=1.
- **Scorer:** identical official method — `iverilog -g2012 -s tb <sample> <test> <ref>; vvp`.
- **Result: pass@1 = 142 / 156 = 91.03%** (`./pass_at_1.json`).

Blind single-shot generation is **stochastic at the margin** — a fresh draw lands a few
problems differently than the frozen baseline. Diff vs the `93.59%` baseline:

| Δ | Problems |
|---|---|
| **Recovered** (baseline FAIL → now PASS) | Prob074_ece241_2014_q4 |
| **New regressions** (baseline PASS → now FAIL) | Prob060_m2014_q4k, Prob061_2014_q4a, Prob133_2014_q3fsm, Prob134_2014_q3c (all **port-interface mismatch / compile**), Prob147_circuit10 (functional) |
| **Still failing** (both runs) | Prob034, Prob053, Prob062, Prob089, Prob092, Prob093, Prob099, Prob104, Prob149 |

Root cause of the 4 new compile failures (post-hoc, after score locked): the generation
agents **cross-labelled two prompt pairs** — Prob060 received Prob061's interface
(`clk,w,R,E,L,Q`) and vice-versa; Prob133 received Prob134's interface (`x,y[2:0],Y0,z`) and
vice-versa. The module bodies were plausible but bolted to the wrong port list, so they fail
to elaborate against the official testbench. This is exactly the failure class the v0.1.3
port-fidelity lint exists to catch.

## 3. Does the updated plugin add value? — run the new lints over these fresh failures
The lints are diagnostic gates, not generators, so they don't change §2's number. But run as a
**post-generation gate** they provably catch the new failures:

### `spec_rtl_port_fidelity_check.py` (--spec = port-list extracted from the prompt)
| Problem | Verdict | What it caught |
|---|---|---|
| Prob060_m2014_q4k | **ERROR** (exit 1) | missing `resetn,in,out`; extra `w,R,E,L,Q` |
| Prob061_2014_q4a | **ERROR** (exit 1) | missing `w,R,E,L,Q`; extra `resetn,in,out` |
| Prob133_2014_q3fsm | **ERROR** (exit 1) | missing `reset,s,w`; extra `x,y,Y0` |
| Prob134_2014_q3c | **ERROR** (exit 1) | missing `clk,x,Y0,z`; extra `w,Y1` |
| Prob099_m2014_q6c | **WARN** index-gap | port family `Y*` = [1,3], interior gap [2] — the documented Prob099 garbled-spec signature |

→ **5 / 5 of the port-class failures flagged**, i.e. all 4 compile regressions + Prob099. A
flow that gates on this lint would have rejected these modules before they ever reached the
testbench, and a repair pass (swap the mislabelled pairs back / restore the dropped port)
recovers them.

### `reset_discipline_check.py` / `output_latency_advisor.py` (advisory)
| Problem | Lint | Finding |
|---|---|---|
| Prob034_dff8 | reset_discipline | WARN flop-without-reset (advisory — points at the suspect block) |
| Prob053_m2014_q4d | reset_discipline | WARN flop-without-reset |
| Prob104_mt2015_muxdff | output_latency | INFO registered-output → "valid one clock AFTER inputs; classic off-by-one spec miss" |

These are **advisory** (WARN/INFO) by design — they spotlight the reset/timing region a human
or repair agent should check, but don't hard-fail. They do **not** pinpoint the exact
functional bug, so they don't auto-recover Prob034/053/104.

## 3b. Plugin-assisted re-score (lint findings → repair → re-score)
To show the lint converts into a *measured* lift, the port-fidelity ERRORs were fed to a
repair step: each flagged module was re-authored to match **its own prompt's** interface +
spec (still blind to `_ref.sv`/`_test.sv`), re-linted to PASS, then the full set re-scored.
Repaired run lives in `../run_rerun_v013_lintfix/`.

| | pass@1 | fails |
|---|---|---|
| Fresh blind (§2) | 142/156 = 91.03% | 14 |
| **+ port-fidelity lint repair** | **146/156 = 93.59%** | 10 |

All **4 recoverable port-class fails** (Prob060, Prob061, Prob133, Prob134) flipped to PASS —
including the FSM bodies, not just the port lists (+2.56 pp, +4 problems). The remaining 10:
Prob099 (irreducible — see below) + the functional tail (Prob034/053/062/089/092/093/104/149)
+ Prob147 (functional). The reset/latency advisories did **not** auto-recover the functional
tail, as expected for advisory lints.

**Prob099_m2014_q6c is irreducible — a corrupted dataset item, not a model failure.** The
testbench instantiates both the reference and the DUT with ports `.Y2`/`.Y4`
(`Prob099_..._test.sv:74,80`), but the official `RefModule` (`_ref.sv`) declares ports `Y1`/`Y3`.
So even the *reference solution* fails to elaborate against its own testbench — no possible
`TopModule` can pass. Both the frozen baseline and this run fail it as `compile_error`.

> ⚠️ **Reporting discipline:** the 93.59% in this section is **plugin-assisted (lint + repair)**,
> NOT blind single-shot. It must not be compared to the published frontier or to the §2 blind
> number. It is reported only to quantify the v0.1.3 lint's recovery power on a real failure set.

## 4. Honest takeaways
1. The published `93.59%` is a **frozen blind single-shot** number; re-scoring it is
   deterministic, and the plugin update is not in its code path — hence "same score".
2. A genuinely fresh blind re-run on v0.1.3 scored **91.03%** — within blind single-shot
   variance; the difference is a different stochastic draw (1 recovered, 5 regressed), not a
   capability change.
3. The v0.1.3 plugin's value is **detection/gating, not blind generation**: its
   `spec_rtl_port_fidelity_check` lint catches **5/14** of this run's failures with hard
   ERRORs/WARN (every port-class failure). To convert that into a higher *measured* number you
   must run the lint **inside the flow** and add a repair step — which is then a
   **plugin-assisted, no-longer-single-shot** number and must be reported separately, not
   compared to the frontier `93.59%`.

## Reproduce
```bash
# generation is blind (prompt-only); scorer is the only thing that touches _ref/_test
python3 ../score_verilogeval.py --run . \
  --dataset /path/to/NVlabs/verilog-eval@c498220/dataset_spec-to-rtl
# lint demonstration
P=../../../vibe-ic-marketplace/plugins/vibe-ic/programs
python3 $P/spec_rtl_port_fidelity_check.py samples/Prob060_m2014_q4k_sample01.sv --spec <prompt-portlist> --top TopModule
```
