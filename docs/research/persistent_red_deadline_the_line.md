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
