# vibe-ic Guide Map — Entry Paths · Convergence Loops · Expected Results

> The one page the IC Expert Agent (and the user) reads to know **① capability scope
> ② all entry paths ③ expected results**. Canonical sources it summarizes:
> `plugins/vibe-ic/flow/phase1_phase2_phase3.yaml` (53-step flow, enforced by
> `flow_compliance_check.py`), `agents/ic-expert-agent.md § IC-EXPERT OPERATING MAP`,
> `benchmark/BENCHMARK_REGISTRY.json`, `benchmark/CAPTURE_ROUTING.json`.

## Capability scope

Spec/NL/docs → **Phase 1** (L1–L23 design docs) → **Phase 2** (RTL → lint → synth →
spec-conformance → audit) → **Phase 3** (PnR → CTS → DRC/LVS/STA/IR-drop) → GDS.
Plus **Analog A1–A9**, **Mixed-signal M1–M4**. Program-first + AI-backup at every step
(dual-track convergence); §4.05 — read only the design INPUT, never the oracle.
Flow size: **44 main-track steps + 9 analog steps ≈ 53**, 3 phases.

## Entry paths (the agent picks by condition)

| # | Condition | Entry | How |
|---|---|---|---|
| E1 | User has an **input folder** (docs/spec) | **Phase 1 front door** | `vibe_ic_one_shot_runner.py <project> --pdk sky130A` |
| E2 | User only has **a conversation** | **Phase 1 front door (dialogue)** | Talk to the IC Expert Agent → unified DOC→JSON track → L1–L23 |
| E3 | User imports **design documents** | **Phase 1 front door (doc import)** | Docs → `phase1_one_shot_runner.py` → L1–L23 |
| E4 | **Debug task** — RTL already exists, must be fixed/completed (e.g. CVDP) | **Phase 2 mid-entry** | Runner detects `rtl_gen=null` → WAIVE `spec-to-rtl` → author into `phase2/stage1/rtl/` → runner gates fire → converge |
| E5 | **Benchmark** run | **Benchmark dispatch** | `benchmark_dispatch.py` routes to the registry Shape (A/B/C/D) — never a hand-rolled harness |

> **Rule 0:** a benchmark enters through the SAME door as a general IC task (E1–E4).
> The only benchmark-specific glue is the thin IO shell (stage record → project;
> gate/scorer out). There is exactly one solve entry.

## Convergence loops (know every one)

| Loop | Where | Purpose |
|---|---|---|
| **spec-to-rtl dual-track** | Phase 2 `step_rtl_gen` | program RTL dispatch first; on `rtl_gen=null` WAIVE to the AI `spec-to-rtl` skill, then runner gates re-fire |
| **eco_loop** | Phase 2 | close-loop RTL repair when a gate (hygiene/conformance/lint/synth) fails |
| **analog-sizing-loop** | Analog A-track | transistor sizing convergence against spec targets |
| **Analog Corner Sweep (PVT)** | Analog A-track | re-sim across PVT corners until all pass |
| **ADI (Analog-Digital Interface) loop** | Mixed-signal | `adi-spec-gen` → `L5_ADI_SPEC.json`; converge the analog↔digital interface |
| **benchmark converge → capture → distill** | Benchmark Agent | every fail → official PASS → distil the general fix into `programs/*.py` so the next blind run auto-recovers (program-first) |

## Expected results (self-check targets)

**Per-phase artifacts:**
- Phase 1 → `phase1/generated_docs/L1..L23*.json` (13 L-docs gate).
- Phase 2 → `phase2/stage1/rtl/<top>.v` + lint/synth/conformance/audit reports.
- Phase 3 → PnR/CTS/DEF/GDS + DRC/LVS/STA/IR reports.
- Orchestrator → `reports/orchestrator/vibe_ic_one_shot.json`.

**Verified benchmark scores** (plugin v1.3.27–29, Opus 4.8, iverilog, §4.05-blind):

| Benchmark | Shape | Score | Excluding floor/defect |
|---|---|---|---|
| VerilogEval-v2 | C | 153/156 | 100% |
| VerilogEval-Human | C | 153/156 | 100% |
| RTLLM v2.0 | B | 43/50 blind (44/50 re-score) | **43/43 = 100%** ex 5 dataset defects + 2 tool-gaps |
| cvdp-open (302 nonagentic) | C/D | 210/302 single-shot | — |

Reproduce deterministically: `tools/release/verify_clean_platform.sh` (asserts these
numbers by re-scoring the committed samples).

## Guardrails the agent always holds

- **Program-first**: try the deterministic program; AI-backup is the independent
  second track, not an on-failure fallback — converge every disagreement.
- **§4.05 blindness**: author reads ONLY prompt + provided context; the scorer is the
  only thing that touches the testbench/oracle.
- **flow compliance**: no PASS is real without `flow_compliance_check.py` exit 0.
