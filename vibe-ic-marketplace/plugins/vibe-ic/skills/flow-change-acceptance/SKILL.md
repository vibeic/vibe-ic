---
name: flow-change-acceptance
description: "Validate changes to shared flow behavior, runners and verdict rules before landing: exercise actual consumers, known-good and known-bad cases, and retain honest evidence scope. Apply to flow-level implementation or review, not unrelated documentation edits. A repair does not automatically require a new checker, global gate or compliance template."
---

# flow-change-acceptance — the standard for changing the flow itself

A fix to one cell is judged by that cell. **A change to the flow is judged by every
cell that will ever run through it, including the ones nobody is watching.**

That asymmetry is the whole reason this skill exists:

| | a fix to one design | a change to the flow |
|---|---|---|
| blast radius | that design | every design, and every future design |
| failure mode | that design fails | every design agrees, and every design is wrong |
| who notices | whoever ran it | **nobody** — a flow that lies is indistinguishable from a flow that works |

Every criterion below is written from a **measured** failure in this repo. None of
them is a style preference.

## Choose the smallest sufficient verification change

Verification protects a product contract; its growth is a cost, not a product
outcome. A past incident does not automatically justify another permanent gate.

Before adding machinery, identify the actual failed behavior and its consumer.
Prefer fixing the producer or removing duplicate state, then extending the
existing behavioral test for that contract. One maintained test implementation
can cover many data cases; do not copy a checker or test module for each issue.

Separate these scopes:

* A local regression case proves a specific failure is repaired. Keep it with
  the responsible component and use the existing selection mechanism.
* A global release gate is justified only by a cross-cutting risk that cannot
  be covered at its owning boundary. Review its applicability, existing overlap,
  expected execution cost and maintenance owner before making it mandatory.
* Report-format advice and documentation lint are not evidence that a design,
  simulation, verifier or repair actually worked. Do not promote a preferred
  heading or prose pattern into a product-admission requirement.

When equivalent checks already exist, consolidate their implementation and
retain the discriminating cases. Changing one declaration should not require
hand-synchronizing its copies or adding a new checker to check their equality.
Prove that genuine bad inputs still fail and legitimate changes no longer
cause representation-only failures. Do not use blanket test deletion, assertion
caps, weaker thresholds, hidden skips or rewritten baselines as substitutes.

This is authoring/review guidance, NOT a request for another global policy
checker. Existing checks are not automatically reclassified by this paragraph;
change their actual producers/consumers with scoped behavioral evidence.

---

## The six criteria

### 1. Bidirectional negative control — a test that cannot fail proves nothing  <!-- measured: #298, #295 -->

Every new gate ships a test that **FAILS against the pre-fix code** and **PASSES
after**. Assert both directions explicitly; running only the post-fix direction
measures nothing.

**⚠️ The vacuous-pass trap.** When a check does not exist yet, a
`test_..._clears_the_finding` assertion passes *vacuously* — the finding never fires
because nothing can fire it. Such a test is only meaningful **paired** with its
`test_..._fires` sibling. Never present a "clears" test as a standalone negative
control.

> *Measured:* an author of a Phase-1/Phase-3 supply gate wrote both directions,
> then flagged in their own handoff that the `*_clears_the_finding` half passed
> vacuously pre-fix and was only valid paired with `*_fires`. That self-caught
> caveat is the standard, not an exception.

### 2. Corpus sweep — zero false positives, or the gate is a bug  <!-- measured: #298, #309, #312 -->

Run the new gate over the real existing runs available to you. **A gate that fires
on a legitimately-complete design is a bug in the gate, not a finding.** Narrow it or
drop it, and report what you swept and what you could not reach.

The cost of a false positive is not noise — it is that people learn to ignore the
gate, which is how a repo ends up with gates nobody acts on.

### 3. Prove-by-run that a BLOCKING gate actually blocks  <!-- measured: #306 -->

If you claim a gate blocks, **run it and show the flow stopped**. Do not infer it
from reading the code.

> *Measured, and the reason this criterion exists:* `cts_quality_check` is wired
> into the flow, has a test, and returned `verdict: FAIL` with `waiver: None` on
> three consecutive plugin versions of the same cell — while the flow went on to
> ship a 44 MB `post_cts.def` and a 181 MB `routed.def` anyway. Eleven gates in that
> same run carried FAIL and none stopped anything. A subsequent audit put the number
> at **62 of 72 gates cannot block**.
>
> A gate that fails without blocking differs from no gate only in being auditable
> after the fact.

### 4. No design, PDK, or vendor literals  <!-- enforced: source_chip_agnostic_check -->

The flow is shared by every design. **The moment a flow-level program hardcodes a
pin name, a cell name, a PDK name, or a vendor part number, it stops being flow and
becomes that design's private patch** — and it will silently misbehave on the next
design.

Drive every decision from inputs the design itself supplies: a macro's own LEF `USE`
records, the declared constraint files, the top-level port list, the design's own
L-docs. Test fixtures must be **synthesized neutral data**, never a copy of a real
design's files.

