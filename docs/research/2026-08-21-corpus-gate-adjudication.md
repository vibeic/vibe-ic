# Adjudication: the two corpus gates

Owner ruling, 2026-08-21: *"adjudicate them, do not renew. A deadline that gets
extended each time it arrives is not a deadline, it is a comment. For each of
the two, write the verdict down: either it is a real finding about the design
and it stays red until fixed, or its population is genuinely empty and it must
report rc=2 NOT CHECKED with the measured population count in the message.
Renewal is not one of the options."*

Both verdicts are **real finding, stays red until fixed**. Neither row is
renewed; both remain expired and both therefore refuse a landing.

## FIRST, THE OPTION THAT DID NOT APPLY — AND IT IS ALREADY BUILT

The ruling's second branch is already implemented in both gates, and correctly.
Driven with an empty population:

```
$ l_doc_field_producer_check.py --corpus <empty dir> --corpus-may-be-absent
UNDETERMINED: … holds no L-doc this gate can read (0 of them carry a `fields`
object), so 0 document(s) were scanned against 18 field(s) read by checkers.
A zero denominator cannot say whether a field has a producer …
rc=2

$ evidence_citation_resolves_check.py --corpus <empty dir> --corpus-may-be-absent
UNDETERMINED: … this gate enumerated 0 file(s) it can read there (no .md, no
.json), so 0 citation(s) were checked. Nothing enumerated is 'I found nothing
to read' …
rc=2
```

rc 2, with the measured population count in the message, in both. So the
question is only whether the populations are empty here. **They are not**, and
that is measured, so the first branch is the one that applies.

## VERDICT 1 — `L-doc field producer`: REAL FINDING

Population, measured: **48 L-docs** under the published corpus, **18 fields**
read by checkers. Not empty by any margin.

Three fields are read and never produced:

| field | readers | present in | populated in |
|---|---:|---:|---:|
| `floorplan_hints` | 1 | 4 docs | **0** |
| `power_budget_uw` | 1 | 4 docs | **0** |
| `sdc_constraints_path` | 1 | 4 docs | **0** |

The single reader of all three is **`l19_pdk_floorplan_contract_check`**. The
consumer sees an empty value and an empty value is indistinguishable from a
clean one — the vacuous-pass shape this repo removes from gates one at a time.
It is a finding about the design, not about the corpus being absent: the
documents exist, they carry the key, and nothing ever fills it.

**It reaches further than its own gate.** `power_budget_uw` is also read by
`area_total_vs_budget_check` and `power_total_vs_budget_check` — and
`area_total_vs_budget_check` is one of the two AUDIT_ONLY programs that redden
`flow-gate enforcement audit`. So the chain is: a field with no producer feeds a
budget check that declares no intent, and nothing blocks at either end. Two of
the eight rows are the same defect seen from two directions.

The fix is either the L-docs populate the three fields or
`l19_pdk_floorplan_contract_check` declares them optional and says so. Both are
decisions about the contract; neither is a grace period. **Stays red.**

## VERDICT 2 — `evidence citation resolves`: REAL FINDING, AND ONE QUARTER OF IT WAS THE GATE'S OWN DEFECT

Population, measured: **149 contributing documents** of 1037 files enumerated,
**105 citations** checked. Not empty.

Two findings, adjudicated separately.

**(a) 113 baseline entries now RESOLVE.** Real. The debt was paid and the
baseline was not shrunk, so it has become a standing waiver for citations that
are no longer broken. Mechanical to clear and it must be cleared.

**(b) 4 NEW dangling citations — of which 3 are real and 1 was ours.** Checked
one at a time:

| citation | verdict |
|---|---|
| `END_TO_END_CAMPAIGN.md::benchmark-data/evaluation/cvdp/CVDP_CAMPAIGN_FOLLOWUP.md` | real — absent everywhere |
| `METHODOLOGY.md::sha256/BENCHMARK_VERIFICATION_REPORT.md` | real — absent everywhere |
| `METHODOLOGY.md::sha256/RESULT.md` | real — absent everywhere |
| `OSS_EDA_FORK_ROADMAP.md::tools/vibeic-eda/FIX_STATUS.md` | **NOT dangling** — this repo ships that file |

The fourth was the gate reporting its own scope as the document's defect, which
is the failure #1044 is about and precisely what the gate's `outside` class
exists to prevent. `_resolves_outside_the_scan_root` walked up from the scan
root, and its comment read *"benchmark-data/ic -> benchmark-data -> repo root"*
— true while the published cells lived inside this repository. **`c5d7f2d00`
made the corpus a sibling of the repo rather than a child**, so the walk now
arrives at `$HOME` and `/`. The disclosed OUT OF SCOPE count had fallen from the
7 measured when that comment was written to 2, which was the visible half of
the same loss.

Fixed here: the repository is located from where the PROGRAM ships rather than
inferred from where the corpus sits. OUT OF SCOPE 2 → 3, dangling 4 → 3. The
gate is **still red** on the three real ones and on (a). **Stays red.**

