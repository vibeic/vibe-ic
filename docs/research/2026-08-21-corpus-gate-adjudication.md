# Adjudication: the two corpus gates

Owner ruling, 2026-08-21: *"adjudicate them, do not renew. A deadline that gets
extended each time it arrives is not a deadline, it is a comment. For each of
the two, write the verdict down: either it is a real finding about the design
and it stays red until fixed, or its population is genuinely empty and it must
report rc=2 NOT CHECKED with the measured population count in the message.
Renewal is not one of the options."*

Both verdicts are **real finding, stays red until fixed**. Neither row is
renewed; both remain expired and both therefore refuse a landing.

> ## RE-MEASURED 2026-08-22 — BOTH VERDICTS ARE SUPERSEDED BY A LOCATION TEST
>
> The verdicts below were measured against a population that has since moved,
> and — more importantly — against a corpus that is **not this repository's**.
> Kept in full because they were true when measured; do not read them as the
> current state.
>
> ### The discriminating pair
>
> Same commit, same gates, same host. Only the WORKTREE LOCATION differs, and
> each run repeated twice:
>
>     worktree under /home/reyerchu   0 passed, 3 failed
>     worktree outside $HOME          2 passed, 1 failed
>
> `L-doc field producer` and `evidence citation resolves` flip; `liar census
> controls still fire` does not. The two that flip are found by the corpus
> parent-walk climbing out of the worktree into `/home/reyerchu/benchmark-data/
> ic` — a directory that is **its own git repository** (HEAD `48644ee`,
> 2026-08-22) and is not this repo's corpus. benchmark-data left this repo at
> v1.10.56.
>
> So the red these two rows acknowledge was produced by judging a foreign
> corpus that happened to sit in an ancestor directory of the checkout.
>
> ### Neither published state is the honest one
>
> Inside `$HOME` the gates FAIL, judging a corpus that is not theirs. Outside,
> they PASS having scanned nothing — and they say so themselves:
>
>     [l_doc_field_producer_check] NO_CORPUS: ... NOTHING WAS SCANNED, 0
>     published L-doc(s) were examined and nothing is claimed about them
>
> and the run's own closing line reads *"all 93 gate(s) passed, but 1 loop
> corpus expanded over 0 item(s) — NOTHING was checked over"*. A gate that
> prints "nothing is claimed" and is recorded PASS is the vacuous pass the
> owner's ruling names.
>
> ### CORRECTION: "the return code is wrong" was MY error, and the repo already
> ### decided this
>
> An earlier draft of this section said the two gates "must report rc=2 NOT
> CHECKED; only the return code is wrong". That is wrong and it contradicts a
> deliberated position I had not read.
>
> `NO_CORPUS (rc 0)` is reachable ONLY when the CALL SITE opts in with
> `--corpus-may-be-absent`. It is never a default. `repo_hygiene_gates.sh`
> passes it at 20 sites, each with a written justification citing the v1.10.56
> corpus move (vibe-ic#1710), and at line 117 it documents a gate where the
> flag is DELIBERATELY withheld for precisely the reason I was about to
> re-raise: *"rc 0 here would be this gate printing a PASS over a population it
> never opened"*.
>
> The flag does not silence anything. Quoting the call site: a
> `$VIBE_IC_BENCHMARK_DATA` that is set and broken is STILL `UNDETERMINED`, a
> corpus that IS supplied is STILL fully adjudicated, and a corpus present but
> holding no L-doc is `UNDETERMINED` rather than a comparison against zero. The
> only thing it converts is nothing-anywhere, into a NO_CORPUS that STATES 0
> documents were examined. Before the flag, these gates refused rc 2 on every
> landing after v1.10.56 — which is the breakage it was introduced to fix.
>
> So the gates are right, the flag is right, and I am not proposing to change
> either.
>
> ### THE GAP THAT SURVIVES THE CORRECTION
>
> What remains is one level up, in the AGGREGATION rather than the gate. The
> dispatcher records a NO_CORPUS gate in the same `PASS` bucket as a gate that
> actually adjudicated something.
>
> **Costed, because a recommendation without a number is how the last one went
> wrong.** `repo_hygiene_gates.sh` invokes exactly **10** gates with
> `--corpus-may-be-absent`. Ran all 10 from a worktree OUTSIDE `$HOME`, where
> the corpus is genuinely absent rather than accidentally found:
>
>     L-doc field producer              PASS   says NOTHING WAS SCANNED
>     tracked-symlink portability       PASS   says NOTHING WAS SCANNED
>     tracked-symlink target present    PASS   says NOTHING WAS SCANNED
>     evidence citation resolves        PASS   says NOTHING WAS SCANNED
>     citation routing is true          PASS   says NOTHING WAS SCANNED
>     cross-layer reference regression  PASS   says NOTHING WAS SCANNED
>     step FAIL bubbles up              PASS   says NOTHING WAS SCANNED
>     L4 -> SystemRDL disposition       PASS   says NOTHING WAS SCANNED
>     published-evidence index honest   PASS   says NOTHING WAS SCANNED
>     published records not superseded  PASS   says NOTHING WAS SCANNED
>
>     RECORDED PASS WHILE REPORTING NOTHING SCANNED: 10 of 10
>
> and the roll-up:
>
>     declared 93   ran 10   decided 10   passed 10   failed 0
>     "repo_hygiene_gates: all 93 gate(s) passed"
>
> So it is not two gates, it is **ten** — a ninth of the declared set — each
> counted by `PROCESS_STATES` among those that "actually ran". The gates said
> "NOTHING WAS SCANNED ... nothing is claimed about them"; the summary answered
> "passed".
> The machinery to say otherwise already half exists — the same run prints
> *"1 loop corpus expanded over 0 item(s) — NOTHING was checked over"* — but
> that is `GATE_CORPUS_STATE` in `tools/ci/_gate_dispatch.sh:1374`, which
> tracks LOOP CORPORA, not gates. It is careful where it applies — it refuses
> to call an absent corpus "EXPANDED with 0 items" because *"a consumer reading
> `items: 0` off an EXPANDED row is reading a measured population, and there
> was none"*. That is exactly the distinction wanted here. But a NON-loop gate
> that exits rc 0 NO_CORPUS gets no equivalent: the per-gate vocabulary is
> PASS / FAIL / NOT_CHECKED / WROTE_CORPUS / LISTED / OTHER_SHARD /
> OUT_OF_SCOPE / QUEUED, and it lands in PASS. `hygiene_finding_delta`'s
> `PROCESS_STATES` then counts it among the gates that "actually ran".
>
> The honest fix is therefore a DISPATCH state, not a return code: NO_CORPUS
> should be recorded and counted separately, so "93 passed" cannot absorb it.
> That is a smaller change than the one I first proposed and it does not
> reopen #1710.
>
> ### A THIRD THING ABOUT `evidence citation resolves`, FOUND WHILE CHECKING
> ### SOMETHING ELSE
>
> Its own controls do not fire, and have not for at least 247 commits.
>
> `programs/tests/test_evidence_citation_resolves_check.py` has four tests that
> plant a defect and require the gate to refuse it:
>
>     test_dangling_citation_fails
>     test_resolution_never_escapes_the_scan_root
>     test_untracked_artifact_does_not_satisfy_a_citation
>     test_a_citation_pointing_at_a_symlink_is_not_shipped_content
>
> All four fail on main today, in BOTH worktree locations (so this is not the
> $HOME artefact above), and all four already failed at `0095513a0` — the last
> commit that matched an authorised protected state, 247 commits back.
>
> The mechanism, from the first one: the control plants a dangling citation and
> asserts rc 1. The gate answers rc 0 with
>
>     OUT OF SCOPE : 1 citation(s) resolve against the repository but ABOVE
>                    this gate's scan root
>     WARNING      : git-tracked file set unavailable — falling back to plain
>                    filesystem existence
>
> So the OUT-OF-SCOPE narrowing absorbs the very defect the control exists to
> plant, and the control can no longer fail the gate for the reason it was
> written. That is the same shape as `liar census controls still fire`: a
> control that cannot fire is not a control.
>
> This is NOT in the 75-file targeted selection either — `ci_targeted_test_
> select --base origin/main` routes 0 of these — so no two-arm measurement of
> any branch has ever seen them.
>
> #### ADJUDICATED: the CONTROLS are right and the GATE is wrong
>
> Reproduced by hand, outside pytest. Identical fixture — one document saying
> a document citing a proof-log filename it does not ship — placed at
> different depths. **Only the path changes:**
>
>     scan root 2 levels below /tmp   rc=0  OUT OF SCOPE   MISSED
>     scan root 3 levels below /tmp   rc=0  OUT OF SCOPE   MISSED
>     scan root 4 levels below /tmp   rc=0  OUT OF SCOPE   MISSED
>     scan root 5 levels below /tmp   rc=1  [FAIL]         DETECTED
>     scan root 6 levels below /tmp   rc=1  [FAIL]         DETECTED
>     scan root 7 levels below /tmp   rc=1  [FAIL]         DETECTED
>
> The cause is a stray proof-log file directly in /tmp (1448 bytes, dated 2026-08-17,
> left by some earlier run). The gate resolves a citation by walking UP from
> the scan root, reaches at most FOUR parent levels, and if it finds a file of
> that name it reports
>
>     OUT OF SCOPE : 1 citation(s) resolve against the repository but ABOVE
>                    this gate's scan root — the document is correct and this
>                    gate is not the one that judges it
>
> and passes. pytest's `tmp_path` sits 3 levels below `/tmp`, inside that
> window, which is why all four controls fail.
>
> The OUT-OF-SCOPE rule is reasonable INSIDE the repository, where "above the
> scan root" means another part of a tree someone owns. It is not reasonable
> when nothing encloses the scan root: the gate's own output says
> *"git-tracked file set unavailable — falling back to plain filesystem
> existence"*, and in that state "the repository" is just the filesystem, so
> **any unrelated file with the cited basename within four parents silences a
> real dangling citation**.
>
> So the four controls are correct and are red for a real reason, and the fix
> belongs in the gate: when no git-tracked file set is available, do not
> resolve above the scan root at all. That also makes this the exact mechanism
> behind the `HOST_DEPENDENT_VERDICT` that
> `gate_host_independence_check` reports for this same gate — it is reading
> something that is not in the commit, and this is what.
>
> Not fixed here: it is a behaviour change to a gate I do not own, and the
> owner may prefer a different boundary. That stray file was left in place —
> it is not mine to delete.
>
> A note for whoever writes this up again: the first draft of this section
> named the file in backticks, and the extractor reads a backticked
> filename-like token as a CITATION. Measured: it added exactly 2 dangling
> citations to this repo (138 -> 140), from this document. Writing about
> dangling citations created two. Name such files without backticks.
>
> ### Consequence for the two ledger rows
>
> Both rows have aged past `MAX_BOUND_COMMITS = 500` (549 behind), so no legal
> `max_commits` can cover them: they can never again be legitimately
> acknowledged. They are also, by the measurement above, not genuine repo reds.
> Their honest disposition is removal-with-a-reason once the gates return rc=2
> — not renewal, which the ceiling refuses anyway.

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
