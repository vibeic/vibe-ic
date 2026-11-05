---
name: phase1-coverage-loop
description: "Compare requested design documents with their generated consumer fields, fix general extraction defects, and verify meaning survives."
---

# Phase 1 coverage loop

Read `CHARTER.md` and operate as `ic-expert-agent`. Use the requested design
prompts and documents as input. Preserve the expert DB, the per-layer lessons,
and the ownership of each fact across the generated layers.

## Check source meaning at the consumer

1. Run the normal Phase 1 public entry on the current input.
2. Read the source documents and generated fields. Verify each admitted fact where its actual downstream consumer reads it.
3. Use `phase1_input_vs_generated_completeness_check.py` for its existing token-coverage measurement. Read its JSON result without turning the measurement into whole-design acceptance.
4. Review semantic omissions and incorrect ownership independently. A correct token in an unrelated layer is still a consumer gap.
5. Reproduce a general extractor defect, fix its owning producer, and rerun the affected extraction and tests.
6. Save the input, generated result, exact discrepancy, and verification scope outside the plugin repository.

The existing token-coverage classification remains FAIL below 50 percent with
at least 10 tokens, WARN from 50 to 80 percent, and PASS at or above 80 percent,
with its existing SKIP cases. These are the program's measurement labels, not
new signoff limits. Keep all source-derived values and native limits unchanged.
A clustered missing pattern is useful evidence of an extractor defect even
when a coarse coverage percentage looks acceptable.

Review a fix against the actual consumer. If the defect was in document
meaning, verify the corrected meaning through the relevant RTL or tool path
when that path is in scope. Preserve the source's authority and do not invent
missing requirements from a benchmark name or expected answer.

For open benchmarks, authors and reviewers remain blind to hidden oracle,
harness, and golden contents. Program First, independent AI review and backup,
and official scoring remain the product path through `benchmark_dispatch.py`.

Continue through the requested input set until its work is complete. Report
remaining gaps and external dependencies plainly. Use only the task's current
authorization for messages, issues, repository writes, and landing.
