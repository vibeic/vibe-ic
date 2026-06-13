# VerilogEval-Machine (legacy iccad2023 machine descriptions) — Vibe-IC v0.1.21 blind run

## Headline
**pass@1 = 134 / 143 = 93.71%** — fully blind, 8 parallel prompt-only agents, official testbench
scoring (`iverilog -g2012 -s tb <sample> <test> <ref>; vvp` → `Mismatches: 0`).

VerilogEval-**Machine** = the auto-generated (LLM-written) problem descriptions from the original
2023 VerilogEval. **It was dropped in VerilogEval v2** ("MachineEval is not supported in
VerilogEvalV2"), so the descriptions were fetched from the upstream `v1.0.0` tag
(`descriptions/VerilogDescription_Machine.jsonl`, 143 of the 156 problems have a machine
description). Each prompt = the verbose machine `detail_description` + the exact iccad2023 module
header; scored against the same test/ref as the other tasks.

## Cross-task comparison (same plugin v0.1.21, same blind pipeline)
| Task | prompt style | pass@1 |
|---|---|---|
| spec-to-rtl (v2) | structured interface bullets | 152/156 = 97.44% |
| Human (iccad2023) | concise human prose + header | 152/156 = 97.44% (153 solvable) |
| **Machine (iccad2023 legacy)** | **verbose LLM-generated prose + header** | **134/143 = 93.71%** |

Machine is ~3.7 pts lower — as expected: the auto-generated descriptions are noisier and, in
several cases, **omit or contradict information** the circuit actually needs.

## The 9 fails — dominated by machine-description quality, not the plugin
- **Description omits essential behavior (unsolvable from the machine prompt alone):**
  - **Prob131_mt2015_q4** — prose gives only the 3-gate WIRING topology, never the gate functions.
  - **Prob133_2014_q3fsm** — prose lists state transitions but gives NO `z` output definition.
  - **Prob122_kmap4** — under-specified K-map (3 rows + a vacuous "same output for any combination").
  Agents flagged all three as defects and implemented the most defensible guess; the missing info
  is simply not in the machine description (the Human description has it).
- **Description noise / ambiguity led to a wrong interpretation:**
  - **Prob067_countslow** (reset sync/async wording), **Prob072_thermostat** (fan-logic gloss),
    **Prob085_shift4**, **Prob105_rotate100** (shift-vs-rotate / ena encoding),
    **Prob145_circuit8** (mixed-clock latch+FF), **Prob099_m2014_q6c** (garbled one-hot prose).

So the machine-vs-human gap is the benchmark's own description quality — the plugin gates/skills
behaved identically (uninit-init, dual-edge canonical form on Prob078 ✓, QM K-map minimization,
Moore registering, spec-defect flagging fired on exactly the broken machine prompts).

## Reproduce (dataset is regenerable, not vendored)
```bash
# 1. fetch upstream v1 machine descriptions
git clone --depth 1 --branch v1.0.0 https://github.com/NVlabs/verilog-eval /tmp/veval_v1
# 2. synthesize dataset_machine/: per problem, prompt = detail_description + iccad2023 _ifc.txt,
#    copy iccad2023 _ref.sv/_test.sv  (143 problems that have a machine description)
# 3. score
python3 score_verilogeval.py --run run_v0121 --dataset dataset_machine
```
(`dataset_machine/` and `run_v0121/work/` are git-ignored — regenerable from upstream + iccad2023.)

## v0.1.22 targeted re-verify (Prob067, Prob145) — blind, official testbench
Both fixed by the v0.1.22 general enhancements, verified blind:
- **Prob067_countslow → PASS (0/499).** reset STRUCTURE-beats-adjective skill: the agent read the
  prose's "always block on the rising clock edge that first checks reset" as a SYNCHRONOUS reset
  (despite the "asynchronous" label) and implemented `always @(posedge clk) if(reset)...`. (The
  deterministic `spec_conformance._detect_reset` still soft-FAILs on the bare "asynchronous"
  keyword — correctly surfaced as a NOT-LLM-confirmed candidate that the agent overrode; hard gates
  pass. This is the intended program-proposes / LLM-confirms split.)
- **Prob145_circuit8 → PASS (0/240).** Level-sensitive-`@(*)` skill: the agent authored the
  transparent latch as `always @(*) if(clock) p=a;` from the start (the broken `always @(a)` form
  the rtl_hygiene_lint rule 6 `incomplete-sensitivity-list` gate would have flagged).

**Net Machine with v0.1.22 = 136/143.** Residual 7 are description defects (072/105/085 prose vs
ref, 131/133/122 omit info, 099 garbled) — not honestly fixable from the machine prompt.
