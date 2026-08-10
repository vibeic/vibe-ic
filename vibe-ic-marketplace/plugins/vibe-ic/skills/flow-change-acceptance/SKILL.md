---
name: flow-change-acceptance
description: "MANDATORY before landing any change to the FLOW itself — a gate, a check, a step, a phase runner, a verdict rule, or anything under programs/ that every design passes through. Flow-level changes are foundational: when they are right every cell benefits, and when they are wrong every cell lies at once and nobody notices. This skill is the acceptance standard for that class of change: bidirectional negative control (a test that cannot fail against the pre-fix code proves nothing), corpus sweep with zero false positives, prove-by-run that a gate declared BLOCKING actually stops the flow, no design/PDK/vendor literals, an explicit BLOCKING-vs-ADVISORY declaration, and degrade-loudly-never-silently. Every criterion here was written from a measured failure in this repo, cited inline. Triggers on: authoring or reviewing a gate/check/step, 'add a gate', 'this check should catch', 'why did the flow not catch', 'land a flow fix', 'flow-level change', '流程層改動', '加一個檢查', '這個 gate 為什麼沒擋住'."
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
by sweeping a repo data root. `real_artefact_test_backing_check` reports the split
per changed test module, ADVISORY.

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
- [ ] the pre-fix control was **graded, not asserted** — capture it and hand it
      to the program, because "the tests fail pre-fix" is true of every new file
      ever written:

      ```
      PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 python3 -m pytest <the new tests> \
          -q -p no:cacheprovider --junitxml=/tmp/control.xml     # on clean main
      python3 programs/control_substance_check.py --junit /tmp/control.xml
      ```

      and pass the same file to the merge gate, which BLOCKS on a control whose
      every failure is an absence:
      `gatekeeper_review.py --base <b> --head <h> --control-junit /tmp/control.xml`
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

## Candidates to promote from this prose into programs

Program-first applies to this skill too. These criteria are mechanically checkable
and should become deterministic checks rather than relying on an author remembering:

- every gate declares BLOCKING vs ADVISORY (missing declaration ⇒ fail)
- ~~every new gate's test suite contains at least one assertion that fails against
  the parent revision~~ — LANDED as `control_substance_check`, and sharpened: the
  criterion is that an assertion OBSERVED A VALUE, not merely that it failed
- no flow-level program under `programs/` matches a design/PDK/vendor literal list
- every `if <remedy> is not None:` decision point has an `else` that records the
  decline

Until they exist as programs, they live here — and a reviewer is expected to check
them by hand.

---

## Which of these are now PROGRAMS (this doctrine obeys program-first)

Landed, so the criterion is checked rather than remembered:

| criterion | program | measured in |
|---|---|---|
| §3, §5 | `flow_gate_enforcement_audit` — ENFORCED / AUDIT_ONLY / ORPHANED, and flags a gate declaring blocking while wired advisory | #306 |
| §6 | `silent_decline_audit` — AST audit for remedy call sites whose refusal discloses nothing | #307, #312 |
| §4 | `source_chip_agnostic_check` | CI |
| "empty vs clean" | `phase1_expert_track_evidence_check` — NEVER_RAN vs RAN_EMPTY | #312 |
| §1 | `control_substance_check` — reads the pre-fix control's OWN pytest report and counts how many failures observed a VALUE, as against only noticing that something was absent. Composed by `gatekeeper_review --control-junit`, which BLOCKS on a tautological control | #381 |

Still prose, worth promoting:
- corpus-sweep evidence should be an artefact, not a claim in a PR body (§2)

PROMOTED, and the reason it needed promoting: "every new gate's tests must
contain at least one assertion that FAILS on the parent revision" is not the
property that matters, and running them against `HEAD~1` does not measure it.
Measured on two live PRs — one control collected NOTHING (a
`ModuleNotFoundError` for the module the fix introduces; 551 lines of new test,
zero assertions executed) and another reported "4 of 4 behavioural" when three
of the four failed on the ABSENCE of a field the fix adds. Both "failed on the
parent revision". `control_substance_check` grades the difference, and
`gatekeeper_review --control-junit` is where it blocks.

## Compliance gate (mandatory)

This skill ships `compliance.yaml`, and its patterns are enforced by
`tests/test_compliance.py` in this directory. Before landing a change that
claims to follow this doctrine, run the deterministic gate:

```bash
python3 -m pytest -q \
    plugins/vibe-ic/skills/flow-change-acceptance/tests/test_compliance.py
```

The gate is the point of the doctrine, not a formality: every criterion
above exists because a change that skipped it shipped a false certificate.
A criterion asserted in prose and not measured by the gate is exactly the
kind of unenforced declaration §5 tells you to refuse.

**This section was missing until 2026-07-26.** The skill was landed during
the #306/#307/#312 campaign with its `compliance.yaml` and tests in place
but no Compliance-gate section in `SKILL.md`, so
`test_every_skill_md_has_compliance_gate` had been RED on `main` — unseen,
because CI runs the cadence-correct targeted subset rather than the full
suite. A doctrine file about unenforced declarations shipped with an
unenforced declaration of its own.
