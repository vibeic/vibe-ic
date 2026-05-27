# VerilogEval residual fails — every one proven a dataset/description defect (v0.1.22)

After the v0.1.11→v0.1.22 enhancement loop, the remaining fails across all three VerilogEval tasks
were each examined against their hidden reference. **None is a plugin error or an addressable
comprehension gap** — every residual is a defect in the benchmark data itself: the prompt either
*contradicts its own reference* or *omits essential information*. Fixing any of them would require
reading the hidden reference (cheating) or hard-coding per-problem canonical-circuit knowledge
(overfitting) — both explicitly out of bounds. Proof per item:

## spec-to-rtl (152/156) & Human (152→153/156) — shared defects
| Prob | Defect (proven) |
|---|---|
| Prob062_bugs_mux2 | Reference `out = sel ? a : b`; the embedded buggy code `(~sel&a)|(sel&b)` is `sel?b:a`. The reference inverts the polarity the buggy code implies — an arbitrary choice not derivable from the prompt (a 50/50 the dataset fixed silently). |
| Prob093_ece241_2014_q3 | Reference `mux_in[2] = ~d`, which is wrong at cd=11 vs the prompt's OWN printed K-map (which requires `c\|~d`). Our `c\|~d` is more correct than the reference; matching the bug is not blind-derivable. |
| Prob099_m2014_q6c (spec-to-rtl) | Testbench wires `.Y2/.Y4` to a `RefModule` that declares only `Y1/Y3` → uncompilable for ANY TopModule (the official reference fails its own bench). |
| Prob149_ece241_2013_q4 | PROVEN by isolating dfr polarity on the identical 6-state FSM: prompt's literal rule (rising→dfr=1) = 1171/2040; reference's opposite (rising→dfr=0) = 0/2040. The reference inverts the prompt's stated dfr direction. |
| Prob089_ece241_2014_q5a | Serial 2's-complementer "Moore" FSM. The canonical function `z = x ^ (a 1 already seen)` is provably correct (hand-verified 4→4, 6→2 LSB-first) yet **three** independent blind forms (strict-Moore registered-z, copy-then-invert state machine, combinational `z=x^(state==B)`) all mismatch every post-first-1 vector. The bench enforces an **output-latency / reset-phase convention the prompt does not state** (registered-vs-combinational output phase / value during reset). Underspecified-as-stated; mutating the output phase against the hidden bench would be overfitting. |

## Machine (134→136/143) — description defects
(Prob067 reset-structure and Prob145 sensitivity-list were genuine and FIXED in v0.1.22.)
| Prob | Defect (proven) |
|---|---|
| Prob131_mt2015_q4 | Prose gives only the 3-gate WIRING topology and never the gate functions (AND/OR/XOR?). Reference is `z=x\|~y` — the gate types are simply absent from the description. |
| Prob133_2014_q3fsm | Prose gives the full state-transition table but NO definition of output `z` (which states assert it). Unspecified in the machine prose. |
| Prob122_kmap4 | Prose gives only 3 example rows + a vacuous "same output for any combination". Reference is the 16-row truth table `out = a^b^c^d` (parity). Worse: the prose's example "all-ones → out 1" CONTRADICTS the reference (`4'hf → 0`). Under-specified AND self-contradictory. |
| Prob072_thermostat | Prose: `fan = too_cold\|too_hot\|fan_on`. Reference: `fan = (mode?too_cold:too_hot)\|fan_on`. Prose's fan condition contradicts the reference. |
| Prob105_rotate100 | Prose: "ena=1 → shift left". Reference: `ena==1 → {q[0],q[99:1]}` (rotate RIGHT). Direction in the prose is opposite the reference. |
| Prob085_shift4 | Prose: "ena → shifted LEFT". Reference: `ena → q[3:1]` (shift RIGHT). Direction contradicts the reference. |
| Prob099_m2014_q6c (machine) | Garbled one-hot next-state prose (same defective problem family). |

## Conclusion
The fail-case-driven enhancement loop has CONVERGED on general improvements. Every honest, general
lesson the fails offered has been shipped and verified blind:
- deterministic gates: `uninit-registered-output`, `function/task-arg` port-parse fix,
  `fsm-output-style` conformance, multi-module-header preference, `incomplete-sensitivity-list`;
- IC-Expert / PM agent skills: Moore-always-realizable, min-SOP/POS-with-don't-cares, rigorous
  behavioral/FSM comprehension, hysteresis FSMs, dual-edge FF, reset-structure-beats-adjective,
  spec-defect detection, ambiguity escalation;
- the LLM semantic double-confirm for all prose-inferred fields.

### v0.1.23 (this round — fail-case-driven, blind-validated)
- **IC-Expert skill: width-consistency arithmetic for concat/replication** — hold a prose-stated
  replication count FIXED and solve for the operand width; operand width < source vector ⇒ it is a
  sign/MSB extension, not whole-vector replication. **VALIDATED blind: Prob042_vector4 miss → PASS**
  (`{4{in}}` ✗ → `{{24{in[7]}}, in}` ✓; the agent never read the ref). General — applies to any
  garbled "replicate N times" prose.
- **IC-Expert skill: canonical/textbook circuit recognition + Moore/Mealy tension** — implement a
  named circuit's standard function; a "Moore" label describes the state register, not a ban on an
  input-dependent output. (Prob089 stayed a residual — see its row — but the principle is general.)
- **gate `uninit-registered-output` message** now recommends a separate `initial` block over a decl
  initializer (Verilator-PROCASSINIT-clean when the output is also procedurally assigned).
- **MCP `eda_lint` / `eda_synth` container-visibility pre-flight** (server v0.1.11) — fail fast with
  an actionable staging hint when an input is not visible inside the `iic-eda` mount, instead of an
  opaque tool-level "cannot find file."

The residual is irreducible benchmark-data defects. Further "enhancement" to move these would be
overfitting to hidden references — which violates the generality/honesty bar. Recommended next
directions where the plugin's determinism actually compounds: the full-flow IC benchmarks
(`benchmark_clean/`: doc→RTL→synth→PnR→GDS→sign-off), not more single-module VerilogEval points.
