# THE LINE — where the persistent-red deadline is read, and what would set it

> **STATUS: CLOSED, AND THIS DOCUMENT WAS WRONG ABOUT ITS OWN SUBJECT UNTIL
> 2026-08-29.** Two of its statements had gone false and both pointed the next
> reader away from the mechanism:
>
> * **"The program is also on nobody's landing path."** FALSE at 073a703de. The
>   forcing function this document argued for WAS BUILT, in the place it named:
>   `landing_merge_verdict.py:944` loads `gate_red_since_check` by path and
>   `:1385` calls `inherited_red_reasons`, appending every string it returns to
>   `reasons` — the refusing list, not `notes`. `gatekeeper_review.py:1634`
>   invokes the CLI as well. The grep table below is kept because it was the
>   measurement that motivated the work, and it now measures 3 (comments) in
>   `gatekeeper-land.sh` and 1 in `repo_hygiene_gates.sh`.
> * **"that ledger is `"acknowledged": []`."** FALSE when written against a tree
>   carrying two rows. It is true again as of 2026-08-29 — for the opposite
>   reason, and that difference is the whole point: an empty ledger USED TO mean
>   nobody was acknowledging, because a row was voluntary and pure cost. It now
>   means nothing is owed, because an inherited blocking red that no row names
>   REFUSES the landing.
>
> **The two rows the ledger carried were retired on 2026-08-29 and neither was
> renewed.** `tools/ci/gate_red_since.json`'s own `_doc` carries the per-row
> evidence; in one line each:
>
> * `PPA measurement coverage` — **FIXED.** The row acknowledged 54 refused
>   records and said it closes when `trials/b000` is re-produced. It was
>   (c775e92eb, 2026-08-25). Measured through the gate's own `_index_from`:
>   91 indexed / 54 refused at the row's `since`, 117 indexed / **0 refused** at
>   073a703de.
> * `L-doc field producer` — **the red is CORRECT and stays.** With no corpus the
>   gate is rc 0 PASS and the row read `stale`; with `VIBE_IC_BENCHMARK_DATA`
>   pointed at a clone it is rc 1 over 48 L-docs and the row read `expired`. No
>   tree satisfied it in either direction, and its own `adjudicated` ruling
>   ("REAL FINDING — stays red until fixed, NOT renewed") forbids the renewal
>   that would have cleared it. Nothing in this repository can populate
>   `floorplan_hints` / `power_budget_uw` / `sdc_constraints_path` — the subject
>   is in `vibeic/benchmark-data` — and the gate blocks the hygiene suite on its
>   own, with no row here. The cause, owner and closing condition live at the
>   gate's own wiring site (`uncheckable_until 2027-02-28`,
>   `tools/ci/repo_hygiene_gates.sh`).
>
> **LINE NUMBERS BELOW ARE THE 2026-08-12 TREE'S AND HAVE ALL MOVED**, and one
> of them cites a field that no longer exists: `bound = int(row["max_commits"])`
> became `bound = float(row["max_days"])` when the clock stopped being a commit
> count (a commit count is a property of the merge topology; a 97-branch
> assembly expired every shipped row). At 073a703de the same five hops are
> `gate_red_since_check.py:552` (the loop over the ledger), `:607` (`age`),
> `:616` (the bound), `:643` (the expiry), `:653` (the NEW partition) and
> `:1033` (the PASS line).

Published before any change, because three other lanes are working around this
and the name is worth more to them than the fix.

## Where the deadline is READ

    vibe-ic-marketplace/plugins/vibe-ic/programs/gate_red_since_check.py

      :194   for row in ledger:            <- THE LOOP'S DOMAIN IS THE LEDGER,
                                              not the set of red gates
      :223   behind = age(since)
      :268     git rev-list --count {sha}..HEAD
      :231   bound = int(row["max_commits"])          <-- READ HERE
      :243   if behind > bound:
      :244     findings.append(Finding("expired", label, ...))   <-- BITES HERE
      :253   new = [l for l in red if l not in acknowledged_gates]
      :350   "[PASS] gate_red_since: every red is NEW or owned by a live,
              unexpired acknowledgement"

`:350` is the whole thing in one sentence: **a red owned by nobody is a PASS
condition IN THIS PROGRAM.** The deadline is only ever evaluated for a label that
already has a row in `tools/ci/gate_red_since.json`, and on 2026-08-12 that
ledger was `"acknowledged": []`.

That sentence is still true of `gate_red_since_check` and is no longer true of a
landing, which is exactly the split this document argued for: the program still
only REPORTS an unowned red (failing it twice would say nothing extra), and
`landing_merge_verdict` REFUSES it. So "unowned" is now the expensive state and
an empty ledger is the cheap one — the reverse of the incentive this document
opens by describing.

