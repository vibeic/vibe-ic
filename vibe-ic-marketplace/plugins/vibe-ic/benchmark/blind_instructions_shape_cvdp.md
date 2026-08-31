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
