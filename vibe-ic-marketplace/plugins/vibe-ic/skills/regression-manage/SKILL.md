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

1. **Aggregate results**: pass / fail / error / timeout per job
2. **Deduplicate** — group identical failures into one issue
3. **Classify severity**:
   - P0: tape-out blocker (regression was green, now red)
   - P1: new failure on feature branch
   - P2: flaky (passes on retry)
   - P3: environmental (tool license, disk, network)
4. **Auto-triage**:
   - Timing fail → `/sta-review`
   - DRC fail → `/drc-fix`
   - Functional fail → `/rtl-repair` or `/testbench-gen`
   - Formal fail → `/formal-verify`
5. **Flaky test quarantine**: move to a separate suite with a ticket, don't let them hide real regressions
6. **Generate report**: daily Slack / email summary with actionable items

## Output format

- `regression/<date>_report.md`:
  - Summary dashboard (pass %, trend, P0 count)
  - New failures with suggested owner + skill
  - Flaky list with retry count
  - Known issues still open
- Structured handoff tickets for each failure

## Technical basis

Test-farm orchestration patterns from large-scale SoC projects. Flaky-test management best practices from Google / Meta engineering blogs. LSF / Slurm / Jenkins are the standard back-ends.

## Handoff

- P0 failures → direct routing to failing-step skill
- Repeated flaky → `/testbench-gen` or `/coverage-closure` (for stimulus stability)
- Trending risk → `/tapeout-checklist` as a red flag

## Compliance gate (vibe-ic-d - mandatory when deterministic edition is installed)

If you have the `vibe-ic-d` plugin installed alongside `vibe-ic`,
after producing your output, save it to a file and run:

```bash
python3 plugins/vibe-ic-d/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic-d/skills/regression-manage/compliance.yaml \
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed.
`compliance.yaml` in the corresponding vibe-ic-d skill directory enumerates
every required element of your output: section headers, metadata fields,
handoff lines, tool invocations.

**Your task is not complete until the audit returns PASS.** Missing
elements are the single largest source of skill-execution non-determinism
across different agents.