The program was also on nobody's landing path — TRUE ON 2026-08-12, FALSE NOW;
see the STATUS block. `grep -c gate_red_since_check`, as measured then:

    tools/gatekeeper-land.sh          0
    tools/gatekeeper-verify-merge.sh  0
    tools/ci/repo_hygiene_gates.sh    0
    tools/git-hooks/pre-push          0
    tools/ci/_gate_dispatch.sh        0

Its only caller is `gatekeeper_review.py:1318 gate_red_since_gate`, invoked at
`:1682` — the REVIEW role, not the landing.

## What would have to SET it

A row is voluntary and pure cost. The ledger's own `_doc` says so: *"A row here
grants NO leniency ... The ONLY thing a row does is start a clock."* Voluntary +
pure cost = never written, which is why the ledger is empty.

So the thing that must change is not the deadline — it is correct — but the
**forcing function**. The one place in the system that knows a red is INHERITED
rather than new is:

    vibe-ic-marketplace/plugins/vibe-ic/programs/landing_merge_verdict.py:1183-1185

      for key in sorted(set(was_red) & set(now_red)):
          notes.append(f"gate fails on the base too, so it is not this "
                       f"branch's — {now_red[key]}")

`notes` never refuse; only `reasons` do. Requiring a row THERE is what starts
the clock, and it needs no new persistence: the ledger is a tracked file in the
base tree.

## Why it is mechanism (2), with the other two ruled out

  (1) the verdict is never produced (rc 2 NOT CHECKED / skipped) — RULED OUT:
      different rc, different path (`_gate_dispatch.sh:1167`), and disciplined —
      every `run_tolerating_uncheckable` needs a dated `uncheckable_until` and a
      passed date fails the sweep.
  (2) the verdict IS produced, recorded and parsed, and the decision declines to
      act on it — THIS ONE.
  (3) produced then lost — RULED OUT: `landing_completion_record.py:261` demands
      the complete 24-unit population, `:182`/`:200` pin the order,
      `landing_merge_verdict.py:1029-1041` demands the terminal record, and
      `:1165-1170` refuses a base-red gate gone absent as SILENCED.

The chain for (2), every hop:

    repo_hygiene_gates.sh exits 1
      -> gatekeeper-land.sh `run`: prints "  FAIL  <label>", FAILED=1 (:169),
         landing_record   -- the red IS in the journal
      -> parse_land_log (:836) via _LAND_LINE (:269)
      -> LandLog.blocking_failures (:399-401)
      -> was_red / now_red (:1156-1157)
      -> :1183-1185  set(was_red) & set(now_red) -> notes.append(...)

## Corroboration, four readings of one mechanism

  * an always-run BLOCKING gate green at `9cc09b863~1`, red v1.11.5..v1.11.18 —
    35 commits, 13 version-bearing landings, correct wiring, blocking nothing;
  * `ci_targeted_test_select --base 7fcbc7397~1` selects 325 tests including 16
    `test_matrix_*` — SELECTED, and the red simply not acted on;
  * the ninth matrix dimension, built around "does a step's verdict get
    CONSUMED";
  * and from the code: `flow-gate enforcement audit` is dispatched with plain
    `run` at `tools/ci/repo_hygiene_gates.sh:385` — BLOCKING — and measured rc=1
    on `origin/main` at 752a8baa, while `landing_merge_verdict.py:1141-1145`
    records the same gate red on the base at `e4880703b` on 2026-08-12.
    Between those two measured endpoints: 704 commits, 96 version bumps, 9 days,
    every landing successful.

---

# WHY IT HAS NEVER BEEN OPENED: any enforcement inside the suite SUBTRACTS ITSELF

Published second, and before the fix, because it rules out the cheap placement
and three lanes are about to try it.

The obvious home for "an unacknowledged red must fail" is
`gate_red_since_check.py` itself — it already reads the dispatcher's record, it
already owns the deadline, and it is NOT a protected path. Turning its `new`
partition (`:253`) from a report into a `Finding` is a few lines.

**That does not work, and the reason is the mechanism itself.**

If the refusal lives in a gate INSIDE `repo_hygiene_gates.sh`, then that gate's
own verdict is subject to the same subtraction as every other gate in the suite:

    base arm      : inherited red R has no row -> gate_red_since_check FAILS
    candidate arm : inherited red R has no row -> gate_red_since_check FAILS
    landing_merge_verdict: FAIL on both arms -> `carried`
                           "…{len(carried)} carried (which do NOT block)"

So the refusal is inherited on the very first landing after it is wired, and is
subtracted from then on. The gate that exists to stop a permanently-red gate
becomes a permanently-red gate.

The mirror case is no better. If a branch DID add the row, the candidate's check
passes while the base's fails; the verdict classifies that as `cleared`, which is
reported and never required. So neither adding the row nor omitting it changes a
landing's outcome, in either direction.

