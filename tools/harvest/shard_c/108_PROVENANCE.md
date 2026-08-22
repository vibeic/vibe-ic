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

**30 of these rows authorise deletion and none of them has been checked by
`bin_jharv2/predelete_guard.sh`.** Run it before acting on any of them.
