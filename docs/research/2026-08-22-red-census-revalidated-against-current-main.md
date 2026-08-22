# The v1.11.66 red census, re-measured against current main (244 commits later)

host 8hd-3 · 2026-08-22 · branch `next/red-census-vs-current-main`, cut from
`origin/main` at **a4caccefe**

## IF YOU READ ONE SCREEN, READ THIS

**The frozen branch `ptmo/main-red-triage-v11166` @ `88cf416b6` still merges
cleanly onto current main and the merged tree was RUN** (Part 5): 11 files, no
conflicts, `6 failed / 128 passed` — the same failing set it measures alone. **It
needs no rebase and changes no number it reports once landed.**

**Its findings survived 244 commits, and FOUR of its five requests have been
answered upstream** (Parts 2, 6): the flow-gate intent declared, two checkers
wired exactly where it predicted, the liar-census pin bumped with the start of a
cure. **The fifth (`ppa_pr_scope_check`) has a venue after all** — the merge
verifier, which already computes the `--base`/`--head` pair it takes (Part 7).

**WHAT REMAINS, and who can act** (final grouping, Part 17 — 30 on the frozen
branch's tree, 33 on main; the difference is the branch's own effect, Part 18):

| n | group | what it needs |
|--:|---|---|
| 14 | corpus/record | **re-point the records** to a `repo`/`published` kind. Publishing does not help — `home` roots are excluded by design. A registry waiver is the third route and is **available but forbidden to me** (Part 8) |
| 6 | landing-verdict | **2** need ONE LINE: `gatekeeper-verify-merge.sh` announcing `RUN_ID`. **4** are fully diagnosed: `validate` requires an `origin` its only caller's subject cannot have — both shipped in `7c376e348` (Part 12) |
| 5 | vacuity | **the fix is already written twelve lines from the defect.** `#901` diagnosed this mis-fire in prose and fixed it for the structured channel; the uncounted legacy branch at `:10120` runs first (Part 15) |
| 3 | mutation ledger | red **BY DESIGN** — frozen `applies_to` demands a measurement that the d3 red currently blocks (Part 16) |
| 1 | 63x8 anti-skip | a considered disagreement between two rules, both defensible (Part 13) |
| 1 | `magic` | environment, not a defect |

**Nothing here is closable by an agent under this brief.** Every one needs a
protected file, a product decision, a corpus publication, or an infrastructure
call — **and the one that is technically available (the waiver) is the one the
brief forbids.**

---

## RECONCILIATION — which rows of the FROZEN branch this supersedes

`ptmo/main-red-triage-v11166` is frozen at `88cf416b6` and **cannot be updated**.
Its section C is correct as of `a00f53f20`. **Read this table alongside it**; where
they disagree, this document is later and says why.

> **THE FINAL GROUPING IS PART 17. THIS TABLE DOES NOT REPEAT IT — DELIBERATELY.**
> The rows below map frozen-branch rows to what CHANGED, and the two marked
> `-> Part 17` moved again after being written. **This table has gone stale twice
> from appending, in a document whose own finding is that appending does exactly
> that.** Rather than patch it a third time, the counts now DELEGATE to Part 17
> instead of duplicating it: *anchor, do not chase.* If a row and Part 17
> disagree, **Part 17 wins**, and this note is the reason.

| frozen section C row | status on `a4caccefe` |
|---|---|
| **3** — `flow_gate_enforcement_audit` exits 1 on two undeclared gates | **CLOSED.** The audit exits 0, both gates declare `ENFORCEMENT`, declared intent 41 → 44. **The decision it asked for was made** (Part 2) |
| **3** — 63x8 remainder | **CHANGED TWICE — see Part 17 for the count.** The in-file-interaction test is GREEN upstream (Part 1), and the remainder shrank again when the last red proved downstream of D3 (Part 17). |
| **5** — the vacuity conditional | **unchanged, but the DECISION has moved** — see Part 3: the question is now about a gate program's disclosure channel, not the flow's tiering logic |
| **16** — the corpus/record situation | **CHANGED TWICE — see Part 17 for the count.** Split once when the ledger three proved red BY DESIGN rather than downstream (Part 16), and again when a third 63x8 red proved downstream of D3 (Part 17). |
| **6** — landing-verdict | **unchanged**, and the arithmetic re-confirms the frozen branch's own count exactly |
| **1** — `magic` | **unchanged** (environment) |

**Net: 34 → 30 open.** Nothing in the frozen branch became WRONG; four items became
DONE, three of them by a decision it requested.

## Why this exists

The census in `ptmo/main-red-triage-v11166` (frozen at `88cf416b6`) was measured
against **`a00f53f20`**. Main is now **`a4caccefe`** — **244 commits later**, and
some of them touch the very files the census measures. **A census is a statement
about a tree, and the tree moved.** This re-measures it so the frozen branch's
findings can be trusted or discounted by name rather than by age.

Measured on a CLEAN checkout of `a4caccefe` (none of the frozen branch's changes
present), `VIBE_IC_BENCHMARK_DATA` set — without it 61 D3 cells report nothing.

    24 failed, 257 passed, 2 xfailed   (965s)

## Result: the census holds, with ONE item fixed upstream

