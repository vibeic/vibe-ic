# THE LINE — where the persistent-red deadline is read, and what would set it

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
condition.** The deadline is only ever evaluated for a label that already has a
row in `tools/ci/gate_red_since.json`, and that ledger is `"acknowledged": []`.

The program is also on nobody's landing path. `grep -c gate_red_since_check`:

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

## THEREFORE

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
