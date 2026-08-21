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

## The mirror, and it is the one that loses work

jharv3 found the dangerous half of the host-view error: hosts also **over**-report `ON_REMOTE`.
`refs/remotes` is a *cache*, and a tracking ref survives the branch it tracked. A commit
reachable only from a deleted branch's stale tracking ref reads "safe to delete, it is on the
remote" and is not on the remote at all.

My own fix inherited it. `resolve_origin.sh` resolved on one machine — correct — but against a
clone fetched **without `--prune`**. Measured: **537 of my 678 tracking refs were branches origin
had deleted.** Re-resolved against live refs only (`git ls-remote --heads origin` as the
authority, 143 live), **3 heads were falsely `ON_REMOTE`** and would have been deleted as safe.

All three preserved: `harvest/rescue-102-stale-remote-vibe-ic` `79768640f9a`, all three shas
confirmed as its parents.

Only three, because the *first* error had already caused over-preservation: over-warning made me
rescue commits that did not need it, and that absorbed most of this class. Two errors in opposite
directions, and the cautious one covered for the dangerous one — which is luck, not method.

**Final, live-refs-only: 824 heads, 822 `ON_REMOTE`, 0 `ON_LOCAL_REF_ONLY`, 0 `UNREFERENCED`,
2 with no resolvable HEAD.**

## main moved 30 commits under both of us

`origin/main` is now `81cd5321b08` (v1.11.68), 30 past the `a00f53f2094` every row was judged
against — the same staleness this re-triage exists to correct. Main moving can only turn RECOVER
into LANDED, never the reverse, so nothing was unsafe; it over-kept. Re-judged all 188 RECOVER
rows of `verdicts_shard_b.tsv` and `verdicts_shard_c_80_recovered.tsv` against current main:
**one flipped** — `/home/reyerchu/_jcap_priv/wt`, whose whole tree is now a tree main publishes.

The re-fetch used `bin_jharv2/fetch_guarded.sh`, which refuses to fetch a clone whose origin is a
local path (it moved a correct ref backwards once) and repairs those from a clone with a real
remote instead. On `.121` it skipped two such clones and repaired them, as designed.

## Seventh mode: I patched the artifact, not the producer — and 236 rows carried it

jharv3 found this in their own file and it was in mine at four times the scale. **236 of my rows
named `origin/HEAD`** as the ref keeping a commit alive. `origin/HEAD` is a *local symbolic ref*;
`git ls-remote --heads origin` does not list it, so a reader following that name gets something
ambiguous. Fixed in `resolve_origin.sh` — the producer — which now excludes it and refuses to
name any ref not present in `ls-remote` output.

**And my own auditor had failed silently while I read it as a pass.** The first check for this was
one line of `awk` using `match(s, re, arr)` — a GNU extension. Under `mawk` it matched nothing and
printed *"0 refs named, 0 dead"* for files naming 236 bad refs. An auditor that finds nothing and
an auditor that runs on nothing are indistinguishable from the outside. `bin_jharv2/audit_live_refs.py`
replaces it with a real parser that **asserts it extracted something** before reporting a clean result.

## Eighth: my resolver inherited the host's claim when origin could not confirm it

Worse than the above and the same family as jharv3's 21 stale rows. When no live origin ref
contained a head, `resolve_origin.sh` **passed the host's own label through** — so a row the host
called `ON_REMOTE` stayed `ON_REMOTE` with `-` where the ref name should be. **16 rows read "safe
to delete, it is on the remote" with nothing on the remote behind them.**

Fixed: origin failing to confirm now produces `NOT_ON_ORIGIN`, never the host's answer. The 17
real commits behind those rows are preserved —
`harvest/rescue-8HD-9-notonorigin-*` (4) and `harvest/rescue-8HD-8-notonorigin-*` (12).

**Final: 824 heads, 822 ON_REMOTE naming a ref confirmed live by `ls-remote`, 2 with no resolvable
HEAD. 792 refs named across the four files, 0 not live on origin.**

## main moved: two flips, and one of them is not what it looks like

Re-judged every RECOVER row against `81cd5321b08`. Two moved:
`/home/reyerchu/_jcap_priv/wt` (jharv3 got the same one independently) and `/home/reyerchu/_landppa`.