Note that the same commit that reddened both gates is the one that broke the
scope predicate. That is not a coincidence to explain away — it is the shape of
a corpus relocation whose consumers were not all moved with it.

## A THIRD THING, FOUND WHILE ADJUDICATING, WHICH MATTERS MORE THAN EITHER

**The acknowledgement ledger bought a green.**

`tools/ci/gate_red_since.json` gained its first rows yesterday. One of them
reads, in its `why`:

> closed_loop_edge_check, ppa_pr_scope_check and slot_pad_budget_check are
> consulted by no automatic verdict, so the tree looks identical whether they
> would pass or fail.

`gate_is_wired_check` enumerates its wiring sources with `tools/ci/*`. It read
that sentence, found all three names, and counted them **wired**. `unwired` fell
61 → 58 and the gate turned **PASS**. Isolated to that one file, on an otherwise
clean tree at `6dfe15a32`:

```
clean 6dfe15a32                          unwired: 61   [FAIL]
clean 6dfe15a32 + gate_red_since.json    unwired: 58   [PASS]
clean 6dfe15a32 + RESULT_ROWS.md         unwired: 61   [FAIL]
```

The ledger's own `_doc` promises *"there is nothing a row can silence and no
green a row can buy"*. It was exactly wrong, and in the worst possible
direction: **the acknowledgement silenced the finding it acknowledged**, so the
more honestly a row described its red, the more certainly it hid it. Had this
shipped, writing the eight rows would have closed one of the eight reds by
describing it.

The gate already holds this rule one level in — `executable_text` strips
comments and docstrings because "a comment naming a gate is not a caller", with
a measured case where believing one would have hidden a gate that runs nowhere.
A register of red gates is the same thing. `_NOT_A_RUNNER` now excludes the
ledger, named from `gate_red_since_check.LEDGER_REL` so a move cannot leave the
exclusion pointing at nothing, and `test_ledger_is_not_a_runner.py` pins both
directions — the ledger is not read, and everything else under `tools/ci/` still
is, because for several gates that directory holds the only caller there is.

## ONE MEASUREMENT THAT CHANGES WHAT A ROW MEANS

The red set depends on whether the published corpus is bound:

```
corpus UNBOUND   85 declared,  8 FAIL, 10 NOT_CHECKED
corpus BOUND     88 declared,  9 FAIL, 12 NOT_CHECKED
```

Binding it adds four per-cell gates and removes one empty-corpus gate. A row is
therefore true against a stated corpus state, not absolutely — and a host that
binds the corpus will see a ninth red (`an argued direction is pinned`) that has
no row. That is not an argument for a ninth row written blind; it is an argument
for the landing path to state which corpus it measured against, which the
hygiene record already does.

---

# ADDENDUM 2026-08-22 — THE CORPUS MOVED AND TOOK BOTH VERDICTS WITH IT

Everything above was measured against `/home/reyerchu/benchmark-data` as it
stood on 2026-08-21. That clone has since advanced to `b971220` (06:26) and
**shrank from 1037 enumerated files to 70**. Re-measured:

    L-doc field producer       then 48 L-docs, 3 fields present in 4 docs and
                                    populated in 0            -> a producer finding
                               NOW  "0 of them carry a `fields` object, so 0
                                    document(s) were scanned against 18
                                    field(s)"                 -> rc 2 UNDETERMINED

    evidence citation resolves then 149 contributing docs of 1037, 105 citations,
                                    113 baseline resolved, 4 dangling
                               NOW  66 of 70, 28 citations, 132 baseline
                                    resolved, 5 dangling

**`L-doc field producer` has moved from the owner's first branch to the second.**
The ruling was: *either a real finding about the design that stays red until
fixed, or its population is genuinely empty and it must report rc=2 NOT CHECKED
with the measured population count.* Its population is now genuinely empty and it
reports exactly that, naming both counts. **The gate is behaving correctly.**

**So the defect is the DISPATCH, not the gate.** `repo_hygiene_gates.sh` runs it
with a plain blocking `run`, under which rc 2 is recorded **FAIL** — a gate that
correctly says "I could not look" reaches the roll-up as "I looked and it was
bad". `run_tolerating_uncheckable` plus a dated `uncheckable_until` is the
mechanism that exists for exactly this. That file is a PROTECTED path, so the
change is not made here.

**`evidence citation resolves` stays on the first branch**: 66 documents and 28
citations is not an empty population, and both findings are real.

The figures above are kept and dated rather than edited in place. They were true
when measured and they are the evidence for the reasoning that follows them; a
verdict that silently restates itself against a moved corpus is the shelf-life
failure this addendum exists to record.

## ONE MORE STATE WORTH NAMING

`L-doc field producer` and `evidence citation resolves` are now **501 commits
behind** against `MAX_BOUND_COMMITS = 500`. No legal bound can cover them any
more: they can be renewed by moving `since` forward, or fixed, and there is no
third option. That is the ceiling doing its job — it forbids an unattended
remediation, not a long one — but it means neither row can be honestly
re-acknowledged as it stands.