| file | census @ a00f53f20 | main @ a4caccefe | verdict |
|---|--:|--:|---|
| `test_matrix_d3_outputs_produced.py` | 11 | **11** | **unchanged** |
| `test_matrix_63x8_coverage.py` | 5 | **4** | **one FIXED upstream** |
| `test_landing_merge_verdict.py` | 6 *(with the frozen branch's fixes)* | **9** | **accounting closes exactly** |

### The landing-verdict arithmetic, which is the real check

    current main                                    9
      − 4  closed by the frozen branch (design A + the 3 design-C tamper guards)
      + 1  ADDED deliberately: post_bootstrap_equal_corpus_uses_ordinary_delta
      = 6  the frozen branch's measured six                        ✓

**That `+1` is not a regression — it is the frozen branch's section B**, which
asks for exactly one decision: the test passes on main only because it reads
`delta.get("corpus_transitions", [])`, and the key is ABSENT. The change demands
the key, so a silent pass becomes a loud failure. **Main's green there is
vacuous, and this measurement is independent evidence of it: the test passes at
`a4caccefe` while the producer still never runs.**

### The one fixed upstream

`test_nested_outcome_run_outlives_old_fixed_bound_with_semantic_progress` — red
in the census, **GREEN on current main.** The frozen branch had diagnosed it as
**deterministic in-file interaction, not a flake** (3/3 pass in isolation, fails
in-file across two independent runs). The upstream commits describe the same
shape from the other side:

> *"the renewal test slept for exactly the window it was renewing, so its green
> was scheduler jitter and its red was blamed on the host"*
> *"red 10 was the same disease as red 12 all along — killed BETWEEN collections,
> and I had filed it as weather"*

**Independent agreement on a diagnosis is worth more than either measurement
alone**, and it is the one item in the census that can now be struck.

## What this means for the frozen branch

* **21 of the 22 reds** the census records in these three files **still exist on
  current main.** The findings are not stale.
* **The one that moved, moved to GREEN**, and its cause was independently
  confirmed rather than contradicted.
* **The D3 eleven are untouched by 244 commits** — consistent with the census's
  conclusion that they need a corpus/record decision, which no amount of ordinary
  landing work will supply.

## What was NOT measured here

The other 12 reds of the 34 (the BOTH-bucket files: flow-gate audit, vacuity,
mutation ledger, magic). **They were not re-run against `a4caccefe`**, so their
status on current main is UNKNOWN rather than assumed unchanged. Naming that
because a census that quietly re-uses old numbers for the parts nobody re-ran is
the exact defect the frozen branch spent its length cataloguing.

---

# Part 2 — the remaining 12, now measured. **Three are CLOSED upstream.**

Part 1 said the other 12 reds were NOT re-run and their status was UNKNOWN. Run
now, same clean checkout of `a4caccefe`, same corpus pointer:

    9 failed, 256 passed   (332s)

| file | census | main @ a4caccefe |
|---|--:|--:|
| `test_matrix_mutation_ledger.py` | 3 | 3 |
| `test_issue901_structured_vacuity...py` | 3 | 3 |
| `test_v0_2_96_issue460_coverage_bridge.py` | 2 | 2 |
| `test_digital_hardmacro_gen.py` (`magic`) | 1 | 1 |
| `test_organic900_901_ratchet_and_json_vacuity.py` | 1 | **0** |
| `test_issue490_drc_report_check_argv.py` | 1 | **0** |
| `test_issue306_register_paydown.py` | 1 | **0** |

**The three that closed are exactly the three the census attributed to
`flow_gate_enforcement_audit` exiting 1.** Not a coincidence and not an
inference — verified directly:

    flow_gate_enforcement_audit.py   ->  exit 0   (was 1)
    declared intent                  ->  44       (was 41)
    [PASS] no NEW enforcement contradiction
    area_total_vs_budget_check       ->  declares ENFORCEMENT
    tapeout_docs_gen                 ->  declares ENFORCEMENT

**THE DECISION THE CENSUS ASKED FOR HAS BEEN MADE — and made better than either
option I offered.**

The census (M80) argued that `advisory` was the wrong answer for
`area_total_vs_budget_check`, because a gate written *because nothing read the
area number* would then be declaring that the number still need not be read. The
options I named were **wire it**, or **declare `blocking` and stay red until
wired**.

The author chose `advisory` **and removed the implication I objected to**, by
scoping the token in the declaration itself:

> *"ENFORCEMENT: advisory — no runner spawns this gate inline, so its exit status
> cannot stop step 9 while step 9 is running. **That is the ONLY axis this token
> names** and the one `flow_gate_enforcement_audit` measures. The other two axes
> are [...]"*

**My objection was to what `advisory` would IMPLY. The fix was to delete the
implication, not the value** — a third option, and a better one than either of
mine. **The census's analysis was right about the hazard and wrong about the
remedy space**, which is the same shape as its "publish a run tree" error: the
diagnosis held and the list of available moves was too short.

## Revised standing of the 34

    11  D3 cells                     unchanged on current main
     6  landing-verdict              confirmed, accounting closes exactly
     4  63x8 coverage                one FIXED upstream (was 5)
     3  flow-gate audit              **CLOSED UPSTREAM** — decision made
     5  vacuity conditional          unchanged
     3  mutation ledger              unchanged — but RE-GROUPED in Part 16: red BY
                                      DESIGN (frozen `applies_to`), not downstream of D3
     1  magic                        unchanged
    ---
    30 of the 34 still stand on `a4caccefe`; **4 are closed**, 3 of them by a
    decision the census asked for and one by an independent fix that agreed with
    the census's diagnosis.

---

# Part 3 — a THIRD path for the 5-red vacuity decision, and why it is unreachable today

Twice now the census's remedy-list was too short (the flow-gate token; "publish a
run tree"). **So I went looking for a third option on the largest remaining
decision — the vacuity conditional that owns 5 reds — instead of restating the two
I had.**

**THE MACHINERY FOR A THIRD OPTION ALREADY EXISTS**, at
`flow_compliance_check.py:10168`, and its comment states the design intent
exactly:

> *"the tier is a per-STEP word and a partially vacuous step has no such word:
> some of its clauses examined the design and some examined nothing. **Both facts
> are true and one label can carry only one.** Whichever tier resolved above, the
> clauses that disclosed emptiness [...] are named HERE [...] **rather than being
> dropped for failing to be unanimous.**"*

```python
if result.status != "VACUOUS_PASS" and json_vacuous_hints:
    result.partial_vacuity_disclosed = True
```

**That is precisely what the five failing tests want**: resolve the waiver AND
disclose the vacuity, rather than choosing between them.

**AND IT IS UNREACHABLE FOR STEP 4. MEASURED, not reasoned:**

| | |
|---|---|
| Step 4's vacuity arrives on the **LEGACY** channel | `_VACUOUS_HINT_PREFIX`, branch at `:10120` |
| the disclosure requires the **STRUCTURED** channel | `json_vacuous_hints`, `_JSON_VACUOUS_HINT_PREFIX` |
| and it is guarded on | `status != "VACUOUS_PASS"` — which the legacy branch has just set |

**So M46's standing warning is CONFIRMED, and now has a mechanism rather than an
instinct.** Dropping `and not vacuous_hints` from the waiver condition would
resolve Step 4 as WAIVED **and lose the vacuity entirely**, because
`partial_vacuity_disclosed` does not fire for legacy-channel emptiness. The guard
is the only thing carrying that fact.

**THE THIRD PATH, stated as a candidate and NOT as a recommendation:** have
`professional_tb_check` disclose through the STRUCTURED channel — its `--json`
report — rather than (or as well as) the legacy one. `_json_report_signals_vacuous`
reads that file, and the hint is *"recorded unconditionally alongside whatever the
legacy channels say"*. If Step 4's emptiness arrived that way, the waiver branch
could resolve and the disclosure would fire on its own.

**WHAT I HAVE NOT ESTABLISHED, and it is the load-bearing half:** whether the two
channels are semantically interchangeable. The legacy hint appears to say *the
GATE was vacuous*; the JSON hint says *this CLAUSE disclosed emptiness*. **Those
may not be the same claim**, and `professional_tb_check.py` is NOT protected — so
this is a change someone could make quickly and wrongly. **I am naming the path,
the mechanism, and the exact reason it is blocked today. I am not recommending
it**, because I did not measure whether the swap preserves what the legacy channel
means.

**What this changes for the owner:** the decision is no longer "should `:10057`
decline the waiver branch". It is **"should Step 4's emptiness be disclosed on the
structured channel, which would make the conditional moot"** — a question about a
gate program, not about the flow's tiering logic.

---

# Part 4 — the frozen branch's ONLY program change, re-characterised against current main

`hdl_declaration_scan_strips_comments_check.py` is the one file in
`ptmo/main-red-triage-v11166` that is a PROGRAM rather than a test, doc or
fixture. **Its value proposition has changed, and the batch should know before it
lands.**

**On the frozen branch's base (`a00f53f20`):** the gate FAILED. 175 sites against
a 170 baseline, a BLOCKING list of 5 names of which 2 were verified false
positives. The fix closed a red.

**On current main (`a4caccefe`) — measured:**

    current main's analyser on current main :  170  (baseline 170)  -> exit 0, PASSES
    MY analyser             on current main :  165
    false positives removed                 :    5
    newly flagged                           :    0

**THE GATE ALREADY PASSES. The fix no longer closes a red.**

**What it still is, stated exactly:**

* a **precision fix** — it removes 5 verified false positives and flags nothing
  new. Two of that class were checked in source on the frozen branch
  (`slot_pad_budget_check` strips on its first two lines;
  `memory_read_pipeline_check` reaches its scan through a for-target chain).
* **5 regression tests**, of which 4 go red when the analyser is reverted — pure
  additions, and the suite had NO coverage for this before (11 tests passed
  identically with and without the fix).
* **NOT redundant.** Current main's `stripped_locals` contains **zero**
  occurrences of `ast.For` or `comprehension`, and the 244 commits **never touched
  this file** — so there is no conflict and no independent fix.

**ONE CONSEQUENCE A LANDER MUST DECIDE:** applying it takes the population
**170 → 165**, which is BELOW the recorded baseline. The gate treats a shrink as a
`[NOTE] baseline shrank by 5. Re-run with --write-baseline.` — **a note, not a
failure**, so it still exits 0. **The frozen branch declined to write that
baseline and still does** (standing instruction: never `--write-baseline`, including
when the gate asks). **Re-recording it is the lander's call, and it is now the only
action this change requires.**

**Why the count moved from 175 to 170 without anyone fixing the analyser:** other
work removed or rewrote 5 of the scan sites. **That is worth noticing rather than
waving at — a gate whose population drifts by 5 in 244 commits is measuring a
moving subject, and its baseline is a pin in sand.** The frozen branch's M54
argument about the liar census — that a hand-maintained number an author must
remember is *"prose wearing an assertion"* — applies here with the same force, and
neither gate has had that cure.

---

# Part 5 — the frozen branch MERGES CLEANLY onto current main, and the merged tree was RUN

The freeze exists because a batch that keeps absorbing changes never lands. **The
question that actually decides whether this branch costs the batch anything is
whether it merges and behaves** — asked and answered here rather than left for the
lander to discover.

**MERGE — clean, in a throwaway worktree at `origin/main` (`a4caccefe`):**

    git merge --no-commit --no-ff ptmo/main-red-triage-v11166   ->  exit 0
    conflicted files                                            ->  NONE
    result vs current main    11 files, 9819 insertions, 50 deletions

**That is exactly the frozen branch's own stat.** The merge added nothing and lost
nothing; two files auto-merged (`test_pad_and_seal_ring...`, `matrix_d3_output_manifest.json`)
and both produced the branch's own line counts.

**A CLEAN MERGE IS NOT A WORKING TREE, so the merged tree was run:**

| suite, on the MERGED tree | result |
|---|---|
| `test_hdl_declaration_scan_strips_comments` | **16 passed** (11 existing + the 5 added) |
| `test_pad_and_seal_ring_on_the_chip_path` | **46 passed** |
| `test_hermetic_candidate_runner` | **17 passed** |
| `hdl_declaration_scan_..._check.py` (the gate) | **exit 0** — `165 (baseline 170)`, `[NOTE] baseline shrank by 5` |
| `test_landing_merge_verdict` | **6 failed, 128 passed** — **failing set IDENTICAL to the frozen branch's six** |

**Every prediction in Part 4 held on the real merged tree**, including the
`[NOTE]` about the shrunk baseline — which remains the single action this change
asks of a lander.

**What this settles for the batch:** the frozen branch is **244 commits behind and
still merges clean**, and the merged tree measures exactly what the branch
measured in isolation. **It does not need a rebase to land, and it does not change
any number it reports once landed.** If it is dropped from this batch it is for
sequencing, not for cost.

**Verified by running, not by `merge --no-commit` exiting 0** — an automatic merge
succeeding is a statement about text, and every claim this branch makes is about
behaviour. The worktree was removed afterwards; nothing in play was touched.

---

# Part 6 — FOUR of the census's five requests have been answered upstream

Part 2 found the flow-gate decision made. **I checked whether that was the only
one. It was not.**

| census request | status on `a4caccefe` |
|---|---|
| declare intent on the two undeclared flow gates | **DONE** (Part 2) — and solved by a third option better than either the census offered |
| wire `closed_loop_edge_check` | **DONE** — `repo_hygiene_gates.sh:1637`, `run "closed-loop edges resolve" ...` |
| wire `slot_pad_budget_check` | **DONE** — flow yaml `:1118`, `program_exit_zero: "slot_pad_budget_check . --json ..."` |
| the liar-census pin | **BUMPED** 179 → 181, with a partial cure attached |
| wire `ppa_pr_scope_check` | **still unwired** — 0 occurrences anywhere |

**THE TWO PLACEMENTS LANDED WHERE THE CENSUS PREDICTED, and the prediction was
not a guess.** M88 derived both from a rule `repo_hygiene_gates.sh` states about
itself — *"its subject is the shipped flow document [...] a repo-wide invariant
needing no PR context and no design run"*:

* `closed_loop_edge_check` — subject is the flow's `closed_loop:` blocks, no PR
  context, no run → **hygiene**. It landed in hygiene.
* `slot_pad_budget_check` — needs a design run → **a flow clause on the chip
  path**. It landed as a flow `program_exit_zero` clause.
* `ppa_pr_scope_check` — needs PR context, so the rule EXCLUDES it from hygiene.
  **It is the one still unwired**, which is consistent: it is the one with no home
  the stated rule can give it.

**The credit belongs to the rule, not the reading.** The census's contribution was
noticing that the file already answered the question; anyone who read the same
paragraph would have placed them the same way.

**THE LIAR CENSUS IS THE INTERESTING ONE, because the census said "do not bump"
and it was bumped.** M54 argued the literal was *"prose wearing an assertion"* and
a fifth bump would repeat the defect. What landed is a bump **plus** the beginning
of the cure, with the open question preserved verbatim:

> *"how a DELIBERATE shrink is authorised — is still the flow owner's to answer,
> and is deliberately NOT answered here. What is fixed is that the next author can
> MEASURE the delta against the tree they are landing on instead of reconstructing
> it by hand from a base that may have moved."*

**That is a better outcome than either "bump it" or "do not bump it".** The number
still needs remembering, but the DELTA no longer needs reconstructing — which is
the half of the problem that was costing measurement rounds. **The census was right
that a bare bump was the wrong move and wrong that the only alternative was a full
derivation.** Third time on this branch that the remedy space was larger than the
two options I could see.

---

# Part 7 — the LAST open request, and my move-list was too short a fourth time

`ppa_pr_scope_check` is the one census request still unanswered upstream. **M88
called it "the only one of the three the repo does not already answer" and sent it
to "a PR-context runner" — a venue I could not point at.** Checked, and that was
wrong.

**IT DOES NOT NEED A FORGE PR. Its own docstring says what it needs:**

> *"It decides WHICH questions apply, **from the change-set itself**."*

And its interface takes refs, not a PR number:

    --repo  --base <git ref>  --head <git ref>  --changed-file  --diff-file
    --answers  --catalogue  --json

**"PR" in the name is the REVIEW CHECKLIST it automates, not a forge dependency.**
I read the word and inferred the dependency.

**THE VENUE EXISTS AND IS NOT HYPOTHETICAL.** `gatekeeper-verify-merge.sh`
computes exactly the pair this program takes:

    BASE_SHA="$("${G[@]}" rev-parse "$BASE")"            :945
    HEAD_SHA=...                                          on BOTH the --pr and --ref paths

**So the answer is the merge verifier, not "a PR-context runner somewhere".**
The verifier is where change-set-scoped checks belong, and it already resolves the
change-set on every landing, PR or not.

**M88's RULE still holds; my APPLICATION of it did not.** The hygiene criterion is
*"a repo-wide invariant needing no PR context and no design run"*, and a
change-set IS context hygiene does not have — so excluding it from hygiene was
right. **What was wrong was concluding that the remaining venue was
hypothetical.** It is `gatekeeper-verify-merge.sh`, which is PROTECTED — so this
joins the other protected-file asks rather than being the one homeless item.

**FOURTH TIME on this branch that the remedy space was larger than the two options
I could see** — after the flow-gate token, "publish a run tree", and the liar
census. **The pattern is now consistent enough to state as a finding about the
method rather than about any one item: when I could see exactly two options, the
real answer was outside both, four times out of four.**

---

# Part 8 — the D3 group's THIRD remedy, checked at last: available to me, and FORBIDDEN to me

Having just recorded that a two-option list means the third was not found, I
applied it to the largest group. **The D3 test names THREE remedies and I had only
ever examined two:**

> *"Close it by **re-pointing the record** at a root that carries the artefact, by
> **publishing a run tree** that does, or by **waiving the cell through the one
> waiver registry with the disclosure** — never by widening the skip."*

* **publish** — refuted (Part 1 / M105): `home` roots are excluded by
  `_ADMISSIBILITY` on purpose, so publishing anywhere leaves them untouched.
* **re-point** — what the census recommends.
* **waive** — **never examined until now.**

**MEASURED:**

    matrix_63x8/waivers.py                     NOT protected
    test_d3_waivers_meet_the_registry_bar      asserts a shared VALIDATOR passes,
                                               "not by hope"

**So the third remedy is the only one of the three I could physically perform** —
the other two need data or records I do not own, and this one is an unprotected
file with a validator that would catch a malformed entry.

**AND IT IS THE ONE THE BRIEF EXPLICITLY FORBIDS.** The standing constraint is
*"never weaken a predicate, **widen a waiver**, or edit a fixture to suit"*, and
the test's own line ends *"never by widening the skip"*. **A waiver here would make
16 reds disappear without any of them being answered.**

**That is a THIRD category, distinct from the two this document keeps
distinguishing.** It is not *blocked* (I can do it) and not *out of scope* (it is
squarely a test-registry edit). **It is available, effective, and prohibited** —
and the prohibition is the entire reason the census has value. A triage that may
waive its own findings is not a triage.

**Recorded because the owner is not bound by my brief.** Waiving with disclosure
is a legitimate move for whoever owns the corpus decision, and the registry is
built to make it a recorded, validated act rather than a quiet one. **They should
know it is on the table; I should not be the one to put it there.**

**This closes the survey: all three named remedies for the 16-red group are now
examined**, one refuted by measurement, one recommended, one available-and-declined.

---

# Part 9 — the 4 corpus/bootstrap reds: the ask was ONE option, and it is smaller than it looked

Part 8 applied the "two options means you have not found the third" rule to the
16-red group. **The 4 corpus/bootstrap reds had it worse: I gave ONE option** —
*"someone who understands the trusted-parent-evidence protocol must decide whether
a fixture can satisfy it"* — which is not a remedy list, it is a shrug with a job
title attached.

**Narrowed by reading the check instead of naming the protocol.**

The blocker is `benchmark_data_landing_checkout.py:161`, and it is one command:

```python
proc = _git(checkout, "remote", "get-url", "--all", "origin")
urls = proc.stdout.splitlines() if proc.returncode == 0 else []
if urls != [expected]:
    got = urls if urls else ["<missing or unreadable>"]
    raise Refusal(f"origin must be exactly {expected!r}; observed {got!r}")
```

**The observed value was `['<missing or unreadable>']`, which is the EMPTY case** —
so `git remote get-url --all origin` returned NON-ZERO on `$BENCHMARK_B2`. **Not a
mismatched URL. No origin readable at all.**

**And `$BENCHMARK_B2` is a git WORKTREE**, not a clone —
`gatekeeper-verify-merge.sh:884` removes it with `git worktree remove`. A worktree
reads its remotes from the parent's shared config, so `origin` should resolve.

**So the ask is no longer "understand the protocol". It is: why does
`git remote get-url --all origin` fail on `$BENCHMARK_B2` at the moment the
trusted-parent-evidence step re-validates it?** That is a question with a
one-command reproduction, not a design review.

**What I did NOT establish**, and it is the half that decides who can act: whether
the worktree is absent at that instant, whether the fixture's parent checkout lacks
the remote, or whether the enumeration step disturbs it. **Three candidates, none
measured** — and I am naming them as candidates rather than picking the one that
would make my earlier framing look best.

**The value of the narrowing is who it hands the work to.** "Understand the
trusted-parent-evidence protocol" needs the protocol's owner. **"Find why one git
command returns non-zero on a worktree" needs anyone who can run it** — and the
reproduction is the sentinel fixture already built and reverted on the frozen
branch.

---

# Part 10 — one of Part 9's three candidates is now the leading one, by a controlled test

Part 9 named three candidates for why `git remote get-url --all origin` returns
non-zero on `$BENCHMARK_B2`, and measured none. **Two of the three are now
testable without the fixture, because they are claims about git rather than about
this repo.**

**Controlled test** — a bare remote, a clone, a worktree of that clone:

    clone's origin                       -> /tmp/.../remote.git   rc=0
    WORKTREE's origin                    -> /tmp/.../remote.git   rc=0
    same command after `worktree remove` -> "cannot change to ...: No such file
                                            or directory"          rc!=0, stdout EMPTY

**A worktree DOES inherit its parent's origin.** So *"the fixture's parent
checkout lacks the remote"* and *"the enumeration disturbs the config"* both
predict a WRONG URL or a readable one — **neither produces the empty case.**

**An ABSENT PATH produces the empty case, and `_origin` renders empty as exactly
the string that was observed:**

```python
urls = proc.stdout.splitlines() if proc.returncode == 0 else []
got = urls if urls else ["<missing or unreadable>"]
```

**So the leading candidate is that `$BENCHMARK_B2` is NOT THERE when the
trusted-parent-evidence step re-validates it** — not that its config is wrong.

**What this does NOT establish**, and the distinction matters: I have shown that
an absent path produces the observed string. **I have NOT shown that the path was
absent in that run** — a broken-but-present worktree could conceivably produce it
too. **This raises one candidate above the others; it does not close the
question.**

**And it is cheap to close.** One line of instrumentation — `ls -d "$BENCHMARK_B2"`
immediately before the re-validation — settles it. **That is a different order of
work from "understand the trusted-parent-evidence protocol", which is where this
item stood two commits ago.**

**Note on the instrument:** the controlled test failed TWICE for setup reasons
before it ran — an empty commit left the clone with no checkout, then the bare
remote's default `HEAD` pointed at `master` while the push created `main`. **Both
failures looked like results.** The fixture in this repo does
`symbolic-ref HEAD refs/heads/main` for exactly that reason, and copying what the
repo already does is what made the test work.

---

# Part 11 — CLOSED. The blocker is a structural incompatibility, not a fixture I got wrong

Parts 9 and 10 narrowed the 4 corpus/bootstrap reds from *"a protocol judgement"*
to *"why does one git command return non-zero"*, and raised "the path is absent"
as the leading candidate. **The candidate is wrong and the real answer is
better.** Traced end to end, entirely by reading:

| step | evidence |
|---|---|
| `build_trusted_transition_evidence` calls `validate_benchmark_snapshot "$BENCHMARK_B2"` | `:806` |
| which runs `benchmark_data_landing_checkout.py validate --checkout ...` | `:340-345` |
| whose `_inspect` calls `_origin` **unconditionally** | `:324` |
| `_origin` requires `git remote get-url --all origin` == the expected URL | `:155-161` |
| `$BENCHMARK_B2` is built by `materialize_hermetic_git_subject` | `:1237`, before the call at `:1378` |
| which runs `hermetic_git_subject.py` — **`git init`, and ZERO remote-configuring lines** | `:206`; grep count 0 |

**`$BENCHMARK_B2` EXISTS. It has no `origin` BY CONSTRUCTION.** An object-exact
hermetic subject is `git init`-ed from objects — it is not a clone and not a
worktree, and its own docstring says so. **The origin check expects a clone. The
two cannot both be satisfied.**

`['<missing or unreadable>']` is not a symptom of a missing directory or a broken
fixture. **It is `git remote get-url` returning non-zero on a repository that was
deliberately built without remotes.**

**WHY THIS WAS LATENT.** `build_trusted_transition_evidence` runs only on the
routed-transition path — the path gated by an env knob that cannot cross into the
arm since the hermetic migration. **Nothing had executed it. M92's sentinel made
it run for the first time, and this is what it found.**

**So the ask for these 4 reds changes shape completely:**

* **NOT** *"judge whether a fixture can satisfy the trusted-parent-evidence
  protocol"* — the fixture is not the subject.
* **IT IS:** the origin check and the hermetic subject materialisation are
  **incompatible by construction**, and one of them must give — either the check
  is not the right check for a hermetic subject, or hermetic subjects need a
  recorded origin. **Both files are PROTECTED**, so it is the same owner's call,
  but it is now a two-line question rather than an open-ended review.

**WHAT I HAVE NOT ESTABLISHED:** whether this path ever passed. If it did,
something about the materialisation or the check changed and the history would
name it; if it never did, the routed-transition evidence has never been produced
under the hermetic runner at all. **I did not measure that, and it decides whether
this is a regression or a gap that shipped.**

**The sentinel that was built and reverted paid for itself here.** It did not hit
"a fixture I got wrong"; **it exposed an incompatibility that no test has reached
since the migration**, and the only reason it looked like my fixture's fault is
that mine was the first run to get that far.

---

# Part 12 — a GAP THAT SHIPPED, not a regression; and the check is right for one caller and impossible for the other

Part 11 left one thing open: **has the routed-transition path ever passed?** It
decides whether this is a regression or a gap. **Answered from history.**

**All FOUR components arrived in the SAME commit:**

    7c376e348  feat(landing): activate the semantic landing runtime [v1.10.69]
               2026-08-18 22:28:49 +0800

      benchmark_data_landing_checkout.py   the origin check
      hermetic_git_subject.py              the no-remotes materialisation
      build_trusted_transition_evidence    the caller
      GATEKEEPER_STUB_ROUTED_TRANSITION    the env knob gating the only test

**So it is a GAP THAT SHIPPED, not a regression.** Nothing changed under the
check; the incompatible pair landed together — **complete with the test that would
have caught it, gated behind an env knob the same architecture prevents from
crossing.** The commit introduced the defect, the detector, and the reason the
detector cannot fire, in one act.

**AND THE CHECK IS NOT WRONG — IT IS RIGHT FOR THE OTHER CALLER.** The program is
used two ways, and only one of them can satisfy an origin requirement:

| call | checkout | has an origin? |
|---|---|---|
| `measure` — `:662` | `$configured`, the operator's real benchmark-data **CLONE** | **yes.** The check is correct and load-bearing here |
| `validate` — `:806` | `$BENCHMARK_B2`, a **`git init`-ed hermetic subject** | **no, by construction** |

`validate_benchmark_snapshot` has **exactly one call site**, and it is the
hermetic one. **So the validate path can never pass, and the measure path needs
the check it shares.**

**That is why the remedy is not "delete the origin check".** It is correct where it
runs on a clone. **What is wrong is applying a clone-shaped invariant to a subject
built from objects** — and the fix is a distinction the program does not currently
draw, not a deletion.

**This closes the 4 corpus/bootstrap reds as a DIAGNOSIS**, at a level a
protected-file owner can act on in one sitting:

* not *"understand the trusted-parent-evidence protocol"* (Part 9),
* not *"a fixture I got wrong"* (Part 11),
* but **"`validate` requires an origin that its only caller's subject cannot have,
  and both shipped together in `7c376e348`."**

**What remains unmeasured, and it is small:** whether `measure`'s origin check and
`validate`'s can be separated without weakening the first. That is a design
question for the owner of two protected files — and it is the whole of what is
left on this item.

---

# Part 13 — the anti-skip finding HOLDS, and the skip it objects to was a REVIEWED, NARROWED decision

**Re-checked on current main: unchanged.** `test_every_na_cell_asserts_a_live_precondition`
still flags exactly `d3:2309` and `d7:375` — **same lines after 244 commits**, so
the census's M102–M104 finding stands without amendment.

**But the census framed the skip as an oversight, and it was not.** It landed in

    c8c2ab0f7  test: apply the corpus-absent skip only where it is MEASURED to be needed
               2026-08-16

whose body shows its author had already reasoned about the exact hazard the census
attributed to them:

> *"CAUSE 2, REAL: the marker was over-applied. 19 tests carried `@needs_corpus`
> that were not in the introduced-failure set — **a green test switched off is
> exactly the failure mode the review exists to catch**, and it happened."*

**They named the hazard, measured where the skip was actually needed, narrowed it
to those sites, and had the result adversarially reviewed.** The census's
characterisation — that the skip "re-introduces the host-dependence #527 removed"
— is true of its EFFECT and unfair about its ORIGIN.

**So this is a disagreement between two careful positions, not a defect:**

| position | rule |
|---|---|
| the skip's author | apply a corpus-absent skip **only where it is measured to be needed** |
| the anti-skip gate | a **cell test** may not skip at all — the three states are ENFORCED, WAIVED, NA |

**Both are defensible and they are incompatible on exactly these two call sites.**
M104's conclusion still follows from the gate's rule — if no skip is legal in a
cell test and no host-premise NA or WAIVED is legal either, ENFORCED is what
remains, and the corpus stops being optional. **What the census got wrong was
implying nobody had thought about it.**

**Worth stating because it is the second time in this document that reading the
commit changed the finding's tone rather than its content** (the first was the
flow-gate token, where the author answered an objection I had framed as a binary).
**A red line and a considered decision look identical from the outside; the
difference is one `git log -1` away, and the census took the shortcut both times.**

