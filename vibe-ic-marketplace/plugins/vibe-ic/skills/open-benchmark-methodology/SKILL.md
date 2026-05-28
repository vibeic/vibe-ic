---
name: open-benchmark-methodology
description: "MANDATORY consult any time these keywords appear: VerilogEval, VerilogEval-v2, VerilogEval-Human, CVDP, RTLLM, PyHDL-Eval, RTL-Repo, MetRex, ResBench, ChipAgentsBench, vibeic-bench, benchmark, pass@1, doc→RTL, doc→GDS, run benchmark, rerun benchmark, score benchmark, benchmark methodology, benchmark floor, benchmark defect. The doctrine: program-first, agent-only-on-failure — Vibe-IC's product is the deterministic runner chain (vibe_ic_one_shot_runner.py → phase1/2/3 + plugin programs + MCP-EDA), so a benchmark NUMBER must measure what the runner can do, not what a direct AI agent can do with the same MCP tools. This skill encodes (§1) where Vibe-IC is a program vs an LLM in v0.1.26+, (§2) the five canonical run-shapes (A=full-runner / B=runner --skip-phase3 / C=gates.py harness / D=agentic-with-runner / E=blocked-or-out-of-scope), (§3) mandatory tool-substitution disclosure (Synopsys VCS→iverilog, DC→yosys+OpenROAD, NVIDIA cvdp-sim→iic-osic-tools) + the cwd=design_dir rule, (§4) the triage rubric A-H separating FLOOR (benchmark-defect / under-spec / tool-gap / spec-ambiguity) from agent-fixable (description-clue-missed / convention-inference / real-RTL-bug), (§5) per-benchmark cheat sheet with current shape + status + any TARGET RE-RUN flagged, (§6) mandatory RESULT.md sections, (§7) tie-breakers, (§8) re-run obligations. Triggers also on phrases like 'run X benchmark', 'reproduce X', 'rerun X', 'is this the right method', '應該用什麼方法跑這個 benchmark', '怎麼測 X', '是否方法錯誤'. NEVER propose a benchmark run plan, interpret a benchmark result, or call something 'benchmark floor' without consulting this skill first."
---

# Open-Benchmark Methodology — program-first, agent-only-on-failure

This skill records the **canonical method** for driving any open IC-design benchmark through
Vibe-IC. The core doctrine, established by hard-won evidence from the 2026-05-28 benchmark
sweep (see `benchmark_external/RESULT_MCP_EDA_v0125_FRESH.md`, `benchmark_clean/RESULT_v0125_fresh.md`,
`benchmark_external/rtllm/RESULT.md`):

> **Vibe-IC's product is the deterministic runner chain** (`vibe_ic_one_shot_runner.py` →
> `phase1/2/3_one_shot_runner.py` + plugin programs + MCP-EDA tools). The benchmark NUMBER
> we publish must measure **what the runner can do**, not what a fresh AI agent can do with
> the same MCP tools.
>
> Direct-agent authoring (no runner) only tests "Opus + MCP-EDA" generic LLM-with-tools
> capability — that's not Vibe-IC's value proposition.

⛔ **Do not pick the run-shape by feel.** Read § 1 (taxonomy) and § 2 (decision matrix) below
before invoking any benchmark agent or runner.

## § 1 — Where Vibe-IC is a PROGRAM and where it's an LLM (the boundary every benchmark designer must respect)

In v0.1.26 the plugin's `phase2_one_shot_runner.step_rtl_gen` for the `digital_arithmetic_primitive`
class (and any class whose `rtl_gen=null`) **WAIVES with `fallback_skill=spec-to-rtl`**. The
spec-to-rtl skill is an AI skill — there is **no deterministic spec→Verilog program**, because
natural language to RTL fundamentally requires a language model. What IS deterministic:

| Step | Deterministic program? | Where |
|---|---|---|
| Phase 1: NL prompt → L1-L13 JSON | ✅ | `phase1_engine` / `phase1_one_shot_runner.py` |
| ic_class detection + dispatch | ✅ | `phase2_one_shot_runner.py` + `ic_class_profile.py` |
| **spec → RTL authoring** | **❌ AI skill** | `spec-to-rtl` (fallback skill) |
| RTL hygiene (power-up `--fix`, latch repair) | ✅ | `rtl_hygiene_lint.py --fix` |
| Spec-conformance gate (ports/widths/reset) | ✅ | `spec_conformance_check.py` |
| Lint / synth / FPGA / cocotb (MCP-EDA) | ✅ | `eda_lint`, `eda_synth`, `eda_cocotb`, `eda_simulate` |
| Phase 3: PnR / DRC / LVS / STA | ✅ | `phase3_one_shot_runner.py` + OpenROAD/klayout |

