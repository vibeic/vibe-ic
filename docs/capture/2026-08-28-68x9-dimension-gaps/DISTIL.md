# DISTIL — the four 68x9 dimensions that did not catch their own defect

The capture step produced `recoveries.json` from the 68x9 mutation probe run on
plugin v1.12.33; this file records the DISTIL step run against it on
2026-08-28. Every disposition below is backed by a number taken on this tree.

## What the probe measured

The matrix is 68 flow steps x 9 dimensions = 612 cells. A named mutation was
run against each dimension's own defect class. **Five reddened. Four did not.**

| Dim | Mutation | Verdict | What was actually broken |
|---|---|---|---|
| D1 `wiring` | MUT-B: remove what hands the executor its gate dict for step 21 | **GREEN**, 86 passed | the step vanished from the tally; MISSING 40 -> 39; 18 blocked steps unblocked |
| D2 `falsifiable` | M2: kill the namesake verdict, leave the absence arm | **GREEN** | 54 of its 121 reds were earned on EMPTY |
| D3 `outputs_produced` | MUT-B1: delete the WRITER of A8's declared `.gds` | **GREEN** everywhere | 122 of 166 entries ask the committed corpus, not the source |
| D6 `skip_discipline` | M1: the gate stops working and says `VACUOUS_PASS` | **GREEN**, byte-identical | step 16 moved from `status='FAIL'` to `status='VACUOUS_PASS'` |

The control arms all reddened: MUT-A (a gate naming a missing program) reddened
D1, M1 (a gate that always exits 0) reddened D2, and M1b (the same gate as M1
but SILENT) reddened D6 hard. So each dimension works — on the defect it was
built for, and not on the seam one level over.

## Bucket-A records: 4, all shipped

Program-first, per `benchmark-enhancement-capture`. None needed
`why_not_bucket_a`: every one of the four reduces to a structural question over
source or over a census, with no judgment step.

| Record | Shipped as | Wired as |
|---|---|---|
| `gate_dict_reaches_the_executor` | `programs/every_declared_step_reaches_the_evaluator_check.py` | gate — `every declared step reaches the evaluator` |
| `declared_output_has_a_live_producer` | `programs/declared_output_has_a_live_producer_check.py` | gate — `a declared output has a live producer` |
| `a_disclosure_token_is_not_a_working_gate` | `programs/vacuous_disclosure_needs_a_runtime_condition_check.py` | gate — `a disclosure token needs a runtime condition` |
| `a_red_that_only_means_nothing_ran` | `programs/gate_red_is_more_than_absence_census.py` | census — `gate red is more than absence` `--self-test` |

Each ships with a test carrying BOTH directions and a
`tools/ci/gate_fixtures/` pair at the same denominator.

## Why one of the four is a census and three are gates

Three sweep CLEAN on this tree today, so they land refusing:

* every declared step reaches the evaluator — **68 declared, 68 reached**
* a declared output has a live producer — **197 declared: 42 WRITE-SITE, 155
  TOKEN-TRACE, 0 NO-TRACE**
* a disclosure token needs a runtime condition — **627 gate modules scanned, 0
  unconditioned disclosures**

The fourth does not, and says so instead of being narrowed until it does.
MEASURED over 629 gate modules: **234 ABSENCE-ONLY, 141 VERDICT-BEARING, 254
NO-LITERAL-RED** (a computed exit this scanner cannot decide — named as
undecidable, never folded into either answer). A large minority of gates can
only fail on an absent input, and for some of them that is correct: a presence
gate's whole subject IS whether the artefact is there. Which of the 234 should
grow a content arm is a maintainer's backlog, not something a new census may
decide, so it follows the repo's existing census convention
(`only_the_declaring_step_writes_its_output_census`): informational exit,
`--self-test` in the hygiene lane, and the count PRINTED rather than capped.

## What each program does NOT claim

* **D1's** — it says every declared step reaches the evaluator. It says nothing
  about the verdicts; on a stub project almost every gate legitimately skips,
  and demanding a verdict would test the fixture instead of the wiring.
* **D3's** — it says something in the source still writes the path. Whether
  what gets written is CORRECT is `flow_output_substance`'s question, given a
  run; whether TWO steps write it is
  `only_the_declaring_step_writes_its_output`'s. Its write-site scan reuses
  that gate's own helpers rather than growing a second, differently-wrong copy.
* **D6's** — it says a disclosure is guarded by a runtime fact. Whether that is
  the RIGHT fact is a judgment about the gate's subject. Half (b) of D6, the
  tier a skip is reported at, remains `gate_skip_routing_check`'s.
* **D2's** — it classifies the red a gate can reach. It does not decide that an
  absence-only gate is wrong.

None of the four replaces its dimension. D1 keeps proving the walk INSIDE the
executor is complete; D3 keeps proving the artefact once existed. The four
programs ask the half that was never asked.

## Three false starts, each of which would have shipped a green that was not earned

Recorded because the failure mode is the same one the matrix has:

1. **The `__main__` guard read as a runtime fact.** `if __name__ == "__main__":`
   contains a Compare and a Name, so the first version of D6's rule counted it
   as conditioning — which cleared every disclosure inside `main()`, i.e. the
   whole population the gate exists to judge. It still passed its own unit
   tests, which are written as bare functions with no `__main__` block. That is
   a check that fires only on the shapes it was tested with.
2. **Prose read as an emit.** The first version flagged 220 sites, nearly all
   docstrings DISCUSSING `VACUOUS_PASS` and constant tuples listing the
   vocabulary. Narrowed to actual `print` / `exit` / `.write` calls, and to a
   sentinel at LINE START, which is the consumer's real contract
   (`line.lstrip().startswith(...)`).
3. **A matcher that matched everything.** D3's first matcher credited every
   declaration with a producer, because a destination rendered as bare `*` (an
   unresolved variable) fnmatches any declared basename. 197/197 WRITE-SITE was
   the tell: a program that answers "yes" always is the defect it was written
   to correct.
