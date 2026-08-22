# Census: what the two corpus gates find, and no longer look at

Owner ruling, 2026-08-22: *"A stands, take C now, and B becomes its own row. …
The six findings are real and they must not evaporate because the fix that made
the gates honest also made them quiet. File them as a census row … a census
records debt and changes nothing that blocks — the gate is the thing that
refuses, the census is the thing that remembers."*

**This file blocks nothing.** It is not wired into any gate and must never be.
It records debt so that a real improvement — vibe-ic#1710 — does not silently
cost coverage.

## WHY THIS EXISTS, IN ONE SENTENCE

**8HD-8 was accidentally getting real coverage from a tree nobody named.**

Before #1710, `l_doc_field_producer_check` and `evidence_citation_resolves_check`
resolved their corpus with an unbounded `Path.parents` walk that left the
checkout, ran into `$HOME`, and adopted whatever `benchmark-data/` it found
there. On a machine that had one they scanned it and reported real defects; on a
machine that did not they reported nothing. A gate that passed on one machine and
failed on another was never two verdicts about the code — it was one verdict
about the machines. #1710 bounds the walk at the repository root, so both gates
now return the same `NO_CORPUS` on every host, naming the path they looked for.

That is the right fix and it is not being undone. But the findings the accidental
scan was surfacing are real, and this is where they are kept until someone points
the gates at a corpus deliberately (the "B" row: *does EVERY landing host carry a
corpus checkout, and does the pointer resolve to the SAME tree on each?* — measure
before wiring, or B reintroduces host-dependence inverted).

## HOW THESE WERE MEASURED

Both gates, run deliberately against a named corpus rather than a discovered one:

```
cd vibe-ic-marketplace/plugins/vibe-ic
VIBE_IC_BENCHMARK_DATA=<a clone of vibeic/benchmark-data> \
  python3 programs/l_doc_field_producer_check.py       --corpus-may-be-absent   # rc 1
VIBE_IC_BENCHMARK_DATA=<same clone> \
  python3 programs/evidence_citation_resolves_check.py --corpus-may-be-absent   # rc 1
```

Corpus used: `vibeic/benchmark-data` at `146d6656`. Population as the gates
report it: **48 L-doc(s)**, **149 contributing document(s)** of 1037 files.

## FINDING 1 — three declared fields that NO document populates

`l_doc_field_producer_check` rc 1:

> 3 field(s) READ by a checker that NO document populates — the consumer sees an
> empty value, and an empty value is indistinguishable from a clean one

| field | readers (measured by grep over `programs/`) | present in | populated in |
|:--|:--|--:|--:|
| `floorplan_hints` | `l19_pdk_floorplan_contract_check.py`, `floorplan_contract.py`, `phase1_post_process.py` | 4 docs | **0** |
| `power_budget_uw` | `l19_pdk_floorplan_contract_check.py`, `phase1_post_process.py`, `power_total_vs_budget_check.py` | 4 docs | **0** |
| `sdc_constraints_path` | `l19_pdk_floorplan_contract_check.py`, `phase1_post_process.py`, `phase1_doc_one_shot_runner.py` | 4 docs | **0** |

The gate counts one *reader* per field (the checker that reads it as a
declaration); the table above names every program that mentions the key, which
is wider and is the more useful thing for whoever pays this down.

`power_budget_uw` is the one to look at first: `power_total_vs_budget_check`
exists to compare a synthesised power figure against a declared ceiling, and the
ceiling is never populated — so that comparison has been running against an
empty authority.

## FINDING 2 — three documents citing a proof they do not ship

`evidence_citation_resolves_check` rc 1:

> 3 NEW dangling evidence citation(s) — the document points at a proof it does
> not ship

| document | citation that resolves to nothing |
|:--|:--|
| `END_TO_END_CAMPAIGN.md` | `benchmark-data/evaluation/cvdp/CVDP_CAMPAIGN_FOLLOWUP.md` |
| `METHODOLOGY.md` | `sha256/BENCHMARK_VERIFICATION_REPORT.md` |
| `METHODOLOGY.md` | `sha256/RESULT.md` |

## RECORDED FACT — 113 baseline entries now resolve

The same run reports, verbatim:

```
  unresolved now : 26   baseline: 136
[FAIL] 113 baseline entr(ies) now RESOLVE — the debt was paid; shrink the
       baseline so it cannot become a standing waiver
```

The arithmetic reconciles and is worth stating so nobody re-derives it: of the
136 baseline entries, **113 now resolve** and 23 remain unresolved; 23 + the 3
NEW dangling citations above = the **26** unresolved now.

**The baseline was NOT rewritten, and that refusal is deliberate.** The gate asks
for `--write-baseline`; that is forbidden here even when the gate asks, and the
owner's ruling is explicit that the refusal is worth more than the tidier
baseline: *"Recording that they resolve loses nothing; rewriting the baseline
would have converted a real improvement into a standing waiver nobody could
audit."* Whoever shrinks it later should shrink it to a **measured** 23, not to a
number carried from here.

## WHAT THIS FILE IS NOT

It is not a gate, not a baseline, not an exemption and not a waiver. Nothing
reads it and nothing should. If a future change makes one of these six findings
false, this file goes stale and that is fine — the gates above are the authority,
and they will say so the moment anyone points them at a corpus on purpose.
