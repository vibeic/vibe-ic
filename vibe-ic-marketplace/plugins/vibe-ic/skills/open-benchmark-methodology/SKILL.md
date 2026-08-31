---
name: open-benchmark-methodology
description: "Mandatory for VerilogEval, VerilogEval-v2, VerilogEval-Human, CVDP, RTLLM, PyHDL-Eval, RTL-Repo, MetRex, ResBench, ChipAgentsBench, benchmark, pass@1, benchmark floor/defect, run/rerun/score benchmark, or interpreting benchmark results. Enforces one general product entry, clean-room blind evaluation, Program First plus independent AI review/backup, official host scoring, evidence-backed triage, and capture of general enhancements."
---

# Open-Benchmark Methodology

The benchmark measures the Vibe-IC product path, not a benchmark-tuned agent.
Every runnable RTL evaluation uses the same solve core as an ordinary IC-design
request. Dataset differences are allowed only at the input/output boundary.

## Rule 0 — one product entry

For the open RTL suites in `benchmark/BENCHMARK_REGISTRY.json`, the only
authoring path is:

```text
benchmark_dispatch.py <bench> --solve
  -> benchmark_io_adapter.stage           (input translation only)
  -> task_nature_route                     (prompt/context evidence only)
  -> vibe_ic_one_shot_runner --entry-step  (normal product runner)
  -> Program candidate or declared AI backup
  -> independent hash-bound AI review
  -> benchmark_dispatch.py <bench> --resume
  -> accepted candidate
  -> benchmark_dispatch.py <bench> --score
  -> official host scorer
```

For whole-IC `benchmark_clean`, use the ordinary `/vibe-ic-all` entry,
`vibe_ic_one_shot_runner.py`, and the `benchmark-verify` skill. A benchmark IC
must not select another solver because of its IC name.

Forbidden alternatives include:

- benchmark-name or problem-id routers, task loops, tier pipelines, solve
  pipelines, Phase-1 wrappers, prompt exporters, or free-hand authoring loops;
- choosing a route from a CVDP `cid`, benchmark label, problem name, expected
  answer, prior score, or hidden harness;
- writing scoreable RTL directly and then calling a gate/scorer;
- publishing a partial previous-failure run as a benchmark result.

`benchmark/benchmark_entry_surface_check.py` enforces the shipped entry surface
and is called by `--solve`. If it fails, stop and repair the product entry before
running a benchmark.

## General core and thin adapters

Benchmark-specific code may only translate formats or invoke the official
scorer. A thin adapter may:

- stage the current record's visible prompt and supplied context into a normal
  project;
- collect an already-produced candidate;
- package exact accepted bytes into the scorer's required envelope;
- run image/tool preflight and translate official verdict files.

It may not classify the task, author or repair RTL, choose a product step,
infer hidden interface facts, assign PASS/FAIL, or use reference values. Logic
that works from ordinary prose/RTL belongs in a neutrally named general program
and must be reachable from a non-benchmark Phase-1/project flow.

For CVDP, `output.context` values are hidden golden data. At the post-acceptance
host packaging boundary only, the adapter may read its path keys to construct
the official multi-file response envelope. It must never expose values to the
solver or reviewer and must refuse ambiguous file/module mappings.

## Program First, AI Backup, AI authority

This is a sequence, not two independent racing solvers:

1. Program runs first through the normal runner.
2. If Program emits a candidate, an independent AI reviews the exact frozen RTL
   hash against the visible prompt/context.
3. If Program declares a supported WAIVE or route-level AI backup, AI may author
   the missing candidate into the runner-owned RTL directory; `--resume`
   re-enters the same product gates.
4. If AI agrees with Program, record acceptance for that exact hash.
5. If AI disagrees, it must identify the prompt requirement and provide a
   prompt-derived executable test that fails on the frozen Program candidate.
   Prose disagreement alone cannot replace the candidate.
6. A repair must pass that immutable challenge, the same runner gates, and a
   fresh independent AI review. AI is the final semantic authority only after
   this evidence chain is complete.

Every candidate therefore has two required checks: deterministic product gates
and semantic AI review. `program_first_ai_acceptance.json` must be `COMPLETE`
before scoring.

## Blind clean-room evaluation

A canonical run is a fresh full-dataset run. Do not read or inherit:

- prior samples, run artifacts, result files, or agent memory;
- sibling problems' solutions, testbenches, build scripts, or conventions;
- hidden harnesses, reference/golden outputs, or the host scorer during solve,
  review, repair, or optimization;
- prior failing IDs as a way to narrow the evaluation.

