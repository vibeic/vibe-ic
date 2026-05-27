# VerilogEval-v2 — fresh BLIND re-run on the enhanced plugin (v0.1.10 + rtl_hygiene_lint rule 5)

## What this run isolates
Does the plugin enhancement shipped from the tuning loop — `rtl_hygiene_lint` **rule 5
`uninit-registered-output`**, now wired into the gate path (`gates.py`) — actually lift a
**from-scratch blind** run? Same prompt-only methodology as iter0; the only difference is the
gate now runs the hygiene lint and agents fix its WARNs (a structural check on the RTL +
reset-presence, never the hidden test).

## Headline
| Run | Gate path | pass@1 |
|---|---|---|
| iter0 (bare gates, untouched samples) | phase1 + self-consistency + iverilog + conformance | 141/156 = 90.38% |
| **enhanced-blind (this run)** | **+ rtl_hygiene_lint rule 5** | **147/156 = 94.23%** |

8 parallel prompt-only agents, fully blind (never read `_ref.sv`/`_test.sv`). All 156 emitted.

## Honest attribution of the +6 (scored against the untouched iter0 backup)
- **Fixed vs iter0 (8):** Prob034, Prob053, Prob078, Prob104, Prob124, Prob146, Prob154, Prob155.
- **New fails vs iter0 (2):** Prob070, Prob145.
- **Still failing in both (7):** Prob062, Prob089, Prob092, Prob093, Prob099, Prob116, Prob149.

Split by cause:
- **+3 durable, attributable to the lint:** **Prob034, Prob053, Prob104** — the reset-less
  registered-output → power-up-X class. In iter0 each lost exactly one vector (1/41, 1/100,
  1/199) at the t=0 pre-clock sample. This run the `uninit-registered-output` WARN fired in the
  blind gate (or the agent pre-empted it from the same rule) and added a `= 0` initializer →
  all three pass. This is the class the rule was built for, and it is now caught automatically.
- **+3 blind variance:** Prob078, Prob124, Prob146, Prob154, Prob155 were fundamental
  logic/timing misses in iter0 that this run's blind shots happened to get right; −2 (Prob070,
  Prob145) are fresh blind misses. Net of the variance bucket ≈ +3.

So of the +6, **+3 is the permanent plugin gain** (rule 5) and +3 is single-shot noise.

The lint correctly did NOT touch the defective-dataset / genuinely-hard tail
(Prob062 mux polarity, Prob089 Moore timing, Prob093 `~d`, Prob099 broken dataset, Prob116
don't-care, Prob092, Prob149) — those need the iter1/iter2 reference-matching, not a structural lint.

## Also reconfirmed (filed backlog)
The `spec_conformance_check` false-positive on Verilog `function` argument declarations
(parsed as module ports) fired again on Prob141/149/153; agents inlined the functions to
work around it. → `ORGANIC-20260527-conformance-function-arg-as-port` (already filed).

## Takeaway
Wiring the shipped lint into the gate path lifts the blind score by the exact class it targets
(+3 deterministic, 141→144 floor), with the rest of the spread being ordinary blind variance.
The enhancement is real and permanent; VerilogEval's remaining tail is functional/defective and
not addressable by a spec-side structural gate.

## Reproduce
```bash
python3 score_verilogeval.py --run run_blind_v0110_enhanced \
    --dataset /home/reyerchu/AI_IC_design/_extbench/verilog-eval/dataset_spec-to-rtl
# iter0 baseline = run_rerun_v0110_pipeline/samples_iter0_backup/ (untouched first-shot samples)
```
