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

**Step 0 — run the deterministic structural lint FIRST (do not eyeball it).**
The presence/structure half of the checklist above — *is each declared signal's
`{direction, width, polarity, clock, reset}` present? does each timing statement
name a reference edge? does each declared mode have entry + exit? are the four
corner-case checklist items covered?* — is mechanical and must run identically
every time. Run it before any human reading so the rest of your review is spent
only on judgment:

```bash
python3 programs/spec_review_lint.py <spec_file> --json spec/spec_review_lint.json
# add --strict to make any WARN finding fail the gate (exit 1)
```

The lint is chip-AGNOSTIC and no-false-alert: it flags ONLY genuinely-missing
declared structure (a signal that IS declared but lacks an attribute, a real
timing statement with no edge, an uncovered corner-case item). A pure-prose spec
with no interface list yields no signal findings; an empty/short spec SKIPs; a
missing file exits 2. Treat every `WARN` as a concrete must-fix gap and fold the
JSON findings into your dimension table below. It does NOT judge ambiguity wording
or propose rewrites — that is your job in steps 3-5.

1. Read the spec end-to-end
2. For each dimension above, mark each section as GREEN / YELLOW / RED — seed the
   Unambiguous / Testable / Complete-corner-cases rows from `spec_review_lint.json`,
   then apply judgment to the consistency / interface / non-functional rows
3. List specific sentences that are ambiguous with suggested rewrites **(judgment —
   the lint does not do this)**
4. Flag missing subsections **(judgment, beyond the lint's structural items)**
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

## Compliance gate (mandatory)

After producing your output, save it to a file and run:

```bash
python3 plugins/vibe-ic/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic/skills/spec-review/compliance.yaml \
    <your_output_file>
```

Exit 0 = PASS, exit 1 = FAIL with specific missing elements listed.
`compliance.yaml` in the corresponding skill directory enumerates
every required element of your output: section headers, metadata fields,
handoff lines, tool invocations.

**Your task is not complete until the audit returns PASS.** Missing
elements are the single largest source of skill-execution non-determinism
across different agents.