---

# Part 14 — the vacuity guard is not a wrong decision. It is an OLD one that a later change made half-unnecessary

Part 13 named the shortcut: *a red line and a considered decision look identical
from the outside, and the difference is one `git log` away.* **Applied to the
5-red vacuity item, which the census has characterised three times without ever
reading the guard's origin.**

**MEASURED — the two halves are two months apart:**

    and not vacuous_hints        2026-06-14   v1.0.38, #651
                                              "PASS_WITH_WAIVERS distinct rc 3 + waivers.json"
    partial_vacuity_disclosed    2026-08-11   #901
                                              "count the clauses that RAN, so a structured
                                               NOT_APPLICABLE reaches the step tier"

**In June, one label had to carry one fact**, so the waiver branch was written to
stand down when a vacuous hint was present. **That was correct: there was no way to
say "waived, and partially vacuous".**

**In August, #901 BUILT that way** — and its own comment says exactly why:

> *"a partially vacuous step has no such word: some of its clauses examined the
> design and some examined nothing. **Both facts are true and one label can carry
> only one.** [...] named HERE [...] rather than being dropped for failing to be
> unanimous."*

**But #901's disclosure covers the STRUCTURED channel only** (`json_vacuous_hints`),
**and the June guard was never revisited for the LEGACY one.** Step 4's emptiness
arrives on the legacy channel, so it still falls under the June rule, in a codebase
that has since built the August answer.