The **runner wraps the AI authoring step inside a determined pipeline of gates** (hygiene, conformance,
lint, synth, audit) **and is what Vibe-IC actually delivers**. A benchmark that bypasses the runner
and lets an agent author RTL directly tests only "the LLM under our roof", not "Vibe-IC".

## § 2 — Decision matrix: which run-shape for which benchmark

For every new benchmark, answer these questions in order:

1. **Is the benchmark a full IC** (multiple modules, register map, FSM, SoC integration, with a
   constraints / floorplan / PDK target)? → **Shape A: full runner**.
2. **Is the benchmark a substantial standalone design** (counter / FIFO / FSM / ALU / arithmetic
   block with its own testbench) at the single-module level? → **Shape B: lightweight runner-path
   (skip phase3)**.
3. **Is the benchmark an atomic micro-problem** (≤ 30-line spec, single small module, one prompt
   file like VerilogEval `Prob001_zero_prompt.txt`)? Running the full runner is over-fitting the
   overhead; use **Shape C: gates-based lightweight harness**, which still drives plugin PROGRAMS
   for the verification gates (phase1_engine, spec_conformance_check, rtl_hygiene_lint --fix) but
   skips the runner's IC-level chrome.
4. **Is the benchmark an agentic SoC/multi-task problem** (CVDP-style cocotb harness, RTL-Repo,
   ChipAgentsBench)? → **Shape D: agentic-with-runner** (drive through `vibe_ic_one_shot_runner.py`,
   let `catalog-glue-author` fire if it's REUSED-IP shape).
5. **Is the benchmark's oracle gated, removed, or non-functional-metric**? → **Shape E: document
   as blocked / out-of-scope**, do NOT report a fake number.

### The four real shapes — concrete templates

#### Shape A — Full runner (chip-grade)
**When**: benchmark IC includes L1-L9 design-doc-style inputs (or upstream docs you transcribe into
L1-L9), targets a PDK, expects DRC/LVS/STA sign-off. Examples: `benchmark_clean/{spm,sha256,subservient,u_hawaii_adc}`.

```bash
# Path B: vendor docs already in input/docs/L*.md
python3 ${PLUGIN_PROGRAMS}/vibe_ic_one_shot_runner.py <project> \
    --pdk sky130A --ic-name <ic>
# Result: <project>/reports/orchestrator/vibe_ic_one_shot.json
```

Use agents ONLY when a step inside the runner FAILs (close-loop ECO, never as the primary author).

#### Shape B — Lightweight runner-path (substantial standalone, no silicon)
**When**: each problem is a real design with a testbench but you don't need PnR (e.g. RTLLM,
PyHDL-Eval-if-it-becomes-ungated). The `design_description.txt` (NL prose) is the spec.

Per-design setup — stage the prompt in **both** locations to work around the
`ORGANIC-20260528-phase1-prompt-md-not-ingested` gap (v0.1.30 doesn't auto-bridge):
```
<problem-project>/input/phase1_prompt.md          ← exactly the design_description.txt content
<problem-project>/input/docs/design_description.md ← copy of the same (what the ingester actually consumes)
```

Run the runner with phase3 skipped:
```bash
python3 ${PLUGIN_PROGRAMS}/vibe_ic_one_shot_runner.py <problem-project> \
    --skip-phase3 --skip-analog --skip-hardware
# Outputs RTL at <problem-project>/phase2/stage1/rtl/<top>.v
```

**Important** — the runner WAIVES `step_rtl_gen` for IC classes with `rtl_gen=null` in
`ic_class_registry.json` (currently: digital_arithmetic_primitive, digital_cmd_driven,
bare_fpga, processor_cpu, unknown_protocol_class — see
`ORGANIC-20260528-null-rtl-gen-classes-need-bridge`). When WAIVED, the runner explicitly
directs: *"AI invokes skill spec-to-rtl"*. There is no actual `spec-to-rtl` skill file —
the AI plays the spec-to-rtl ROLE: author RTL at `phase2/stage1/rtl/<top>.<v|sv>` using
the L docs the runner just emitted, then RE-INVOKE the runner so its downstream gates
(`chip_top_gate_wrapper_gen` / `rtl_hygiene_lint --fix` / lint / synth /
`spec_conformance_check` / `eco_loop` / `full_stack_tb_gen` / `final_audit`) fire on your
RTL. **This is NOT bypassing the runner — it IS the runner's design.** Bypass means
authoring with MCP only, outside the runner's pipeline (what the 2026-05-28 wrong-shape
RTLLM 37/50 did).

