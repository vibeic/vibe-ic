# Checking the check — five ways a verification step lied tonight

Companion to `HARVEST_RULE.md`. That file says how to judge a worktree. This one is about
the step *after* judging: the check that says the judgement is sound. Between `jharv2` and
`jharv3`, five separate checks reported success while doing nothing, or the wrong thing.
**Every one of them was silent, and every one looked exactly like a pass.**

Written from shard C (`jharv3`, host .108) with findings from shard B (`jharv2`, .105)
folded in. Neither of us found all five alone; each of us found the other's by re-running
their own audit against the other's description.

---

## 1. A swallowed exit status

`git push ... | tail -2; echo PUSHED` prints `PUSHED` for a push that failed. The pipe
discards the exit status. The one that failed was the 63-parent anchor, so 63 commits would
have sat behind a "preserved" annotation with nothing behind it.

> Check the push **and** re-read the ref from the remote before writing the word "preserved".

## 2. Set-membership standing in for a name test

The audit asked *"is this sha under **some** rescue ref?"* → **120/120 clean** and
**46/46 clean**, on two different agents' files. Re-run as *"does the ref **this row names**
contain the sha **this row names**?"* → one wrong row on each side. It was the same row,
`_v1126`, reached by two unrelated bugs.

> A reader follows the **name**, not the set. Test what the row actually says.

## 3. An auditor out of date with its subject

Once the wording gained a second form — *"IS the tip of"* beside *"is a parent of"* — a
regex that knew only the first reported two **correct** rows as broken. Findings from an
auditor that does not understand its subject are indistinguishable from real ones, and two
good rows were nearly "fixed".

> When the thing being audited changes wording, re-run the auditor **and** confirm its
> finding count moved for a reason you can name.

## 4. An auditor that drops what it cannot parse

Worse than 3: a `sed`-based extractor silently omitted rows it could not match. They
appeared in no column — not pass, not fail. The total simply got smaller and cleaner.

> `UNPARSEABLE` is a **finding**, not a skip. Print it, count it, fail on it.

## 5. A vacuous universal

`LANDED` rows said *"every file this branch owns is byte-identical to main"*. For **8 of 15**
the branch owned **zero** files, so the claim was true of nothing. The same shape bit the
duplicate rule from the other side: a worktree owning nothing hashes an **empty** file list,
so it collides with every other empty one and reads as "byte-for-byte identical" — that cost
five wrong `ABANDON`s.

> An "all X are Y" claim over an empty set is worthless. Either state the count and let a
> zero be visible, or make the claim on something that cannot be empty — the **tree OID**,
> which is a recursive content hash and covers a tree that owns no files.
> The duplicate rule needs the same guard: **owns ≥1 file AND clean worktree.**

---

## The shape they share

In all five, the failing check **printed the same thing as a passing one**. None threw, none
exited non-zero, none looked wrong in a log.

- A check that examined nothing and a check that found nothing are indistinguishable
  **unless the check reports how much it examined.** Print the denominator.
- Derive an annotation from the **measurement**, not from a lookup table beside it. An
  annotation derived from the measurement cannot name a ref that does not contain its sha.
  One derived from a hand-maintained table can, and did.
- Re-run every audit **after** any wording change, not once at the end.

## One more, specific to this fleet

Survivability measured **on** a host is that host's *view* of origin, not origin. A commit
can be on `origin/<branch>` while that host's clone has never fetched it, so the host-side
probe reports `ON_LOCAL_REF_ONLY`. That errs toward caution, but do not read it as
"not on the remote" — confirm against origin before acting.
