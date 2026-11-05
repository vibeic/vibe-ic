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

## Technical basis

Test-farm orchestration patterns from large-scale SoC projects. Flaky-test management best practices from Google / Meta engineering blogs. LSF / Slurm / Jenkins are the standard back-ends.

## Handoff

- P0 failures → direct routing to failing-step skill
- Repeated flaky → `/testbench-gen` or `/coverage-closure` (for stimulus stability)
- Trending risk → `/tapeout-checklist` as a red flag
