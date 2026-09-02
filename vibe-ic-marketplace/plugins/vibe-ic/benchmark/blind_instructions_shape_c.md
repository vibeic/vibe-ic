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
no upper limit / cannot overflow`.

**Section 4-E NO-LEAK (#733), and it is the half that keeps this blind.**
Apply a matched convention ONLY *unless the spec states otherwise* — an
explicit prompt requirement always wins, and a lesson never overrides one. When
the spec is AMBIGUOUS rather than silent, the case stays **spec-faithful**: you
author what the prompt supports and supply no oracle answer. A digest lesson is
a general convention, never benchmark- or problem-specific knowledge, and
reaching for it to settle an ambiguity is the leak this rule exists to stop.

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

## ORCHESTRATION RULES (for the caller spawning the worklist agents — ORGANIC-20260605)

These are REQUIRED, learned from a 312-problem clean-room run where
per-problem fan-out lost ~93% of its agents' results while batch fan-out
completed 312/312. They bind every shape whose worklists fan out over more
than one agent — Shape C here and Shape B (`blind_instructions_shape_b.md`);
Shape D is a single project with no fan-out and is exempt.

1. **Batch granularity is REQUIRED for ≥100-problem datasets.** Spawn ONE
   agent per contiguous SLICE of a worklist (`needs_ai_backup.jsonl`,
   `needs_ai_review.jsonl`, `needs_ai_repair.jsonl`) — NEVER one agent per
   problem. Hundreds of short-lived per-problem subagents lose their final
   structured return far too often; batch agents do sustained multi-problem
   work and return reliably.
2. **The run directory is the authoritative truth — Disk truth.** The runner
   writes backup RTL to its own `write_rtl_to` path and the dispatcher keeps
   `program_first_ai_acceptance.json` regardless of whether an agent's
   structured return survives. Orchestrators MUST reconcile progress from
   those files — never by tallying agent returns.
3. **Resume = `--resume`.** The dispatcher re-derives the un-finished set from
   the run directory; re-dispatch only that (in slices), never re-author what
   is already on disk.
4. **Transcript export is the DEFAULT, not an optional extra
   (ORGANIC-20260605-transcripts-export-default).** `--solve` pre-creates
   `<run>/transcripts/`; the caller MUST export EVERY author, reviewer and
   repair agent's transcript there, named per agent, BEFORE scoring. The score
   front door's `blindness_audit.py` reads them and refuses on violations; a
   run scored without them must disclose `blindness audit unavailable`.
5. **Rate-limit resilience ladder
   (ORGANIC-20260605-ratelimit-resilient-dispatch-ladder).** Provider-side
   burst rate-limiting kills a full-width fan-out within seconds — the kill
   signature is sub-minute workflow death with ZERO/near-zero token usage and
   most agents nulled at once. Naive retries at the same width die
   identically, while a single sustained agent survives. On a burst kill:
   (a) drop to a **1-agent CANARY** that must complete a FULL slice before
   any scaling; (b) resume at **narrow width (2–4 concurrent)** with
   completion-driven dispatch (launch the next agent when one finishes),
   never barrier fan-out; (c) disk-truth reconcile (rule 2) remains the
   resume mechanism. Recognise the signature instead of burning full-width
   retries.

```bash
python3 ${CLAUDE_PLUGIN_ROOT}/programs/benchmark_dispatch.py <bench> \
  --resume --dataset <dataset> --run <run-dir>
```

After `program_first_ai_review_acceptance.json` is COMPLETE, the host runs
`--score`. The dispatcher publishes exact reviewed bytes through the
scorer-facing Shape-C packaging guard; agents never write `samples/` directly.
