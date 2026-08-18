# tools/core_agent/

Deterministic infrastructure called by the **core agent** at every cron
wake-up. The core agent is the "fix-and-push" half of the closed loop
(see [`vibeic.ai/platform.html`](https://vibeic.ai/platform.html));
field agents file issues, the core agent fixes them, the field agent
verifies on real benchmarks.

## Why deterministic?

Prior cron prompts asked the LLM to **classify** open issues into
NEW / FEEDBACK / WAITING based on comment authors and timestamps. The
classifier kept drifting: the same issue with the same labels would
sometimes be picked up, sometimes skipped, depending on phrasing of
the latest comment. That made the loop unreliable.

This program collapses the classification into one rule:

> **An open non-PR issue is *actionable* iff it has NO
> `wait-for-verification` label.**

`NEW`, `FEEDBACK`, `WAITING` all fold into this predicate:
- New issues start without the label → actionable.
- Issues the core agent just fixed get the label → not actionable.
- When the field agent posts counter-evidence, they remove the label
  → actionable again.

The core agent never decides whether to skip — the label state is the
sole source of truth, and the core agent's only job per tick is to
clear the actionable list.

## poll_open_issues.py

```bash
# default: print actionable issue numbers, one per line.
python3 tools/core_agent/poll_open_issues.py

# JSON for programmatic consumption.
python3 tools/core_agent/poll_open_issues.py --json

# different repo.
python3 tools/core_agent/poll_open_issues.py --repo owner/name
```

### Exit codes

| Code | Meaning | Core-agent action |
|------|---------|-------------------|
| `0`  | No actionable issues. | Exit this tick cleanly. |
| `1`  | ≥1 actionable issue.  | Fix each, push, apply `wait-for-verification`. |
| `2`  | I/O or auth error.    | Retry next tick — do NOT treat as actionable. |

### Auth

PAT is read from (in order):
1. `$GITHUB_TOKEN`
2. `$GH_TOKEN`
3. `~/.config/github/token` (mode 0600 preferred)

## Cron prompt template

```
1. Run:
     python3 tools/core_agent/poll_open_issues.py --json
2. If rc == 0  → done. Output "(no actionable issues)".
3. If rc == 1  → for each entry in `actionable`:
                 a. fetch issue body + comments
                 b. write chip-AGNOSTIC fix
                 c. run relevant gates + tests
                 d. commit `vX.Y.Z — for #N <summary>` + push origin main
                 e. post 繁體中文 fix comment
                 f. POST label `wait-for-verification`
                 NEVER close the issue.
4. If rc == 2  → log + exit. Retry next tick.

Hard prohibitions:
  --force / reset --hard / --no-verify / closing issues /
  chip-specific string literals as detection logic.
```

The cron operator wires this template into the recurring trigger; the
core agent itself only ever executes Step 3 per actionable entry.
