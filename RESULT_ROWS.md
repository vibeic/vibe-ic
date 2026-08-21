# The eight rows, and the answer to the question you asked

Branch `agent/jrows-eight-rows` off `6dfe15a32` (v1.11.62).

## 1. EVERY `since` IS MEASURED

Not estimated. `repo_hygiene_gates.sh --shard 0/1 --shard-labels FILE` runs
exactly the eight in a throwaway worktree, 23s a probe. Instrument validated
first on a known answer — `e4c5840d6`, where all eight were already known FAIL,
returned 8/8 FAIL. Geometric ladder to `origin/main~800`, then dense integer
probing of each bracket: 39 probes. Horizon stated: `--shard` does not exist
before roughly `origin/main~500`, so nothing older can be probed this way.

| gate | since | date | age | landings since | bound | verdict |
|---|---|---|---:|---:|---:|---|
| flow-gate enforcement audit | `69ce9260d` | 08-20 | 85 | 59 | 70 | **EXPIRED** |
| L-doc field producer | `c5d7f2d00` | 08-16 | 291 | 97 | 210 | **EXPIRED** |
| evidence citation resolves | `c5d7f2d00` | 08-16 | 291 | 97 | 140 | **EXPIRED** |
| checker execution wiring | `41bfd8a12` | 08-21 | 65 | 50 | 70 | live, 5 left |
| gates are wired to something | `41bfd8a12` | 08-21 | 65 | 50 | 70 | live, 5 left |
| declaration scans strip comments | `9cc09b863` | 08-20 | 83 | 57 | 70 | **EXPIRED** |
| d3 declaration/manifest parity | `d976999c4` | 08-21 | 20 | 17 | 60 | live, 40 left |
| liar census controls still fire | `41bfd8a12` | 08-21 | 65 | 50 | 35 | **EXPIRED** |

Driven against the real dispatch record from `6dfe15a32`, the shipped
adjudicator returns **rc 1 — `5 acknowledgement(s) expired`**.

`9cc09b863` independently corroborates the other agent's report of a gate green
at `9cc09b863~1`: that is the exact commit `declaration scans strip comments`
went red at. Two measurements, different methods, same commit.

## 2. TWO OF THEM TOGGLE, AND THAT WAS TESTED RATHER THAN ASSUMED

`d3` and `liar census` each go red, green and red again across history. That is
the signature of a flaky gate, and **a flaky gate cannot honestly be given a
row** — there is no commit at which it "went red", so any `since` would be a
number I chose. Both were re-probed four times at the same commit: **4/4
identical** each time (`d3` PASS at ~25, `liar census` PASS at ~70). They are not
flaky; they were repaired and broke again. So `since` is the start of the
CURRENT unbroken run, and the earlier episodes became evidence for the bounds.

## 3. WHERE THE BOUNDS COME FROM

Two are **measured** from how long this exact defect took to repair last time:
`d3` was red at ~85 and green by ~25 → **60**. The `liar census` literal was
repaired in 2 commits (~249→~247) and in under 15 (~85→~70) → **35**. Those are
measurements of the fix, not judgements about it.

The other six are priced in days at the **measured** rate of 72–83 commits/day
over 2026-08-19..21: one day for a decision or a handful of one-line edits, two
for a decision plus mechanical work, three for the one whose fix is in another
repository. Each reason is in the row itself, in a new `bound_because` field
declared in the ledger's own FIELDS block rather than smuggled in — the
adjudicator does not read it, the reviewer does, and the reviewer is the only
defence against a bound chosen for comfort.

Five of the eight are past the bound their own fix effort justifies. Bounds that
cleared today's ages were available and I did not take them.

## 4. THE EXPIRY BITES — `test_gate_red_since_rows.py`, 12 passed

Separate from `test_gate_red_since_check.py`, which asks "does the logic work"
over fixtures. This one asks "do the rows this repo actually carries still have
teeth", which no fixture can answer: a row can be perfectly well-formed and
still name a label that no longer exists or a commit this repo does not have,
and both are how a real ledger goes quiet with nobody editing it.

* **evaluable** — every row carries the 3 required keys and owner/why/
  bound_because; every `gate` is named by a `run` line in the declaring script;
  every `since` resolves here; every bound is in 1..500.
* **bites, both directions** — a row past its bound refuses AND states how far
  behind it is; the same row inside its bound does not; a red no row mentions is
  reported NEW and does not refuse.
* **mutation** — every shipped row is driven at bound 1 and at the ceiling. It
  must expire at 1 and NOT expire at 500, or something other than the deadline
  is failing it and its number is decorative. And moving `since` to HEAD
  silences every one, so the refusals are a judgement and not a wall.