`--solve` owns run-directory creation, writes clean-room metadata, pre-creates
the transcript directory, and processes every current dataset case. Separate
scaffolding, benchmark-local authoring, and partial prior-failure evaluation are
not entry points. `--limit` is diagnostic only and its run is ineligible for
canonical scoring.

Export author/reviewer transcripts to `<run>/transcripts/`. The score front
door runs `benchmark_clean_room_check.py` and `blindness_audit.py`. Missing
transcripts require an explicit disclosure; a detected oracle access blocks
the score.

Blind evaluation is the exam. Do not loop against official verdicts. Post-score
analysis may diagnose and capture a general enhancement, but the resulting
plugin change is measured only in a new clean-room run.

## Canonical commands

```bash
python3 programs/benchmark_dispatch.py <bench> \
  --solve --dataset <DATASET> --run <FRESH_RUN>

# Complete only runner-declared AI backup/review/repair worklists, then:
python3 programs/benchmark_dispatch.py <bench> \
  --resume --dataset <DATASET> --run <FRESH_RUN>

# Repeat --resume until program_first_ai_acceptance.json is COMPLETE.
python3 programs/benchmark_dispatch.py <bench> \
  --score --dataset <DATASET> --run <FRESH_RUN>
```

CVDP scoring additionally requires `--scorer-root <official-cvdp-root>` (or
`CVDP_BENCHMARK_ROOT`) and the exact official simulation images. Run the shipped
EDA image preflight before scoring. Do not substitute tools silently.

## Four-stage attribution

Record every problem, including failures, in a per-problem table:

1. Routing — AI semantic decision plus the prompt/context evidence, selected
   nature, general entry step, evidence class, and exit step.
2. Solving — Program, declared AI backup, or evidence-backed AI repair; name the
   emitted candidate hash and reason for any handoff.
3. Verifying — deterministic runner gates and independent AI review; neither
   substitutes for the other.
4. Looping — no loop, AI backup, AI challenge/repair/re-review, optimization/PPA,
   or unresolved tool/dataset defect. State who acted and what evidence closed
   the loop.

The aggregate counts must reconcile exactly to the dataset denominator.

## Official scoring and tool disclosure

Scoring is a host-only post-generation step. Use the benchmark's official
testbench, image, command, cwd, module naming, and response format. Report:

- dataset identity/hash and exact denominator;
- plugin version/commit, MCP/EDA image digest and tool versions;
- official scorer command and substitutions (or `none`);
- raw PASS/FAIL/NOT_MEASURED counts and official logs;
- Program/AI routing, solving, verifying, and looping totals.

Never rewrite the official score to compensate for suspected bad goldens. Keep
the official number and separately disclose evidence-backed dataset defects.

## Failure triage

For every non-PASS, separate:

- product defect: Program/AI/gate/adapter behavior is wrong;
- tool gap: required official capability is absent or incompatible;
- incomplete/ambiguous public specification;
- suspected defective dataset/golden;
- host failure or NOT_MEASURED.

A dataset-defect or floor claim needs a prompt quote, official failure evidence,
and a control showing the prompt-correct interpretation cannot satisfy the
official oracle. A known-systematic tool blocker must cite its tracking issue
number. Never infer a floor merely because one attempt failed.

## Capture enhancement

Post-score recovery is not part of the blind score. When AI finds a correct
repair that Program missed:

1. isolate the general discriminator from prompt and RTL evidence;
2. add a benchmark-agnostic program rule/check/fix at the normal product
   enforcement point;
3. prove the new test fails on the unfixed product and passes after the fix;
4. run no-leak and false-positive controls on non-benchmark/general inputs;
5. issue a version-less PR and wait for it to land;
6. upgrade the installed plugin/MCP and run a new full clean-room benchmark.

Do not encode problem IDs, dataset labels, hidden expected values, or a lookup
table. Capture is successful only when the next ordinary Program First run
produces the right behavior without benchmark-specific knowledge.

## RESULT requirements

Every result must include:

- Summary/status and exact official score;
- clean-room/blindness statement;
- environment and official scorer evidence;
- full per-problem four-stage CSV/JSON path and reconciled aggregates;
- all failures with evidence-backed triage;
- captured enhancements/PRs and what they do not claim;
- reproducible next action.

Save the final result and run the skill compliance check:

```bash
python3 plugins/vibe-ic/_shared/skill_compliance_check.py \
  --requirements plugins/vibe-ic/skills/open-benchmark-methodology/compliance.yaml \
  <RESULT.md>
```

## Handoff

End with `## Summary` or `## Verdict`, followed by a clear `Next:` statement.
