---
name: rtl-review
description: Audit RTL code for lint violations, synthesis hazards, coding-style compliance, and readability. Use when the user says "review this Verilog", "check my RTL", "lint this module", "is this code synthesizable", or shares an HDL file and asks for feedback before simulation or tape-in.
---

# RTL Review

Perform a structured review of RTL code, flagging issues by severity and producing a 0–10 quality score. Acts as an LLM-as-a-judge pre-check before the design hits real EDA tools.

## When to use

Trigger when the user:
- Shares a Verilog/SystemVerilog/VHDL file and asks for feedback
- Says "review", "lint", "audit", or "sanity check" on HDL
- Wants to know if code is synthesizable or clean
- Asks for coding-style or readability comments on hardware code

## Review checklist

Go through every category. For each issue found, record: file, line number, severity (ERROR / WARN / INFO), category, and a one-sentence explanation.

### 1. Synthesis hazards (ERROR)
- Inferred latches in `always_comb`
- Multiple drivers on the same net
- Incomplete sensitivity lists in legacy `always @(*)`
- `initial` blocks outside testbenches
- Non-synthesizable constructs (`$display`, `#delay`, `fork/join`)
- Combinational feedback loops

### 2. Reset and clock-domain hygiene (ERROR/WARN)
- Flops without reset
- Mixed sync/async reset on the same signal
- Cross-clock-domain signals without synchronizers
- Reset recovery/removal violations
- Gated clocks without explicit clock-gating cells

### 3. Style and readability (WARN/INFO)
- `always @(posedge clk)` vs `always_ff` consistency
- `reg`/`wire` vs `logic` in SystemVerilog
- Magic numbers that should be parameters
- Missing header comment
- Signal naming (should follow snake_case)
- Over-wide always blocks (>50 lines)

### 4. Correctness smells (WARN)
- Blocking assignments in sequential logic
- Non-blocking assignments in combinational logic
- Truncation without explicit slicing
- Unintended sign extension
- `x` or `z` literals in synthesizable code

### 5. Parameter and width issues (WARN)
- Implicit width mismatches in assignments
- Hard-coded widths that should be parameterized
- Parameter ranges that allow illegal values

## Output format

Produce a review report with this structure:

```
# RTL Review — <filename>

**Overall Score: X/10**

## Summary
<2-3 sentence verdict>

## Findings

### Errors (must fix)
| Line | Category | Issue |
|------|----------|-------|
| ...  | ...      | ...   |

### Warnings (should fix)
| Line | Category | Issue |
|------|----------|-------|

### Info (consider)
| Line | Category | Issue |
|------|----------|-------|

## Recommendations
- <top 3 things to fix first>

## Next step
Run /rtl-repair to auto-apply fixes, or /testbench-gen to validate behavior.
```

## Scoring rubric

- **10**: No errors, no warnings, production-ready
- **8–9**: Clean code with minor info items
- **6–7**: Some warnings, no blocking errors
- **4–5**: Multiple warnings or one error
- **2–3**: Multiple errors, significant rework needed
- **0–1**: Not synthesizable, major structural issues

## Technical basis

Implements the LLM-as-a-judge pattern validated by RTLBench and similar multi-dimensional evaluation benchmarks. Aligned with industry lint rules from Synopsys SpyGlass, Cadence JasperGold, and Siemens Questa Lint — but pre-filters issues before the paid tools run.

## Do not

- Do not "fix" code in this skill — that is `/rtl-repair`'s job
- Do not run actual simulation — suggest `/testbench-gen` instead
- Do not invent issues; if the code is clean, say so and give a high score

## Compliance gate (vibe-ic-d - mandatory when deterministic edition is installed)

If you have the `vibe-ic-d` plugin installed alongside `vibe-ic-core`,
after producing your output, save it to a file and run:

```bash
python3 plugins/vibe-ic-d/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic-d/skills/rtl-review/compliance.yaml \
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed.
`compliance.yaml` in the corresponding vibe-ic-d skill directory enumerates
every required element of your output: section headers, metadata fields,
handoff lines, tool invocations.

**Your task is not complete until the audit returns PASS.** Missing
elements are the single largest source of skill-execution non-determinism
across different agents.