**What that does NOT mean (vibe-ic#400).** "No copy of a real design's files" forbids
HARDCODING a chip into a fixture. It does not forbid a test from READING a
checked-in artefact — and read literally it pushed authors into a suite that is
100 % synthetic, which is a different failure:

> A change whose tests are all fixtures authored alongside it **cannot distinguish
> itself from its own absence.** Measured: mutating a guard killed 10 of 31 tests —
> every one of them hand-typed in the same commits — while all 4 tests that read a
> checked-in artefact still passed. No document in the repo could tell that guard
> from its absence.

So, for a BEHAVIOURAL change: at least one test must be driven by a real in-repo
artefact, through `programs/tests/_hostpaths.require_repo` / `repo_path` (which
hardcodes nothing — `source_chip_agnostic_check` passes on trees that use it), or
by sweeping a repo data root.

A real-artefact test is still not automatically non-vacuous — an implication whose
antecedent is always false passes either way. What proves a test bites is the
MUTATION RUN criterion 1 already asks for; the split report is what makes a
reviewer ask for it.

> *Measured:* a supply-intent gate was verified chip-agnostic by confirming the only
> `VDD/VSS` occurrence in the new logic was inside a *comment*, and that the pin-type
> decision came from the macro's LEF, not from a name list.

### 5. Declare BLOCKING or ADVISORY — in the gate, not by default  <!-- measured: #306 -->

State in the gate's own docstring/output whether a failure **stops the flow** or
**records and continues**, and why. Silence is not neutral: an unstated default of
"advisory" is how 62 of 72 gates ended up unable to stop anything, which is certainly
not what their authors intended — nobody writes a check for "the clock tree was never
built" and means it as a note.

### 6. Degrade loudly, never silently  <!-- measured: #307, #312 -->

A path that declines to act — a remedy refused, an optional track unavailable, a
budget exceeded — must **emit a named record** saying so. A silent decline reads
downstream as "nothing needed doing".

> *Measured, twice:*
> - The route-loosen call site was `if _lf is not None:` with **no else branch at
>   all**, while the upsize path returned a named FAIL for the same class of refusal.
>   The flow could decline its own rescue and tell nobody.
> - The Phase-1 second track (Expert/AI) was **never executed**: its `ai_patches`
>   sidecar was read by three checks and **written by nothing**, so
>   `ai_captured_tokens_count` could only ever be `0`. A dual-track that silently
>   runs one track reports like a dual-track.

---

## What a completeness check must actually measure

A recurring, expensive mistake: measuring **presence somewhere** instead of
**presence where it is consumed**.

> *Measured:* the Phase-1 completeness model asked "does this vendor token appear in
> ANY layer". A hard macro's supply pin name appeared in the descriptive datasheet
> layer, so the check reported CAPTURED — while the layer the **backend actually
> reads** contained it zero times. The PDN was therefore built with no rail for it,
> synthesis tied the pin off with a TIEHI cell, a signal net landed on a POWER
> terminal, and detailed routing aborted **entirely**: 3278 signal nets, 0 routed,
> LVS unreachable — five steps downstream from where the information had been
> available all along, surfacing as an opaque router error.

So: identify **who consumes the artifact** and check for what that consumer needs, in
the form it needs. "The token exists somewhere in the corpus" is not that.

---

## Before you land

- [ ] negative control fails pre-fix, passes post-fix, **both asserted**
- [ ] no `*_clears` assertion presented as a standalone control
- [ ] corpus sweep run; zero false positives; coverage limits stated honestly
- [ ] if BLOCKING: **prove-by-run**, with the stopped-flow evidence quoted
- [ ] zero design/PDK/vendor literals; fixtures synthesized
- [ ] BLOCKING or ADVISORY declared explicitly in the gate
- [ ] every decline/skip path emits a named record
- [ ] compare failure **name sets**, not counts — a truncating flag such as
      `--maxfail` makes two runs stop at different points and their equal counts
      mean nothing
- [ ] the artifact you tested is the one that carries your fix — verify the plugin
      cache actually contains the changed code before trusting any run

## Reuse existing verification

Program-first means automate useful repeated work. It does not mean convert
every sentence, lesson or code shape into a new permanent admission gate.
Use the relevant existing programs below; invoke them for their actual subject,
and report what they measured. Extend an existing contract implementation when
possible instead of adding another layer that checks the checker.

---

## Which of these are now PROGRAMS (this doctrine obeys program-first)

Landed, so the criterion is checked rather than remembered:

| criterion | program | measured in |
|---|---|---|
| §3, §5 | `flow_gate_enforcement_audit` — ENFORCED / AUDIT_ONLY / ORPHANED, and flags a gate declaring blocking while wired advisory | #306 |
| §6 | `silent_decline_audit` — AST audit for remedy call sites whose refusal discloses nothing | #307, #312 |
| §4 | `source_chip_agnostic_check` | CI |
| "empty vs clean" | `phase1_expert_track_evidence_check` — NEVER_RAN vs RAN_EMPTY | #312 |

Keep corpus-sweep evidence as an artifact with its measured scope (§2). This
requirement does not itself call for a new global checker.

## Compliance gate scope

This skill ships `compliance.yaml` and `tests/test_compliance.py`. They test
the report-pattern machinery, not the feature, the stopped flow, or the truth of
the report's claims. Run these tests when changing this skill's compliance
contract, generator or shared checker:

```bash
python3 -m pytest -q \
    plugins/vibe-ic/skills/flow-change-acceptance/tests/test_compliance.py
```

For a flow behavior change, the actual evidence is the observed behavior and
the substantive positive/negative controls above. A regex-generated "good
output" cannot certify them. Report lint may identify missing explanations;
it must not replace execution evidence or require a new global gate merely
because a skill exists. Existing explicitly declared artifact/receipt checks
still require their real producer evidence; no scope is silently waived.
