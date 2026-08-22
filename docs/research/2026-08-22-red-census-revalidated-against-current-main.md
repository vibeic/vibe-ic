# The v1.11.66 red census, re-measured against current main (244 commits later)

host 8hd-3 · 2026-08-22 · branch `next/red-census-vs-current-main`, cut from
`origin/main` at **a4caccefe**

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
