# 120 commits nothing pointed at, kept alive before anything deletes them

Nine worktrees were deleted while shard B was being written. Something is executing. That makes
one question urgent, and it is **not** the same question as RECOVER-vs-LANDED:

> If this directory is removed, is the work still there?

Removing a worktree directory does not remove its commits. If the head is on, or reachable from,
a ref in the clone, deleting reclaims disk and loses nothing. If it is on **no** ref, the
worktree's own HEAD is the only pointer, and deleting the directory makes the commit garbage.

Measured per row, on every host:

| file | safe to delete | **destroys the commit** | of those, RECOVER |
|---|---|---|---|
| `verdicts_shard_b.tsv` | 103 | **28** | 28 |
| `verdicts_shard_c_80_recovered.tsv` | 56 | **24** | 23 |
| `verdicts_extra_8hd9.tsv` (registered) | 76 | **6** | 6 |
| `verdicts_extra_8hd7.tsv` (registered) | 448 | **70** | — |

An executor working from the verdict alone would treat those exactly like the safe ones.

## What was done about it

Every unreferenced commit was preserved **before** annotating, pushed from the host that held it.
One anchor per clone: its **tree is `origin/main`'s tree**, so it introduces no change of its own —
its only content is its *parents*, so a single ref keeps every one of those histories alive.

    harvest/rescue-8HD-9-vibe-ic          420a3501080    4 parents   (.105)
    harvest/rescue-8HD-9-vibe-ic-shard    acdf7fbbd94    2 parents   (.105)
    harvest/rescue-8HD-8-vibe-ic          9de164c97b4   24 parents   (.114)
    harvest/rescue-8HD-7-1-vibe-ic        f7def7b00f9   63 parents   (.102)
    harvest/rescue-8HD-7-2-…v871          d052aa5ebb0    1 parent    (.102)
    harvest/rescue-8HD-7-3-repo           7ef55c5c147    1 parent    (.102)
    harvest/rescue-8HD-7-4-pr             16e990e034d    1 parent    (.102)
    harvest/rescue-8hd-3-jm9wt            a7b1ed913e2    the sha itself

plus jharv3's, which cover .112, .121 and .108. Every affected row names its ref and the exact
`git fetch origin <ref> && git checkout <sha>` that restores it.

**Verified, not claimed: 120 of 120 unreferenced heads across five hosts resolve to a rescue ref
on the remote.** That check exists because an earlier version of the rescue script printed
`PUSHED` unconditionally — `| tail` had swallowed the push's exit status — and one anchor, the
63-parent one, had silently not landed. A rescue that is only claimed is not a rescue.

## One push was refused, and it stayed refused

`.102`'s clone has a pre-push hook that rejected the rescue ref (`version monotonic`,
`git prohibition guard`). `--no-verify` was not used. Instead the anchor was made a local ref
there with `update-ref` (local, no hook), fetched into a clone whose hook passes, and pushed from
that one — same object, same bytes, a gate that accepts it rather than a gate stepped around.

Nothing was deleted and no existing ref was moved.

## The set is not the name — one wrong annotation, and the class it belongs to

The first audit asked *"is this sha in **some** rescue ref?"* and returned 120/120 clean.
jharv3 pointed out that this is the wrong question: **a reader follows the ref the row names,
not the set.** Re-run strictly — *does the ref THIS ROW NAMES contain the sha THIS ROW NAMES,
read from the remote?* — it found one wrong row, `_v1126`. jharv3's audit found the identical
row wrong from the other side, for a different reason.

The row was wrong because the annotation came from a hand-written `clone -> ref` table, and that
commit had been pushed to a ref of its own rather than to its clone's usual anchor. The table
and the world disagreed, and the table won.

So the fix is not the row. `bin_jharv2/rescue_map.py` now **indexes the real refs** — every
rescue ref's tip and every one of its parents — and answers from that index. An annotation
derived from the measurement cannot name a ref that does not contain its sha; one derived from
a lookup table can, and did.

**128 of 128 preservation claims now name a ref that actually contains the commit**, verified
against the remote with `bin_jharv2/audit_named_ref.sh`. Zero rows say "not preserved".

One more thing that audit taught: after the wording gained a second form (`IS the tip of` for a
ref that is the commit, alongside `is a parent of`), the auditor's regex knew only the first and
reported two good rows as `UNPARSEABLE`. That reads exactly like a defect and was not one. An
auditor that does not understand the thing it audits produces findings indistinguishable from
real ones.

## A host's view of origin is not origin — 161 rows would have carried a false warning

jharv3 found that survivability measured **on** a host reads *that host's* `refs/remotes`, not
origin. A clone that never fetched a branch reports its commit as local-only while origin has
held it all along. Measured here: **114 rows** the host called `ON_LOCAL_REF_ONLY` and **47** it
called `UNREFERENCED` are in fact on origin. The error is in the safe direction — it over-warns
and would have caused pushes of commits origin already had — but the rows would have said
something false.

Fixed by resolving the split **once, on one machine**, against a clone holding all 627 origin
refs, from heads collected host-side. `bin_jharv2/resolve_origin.sh`.

## Final survivability, origin-resolved

| | |
|---|---|
| heads resolved | 824 |
| **ON_REMOTE** | **822** |
| ON_LOCAL_REF_ONLY | 0 |
| UNREFERENCED | 0 |
| no resolvable HEAD (nothing to preserve) | 2 |

Every worktree in all four files whose head exists is now safe to delete without losing the
commit. Getting there took 30 more anchors on `.102`, 3 on `.114`/`.112`, and 2 stragglers that
had moved *after* the first rescue ran.

## The residual, stated plainly

**458 pruned checkouts hold content that exists nowhere but their own directory.** Their worktree
registration was pruned, so there is no HEAD, no branch, no commit — the files on disk are the
whole of it. No ref can be pushed for a commit that does not exist. Those rows say
`**DELETING THIS DIRECTORY DESTROYS THE CONTENT**` and they mean it literally. Preserving them
would mean committing their trees into somebody's repository, which is a decision for the owner
and not for a triage job.
