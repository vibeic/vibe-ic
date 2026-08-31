# Blind AI worklists — Shape C through the general flow

Atomic benchmark problems use the same authoring path as a general IC-design
task. Shape C controls only the final sample filename and host scorer.

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/programs/benchmark_dispatch.py <bench> \
  --solve --dataset <dataset> --run <fresh-run-dir>
```

Per problem, the dispatcher performs the only permitted sequence:
`benchmark_io_adapter.stage → task_nature_route → vibe_ic_one_shot_runner`.
There is no direct free-hand sample path and no per-benchmark authoring gate.

## Blind worklist rules

### Captured lessons are consumed through the general flow

`--solve` renders the chip-agnostic `### Skill:` sections into
`<run>/lessons.md`.  The #733 pre-authoring rule is mandatory for every
problem: open that digest, KEYWORD-MATCH the prompt's design genre, and apply
only a matching general lesson whose stated preconditions hold.  The current
genre list includes `barrel shifter`, `frequency divider / odd / dual-edge`,
`async FIFO`, `serial<->parallel`, `edge/pulse detect`, `FSM Moore`, `gshare`,
`serial twos complement`, `K-map -> mux`, `IEEE-754 float multiply`, and
`saturating counter /
no upper limit / cannot overflow`.  A lesson never overrides an explicit
prompt requirement and never supplies benchmark- or problem-specific oracle
knowledge.

- **CROSS-PROBLEM PROHIBITION:** never read OTHER problems' prompts,
  reference RTL, grading tests, dataset BUILD files, transcripts, or results. This also
  binds every review and close-loop repair actor.
- If `<run>/lessons.md` exists, you MUST read it BEFORE authoring; apply only
  general lessons whose stated preconditions match the current prompt.
- **Transcript export is the DEFAULT:** save every author/reviewer/repair
  transcript under `<run>/transcripts/`. If none is available, RESULT must say
  `blindness audit unavailable`.
- The score front door invokes `programs/blindness_audit.py`; do not self-score
  or attempt to bypass that audit.
- Read only the prompt/current input paths explicitly named by the task.
- Never read golden/reference RTL, grading testbenches, sibling problem files,
  prior run artefacts, or score output.
- Never invoke a host scorer during authoring, review, or repair.
- Backup RTL goes only to the runner-owned path named by the worklist.
- Review every immutable candidate hash independently.
- AI may override Program semantics only with prompt-grounded reasoning. A FAIL
  also needs a self-contained executable challenge that the frozen candidate
  demonstrably fails.
- Repair must pass the immutable challenge, Program re-entry gates, and a new
  hash-bound AI review.

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/programs/benchmark_dispatch.py <bench> \
  --resume --dataset <dataset> --run <run-dir>
```

After `program_first_ai_review_acceptance.json` is COMPLETE, the host runs
`--score`. The dispatcher publishes exact reviewed bytes through the
scorer-facing Shape-C packaging guard; agents never write `samples/` directly.
