# Where `108_*` came from, and why they are copied here

These three files are jharv3's, byte-for-byte, taken from `harvest/shard-c-108-jharv3`. They are
copied — not rewritten, not reinterpreted — because that branch is a separate, deletable ref and
every `harvest/rescue-*` ref was deleted from origin on 2026-08-22 (see `../RESCUE_REANCHOR.md`).
Their blob ids are unchanged, so `git hash-object` here equals `git rev-parse` on the source branch.

## What they add that the deliverable did not have

`108_verdicts.tsv` holds **89 decided worktrees on host 108** — jharv3's own note says "All 30
shard-C rows on host 108 are here, plus 59 checkouts the shard list did not name."

**56 of the 89 paths appear in no verdict file in this branch.** They were invisible to anything
reading `verdicts_all.tsv`.

## Why they are NOT merged into `verdicts_all.tsv`

The vocabulary is different: this file says **KEEP (59) / DROP (30)**, while `verdicts_all.tsv` uses
RECOVER / LANDED / ABANDON. `KEEP` maps cleanly to `RECOVER`. **`DROP` does not map cleanly** — it
is deletion-bound, but whether a given row means "already on main" (LANDED) or "worthless"
(ABANDON) is a distinction this file does not draw, and inventing it would put a verdict in another
agent's mouth in the one direction that is unrecoverable.

So they are here, findable and preserved, with the original vocabulary intact. Mapping them into
the consumable is a decision for whoever owns the merge, not for the agent that found them.

## The 30 DROP rows have now been checked

**All 30 measured SAFE** against live main — results in `108_DROP_guard_results.tsv`.

29 by `predelete_guard.sh`: their own change reverse-applies cleanly onto main, so nothing in them
is absent from it. Sixteen of those first refused as *"clone origin/main is stale"* — unmeasurable,
not unsafe — and were fetched **forward** before being judged; a stale ref manufactures a false
LANDED, so refusing was correct and fetching was the fix.

The thirtieth, `gkaudit_mainck`, has **no remote at all**: a standalone repo whose single commit
`ef4e6bcc4b2` is subject *"origin/main snapshot"*. Its HEAD is in no other clone and on no origin
ref, which is the signature of the loss that happened this morning — but its **tree**
`86df130761f` is byte-identical to main commit `74ac9fa788f`, so every byte it holds is already on
main. Nothing to preserve.

Worth recording how close that went the other way: comparing its files one by one against a
*guessed* nearby main commit reported 87 differences. Tree identity is the decisive test; the guess
was the same crude measure that has been wrong four times in this directory today.

That the verdicts are safe does not make the vocabulary mappable — DROP still does not say LANDED
or ABANDON, and that remains the merge owner's call.