Then run the benchmark's host scorer (its testbench.v + iverilog/etc.) against the emitted
RTL. **The runner orchestrates; the AI fills the spec-to-rtl role inside the pipeline; the
runner's gates fire around it.**

#### Shape C — Lightweight gates-based harness (atomic micro-problems)
**When**: 156-500 atomic micro-problems per dataset, each a 5-30 line prompt yielding a single
small module. Examples: VerilogEval-v2, VerilogEval-Human. Running the full runner per problem
is overhead-dominated and offers no incremental signal.

Use a per-run `gates.py` that drives plugin PROGRAMS directly for verification while letting the
LLM author the RTL:

```python
# benchmark_external/<bench>/run_*/gates.py — canonical template
1. phase1_engine.cli run-all <spec.yaml> -> L*.json    # PROGRAM
2. spec_self_consistency_check.py --spec <prompt>      # PROGRAM
3. iverilog -g2012 compile of sample.sv                # PROGRAM
4. spec_conformance_check.py --rtl-dir . --spec <prompt> --top <module>  # PROGRAM
5a. rtl_hygiene_lint.py --fix <sample>      # PROGRAM (enforced! v0.1.24 lesson)
5b. rtl_hygiene_lint.py --severity WARN <sample>       # PROGRAM
6. MCP eda_lint + eda_synth (gf180 typically)          # PROGRAM
7. emit sample01.sv on hard-gates PASS
```

The agent's only authoring touch: write `spec.yaml` + `sample.sv` per problem. **Every verification
gate is a plugin program** — that's what makes the number meaningful, even though the runner-wrapper
isn't invoked. **The v0.1.25 enforced power-up `--fix` proved this matters**: a fix written into
the gates held across 17 fresh agents; the same fix as free-text guidance regressed.

This shape is documented in `benchmark_external/verilogeval_v2/run_fresh_v0125/gates.py` (canonical).

#### Shape D — Agentic with runner (SoC / multi-task)
**When**: agentic benchmarks where the unit-of-work is a full SoC + cocotb harness (CVDP). The
runner is the right tool because (a) the IC needs `ic_class` dispatch, (b) `catalog-glue-author`
should fire for REUSED-IP, (c) the cocotb harness must be invoked via MCP `eda_cocotb`.

```bash
# Same as Shape A; CVDP-style problems differ only in that the hidden scorer is cocotb
python3 ${PLUGIN_PROGRAMS}/vibe_ic_one_shot_runner.py <problem-project> --pdk sky130A
# Then score via MCP eda_cocotb against the hidden harness in score/src/
```

Examples: `benchmark_clean/subservient_v0125_fresh` (REUSED-IP SoC path).

#### Shape E — Blocked / out-of-scope
**When**: the benchmark's golden oracle is gated, removed, or the metric isn't functional generation.

**Document it honestly in the RESULT.md**, do NOT fabricate a number. Examples this session:
- **PyHDL-Eval**: 168 RefModule golden Verilog solutions deliberately removed from the public repo
  (README confirms anti-training-contamination). `_test.v` needs RefModule to elaborate → can't
  score officially. Same gated-oracle situation as CVDP full.
- **RTL-Repo**: next-line autocompletion scored by Edit-Similarity + Exact-Match (string match
  to upstream verbatim). Not spec→RTL functional generation; anti-correlated with vibe-ic's
  correct-by-construction value.
- **CVDP full**: 1,500+ problems gated by NVIDIA/Turing access (only the public N=1 example
  problem runnable).

## § 3 — Tool-substitution disclosure (mandatory in every RESULT)

Open benchmarks frequently mandate commercial EDA tools we don't have. Every RESULT.md MUST
state the substitution explicitly:

