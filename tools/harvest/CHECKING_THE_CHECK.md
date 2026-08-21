# Checking the check — seven ways a verification step lied tonight

Companion to `HARVEST_RULE.md`. That file says how to judge a worktree. This one is about
the step *after* judging: the check that says the judgement is sound. Between `jharv2` and
`jharv3`, seven separate checks reported success while doing nothing, or the wrong thing.
**Every one was silent, and every one looked exactly like a pass.**

Written from shard C (`jharv3`, .108) with shard B's findings (`jharv2`, .105) folded in.
Neither of us found all seven alone; each found the other's by re-running our own audit
against the other's description.

---

## 1. A swallowed exit status

`git push … | tail -2; echo PUSHED` prints `PUSHED` for a push that failed — the pipe
discards the status. The one that failed was a 63-parent anchor, so 63 commits would have
sat behind a "preserved" annotation with nothing behind it.

> Check the push **and re-read the ref from the remote** before writing the word "preserved".

## 2. Set-membership standing in for a name test

The audit asked *"is this sha under **some** rescue ref?"* → **120/120** and **46/46** clean,
on two agents' files. Re-run as *"does the ref **this row names** contain the sha **this row
names**?"* → one wrong row each. Same row, `_v1126`, two unrelated bugs.

> A reader follows the **name**, not the set.

## 3. An auditor out of date with its subject

Once the wording gained a second form (*"IS the tip of"* beside *"is a parent of"*), a regex
knowing only the first reported two **correct** rows as broken. Findings from an auditor that
does not understand its subject are indistinguishable from real ones.

## 4. An auditor that drops what it cannot parse

Worse: a `sed` extractor silently omitted rows it could not match — not pass, not fail. The
total just got smaller and cleaner. One pass reported 15 of 92 claims and looked healthy.

> `UNPARSEABLE` is a **finding**. Print it, count it, and require the parts to sum to the whole.

## 5. A vacuous universal

`LANDED` rows said *"every file this branch owns is byte-identical to main"* — and for **8 of
15** the branch owned **zero** files. True of nothing. The same shape bit the duplicate rule
from the other side: a worktree owning nothing hashes an **empty** file list and collides
with every other empty one, which cost five wrong `ABANDON`s.

> Make the claim on something that cannot be empty — the **tree OID**, a recursive content
> hash. Guard duplicates with **owns ≥1 file AND clean worktree**.

## 6. A probe answering from the wrong machine's view — **and it runs both ways**

`refs/remotes` is a **cache of** origin, not origin. Measuring survivability *on* a host reads
that host's memory of the remote:

| direction | measured | consequence |
|---|--:|---|
| host **under**-reports `ON_REMOTE` — clone never fetched the branch | 114 + 47 rows (jharv2) | over-warns; rescue pushes for commits origin already had. Wasteful, safe. |
| host **over**-reports `ON_REMOTE` — tracking ref for a branch origin has since **deleted** | 21 rows (jharv3) | says "safe to delete, it's on the remote" when it is **not**. **Destroys the commit.** |

Both from one root; only the second loses work, and it is the one that looks *safer*.

> The rule is not "measure from one machine". It is **measure against the authority, and name
> what the authority is.** Resolving on one machine fixes *which cache* you read; it does not
> make a cache into the authority. `git ls-remote --heads origin` is the authority; a tracking
> ref is a memory of origin, and it outlives the branch it tracked.
>
> Measured: one clone held **678** tracking refs against **143** live branches — **537 stale**,
> because the fetch had no `--prune`. Another held 143 against 144 live and **0 stale** — and
> that clone had no `--prune` either. It simply had not outlived a branch yet. **A clean result
> from an unsound method is luck, and it should be recorded as luck.**

## 7. A fix applied to the artifact, not to the producer

17 rows named `origin/HEAD` as the ref anchoring their commit. `HEAD` is a **local symbolic
ref** — not a branch on origin, absent from `ls-remote`, and ambiguous to anyone following the
name. This had already been found and fixed once tonight, for 4 rows, **by editing the output
file**. Then main moved, the file was rebuilt from its generator, and the generator put it
straight back — for 17 rows this time.

Nothing errored. No count changed suspiciously. The file simply regressed to the bug it had
already been cured of.

> Fix the **producer**. A fix applied to the artifact survives exactly until the next rebuild,
> and rebuilds are silent. If you must patch output, add the assertion that would catch the
> regression — here, "no row may name a ref absent from `ls-remote`".

---

## The shape they share

In all seven the failing check **printed the same thing as a passing one**. None threw, none
exited non-zero, none looked wrong in a log.

- A check that examined nothing and a check that found nothing are indistinguishable
  **unless it reports how much it examined**. Print the denominator; require the parts to sum.
- Derive an annotation from the **measurement**, not a table beside it. One derived from the
  measurement *cannot* name a ref that does not contain its sha. One from a table can, and did.
- Re-run every audit **after** any wording change, not once at the end.
- Ask which *machine* answered, and whether it was entitled to.
- **Compare sets by name, never by count.** 144 live against 143 tracked looks like a single
  missing ref. The same two numbers are equally consistent with 143 tracked refs that are ALL
  stale and 144 live ones ALL missing. Only a set difference by name tells them apart — the
  same set-vs-name error as #2, one level up.
- **A tool that warns and answers anyway is a tool that lied.** `comm` printed "file is not in
  sorted order" and still produced a clean-looking answer. Treat a warning as a refusal.

## Two operational notes

**A refused push is where the tired move is the forbidden one.** `.102` and `.112` refused
rescue anchors (`version monotonic`, `git prohibition guard`). `--no-verify` was not used.
Two routes that keep the gate: (a) make the anchor a **local** ref with `update-ref`, fetch it
into a clone whose hook passes, push from there — same objects, same bytes, through a gate
that accepts them; (b) for a **single** commit no anchor is needed at all — push the sha
straight to a ref: no identity required and no version gate to trip.

**A rescue an hour old is not a rescue.** Heads move. Two of jharv2's had moved after the
first rescue ran; `AI_IC_design/wt_jwire2` moved twice during shard C. Re-verify preservation
against the *current* head, and record the head each verdict was taken against so the next
reader can tell.

**And main moves.** `origin/main` advanced 30 commits (v1.11.66 → v1.11.68) mid-triage. That
can only turn `RECOVER` into `LANDED`, never the reverse — so it over-keeps rather than
destroys — but a file that does not name the main sha it was judged against cannot be
re-checked at all.
