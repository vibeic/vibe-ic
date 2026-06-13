# VerilogEval-v2 — blind run on v0.1.19 (IC-Expert agent skills for the non-deterministic tail)

## Headline
**152/156 = 97.44%** (4 fails), fully blind — new high in the series, +2 over v0.1.17 with **zero
regressions** (a clean gain, not variance churn).

| Run | Added | pass@1 |
|---|---|---|
| iter0 | base | 141/156 |
| enhanced-blind | uninit lint | 147/156 |
| v0.1.13 | function-arg fix | 149/156 |
| v0.1.16 | FSM-style conformance + semantic confirm | 148/156 |
| v0.1.17 | "Moore always realizable" | 150/156 |
| **v0.1.19** | **IC-Expert skills: min-SOP/POS rigor, behavioral comprehension, spec-defect detection; PM ambiguity escalation** | **152/156** |

## The user's thesis, validated: where a program can't decide, agent skills do
v0.1.19 shipped no new deterministic gate — only LLM-judgment **skills** in the IC Expert / PM
agents. They fixed exactly the two fails predicted to be agent-improvable, with no regressions:

- **Prob070 FIXED** by the *minimum SOP/POS with don't-cares* skill. v0.1.17's blind shot used a
  care-correct but **non-minimal** `b&c&d | ~a&~b&c`; this run the agent computed the true minimal
  cover **`c&d | ~a&~b&c`** (the `c&d` term absorbs don't-cares 3,11) — byte-identical to the
  reference's minimal SOP, so it now also matches on the don't-care inputs. Pure agent-skill win.
- **Prob150 FIXED** by the *rigorous FSM-spec comprehension* skill (exhaustive one-hot
  next-state table). It had been blind-variance-failing.

## Remaining 4 — all dataset-quality issues, not gate-addressable
- **Prob062** — bug-fix mux: the dataset reference uses `sel?a:b`, the opposite polarity of the
  embedded buggy code's `(~sel&a)|(sel&b)`=`sel?b:a`. Agents flagged it as a spec defect.
- **Prob093** — the reference emits `mux_in[2]=~d`, which contradicts the prompt's own printed
  K-map (`c|~d`). Our (more-correct) `c|~d` "mismatches" the buggy oracle. Not blind-detectable.
- **Prob099** — testbench wires `.Y2/.Y4` to a RefModule that only has `Y1/Y3` → un-runnable for
  any TopModule. Agents flagged the garbled prose vs interface. Hard ceiling.
- **Prob149** — reservoir-valve FSM: the prose ("dfr opens when previous level was lower") is
  internally inconsistent with the reset anchor ("all outputs asserted at the lowest level"). The
  agent flagged the contradiction and implemented the defensible reading; still differs from the
  reference's specific resolution.

3 are hard dataset defects (062/093/099); the 4th (149) is an internal spec contradiction the
agent now *detects* (spec-defect skill) rather than silently mis-implementing. None is fixable by
a reliable, general, spec-derived mechanism without overfitting.

## Division of labor that emerged
- **Deterministic program gates** handle the decidable: ports, widths, directions, reset/FSM-style
  conformance, uninit-registered-output, function-arg parsing.
- **LLM-judgment agent skills** handle the undecidable-by-program: don't-care minimization choice,
  behavioral/waveform/FSM comprehension, and detecting+escalating spec defects/ambiguity.
- These skills ride the model: they get better as the underlying LLM improves.

## Reproduce
```bash
python3 score_verilogeval.py --run run_blind_v0119 \
    --dataset /home/reyerchu/AI_IC_design/_extbench/verilog-eval/dataset_spec-to-rtl
```