* **authored** — the ledger is tracked and every commit touching it carries an
  author, so a renewal cannot be anonymous; and an expired row stays expired
  with the environment stuffed with every override name a reader might guess at.

Regression: 66 passed across `test_gate_red_since_check.py`,
`test_gatekeeper_review.py`, `test_issue1025_empty_corpus_sweep_blocks.py`.

## 5. A CORRECTION TO THE BRIEF, STATED BECAUSE IT CHANGES THE WORK

`area_total_vs_budget_check` and `tapeout_docs_gen` are **not two of the eight**.
They appear nowhere in `repo_hygiene_gates.sh`. They are the two AUDIT_ONLY
offenders *inside* the first gate's failure:

    [FAIL] 2 NEW gate(s) are AUDIT_ONLY and declare no intent at all
       undeclared::area_total_vs_budget_check
       undeclared::tapeout_docs_gen
       ^^ FAILED: flow-gate enforcement audit

You were right about the substance and one level off about where it sits, so it
is one row, not two, and "the real fix is a decision, not a grace period" is
written into that row's `bound_because`.

## 6. YOUR QUESTION, ANSWERED PLAINLY

> is eight rows the right shape, or is it eight admissions that main should not
> be landing at all today?

**Neither, and the real answer is worse than both: nothing on the landing path
was ever going to ask.**

`gate_red_since_check.py` is run by exactly one thing — `gatekeeper_review.py`,
as a first-class gate that returns rc 1 and denies MERGE_OK. And
`gatekeeper_review.py` is invoked by **no workflow, no git hook, and no script**.
Every hit outside its own tests is a comment or a line of `SKILL.md` prose. The
pre-push hook excludes the hygiene set deliberately, in a written note, because
it is too slow for a hook. `.github/workflows/` does not mention it.

So `--no-verify` is not what has been skipping the deadline. **There was nothing
on the push path to skip.** The only runner is a program an agent runs if it
remembers to — which is, verbatim, what one of the eight reds says about three
other programs:

> A gate nothing invokes produces no verdict, and the tree looks the same either
> way. … a skill mention runs it only if an agent remembers to.

The deadline I opened yesterday, and the eight rows I wrote today, are in that
same class right now.

**On the substance, six rows and two decisions.** Six of the eight went red in
the last 48 hours, from three commits, each of which added programs and left one
clause unfinished: `41bfd8a12` shipped `closed_loop_edge_check`,
`ppa_pr_scope_check` and `slot_pad_budget_check` with no runner and reddened
three gates at once; `69ce9260d` added two AUDIT_ONLY programs; `d976999c4`
declared an output the d3 manifest never measured. That is not rot. That is a
repo landing ~75 commits a day where each landing leaves one loose end and
nothing forces closure within the day. Those six deserve exactly what a row is:
small, local, owned, dated.

The other two are different in kind. `L-doc field producer` and `evidence
citation resolves` both went red at `c5d7f2d00`, the commit that moved published
results to `vibeic/benchmark-data`, and their fix is in **another repository**. A
dated row in this repo cannot make a change happen in that one. For those two a
row is the wrong instrument, and the honest options are to have the checkers
declare the external fields optional, or to accept that these two gates cannot
be green here and say so in the gate rather than in a ledger.

**And the part about how you have been working, since you asked for it written
down.** The flag is not the finding. The finding is that the flag did not
matter: had `gatekeeper_review` been on the push path, five of these eight would
have been named at the moment they were one-line fixes, by the person who had
the context, on the day they were made. Instead each one has survived 17 to 97
version-bearing landings. Landing fast is not the problem and I would not stop
it. What is missing is a step that closes the loop inside the same day, and
right now the repo has one — it is just wired the weakest way there is.

## REQUESTS TO THE LANDER

1. **Land the rows.** They change nothing today except that
   `gatekeeper_review` now returns rc 1 for a named reason instead of a general
   one — which is only visible if something runs it.
2. **Wire `gatekeeper_review` to something.** This is the request that makes the
   other work real, and it is not mine to place: hook, workflow, or
   `gatekeeper-land.sh`. Naming the runner is a decision about how long a
   landing may take, which is yours.
3. **Rule on the two corpus gates** rather than renewing their rows. They are
   already 291 commits and 97 landings old and their fix is not in this repo.
4. **Substitute issue numbers for `owner: repo-gatekeeper`** if you want them —
   one line each. I did not open issues; that is an outward-facing write and it
   is your queue.
5. Three rows come due within about five commits of each other
   (`checker execution wiring` and `gates are wired to something` have 5 left,
   `d3` has 40). At the current rate that is under two hours and half a day. I
   have not padded them to buy room.