| Benchmark mandates | We substitute | Caveat |
|---|---|---|
| Synopsys VCS sim | iverilog 12 | Some VCS-only TB constructs (array-aggregate init, `break;`) reject under iverilog → pure tool-gap floor |
| Synopsys Design Compiler PPA | yosys + OpenROAD (sky130/gf180) | NOT reported as PPA in benchmark RESULT (not apples-to-apples). If you DO report, label clearly |
| Cadence Xcelium | iverilog | Same iverilog-vs-commercial gap as VCS |
| `nvidia/cvdp-sim:v1.0.0` Docker image | `hpretl/iic-osic-tools` (iverilog 13 + cocotb 2.0.1) | Note the substitution + cocotb version delta |

**Run the host scorer FROM the design directory** (`cwd=<design>`) so the TB's relative-path
`$readmemh("reference.txt")` etc. resolves correctly. RTLLM's own `auto_run.py` does this
(`os.chdir(design); make vcs`). Forgetting this caused 3 false fails in our 2026-05-28 RTLLM run.

## § 4 — Triage rubric: agent-fixable vs FLOOR

Every benchmark run produces residual fails. Categorize each into ONE of these buckets BEFORE
spending compute on close-loop:

| Category | Description | Action |
|---|---|---|
| **A. Benchmark description ↔ TB inconsistency** | Spec says one port name; TB wires a different one | **FLOOR** — unsatisfiable blind without cheating. Document with TB-line evidence. |
| **B. Benchmark under-specification** | TB needs a port/param/parameterization the prose never states | **FLOOR** — same |
| **C. Positional-instantiation convention** | TB uses positional with an undocumented port order | **FLOOR** |
| **D. Tool-substitution gap** | TB uses VCS-only / Xcelium-only constructs iverilog can't run | **FLOOR** (under our substitution) |
| **E. Spec-ambiguity functional mismatch** | DUT compiles + runs; spec admits ≥ 2 valid readings (e.g. shift vs rotate, registered vs comb output, phase convention); TB picks one | **FLOOR** — leave spec-faithful, do NOT over-fit to the hidden oracle. Close-loop's job is to confirm own-TB-passes, not to converge on the hidden TB. |
| **F. Description had it, agent missed it** | The clue WAS in the prose (e.g. "whether the result has been consumed" implies a downstream-ready input); agent overlooked it | **AGENT-FIXABLE** — close-loop after closer re-reading |
| **G. Conventional shape inference** | A canonical pattern (e.g. parameterized pipelined adder uses DATA_WIDTH/STG_WIDTH) the agent should have inferred from genre, not from explicit prose | **AGENT-FIXABLE** with a "convention sweep" close-loop pass |
| **H. Real RTL bug** | Algorithm wrong, off-by-one, wrong feedback polarity | **AGENT-FIXABLE** by blind re-derivation + own-TB self-verify |

Honesty check: if you're tempted to label something Category A-D to avoid a hard close-loop, **first
re-read the description top-to-bottom** for clues (Category F/G). The 2026-05-28 RTLLM triage
under-estimated the recoverable fails (radix2_div, adder_pipe_64bit, LFSR) by failing this check.

## § 5 — Per-benchmark cheat sheet (current as of v0.1.26)