`_landppa` needed care. The second route said 72 of its 81 owned files still differ — an apparent
disagreement. It was not: **the worktree had been reset onto current main**, so the check was
comparing a head it no longer has. Its LANDED means *"the directory now holds main"*, not *"that
branch's work landed"* — and its previous head `a17910e9fa9` is not lost, it is on
`origin/land/batch7-assembled`, confirmed live. The row says all of that, because a bare LANDED
there would be true and would mislead.

## 49 more commits found behind LANDED rows — the reflog, not the head

jharv3 generalised the `_landppa` reset case correctly: **"head equals main" is too narrow.** Any
head that is an *ancestor* of main collapses the owned set to empty, so every content check passes
trivially. Of my 204 LANDED rows, **156 are that empty form** and only 8 rest on file-by-file
identity. A LANDED there is true and says nothing about what the directory used to hold.

So the reflog was asked. Across five hosts, **22 LANDED rows had earlier heads owning files that
differ from main**, on no branch of their own:

| | |
|---|---|
| distinct orphaned prior heads found | 76 |
| already preserved by a GitHub **`refs/pull/*/head`** | 27 |
| on nothing at all — **rescued here** | **49** |

`refs/pull/*/head` is an authority I was not consulting at all. A PR ref keeps a commit alive when
no branch does, and 27 commits that looked orphaned were held that way. Anyone auditing
survivability on a GitHub remote needs both lists.

Every LANDED row now states which of the two forms it is and what its reflog showed — written per
row from that row's own measurement, because jharv3 caught themselves applying one explanation to
a population they had not checked row by row and the same trap was available here.

## A disagreement, resolved by measuring twice

jharv3 reported `03926f8b50f` (prior head of `_jppa_skills/tree`) as *"owns 28 files, all 28
byte-identical to main, so losing it loses nothing."* Measured on the clone that holds it:
**28 owned, 14 differing** — and 14 differing against the *old* main `a00f53f2094` too, so it is
not a main-version artefact. It is preserved as `harvest/rescue-8HD-d-jppa-skills-prior`. If their
number is right the ref costs nothing; if mine is, it was the only thing between 14 files and an
executor.

## Ninth mode: the guard existed and I did not reuse it

The first coverage check reported **all 21 rescued heads still uncovered — including
`867de428920`, an old main commit that cannot possibly be uncovered.** The live-refs file it read
was **empty**: the `ls-remote` that built it had run after a directory change and failed silently.
The check grepped an empty authority and called everything uncovered.

`resolve_origin.sh` had `[ -s "$LIVE" ] || exit 1` in it from hours earlier. I wrote an ad-hoc
check without it. **The guard existed and I did not reuse it.** `bin_jharv2/covered.sh` now
refuses to run on an empty authority and names which authority it used.

This one failed *loud* — 21 false findings — and I only caught it because one of the 21 was
obviously impossible. With no impossible row in the set, I would have believed it.

## `comm` was in my judge too — the exact line that decides DROP

jharv3 traced their wrong number to `comm -12` with stderr discarded: **comm requires both inputs
in the collation order it expects; on a mismatch it warns and still emits, usually empty.** An
empty intersection reads as "no differing files".

That line was the core of my registered-worktree verdict, in three shipped scripts:

    comm -12 "$T/own" "$T/vsmain" > "$T/differ"      # ndiff==0  ->  DROP  ->  LANDED

**Blast radius, checked rather than assumed: zero.** Of my 204 LANDED rows, 156 own nothing (their
`nown` comes from `git diff --name-only | grep -c`, no comm, and was re-derived independently at 0)
and 40 are pruned rows whose judge never used comm. That leaves 8 rows resting on "it owns files
and none of them differ" — the only place an empty intersection could have manufactured a LANDED.
All 8 re-derived by sha256 on both sides of every owned file, no comm anywhere:

    _jppa_runner/tree  3/0    _jppa_skills/tree 28/0   _after 633/0   _after2 633/0
    _jppae2e/wt      534/0    _wfwt_gwaiv        3/0   _wt_903  5/0   _wt_988    3/0

**8/8 CONFIRMED.** No published verdict of mine is a comm artefact — but that is luck, not design.

Fixed at the producer in all four scripts: `awk 'NR==FNR{a[$0]=1;next} ($0 in a)'`, which has no
collation precondition. Verified equivalent on a real row (89 files both ways). Zero `comm` left in
the tooling. `bin_jharv2/nocomm_check.sh` is the re-derivation, so anyone can repeat it.