## THEREFORE — AND THIS IS WHAT WAS BUILT

The forcing function has to sit where the subtraction is DECIDED, not where it is
applied — `landing_merge_verdict.py:1183-1185` for the gate-label tier, and the
`carried` list at `:1231-1235` for the finding tier. Both are inside
`landing_merge_verdict.py`, which is `["authority"]` in
`tools/ci/protected_landing_transition.json`.

    not protected : gate_red_since_check.py, gatekeeper_review.py
    PROTECTED     : landing_merge_verdict.py, hygiene_finding_delta.py,
                    repo_hygiene_gates.sh, _gate_dispatch.sh,
                    gatekeeper-land.sh, gatekeeper-verify-merge.sh

and `gatekeeper_review.py` — the only caller of `gate_red_since_check` — is not
on the landing path at all (`gatekeeper-land.sh` names it once, in a comment at
`:262`).

So opening this deadline REQUIRES one change inside the protected authority set,
which means a PREPARE/ACTIVATE pair. That is the whole reason it has stayed shut:
the cheap placement is self-defeating and the correct placement costs a protected
transition.

## WHAT CAN BE BUILT WITHOUT ONE

Everything except the two-line call. The adjudication is already a pure function
(`gate_red_since_check.adjudicate(record, ledger, age) -> (findings, known, new)`,
`:183`), with `age` injected precisely so every branch is reachable from a test
without building a git history. The verdict change is then a call into tested
code, not new logic in a protected file — which is the smallest protected diff
this can be reduced to.

---

# WHAT LANDED, AND WHERE IT IS NOW (measured 2026-08-29 at 073a703de)

    gate_red_since_check.inherited_red_reasons          :666
      one refusal string per inherited BLOCKING red that is unowned, past its
      bound, unbounded, unresolvable, or still bounded in commits

    landing_merge_verdict._load_red_since               :944
      loads it by path, at the moment it is needed, so this file's import graph
      is unchanged — it is executed by the isolated trusted entry

    landing_merge_verdict.decide                        :1385
      for reason in _load_red_since().inherited_red_reasons(
              list((hygiene or {}).get("carried") or []),
              list(red_since_ledger), commit_age):
          reasons.append(reason)          <-- `reasons`, NOT `notes`

    landing_merge_verdict.decide                        :1370-1378
      and when the ledger or the age function is missing it says so —
      INHERITED_RED_DEADLINE_NOT_EVALUATED — rather than reading clean

The protected transition the document predicted was paid: `landing_merge_verdict`
is `["authority"]` in `tools/ci/protected_landing_transition.json` and still is.

## THE ONE THING THAT WAS STILL WIRED THE OLD WAY, AND IS FIXED IN THIS CHANGE

`gate_red_since_check.dispatcher_exemptions` reads `exempt_until` off a gate row
to say which reds are owned by the dispatcher's own dated exemption rather than
by this ledger. `_gate_dispatch.sh` stamps that field on the row BEFORE the gate
runs, so a gate carries its date whatever it then returns — and the tolerance the
date buys is rc 2 only. MEASURED on a real record of `L-doc field producer` with
the corpus mounted: `state: FAIL, exempt_until: 2027-02-28`, and the CLI printed

    red, and DATED by the dispatcher's own exemption …: 1 — L-doc field producer

for a BLOCKING red. Nothing was made green — the suite still exits 1 — but the
one bucket a reader acts on, `NEW red this run (owned by nobody)`, had a blocking
red taken out of it. The credit is now given only to `NOT_CHECKED`, which is the
one state an `uncheckable_until` converts, and the rule is stated as that one
state rather than as a list of exclusions so a state added to `_gate_dispatch.sh`
later is unowned by default.

## WHAT IS STILL OPEN, AND IS NOT THIS CHANGE'S TO CLOSE

`repo_hygiene_gates.sh` is a protected path, so the two declarations below were
READ and not edited; each needs a PREPARE/ACTIVATE pair.

  * the `uncheckable_until 2027-02-28` above `L-doc field producer` says "rc 2 is
    a MEASURED zero over a corpus that WAS read". On a host carrying today's
    `benchmark-data` the gate returns **rc 1** over 48 L-docs, and rc 1 is not a
    state that exemption can convert. The exemption is not WRONG to exist — it
    covers the pointer-unset case — but its stated mechanism no longer matches
    the state the gate actually reaches, and a reader who takes it at its word
    will believe that red is covered.
  * no inventory of the rest of the suite was taken here. This change adjudicates
    the two rows the ledger named and nothing else; if other gates are red on
    both arms and unowned, `inherited_red_reasons` will name them at the next
    landing, which is the mechanism working rather than a gap.