| Benchmark | Shape | Authoring entry | Scoring | Status | Notes |
|---|---|---|---|---|---|
| VerilogEval-v2 (156) | **C** | `gates.py` + LLM | host iverilog + `<Prob>_test.sv` | Done 152/156 = 97.44% | Floor: 062/093/099/149 dataset defects |
| VerilogEval-Human (156) | **C** | `gates.py` + LLM | host iverilog + `<Prob>_test.sv` | Done 153/156 = 98.08% | Floor: 062/093/149 |
| RTLLM v2 (50) | **B** (CORRECT) — was done **C** in 2026-05-28 by mistake, target a re-run | `vibe_ic_one_shot_runner.py --skip-phase3 --skip-analog --skip-hardware` | host iverilog + `testbench.v` (cwd=design) | 37/50 = 74% under wrong-shape; target re-run to measure runner | Iverilog-tool-gap floor: `ring_counter`, `asyn_fifo` (VCS-only TB constructs) |
| CVDP (N=1 example) | **D** (CORRECT) — was done as direct-agent in 2026-05-28, target re-run | `vibe_ic_one_shot_runner.py` | MCP `eda_cocotb` against hidden harness | PASS 9/9 under direct-agent; target re-run to measure runner | spec/harness reset-polarity inconsistency → async-reset resolution |
| PyHDL-Eval (168 Verilog track) | **E** (BLOCKED) | n/a | n/a | Documented blocked — 168 RefModule golden removed from public repo | Self-built-oracle subset is possible but not official pass@1 |
| RTL-Repo (~4000) | **E** (OUT OF SCOPE) | n/a | n/a | Documented out-of-scope — Edit-Similarity / Exact-Match string metric, not functional generation | |
| CVDP full (1500+) | **D** if access granted | runner | cocotb | Blocked by NVIDIA/Turing | |
| benchmark_clean (4 ICs) | **A** | `vibe_ic_one_shot_runner.py` | per-IC cross-check + 6-pillar verify | Done — all 4 PASS_WITH_WAIVERS / analog PASS | sha256 close-loop fixed `phase3` set_wire_rc + setup-repair (v0.1.26) |
| MetRex (25,868) | Not pursued | n/a | n/a | Metric *reasoning* (predict area/delay/power), not generation | |
| ResBench | Not pursued | n/a | n/a | FPGA resource metrics; different toolchain | |
| ChipAgentsBench | Not yet public | n/a | n/a | Plan to re-evaluate when subset releases | |

## § 6 — The benchmark RESULT.md must include

For honesty + reproducibility, every benchmark RESULT.md MUST contain:

1. **Headline** — score, denominator, what was measured (`pass@1` / etc.), what was substituted.
2. **Shape** — A/B/C/D/E (per § 2). State explicitly which entry point drove the run.
3. **Score trajectory** — single-shot, close-loop stages, what each stage changed.
4. **Residual triage** — every fail mapped to ONE of categories A-H (§ 4) with concrete evidence
   (TB line, descriptor quote, iverilog error). Anything in A-E is FLOOR and gets one sentence
   per case explaining why it's unrecoverable blind. Anything in F-H without a close-loop attempt
   is **not allowed** — close-loop or document why close-loop was skipped.
5. **Tool substitution** — list every substitution per § 3 + the disclosure caveat.
6. **Reproduce** — exact command line for scorer + dataset path.
7. **Sequence/plan status** — if this benchmark was chosen out of a roadmap (e.g. open-benchmark.md),
   say which others were intentionally skipped and why (Shape E).

## § 7 — When in doubt

If a future benchmark doesn't cleanly fit A/B/C/D/E:
1. **Prefer A or B** if there's any chance the runner can drive it — the runner is what we measure.
2. **Use C only** if running the full runner per problem is genuinely overhead-dominated (atomic
   micro-problems, ≥100 of them) AND a gates.py can still drive plugin PROGRAMS for every
   verification step. Document the shape choice in the RESULT.
3. **Never go agent-first** without writing a one-paragraph justification in the RESULT explaining
   why no plugin program could drive it. (The 2026-05-28 RTLLM run skipped this justification and
   the methodology was caught later — don't repeat it.)
4. **Never publish a number from Shape E**. Blocked is blocked; out-of-scope is out-of-scope.

## § 8 — Re-run obligations

When re-running a previously-measured benchmark on a new plugin version, the **same shape** must
be used (so the deltas are comparable). If shape changes (e.g. RTLLM C → B re-run target), the
new run is a **separate datapoint**, not a "v0.X.Y improvement" claim. Label clearly in RESULT.

If a backlog fix (e.g. `ORGANIC-20260528-spec-to-rtl-missing-chip-top-wrapper`) lands and could
move the number, mention it explicitly + cite the backlog id in the trajectory section.


## Compliance gate (vibe-ic-d - mandatory when deterministic edition is installed)

If you have the `vibe-ic-d` plugin installed alongside `vibe-ic-core`,
after producing your output, save it to a file and run:

```bash
python3 plugins/vibe-ic-d/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic-d/skills/SKILL_NAME/compliance.yaml \
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed.
`compliance.yaml` in this skill directory enumerates every required
element of your output: section headers, handoff lines, summary blocks.

**Your task is not complete until the audit returns PASS.** Missing
elements are the single largest source of skill-execution non-determinism
across different agents.
