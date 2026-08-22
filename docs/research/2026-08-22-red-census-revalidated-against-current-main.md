# The v1.11.66 red census, re-measured against current main (244 commits later)

host 8hd-3 · 2026-08-22 · branch `next/red-census-vs-current-main`, cut from
`origin/main` at **a4caccefe**

## RECONCILIATION — which rows of the FROZEN branch this supersedes

`ptmo/main-red-triage-v11166` is frozen at `88cf416b6` and **cannot be updated**.
Its section C is correct as of `a00f53f20`. **Read this table alongside it**; where
they disagree, this document is later and says why.

| frozen section C row | status on `a4caccefe` |
|---|---|
| **3** — `flow_gate_enforcement_audit` exits 1 on two undeclared gates | **CLOSED.** The audit exits 0, both gates declare `ENFORCEMENT`, declared intent 41 → 44. **The decision it asked for was made** (Part 2) |
| **3** — 63x8 remainder (1 anti-skip, 1 in-file interaction, 1 shared) | **now 2.** The in-file-interaction test is GREEN upstream, its cause independently confirmed (Part 1) |
| **5** — the vacuity conditional | **unchanged, but the DECISION has moved** — see Part 3: the question is now about a gate program's disclosure channel, not the flow's tiering logic |
| **16** — the corpus/record situation | **unchanged.** 11 D3 + 3 ledger untouched by 244 commits |
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
     3  mutation ledger              unchanged
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