**So the item's real shape, at last:**

* not *"the fixture drifted"* (the census's first reading),
* not *"one decision: should `:10057` decline the waiver branch"* (its second),
* not *"switch `professional_tb_check` to the structured channel"* (its third,
  Part 3 — that is a consequence, not the question),
* **but: `#901` built the disclose-both machinery two months after the guard that
  exists because it did not. Should the guard be revisited now that the machinery
  exists?**

**That is a question with an answer already half-written in the repository**, and
it is the fourth time on this branch that reading the history turned an
"open decision" into "someone already solved most of this, in a place I had not
looked".

**What I have NOT established:** whether the legacy channel can carry a structured
disclosure at all, or whether #901 deliberately scoped itself to the JSON channel.
**Its title — "so a structured NOT_APPLICABLE reaches the step tier" — suggests
deliberate scope**, which would make the remaining gap intentional rather than
overlooked. **I am not guessing which; the commit body would say, and the owner
will know without reading it.**

---

# Part 15 — the 5-red vacuity item, ROOT-CAUSED: #901 diagnosed this mis-fire and fixed it for one channel only

Part 14 stopped one command short, saying *"the commit body would say."* **Read it.
It says something better than expected: `#901` diagnosed EXACTLY this defect, in
prose, and fixed it for the channel it was adding.**

**From `13b34a78a` (#901), the author's own words:**

> *"The tier branch is `passed and vacuous_hints and not non_hint_reasons` while
> its own docstring says it means **"EVERY executed sub-gate was vacuously
> satisfied"** — and a clause that passes SUBSTANTIVELY appends nothing, so
> silence and vacuity are indistinguishable to it and **1-of-10 reads as
> "every"**. That is the mis-fire."*

**AND THE MIS-FIRE IS STILL THERE, FIRST IN THE CHAIN:**

    10120|  elif passed and vacuous_hints and not non_hint_reasons and not skip_hints:
            ^^^ LEGACY channel, NO COUNT            <- evaluated FIRST
    10130|  elif passed and structure_only_hints ...
    10134|  elif (passed and json_vacuous_hints and not non_hint_reasons
                  and len(all_vacuous_cmds) >= len(ran_hints)):
            ^^^ STRUCTURED channel, COUNTED         <- #901's fix, never reached

**#901 added the counted branch for the channel it introduced and left the
uncounted legacy branch AHEAD of it.** A step whose emptiness arrives on the
legacy channel short-circuits to `VACUOUS_PASS` before the count is consulted.

**STEP 4 IS THAT STEP.** Its own failure text reads
**`2 of 6 gate clause(s) here examined nothing`** — four clauses examined
something — and it is nonetheless labelled *"every executed sub-gate was
vacuously satisfied."* **That is 1-of-10 at 2-of-6.**

**THIS EXPLAINS ALL FIVE TESTS, and it is not the guard I spent three sections
on:**

* the three that assert the step is NOT vacuous — **correct; it is mis-labelled**;
* the two that want `WAIVED-DEFERRED` — blocked by `and not vacuous_hints`, **but
  that guard is downstream**: it declines because the status is already
  `VACUOUS_PASS`, and the status is wrong.

**So the remedy is not "should `:10057` decline the waiver branch" (Part 3), nor
"revisit a June guard" (Part 14). It is: the legacy branch needs the same count
the structured branch already has** — and the repository has both the diagnosis
and the working implementation, twelve lines apart.

**What I have NOT established:** whether the legacy branch was left uncounted
deliberately. **#901 says the STEP-level half was deferred as an owner decision**
— *"Every shape of it measurably restates something the repo has already pinned,
and which of them to restate is an owner decision, not a reviewer's"* — so the
gap may be exactly that deferral, still open. **That is the question to put to the
owner, and it now comes with the fix already written next door.**

---

# Part 16 — reading the roots' commit CONFIRMS one census finding and CORRECTS another

Applied Part 13's lesson to the largest group. The `home`-kind roots trace to
`76c73b499 matrix(63x8): re-enumerated on clean main`, and its body settles two
things the census had reasoned about separately.

**CONFIRMED — the in-file-interaction diagnosis, with a mechanism the census did
not have.** The census measured
`test_nested_outcome_run_outlives_old_fixed_bound_with_semantic_progress` as 3/3
green in isolation and red in-file, and called it *"deterministic in-file
interaction, not a flake"*. The commit names the cause:

> *"[they] all die on a **WATCHDOG_STALLED** whose window is 0.25s / 0.45s / 60s,
> and they die **only inside a full-file run whose own nested pytest children
> saturate the box**. Re-run alone on the same tree at load 44.61: `4 passed`.
> **They are detecting the host, not the repo.**"*

**Same conclusion, arrived at independently, from opposite directions** — the
census from an isolation A/B, the commit from the watchdog windows. That is worth
more than either alone.

**CORRECTED — the 3 mutation-ledger reds are NOT "downstream of D3".** The census
(Part 6 / M108) folded them under the corpus root because the replay returned
`ALREADY_RED`. The commit states the actual cause:

> *"`0.5ic/d3` and `1.6x/d3` are ENFORCED with no mutation covering them —
> **`applies_to` is frozen by design, so a new step must redden this gate**"*

**They are red BY DESIGN.** `applies_to` is deliberately frozen so that adding a
step to the flow forces someone to measure and record a mutation for it. **The
gate is doing its job: two new steps arrived and nobody has measured their
mutation yet.**

**The census's `ALREADY_RED` measurement is still true and is a SECOND obstacle,
not the cause** — the mutation cannot be measured today because the d3 cell is red
at baseline. **So the chain is: frozen `applies_to` demands a measurement → the
measurement cannot be taken while d3 is red → the gate stays red.** Two links, and
the census had only the second.

**Revised grouping:** the 16-red "corpus/record" root becomes **13**, with the 3
mutation-ledger reds standing on their own as *"a designed demand for a
measurement that a second, unrelated red currently blocks"*.

**That is the fifth time reading a commit changed a census finding**, and the
second time it split a group the census had merged. **The census's error was
consistent in shape: it inferred causation from co-occurrence** — the ledger reds
and the D3 reds share a symptom, and I grouped on the symptom.

---

# Part 17 — the census is COMPLETE: every one of the 30 is named and caused

One red had never been individually diagnosed —
`test_every_cell_has_a_live_outcome_and_the_outcome_run_is_not_starved`. **Run
alone (157s), it fails with the SAME message as its two neighbours and names the
SAME two D3 reds:**

    the nested outcome run produced red test report(s) outside the matrix cell
    join [...] NORECORD:
      test_d3_evidence_is_live_wherever_the_run_root_exists
      test_d3_the_compliance_audit_does_not_create_declared_outputs

**So THREE 63x8 tests are downstream of TWO D3 reds, not two.** The grouping moves
once more, and this is the last time:

    14  corpus root      11 D3 + 3 nested-outcome (downstream), all one situation
     3  mutation ledger  red BY DESIGN — frozen `applies_to` demands a measurement
                         that the d3 red currently blocks (Part 16)
     6  landing-verdict  2 need one line (RUN_ID); 4 fully diagnosed (Part 12)
     5  vacuity          root-caused: the uncounted legacy branch at :10120 (Part 15)
     1  63x8 anti-skip   a considered disagreement between two rules (Part 13)
     1  magic            environment, not a defect
    ---
    30

**EVERY ONE OF THE 30 IS NOW NAMED, CAUSED, AND ATTRIBUTED TO SOMEONE WHO CAN ACT.**
Nothing is in the "red, cause unknown" state, and — unlike the frozen branch's
version of that claim — no group rests on inference from co-occurrence. **Each
downstream red names its upstream in its own failure text.**

**Three of the six groups were regrouped after reading a commit or running one
test alone.** The census's causes were right; **its GROUPING was wrong three times,
always in the same direction — merging on a shared symptom.** The corrective was
never cleverness. It was running one test by itself, or reading the commit that
wrote the line.

**What a lander should take from the whole exercise:** the frozen branch's
findings survive 244 commits, four of its five requests have been answered
upstream, and the remaining 30 reduce to **four decisions and two environment
facts** — of which one decision (the vacuity count) has its fix already written
twelve lines from the defect.

---

# Part 18 — two corrections: the counts WERE measured, and the 30 is not main's number

**FIRST, a correction in the unusual direction.** Part 17's commit said four counts
were *"safe because their causes are settled, not because I re-checked them"* —
**an admission of unverified reasoning, and it was false.** All four were measured
against `a4caccefe` in Parts 1–2 and the run outputs still hold them:

    vacuity   = issue901(3) + coverage_bridge(2)  =  5   MEASURED
    magic     = digital_hardmacro_gen             =  1   MEASURED
    flow-gate = organic900 + issue490 + issue306  =  0   MEASURED (closed)
    landing-verdict                               =  9   MEASURED

**Understating one's own evidence is still misreporting it.** This document has
corrected overclaims five times; this is the first correction in the other
direction, and it deserves the same treatment — **a claim about what was measured
is checkable either way.**

**SECOND, and more useful to a reader: the census total of 30 describes the FROZEN
BRANCH'S TREE, not current main.** The two differ by exactly the frozen branch's
own effect:

    landing-verdict on current main            9
      − 4  closed by the frozen branch (designs A and C)
      + 1  the deliberate green→red (section B)
      = 6  the census's figure

**So `a4caccefe` carries 33 of these reds, and the frozen branch's tree carries
30.** Every other group is identical on both trees; only landing-verdict moves,
because it is the only file the frozen branch changes that also holds census reds.

**Stated because "30 open" invites the reading "main has 30".** It does not.
**A reader deciding whether to land the frozen branch should know the number
already includes its effect** — the branch is not 30-reds-worth of remaining work,
it is what remains *after* the branch has done what it does.
