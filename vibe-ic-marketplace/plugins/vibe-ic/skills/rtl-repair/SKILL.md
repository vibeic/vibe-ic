---
name: rtl-repair
description: Automatically fix lint violations, synthesis errors, and simulation mismatches in RTL code. Use when the user says "fix this Verilog", "repair the RTL", "resolve these lint errors", "my synthesis is failing", or shares an HDL file with error logs from a lint/synth/sim tool.
---

# RTL Repair

Close the Generate-Compile-Feedback-Repair loop for RTL. Takes a broken module plus a log (lint, synthesis, or simulation) and produces a corrected module, with a diff and a reasoning trace.

## When to use

Trigger when the user:
- Shares RTL plus error output from a lint tool (SpyGlass, Verilator, Icarus)
- Reports a synthesis error from Yosys, DC, or Genus
- Reports a simulation mismatch where golden and DUT differ
- Asks to "auto-fix" the issues surfaced by `/rtl-review`

## Inputs to gather

1. The RTL file(s)
2. The error log or failing-test output
3. Intent: "minimal fix" (patch only the error) vs "refactor for cleanliness"
4. Whether to preserve original comments and signal names

## Repair workflow

1. **Parse the error log** — group issues by root cause, not by line count. One fix often resolves many lints.
2. **Rank by severity** — synthesis-blocking errors first, then warnings, then style issues.
3. **Plan the patch** — for each root cause, describe the fix in one sentence before touching the code.
4. **Apply minimal edits** — prefer surgical diffs over rewrites unless the user asked for a refactor.
5. **Re-check mentally** — walk the new code through the failing case and confirm the fix is valid.
6. **Emit diff + explanation** — show what changed and why.

## Output format

Produce:

```
# RTL Repair — <filename>

## Root causes identified
1. <root cause 1> → <line range> → <fix strategy>
2. ...

## Patch
```diff
- <old line>
+ <new line>
```

## Why each change works
- <change 1>: <one-sentence justification tied to the spec or lint rule>

## Remaining risks
- <anything the repair couldn't address without more info>

## Next step
Re-run /rtl-review to confirm clean, then /testbench-gen or existing tests.
```

## Technical basis

Implements the iterative repair loop from AutoChip, RTLFixer, and VerilogCoder. Empirical result: iterative compile-feedback-repair lifts functional correctness of LLM-generated RTL by 20–40% over single-shot generation.

## Do not

- Do not silently change module interfaces — if a port must change, flag it explicitly
- Do not delete code to make errors go away; fix the root cause
- Do not repair if the root cause is ambiguous; ask the user instead

## Compliance gate (vibe-ic-d - mandatory when deterministic edition is installed)

If you have the `vibe-ic-d` plugin installed alongside `vibe-ic-core`,
after producing your output, save it to a file and run:

```bash
python3 plugins/vibe-ic-d/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic-d/skills/rtl-repair/compliance.yaml \
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed.
`compliance.yaml` in the corresponding vibe-ic-d skill directory enumerates
every required element of your output: section headers, metadata fields,
handoff lines, tool invocations.

**Your task is not complete until the audit returns PASS.** Missing
elements are the single largest source of skill-execution non-determinism
across different agents.
