# Blind AI worklist instructions — CVDP through the general flow

CVDP has no benchmark-specific authoring or routing path. Every record enters
through:

```text
benchmark_io_adapter.stage
  → task_nature_route
  → vibe_ic_one_shot_runner --entry-step <decision>
  → Program gates
  → blind AI backup/review/repair worklists
  → official scorer
```

The only benchmark-aware code before and after that chain is the thin I/O
adapter. It may translate CVDP's JSONL fields and scorer response envelope; it
must not choose a route, author RTL, optimize a candidate, or assign a verdict.

## Start and resume

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/programs/benchmark_dispatch.py cvdp-open \
  --solve --dataset <dataset.jsonl> --run <fresh-run-dir>

python3 ${CLAUDE_PLUGIN_ROOT}/programs/benchmark_dispatch.py cvdp-open \
  --resume --dataset <dataset.jsonl> --run <fresh-run-dir>
```

`--solve` writes three runner-owned queues:

- `needs_ai_backup.jsonl`: Program could not emit RTL and the general route
  declared an AI skill. Author only into each task's `write_rtl_to` directory.
- `needs_ai_review.jsonl`: review the immutable candidate named by
  `candidate_snapshot` and `rtl_sha256`.
- `needs_ai_repair.jsonl`: repair is authorized only after the reviewed
  candidate fails the immutable prompt-derived executable challenge.

Repeat `--resume` until
`program_first_ai_review_acceptance.json.status == "COMPLETE"`. Do not write a
scorer response or a `samples/` file yourself.

## What AI may read

- **CROSS-PROBLEM PROHIBITION:** never read OTHER problems' prompts, context,
  hidden files, transcripts, or results.
- If `<run>/lessons.md` exists, you MUST read it BEFORE authoring and apply only
  lessons whose general preconditions match this task.
- **Transcript export is the DEFAULT:** save every author/reviewer/repair
  transcript under `<run>/transcripts/`. If none is available, RESULT must say
  `blindness audit unavailable`.

For one task, read only the paths explicitly named by that task:

- `prompt_path` / `read_prompt_from`;
- the task's input context already staged under the project;
- `rtl_paths` for the immutable candidate under review;
- runner-produced design documents named by `read_docs_from`.

Input context is the design being completed, modified, optimized, or debugged;
it is not an oracle. Preserve its module names, ports, widths, parameters, and
unmodified behavior unless the prompt explicitly changes them.

## What AI must not read or do

- Do not read dataset `output.*`, `harness`, golden/reference RTL, hidden
  tests, sibling problems, prior runs, prior responses, or prior scores.
- Do not run `run_benchmark.py`, `score_one.py`, or any verdict-level oracle
  while authoring/reviewing/repairing.
- Do not infer the route from `cidNNN`, benchmark identity, problem id, or a
  benchmark-specific table.
- Do not invoke a benchmark-specific router, task loop, Phase-1 entry wrapper,
  prompt exporter, or free-hand draft gate. Those alternate paths are removed.
- Do not edit immutable candidate snapshots, review hashes, or acceptance
  records.

## Program First, AI semantic authority

Review every Program candidate independently. A semantic PASS must explain why
the exact hash satisfies the prompt. A semantic FAIL must:

1. cite prompt evidence;
2. describe the Program limitation;
3. provide the self-contained executable challenge required by the task;
4. demonstrate that the frozen candidate fails that challenge.

Only then may AI repair the RTL. The repair must pass the same immutable
challenge, re-enter the general runner at the task's declared step, pass Program
gates, and receive a fresh hash-bound AI review.

## Model selection for blind authoring (cost policy)

**DEFAULT to a cheaper model with LOW reasoning effort for the blind authoring
pass; reserve Opus for hard triage only.**

Rationale (run_v1239_converge cost lesson): the blind authoring pass is a large
fan-out over many small, well-scoped, single-module problems whose spec is fully
given in the prompt (+ `input.context`). The bulk of these are routine RTL that
the deterministic emit gate verifies anyway, so the marginal pass@1 from
spending a frontier model on every problem is small while the token cost is
large. Spending the top-tier model on the whole fan-out is the dominant,
avoidable cost.

This is a COST policy, not a quality claim. It changes what you spend, never
what counts as a pass: every candidate is gated by the same Program gates and
the same hash-bound review whichever model authored it.

Policy:

* **Blind authoring fan-out -> a CHEAPER model + LOW reasoning effort.** Prefer
  **Haiku** (`claude-haiku-4-5`, $1 / $5 per MTok) for the routine bulk with
  `output_config: {effort: "low"}`; step up to **Sonnet** (`claude-sonnet-5`,
  $2 / $10) for a problem the cheaper model visibly struggles with (its own
  mini-TB fails, or the spec is dense).
* **Reserve Opus** (`claude-opus-5`, $5 / $25) for the **hard triage /
  close-loop** step ONLY -- the residual fails that need careful spec
  re-reading, FLOOR proofs, or independent blind re-solves -- not for the
  first-pass author of every problem.
* Model IDs are the current ones and carry no date suffix. Re-check them
  against the live model list rather than copying a suffix out of an older
  run's notes.

HISTORY: this section was authored, then dropped by the
`blind_instructions_shape_cvdp.md` rewrite in `e9ec0ce1c1` ("benchmark: remove
dataset-specific solve shortcuts"), which was about the SOLVE shortcuts and not
about this policy. `31385d6ffb` carried other dropped contracts onto the new
entry surface and did not carry this one, so for several versions the only
place the policy still existed was a red test. Restored here, on the surface
`benchmark_dispatch.py` actually names to the blind worklist author, with the
model IDs brought current.

## Official scoring

Only after acceptance is COMPLETE:

```bash
OSS_SIM_IMAGE=<official-compatible-image> \
OSS_PNR_IMAGE=<official-compatible-image> \
python3 ${CLAUDE_PLUGIN_ROOT}/programs/benchmark_dispatch.py cvdp-open \
  --score --dataset <dataset.jsonl> --run <run-dir> \
  --scorer-root <cvdp-benchmark-root>
```

The host scorer may read the oracle after generation. AI worklist actors may
not. The score command exports the exact accepted candidate bytes into CVDP's
response envelope, runs the official `run_benchmark.py`, and writes the
per-problem verdicts and triage artefacts under the run directory.
