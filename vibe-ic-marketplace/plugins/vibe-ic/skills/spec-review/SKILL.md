---
name: spec-review
description: Review a natural-language hardware specification for ambiguity, internal inconsistency, untestable statements, and missing corner cases BEFORE it enters spec-to-rtl. Use when the user says "review this spec", "check my spec", "is this spec complete", "spec sanity check", or provides a datasheet draft / PRD for a hardware block.
---

# Spec Review

A bad spec is the cheapest bug to fix and the most expensive to ship. This skill screens a natural-language spec for defects before `/spec-to-rtl` turns the defects into RTL.

## When to use

- Draft PRD / architecture doc for a new block
- Legacy spec being resurrected for a new tape-out
- Spec delta for an ECO
- Before running any generative skill that consumes the spec

## Review dimensions

1. **Unambiguous**
   - Every signal has direction, width, polarity, clock domain, reset domain
   - Every timing statement has a reference edge
2. **Internally consistent**
   - No contradicting statements ("always X" vs "X when Y")
   - Priority order of control signals is explicit
   - Numerical examples match the general rule
3. **Testable**
   - Every behavior can be observed from I/O or debug
   - Every mode has an entry and exit condition
4. **Complete corner cases**
   - Reset during operation
   - Back-to-back transactions
   - Full / empty / overflow / underflow
   - Illegal inputs — defined vs undefined behavior
5. **Interface discipline**
   - Protocol compliance (AXI, APB, AHB, I2C, SPI)
   - Handshake sequencing
6. **Non-functional**
   - Power / clock / area / latency targets stated
   - Safety / security level

## Workflow

1. Read the spec end-to-end
2. For each dimension above, mark each section as GREEN / YELLOW / RED
3. List specific sentences that are ambiguous with suggested rewrites
4. Flag missing subsections
5. Propose cover properties that should exist once the spec is hardened (handoff to `/assertion-gen`)

## Output format

- `spec/spec_review.md`:
  - Dimension score table
  - Line-by-line findings
  - Suggested rewrites (diff-style)
  - Open questions for the designer

## Technical basis

Requirements-engineering principles (IEEE 29148). For hardware specifically: ARM AMBA spec methodology, automotive ISO 26262 requirements tracing.

## Handoff

- Hardened spec → `/spec-to-rtl`
- Testable claims → `/assertion-gen`
- Architecture trade-offs → `/architecture-explore`

## Compliance gate (vibe-ic-d - mandatory when deterministic edition is installed)

If you have the `vibe-ic-d` plugin installed alongside `vibe-ic`,
after producing your output, save it to a file and run:

```bash
python3 plugins/vibe-ic-d/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic-d/skills/spec-review/compliance.yaml \
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed.
`compliance.yaml` in the corresponding vibe-ic-d skill directory enumerates
every required element of your output: section headers, metadata fields,
handoff lines, tool invocations.

**Your task is not complete until the audit returns PASS.** Missing
elements are the single largest source of skill-execution non-determinism
across different agents.
