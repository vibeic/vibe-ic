---
name: regression-manage
description: Manage CI/nightly regression — job orchestration, flaky test triage, result summarization, severity classification, and owner assignment. Use when the user says "regression", "nightly run", "CI", "flaky test", "regression triage", "test farm", "LSF", "Jenkins pipeline".
---

# Regression Manage

> **Doctrine (v0.1.50):** 把修法寫進工具，而非寫進 prompt.
> Programs first; AI is the backstop for owner-assignment narrative.

Once verification, synthesis, P&R, and signoff are scripted, the next
bottleneck is keeping the regression green. This skill triages nightly
/ CI results and routes failures to the right skill / owner.

## Mandatory Deterministic Preflight

```bash
# Validate every incoming regression-failure issue has fixture data:
python3 plugins/vibe-ic/programs/regression_issue_intake_check.py \
    --issue <issue.json> --strict
```

The intake gate rejects issues without a verbatim repro snippet,
expected output, or drop-in fixture — exactly the pattern that
preceded the historical #5 thrashing loop. **Do not start triage on
an issue that fails intake.** Refuse to "diagnose by reading the log"
without the program's PASS.

## When to use

- After each nightly regression completes
- When a critical failure appears mid-day
- When flaky tests are slowing down the team
- Weekly regression health review

## Inputs

1. Regression run log / database (Jenkins, LSF, Slurm, GitHub Actions)
2. Known-failure list with owners
3. Severity policy (tape-out blocker vs warning vs info)
4. Branch / tag under test

## Workflow

The five mechanical steps are deterministic and are now **programs**,
not prose. Run them in order; each emits a JSON report (`--json <out>`):

1. **Aggregate results** (pass/fail/error/timeout per job, pass %, trend,
   P0 count) — enforced by `programs/regression_report_aggregate.py`.
2. **Deduplicate** (normalize-and-hash the failure signature so identical
   failures collapse to one issue) — enforced by
   `programs/regression_failure_dedup.py`.
3. **Classify severity** (P0 was-green-now-red on protected/release;
   P1 new failure on feature branch; P2 flaky passes-on-retry;
   P3 environmental license/disk/network) — enforced by
   `programs/regression_severity_classify.py`.
4. **Auto-triage** (failing-step → target skill: timing→`/sta-review`,
   DRC→`/drc-fix`, functional→`/rtl-repair`, formal→`/formal-verify`, …)
   — enforced by `programs/regression_failure_route.py`.
5. **Flaky-test quarantine** (pass-on-retry AND fail → quarantine + open
   ticket so flakes don't hide real regressions) — enforced by
   `programs/regression_flaky_quarantine.py`.

```bash
python3 programs/regression_report_aggregate.py   --jobs-json jobs.json --json agg.json
python3 programs/regression_failure_dedup.py      --failures-json fails.json --json dedup.json
python3 programs/regression_severity_classify.py  --failures-json fails.json --json sev.json
python3 programs/regression_failure_route.py      --failures-json fails.json --json route.json
python3 programs/regression_flaky_quarantine.py   --tests-json retries.json --json flaky.json
```

6. **Owner-assignment narrative (LLM)**: deciding *which* human / team
   should own a novel failure and writing the human-readable daily
   Slack / email summary requires judgment about org structure, recent
   code authorship, and tone that no fixed table captures. This is the
   single genuine LLM residual — the programs hand you the structured
   facts (severity, route, dedup group, flaky list); you compose the
   actionable owner + narrative on top.

## Output format

- `regression/<date>_report.md`:
  - Summary dashboard (pass %, trend, P0 count) — emit with
    `regression_report_aggregate.py --md <out.md>` (deterministic
    arithmetic; do not hand-narrate the numbers).
  - New failures with suggested owner + skill — the *skill* column comes
    from `regression_failure_route.py`; the *owner* + narrative is the
    LLM residual (Workflow step 6).
  - Flaky list with retry count — from `regression_flaky_quarantine.py`.
  - Known issues still open.
- Structured handoff tickets for each failure (severity from
  `regression_severity_classify.py`, route from
  `regression_failure_route.py`, dedup group from
  `regression_failure_dedup.py`).

## Technical basis

Test-farm orchestration patterns from large-scale SoC projects. Flaky-test management best practices from Google / Meta engineering blogs. LSF / Slurm / Jenkins are the standard back-ends.

## Handoff

- P0 failures → direct routing to failing-step skill
- Repeated flaky → `/testbench-gen` or `/coverage-closure` (for stimulus stability)
- Trending risk → `/tapeout-checklist` as a red flag

## Compliance gate (mandatory)

After producing your output, save it to a file and run:

```bash
python3 plugins/vibe-ic/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic/skills/regression-manage/compliance.yaml \
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed.
`compliance.yaml` in the corresponding skill directory enumerates
every required element of your output: section headers, metadata fields,
handoff lines, tool invocations.

**Your task is not complete until the audit returns PASS.** Missing
elements are the single largest source of skill-execution non-determinism
across different agents.
