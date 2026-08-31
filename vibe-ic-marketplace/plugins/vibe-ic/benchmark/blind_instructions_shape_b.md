# Blind AI worklists — Shape B through the general flow

Shape B changes the scorer-facing layout; it does not have a separate authoring
path. Start every full run with:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/programs/benchmark_dispatch.py <bench> \
  --solve --dataset <dataset> --run <fresh-run-dir>
```

The dispatcher stages only the current problem's declared input, asks
`task_nature_route` for the normal flow entry, and invokes
`vibe_ic_one_shot_runner`. Do not manually build projects, invoke a per-design
runner, copy RTL into samples, or use a benchmark-specific solver.

## AI backup and review

### Captured lessons are consumed through the general flow

`--solve` renders the chip-agnostic `### Skill:` sections into
`<run>/lessons.md`.  The #733 pre-authoring rule is mandatory for every
design: open that digest, KEYWORD-MATCH the prompt's design genre, and apply
only a matching general lesson whose stated preconditions hold.  The current
genre list includes `barrel shifter`, `frequency divider / odd / dual-edge`,
`async FIFO`, `serial<->parallel`, `edge/pulse detect`, `FSM Moore`, `gshare`,
`serial twos complement`, `K-map -> mux`, `IEEE-754 float multiply`, and
`saturating counter /
no upper limit / cannot overflow`.  A lesson never overrides an explicit
prompt requirement and never supplies benchmark- or problem-specific oracle
knowledge.

- **CROSS-PROBLEM PROHIBITION:** never read OTHER designs' prompts,
  reference RTL, tests, dataset BUILD files, transcripts, or results. Each worklist
  actor receives only its current design's visible inputs.
- If `<run>/lessons.md` exists, it is MUST-READ before authoring; apply only
  general lessons whose stated preconditions match the current prompt.
- **Transcript export is the DEFAULT:** save every author/reviewer/repair
  transcript under `<run>/transcripts/`. If none is available, RESULT must say
  `blindness audit unavailable`.
- The score front door invokes `programs/blindness_audit.py`; do not self-score
  or attempt to bypass that audit.
- Work only from the paths in `needs_ai_backup.jsonl`,
  `needs_ai_review.jsonl`, and `needs_ai_repair.jsonl`.
- Read the current design's prompt and staged input RTL only. Never read its or
  another problem's testbench, verified RTL, build scripts, prior runs, or
  scores.
- Author backup RTL only into the runner-owned `write_rtl_to` path.
- Review the immutable candidate named by `rtl_paths` and `rtl_sha256`.
- A semantic FAIL requires prompt evidence plus the task's self-contained
  executable challenge. The frozen candidate must fail it before repair.
- A repair must pass the same challenge, re-enter Program gates, and receive a
  fresh hash-bound AI review.

Resume until acceptance is complete:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/programs/benchmark_dispatch.py <bench> \
  --resume --dataset <dataset> --run <run-dir>
```

Only the host may then invoke `--score`. The score front door exports the
exact accepted bytes through the Shape-B response adapter and runs the official
testbench from its design directory so relative file reads resolve.
