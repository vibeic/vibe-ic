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
no upper limit / cannot overflow`.

**Section 4-E NO-LEAK (#733), and it is the half that keeps this blind.**
Apply a matched convention ONLY *unless the spec states otherwise* — an
explicit prompt requirement always wins, and a lesson never overrides one. When
the spec is AMBIGUOUS rather than silent, the case stays **spec-faithful**: you
author what the prompt supports and supply no oracle answer. A digest lesson is
a general convention, never benchmark- or problem-specific knowledge, and
reaching for it to settle an ambiguity is the leak this rule exists to stop.

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
- When functional confirmation is required, cover every block-eligible item in
  the task's Program-generated `program_review_obligations` across the current
  and active inherited executable challenges; one passing vector is incomplete.
- A semantic FAIL requires prompt evidence plus the task's self-contained
  executable challenge. The frozen candidate must fail it before repair.
- A repair must pass the same challenge, re-enter Program gates, and receive a
  fresh hash-bound AI review.

## ORCHESTRATION RULES (for the caller spawning the worklist agents — ORGANIC-20260605)

Shape B fans its AI backup / review / repair work out over the worklists the
dispatcher writes (`needs_ai_backup.jsonl`, `needs_ai_review.jsonl`,
`needs_ai_repair.jsonl`), so the caller-side rules Shape C learned from a
312-problem clean-room run bind here too. The full doctrine and its rationale
live in `blind_instructions_shape_c.md` § ORCHESTRATION RULES; the rules are:

1. **Batch granularity** — one agent per contiguous SLICE of a worklist,
   never one agent per design. Hundreds of short-lived per-problem subagents
   lose their final structured return far too often; a batch agent does
   sustained multi-problem work and returns reliably.
2. **Disk truth** — reconcile progress from the run directory, never from
   agent returns: the runner-owned `write_rtl_to` paths, the worklists and
   `program_first_ai_acceptance.json` are the record, and `--resume` re-derives
   the remaining work from them. Resume = run `--resume` again; never re-author
   what is already on disk.
3. **Transcript export is the DEFAULT** (above) — every author / reviewer /
   repair transcript is under `<run>/transcripts/` BEFORE scoring; the score
   front door's `blindness_audit.py` reads them.
4. **Rate-limit resilience ladder
   (ORGANIC-20260605-ratelimit-resilient-dispatch-ladder).** Provider-side
   burst rate-limiting kills a full-width fan-out within seconds — kill
   signature: sub-minute workflow death, ZERO/near-zero token usage, most
   agents nulled at once; same-width retries die identically while a single
   sustained agent survives. On a burst kill: (a) drop to a **1-agent
   CANARY** that must complete a FULL slice before any scaling; (b) resume at
   **narrow width (2–4 concurrent)** with completion-driven dispatch (launch
   the next agent when one finishes), never barrier fan-out; (c) disk-truth
   reconcile (rule 2) remains the resume mechanism.

Shape D is a single project with no fan-out and is exempt.

Resume until acceptance is complete:

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/programs/benchmark_dispatch.py <bench> \
  --resume --dataset <dataset> --run <run-dir>
```

Only the host may then invoke `--score`. The score front door exports the
exact accepted bytes through the Shape-B response adapter and runs the official
testbench from its design directory so relative file reads resolve.
