---
name: rtl-review
description: Audit RTL code for lint violations, synthesis hazards, coding-style compliance, and readability. Use when the user says "review this Verilog", "check my RTL", "lint this module", "is this code synthesizable", or shares an HDL file and asks for feedback before simulation or tape-in.
---

# RTL Review (Pattern-A — program-driven, doctrine-compliant v0.1.50)

> **Doctrine (user, 2026-05-29):** 把修法寫進工具，而非寫進 prompt。
>
> The 6-category checklist + 0-10 scoring rubric that previously lived
> in this skill prose is now in **`programs/rtl_review_aggregate.py`**
> (37 pytest cases pin every category mapping + scoring boundary).
>
> **You run the program first.** Claude is the backstop for residual
> prose, NOT the rule applicator.

## When to use

User shares an RTL file or directory and asks for a review.

## Mandatory: run the program FIRST

```bash
python3 plugins/vibe-ic/programs/rtl_review_aggregate.py \
    --rtl-dir <dir-of-.v-and-.sv> \
    --out-md  rtl_review.md \
    --out-json rtl_review.json
```

Exit codes: 0 = PASS or WARN; 1 = FAIL (with `--strict`); 2 = bad input.

The program runs three sub-programs:
- `rtl_hygiene_lint.py` — § 1 synthesis hazards + § 3 style + § 5 width
- `reset_discipline_check.py` — § 2 reset/clock hygiene
- `rtl_precheck_gate.py` — § 4 correctness smells + § 6 port fidelity

It aggregates findings into 6 categories, computes the score (rubric in
`compute_score()`), and emits the same Markdown template the skill
previously asked the LLM to author by hand.

## What Claude does (backstop only)

After the program emits `rtl_review.md` + `rtl_review.json`:

1. **Read the program output.** Do not re-derive any number it already returned.
2. **Refuse to claim a higher score than the program returned.** The
   scoring rubric is deterministic; overriding it would be an honesty-rule
   violation.
3. **Add residual prose** the program cannot author: design-intent
   comments per finding (why a particular latch is intentional, why a
   width-mismatch is parameterised), and short fix-suggestions per
   ERROR / WARN.
4. **Handoff:** if `verdict == "FAIL"`, recommend `/rtl-repair` (which
   runs `rtl_hygiene_lint.py --fix`). If `WARN`, list the items to address
   before tapeout. If `PASS`, proceed to `/checkpoint-gate`.

## Scoring rubric (deterministic, in the program)

The skill USED to enumerate this as prose. It is now `compute_score()`
in `rtl_review_aggregate.py`, pinned by pytest:

| Score | Condition | Verdict |
|---|---|---|
| 10 | 0 errors, 0 warns, 0 infos | PASS |
| 8–9 | 0 errors, 0 warns, INFO-only | PASS |
| 6–7 | 0 errors, 1–4 warns | WARN |
| 4–5 | 0–1 errors OR ≥ 5 warns | FAIL |
| 2–3 | 2+ errors | FAIL |
| 0–1 | not synthesizable | FAIL |

## Anti-patterns

- ❌ **Authoring the score by reading the file.** The program returns
  it; you do not re-derive.
- ❌ **Skipping the program because "it's a small file".** The program
  is the audit trail. Run it on every review request.
- ❌ **Claiming PASS when the JSON output says `verdict: FAIL`.**

## Technical basis

`programs/rtl_review_aggregate.py` + `programs/tests/test_rtl_review_aggregate.py`
(37 pytest cases). The 3 sub-programs all pre-existed; this skill's
former 159-line prose checklist is now a 14-line wrapper because the
rules moved from prompt-space to tool-space.

## Compliance gate

If `vibe-ic-d` is installed:
```bash
python3 plugins/vibe-ic-d/_shared/skill_compliance_check.py \
    --requirements plugins/vibe-ic-d/skills/rtl-review/compliance.yaml \
    rtl_review.md
```

Exit 0 = PASS; exit 1 = the program output is missing a required section
(typically you forgot `--out-md` or the program crashed and you authored
by hand instead).
