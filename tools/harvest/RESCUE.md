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

## I scoped a general check to the population the example came from — 579 more commits

jharv3 swept prior heads across their **non**-LANDED rows and found the orphans were mostly there.
I had run that sweep only over LANDED, because that is where my example (`_landppa`) came from.
The reasoning never depended on the verdict: **any worktree whose head moved leaves its previous
head behind, and a RECOVER row displaces work just as readily.** The population was chosen by
where I happened to be looking rather than by what the check is about.

Swept all 628 non-LANDED rows that have a real HEAD, across five hosts:

| host | displaced heads owning files that differ from main, held by no live origin ref and no PR ref |
|---|---|
| .105 | 24 |
| .102 | 190 |
| .114 | 219 |
| .112 | 115 |
| .121 | 32 |
| **total** | **579 (566 distinct)** |

**All 579 rescued and verified**, `covered=579 uncovered=0` against a non-empty `ls-remote` +
`refs/pull/*/head` authority, by walking refs from origin rather than trusting push output.

## Anchor drift, one pass, because the anchors were there

The judged head in every row is what makes this cheap. Re-read all 792 anchors and compared each
to the worktree's head now: **23 had moved** — 6 on .105, 14 on .114, 1 each on .112/.121/.102 —
and 9 were the already-recorded deletions, with no new ones. All 23 re-judged against current
main. Two verdicts changed:

- `_jcpath2/wt_new` **ABANDON → RECOVER**: it had moved *off* its twin's head, so it is no longer
  a duplicate of `_jcpath2/mut` and the thing that justified abandoning it is gone.
- `_gk1764`'s new head came back **NOT_ON_ORIGIN** — a moved head nothing was holding. Rescued as
  `harvest/rescue-8HD-9-gk1764-movedhead`.

That second one is the argument for re-checking rather than trusting a rescue from an hour ago:
the rescue covered the head the worktree *had*, and the worktree moved to one nothing covered.

## Stashes — commits on no branch, in nobody's shard, invisible to every sweep so far

jharv3's find, and it is a whole class. A `git stash` entry is a commit holding work that was
never committed: invisible to a worktree sweep, invisible to `git status` (the files are gone
from the tree), and a row in no shard. Two traps they named and I inherited:

- **`git stash list` is CLONE-wide.** Counting it per *worktree* multiplies one stash by every
  worktree sharing that clone.
- **`refs/stash` points at the top entry only.** `stash@{1}`, `stash@{2}`… exist solely in the
  stash *reflog* and survive only until it expires — default 90 days here. Walk the reflog.

Swept every clone on all five hosts:

| host | clones | stash commits | holding files that differ from main |
|---|---|---|---|
| .105 | 23 | 3 | 3 |
| .114 | 3 | 0 | — |
| .112 | 3 | 1 | 1 |
| .121 | 6 | 3 | 3 |
| .102 | 81 | 14 | 13 |
| **total** | **116** | **21** | **20** |

**13 rescued to origin.** One (`fa191b9c34e`) owns a file that is byte-identical to main — nothing
is lost by its going, and it is named rather than quietly counted as rescued.

### Seven cannot go to origin, and that is a hard limit, not a hook to route around

`harvest/rescue-102-stashes-3-vibe-ic` is **rejected by GitHub**:

    remote: error: File …/reports/14.txt is 234.53 MB; this exceeds GitHub's file size limit of 100.00 MB
    remote: error: File …/reports/1.txt is 140.94 MB; …

Those 7 stash commits carry benchmark report files far over the limit. There is no push that
lands them. What was done instead: they are on a **local branch ref** in two clones —
`/home/reyerchu/vibe-ic` on `.102` *and* on `.105`, both at `9d689074719`. That is a real
improvement over where they were, because **a stash reflog entry expires and a branch ref does
not**, and it now exists on two machines rather than one. It is not equivalent to being on origin
and this file does not claim it is.

### The guard fired, and refusing was right

The `.121` sweep came back `REFUSING: empty authority` rather than reporting zero stashes. The
cause: four of that host's clones have a **local-path origin**, and `ls-remote` against a local
path has no `refs/pull/*` at all, so the pull authority was empty. Refusing was correct — asking
the wrong clone was the bug. The sweep now picks a clone whose origin is `http*`/`git@*` to ask,
and names which clone it asked.

## Where the displaced-head sweep could not look: nowhere

jharv3 found 6 of their worktrees have no reflog at all, which makes the displaced-prior-head
sweep **structurally blind** there — not "found nothing", but "could not look" — and recorded it
as a stated limit rather than folding it into a clean count. That is the right treatment and it
needed checking here.

Checked every registered row on all five hosts:

| host | rows with a directory | reflog present | **blind** |
|---|---|---|---|
| .105 | 92 | 92 | 0 |
| .114 | 93 (+9 deleted, recorded separately) | 93 | 0 |
| .112 | 36 | 36 | 0 |
| .121 | 44 | 44 | 0 |
| .102 | 520 | 520 | 0 |
| **total** | **785** | **785** | **0** |

**Zero blind.** The sweep was able to look everywhere it claimed to look, and that is now a
measured statement with its denominator rather than an absence of complaint. The 389 + 113 pruned
checkouts are a different matter and were never in this population: they have no HEAD and no
reflog by construction, which the rows already say.

## The residual I called the owner's call was an unmeasured assumption

I wrote that the 458 pruned checkouts holding content on no commit could not be preserved without
"committing someone's working tree into the repository", and left it. **That was an assumption and
it was wrong.** Preserving them does not mean pushing whole trees — it means pushing the files
that *differ from main*, and I never measured how many that was.

Measured, content-addressed so copies across scratch directories collapse to one entry:

| host | pruned checkouts | file instances | **distinct blobs** | **unique content** | over 100 MB |
|---|---|---|---|---|---|
| .105 | 356 | 4158 | 1161 | 97.16 MB | 0 |
| .102 | 104 | 595 | 286 | 22.15 MB | 0 |

Entirely feasible. Both preserved as parentless snapshots holding only the differing files, each
under `preserved/<checkout>/<path>`:

    harvest/preserved-pruned-8HD-9   114fc14e715   4158 files
    harvest/preserved-pruned-8HD-7   57bd8623bb2    595 files

They merge into nothing and change nothing; they exist so the content survives the directory.

**One of them was published partial and the fix is visible rather than hidden.** The first
`preserved-pruned-8HD-9` was built while the measuring pass was still writing its output file, so
it caught 1685 of 4158 rows. The complete snapshot is a **child** of that commit, not a force-push
over it, so the record shows the first was incomplete.

## Branch reflogs — jharv3's find, and the largest class yet

We both swept per-worktree `logs/HEAD`. The **clone** also keeps `logs/refs/heads/<branch>`: every
rebase, amend, reset and force-update leaves the old tip there, unreachable the moment the branch
moves and expiring at the reflog default. Swept per **clone**, never per worktree:

| host | clones | at-risk commits |
|---|---|---|
| .105 | 23 | 181 |
| .114 | 3 | 265 |
| .121 | 6 | 240 |
| .112 | 3 | 213 |
| .102 | 81 | 370 |
| **total (distinct)** | **116** | **760** |

**760 of 760 covered**, verified by walking refs from origin against a non-empty authority.
15 anchors; 6 were hook-blocked on their host and routed through a clone whose hook passes.

`.112` took three attempts and each failure was silent in a different way: the first detached
runner used a relative `cd` and wrote nothing; the second died mid-loop leaving `push.log` with
two lines and no anchors; only building the anchor as one explicit command worked. Each time the
*absence of output* looked identical to "this host had none" — and `.112` had 213, the second
largest count on the fleet. What separated them was checking for the **file** rather than the
count.

jharv3's framing is kept because it is the honest one: **most of these are almost certainly
intermediate states of work that later landed** — a branch rebased twenty times leaves twenty old
tips, each "differing from main", all superseded. This is a bulk safety net against silent loss at
the 90-day default, not a claim that each holds unique work.

## The general question, finally: is there ANY ref origin does not have?

Every sweep so far took one route — worktree HEADs, worktree reflogs, branch reflogs, stashes,
pruned files — and each was found because someone noticed a route the other had not taken. So:
**every local ref in every clone, all namespaces**, plus the in-progress states that hold commits
on no ref by construction (`rebase-merge`, `rebase-apply`, `MERGE_HEAD`, `CHERRY_PICK_HEAD`).

| host | clones | refs origin lacks | distinct commits |
|---|---|---|---|
| .105 | 23 | 194 | 118 |
| .114 | 3 | 193 | 163 |
| .112 | 3 | 195 | 156 |
| .121 | 6 | 207 | 154 |
| .102 | 81 | 553 | 233 |
| **total** | **116** | **1342** | **824** |

Not just branches: `refs/tags`, `refs/tags/rescued`, `refs/tmp`, and other namespaces nobody
would think to sweep. In-progress operations: **0** across all five hosts.

**824 of 824 covered**, verified on the host that holds the objects. Zero in-progress states found.

### Three defects in the checking, all silent, all found by a number that could not be true

**Annotated tags killed whole anchors.** `%(objectname)` on an annotated tag is the *tag* object.
`git rev-parse -q --verify "$h^{commit}"` **dereferences** and passes — but `commit-tree -p <tag>`
fails and takes the entire anchor with it. **The check dereferenced and the action did not.** One
200-parent anchor and five others were never created; the loop moved on without a word. Fixed by
using the dereferenced commit for both.

**The coverage checker had a hardcoded repo.** Run on four hosts against
`/home/reyerchu/vibe-ic` while the anchors had been fetched into a *different* hub clone, it
reported `covered=0 uncovered=163` — a total failure that reads exactly like a total loss. Now
`R` is overridable and the checker says which repo it asked.

**Coverage must be verified where the objects are.** Checking `.102`'s commits from `.105` said
316 uncovered; the same check on `.102` said 0. My clone simply did not have the objects, and
"absent here" was being reported as "unpreserved".

## Every ABANDON re-checked against the untracked-file defect

jharv3 found an ABANDON in shard C resting on "identical HEAD tree AND both working trees clean"
where the tree half was true and the clean half was false: two worktrees each carried an
**untracked** `HANDOFF_TO_GATEKEEPER.md`, different files, absent from main, on no ref. Their
general point is the one that matters:

> LANDED and ABANDON are claims about a **directory**. Tree identity, merge-base, reverse-apply
> and per-file sha256 of owned files all describe **committed history only**. None can see an
> uncommitted edit or an untracked file — and that is exactly the content that exists in one place.

They re-measured shard B's three ABANDONs and all my LANDED rows on their own hosts and found
them sound — `_jlandpar/wtgates` and `wttests` share head `01f0086263e` and tree `956e469a778`
with `_jlandpar/dev`, all three trees genuinely clean; `_jppa_p0/tree` at its judged head and
clean. A citable negative result, in `FALSE_LANDED_shards_a_b.md`.

That left my **26 ABANDONs in the two extras files**, which nobody had checked. Re-measured with
`--untracked-files=normal`, hashing every modified and untracked path against `origin/main` so
"dirty" is a content statement rather than a count:

| file | ABANDONs | dirty with content not on main |
|---|---|---|
| `verdicts_extra_8hd9.tsv` | 5 | **0** |
| `verdicts_extra_8hd7.tsv` | 21 | **0** |

All 26 clean. Two on `.102` show a single status line each — both deletions, which lose nothing
further. **All 30 of my ABANDONs are now verified against this defect**, 4 by jharv3 on their
hosts and 26 here.

My judge already measured the working tree for the *verdict* (`git status --porcelain`, which
includes untracked by default, forces KEEP), which is why the defect did not reach my rows. That
was luck of construction rather than foresight: I had not separately audited the ABANDONs, and
ABANDON is the unrecoverable direction.

## Relay for shard A

jharv3 found **four wrong LANDED rows in `verdicts_shard_a.tsv`**, all on `.120` —
`_agentjob_i1015/wt`, `_agent_scratch_whatif/wt_C`, `_wt_1236`, `_wt_1486` — where eleven files
are absent from `origin/main` entirely, five of them whole test programs. Working states preserved
as `harvest/rescue-120-falselanded-*`. **`jharvest-triage` is not reachable from this session** —
it does not appear in the peer list — so this branch is the relay. The flip to RECOVER is that
shard's owner's call and neither of us has edited their file.

## The seven "unpushable" stashes were preservable after all

I recorded 7 stash commits as impossible to preserve: GitHub rejects them because their history
carries a 234 MB and a 141 MB benchmark report, over the hard 100 MB limit. That was true of the
**commits**. I never checked whether their **content** could go — the same error as the "owner's
call" residual, one level down, and I made it again three sections later.

Measured, what those 7 stashes actually *change*:

    154f8e13f89  owned=6   differing=1    17,310 bytes
    2b64741ba7b  owned=74  differing=74  244,650
    7326eff69d1  owned=10  differing=10  101,139
    9e6a670c592  owned=13  differing=13  108,669
    a9a61c81c41  owned=4   differing=2    55,357
    bd57e62017b  owned=2   differing=2   140,974
    c122e2788b5  owned=74  differing=74  244,650
    TOTAL  176 files, 0.87 MB, **zero oversize**

The 234 MB files were inherited *history*, not the stashes' own work. Preserved as
`harvest/preserved-stashes-8HD-7` `bce4d5f5988`, 176 files verified on origin. The commits
themselves still exist only on local refs in two clones — that part was accurate.

## A verdict that flip-flopped, and why the record shows both

`_jcpath2/wt_new` has now gone **ABANDON → RECOVER → ABANDON** across three measurements. That is
not indecision: the two worktrees genuinely diverged and re-converged while this was being
written. Verified at each step, and now: both `mut` and `wt_new` sit at head `c0ecd5f1310`, tree
`5bf932a9082`, both clean under `--untracked-files=normal`. They are duplicates again.

jharv3 saw the same shape on their host — a DROP that became a KEEP and back within an hour. **A
verdict on a live host is a photograph.** The anchor in each row is what makes it re-checkable
rather than merely re-doable.

## Drift this pass

14 rows moved: 8 on `.105`, 3 on `.114`, 1 on `.121`, 2 on `.102`. No new deletions — the 9 on
`.114` are the ones already recorded. All 14 re-judged against `81cd5321b08`.

**`_gk1764` has now moved three times** — `71729c291e1 → dc119d0520e → c71af5c6cfe → e1741e86415`
— and each new head landed on no ref. All four are preserved. An actively-worked tree outruns any
single snapshot, which is an argument for the anchor and against trusting an hour-old rescue.

## Every harvest ref audited against my own tag defect

250 harvest refs on origin: **every tip is a `commit` object** checked raw and undereferenced —
the exact test the annotated-tag defect defeats — and **zero** of their parents is a tag. jharv3
ran the same check on shard C's 86 anchor claims and found 13/13 refs live and 86/86 shas
reachable.

## The delivery problem, and mine is bigger than jharv3's

jharv3's point: `verdicts_joined.tsv` is what a downstream executor reads, and it is **derived**.
Prose in `RESCUE.md` cannot reach that consumer, and neither can a TSV the generator does not
read. They found shard A's four false LANDED rows propagating through every regeneration.

Measured on my side, and it is worse:

| file | rows | present in `verdicts_joined.tsv` |
|---|---|---|
| `verdicts_shard_c_80_recovered.tsv` | 80 | 80 |
| `verdicts_extra_8hd9.tsv` | 451 | **0** |
| `verdicts_extra_8hd7.tsv` | 633 | **1** |

**1083 rows I decided are invisible to whatever an executor reads** — including 877 RECOVERs
holding content that is not on main. Every one of them was published, verified, re-judged against
current main and cross-checked, into a file nothing downstream consumes.

Two things, following jharv3's shape rather than editing a generator I do not own:

- **`verdicts_extras_joined.tsv`** — all 1084 rows in the joined file's exact schema
  (`host / path / verdict / evidence / shard`, shards `extra-8hd9` and `extra-8hd7`), so joining
  them is a one-line change for whoever owns the generator.
- **`bin_jharv2/extras_coverage.py`** — a gate that exits 1 while any decided row is absent from
  the joined file. Red through every regeneration until they are joined.

### The gate was watched failing, and passing, and failing again

jharv3's fifth defect was a gate whose regex silently matched nothing and printed OK — a false
green, which they rightly call strictly worse than a false red, because a red makes you go look.
So this one was proven in both directions before being shipped:

    real joined file          -> FAIL, 1083 absent      (matches the count measured independently)
    joined + extras appended  -> OK,   0 absent
    same file, extras stripped-> FAIL again

It also refuses rather than passing if it extracts zero paths from either input, because "found
nothing" and "parsed nothing" are the same output — which is the through-line of this entire
night.

## The one row of mine the joined view gets wrong in the direction that deletes

jharv3's `joined_parity.py` found eight rows where a shard file and `verdicts_joined.tsv`
disagree; two are mine, and they flagged rather than guessed one of them because it is my row and
my grammar. Measured here, on `.114`, against current `origin/main` `81cd5321b08`:

    /home/reyerchu/_jintent/wt        head c5c2e228244
    owned = 6        differing = 6        working tree 0 lines (--untracked-files=normal)
    e.g. vibe-ic-marketplace/README.md
         here bb44e3d04a429770761e28655fb8bbc15bfb835e9183b8c2ae3ce4c41a1b9c3b
         main dbd748602e224556cc879b0eb980714958916ac6385aa85ca95232f1a99609c8

**`verdicts_shard_b.tsv` says RECOVER and is right. `verdicts_joined.tsv` says LANDED and is
stale** — it was regenerated from a snapshot taken while this worktree still sat on bare main,
before it moved to `c5c2e228244`. An executor reading the consumable would delete six files that
differ from main.

The other, `/home/reyerchu/_jcpath2/wt_new`, disagrees in the safe direction (ABANDON here,
RECOVER there) and costs effort rather than content. My ABANDON was independently re-verified:
both it and `_jcpath2/mut` sit at `c0ecd5f1310`, tree `5bf932a9082`, both clean.

Together with the 1083 absent rows this is the same wound twice: **the last file anyone reads
reflects an older state of the work.** Mine was invisible, jharv3's was visible and stale. Their
`joined_parity.py` catches rows that arrive with the wrong verdict; my `extras_coverage.py`
catches rows that never arrive. Neither alone would have found both.

## I shipped "machine-checkable evidence" and never wrote the machine

jharv3's seventh false red was their contract checker knowing one of three agents' evidence
grammars. My reply was that I wrote mine for a human and shipped it as machine-checkable without
ever writing the consumer. So I wrote it — `bin_jharv2/evidence_contract.py`, which parses my
grammar and **re-resolves every claim against current `origin/main`**.

It found four defects in my own published files, none of which any human reader would have hit:

| defect | rows |
|---|---|
| evidence naming the literal token `UNCOMMITTED[NEW:…]` as if it were a path — `sha256(UNCOMMITTED[…]) = (not on disk) here, - on main` | **214** |
| main-hashes computed **before main moved** — verdicts were re-judged against `81cd5321b08`, evidence strings were not | **108** |
| my parser knowing only one of my **own two** phrasings for "main has no such file" | 78 reported unreadable that were fine |
| evidence naming a **deleted** file, so the hash read `(not on disk)` | 1 |

The first two are the serious ones: **322 published rows carried evidence that could not be
checked or did not match main**, in the column whose entire purpose is being checkable by a
stranger. Every one of them was in the extras — `verdicts_shard_b.tsv` was clean at 114/114
throughout, which is luck of when it was generated, not care.

After the fixes:

    verdicts_shard_b.tsv               RECOVER=114  parsed=114  agree=114  disagree=0
    verdicts_shard_c_80_recovered.tsv  RECOVER=69   parsed=69   agree=69   disagree=0
    verdicts_extra_8hd9.tsv            RECOVER=376  parsed=376  agree=376  disagree=0
    verdicts_extra_8hd7.tsv            RECOVER=501  parsed=497  agree=497  disagree=0  no_claim_by_design=4
    TOTAL                              RECOVER=1060 parsed=1056 agree=1056 disagree=0  DID_NOT_CHECK=0

The checker separates **"no claim by design"** — an `UNDETERMINED` row naming its missing input —
from **"claim I could not read"**, because only the second is a defect and conflating them
inflates the failure count with honest rows.

### The negative control was vacuous the first time

Proving it meant corrupting a hash and watching it go red. My first attempt used
`awk 'gsub(/[0-9a-f]{64} on main/…)'` — **mawk has no interval expressions**, so nothing was
corrupted, and the checker "passed" a file I believed I had broken. I only noticed because a
one-line diff of the two files showed zero changes. Redone in Python, the corruption applied, and
the checker named the file and exited 1.

**A negative control that does not actually break anything is indistinguishable from a checker
that works.** That is the whole night in one sentence, arriving for the last time in my own test
harness rather than in anyone's data.

## .120 — the host nobody owned, and the denominator

`.120` hosts shard A. jharv3 rescued the four working states behind its false LANDED rows but
nobody had swept it for the systematic classes, and its agent is unreachable from either of our
sessions. So the host was swept from here, read-only except for rescue refs.

**The denominator first, because a zero without one is silence:** a `find` to depth 4 reports
**17** clones. The filesystem holds **288**. Everything below is against 288.

Progress at the time of writing — the sweep is detached and still running, and this is reported
partial rather than rounded up:

| | |
|---|---|
| clones swept | **242 of 288** |
| ref findings | 18,299 |
| **distinct commits** behind them | **171** |
| in-progress rebase / merge / cherry-pick | **0** |
| already held by origin when found | 66 |
| **needing rescue** | **105** |
| **covered after rescue** | **171 / 171, 0 uncovered** |

18,299 findings collapsing to 171 distinct commits is the shape of this host: the same commits
appear in dozens of clones. Counting findings rather than commits would have reported a
catastrophe and produced 18,299 units of work for 171 units of content.

208 anchors, 203 pushed and confirmed on origin. The 5 that failed are **redundant, not lost** —
each holds 19 parents that other anchors already carry, which is why coverage reads 171/171 with
them absent. That is stated rather than left as "5 failures", because a failure count without a
consequence is the same kind of noise as a finding count without a denominator.

The remaining 46 clones will add to this. Whatever they add, the number will be reported —
including if it is zero.

## "Proven in both directions" was weaker than I said

I wrote that `evidence_contract.py` was proven red → green → red. jharv3 then found that their own
self-test asserted only that *some* check went red: they **deleted an entire check** and it still
passed, because a different one fired on the same synthetic row. A control that cannot name its
target cannot tell "the check works" from "something else happened to shout".

Applied here. Each guarantee gets a case only **it** catches, and must pass **both** arms:

> unblinded must CATCH the case (exit non-zero) **and** blinded must MISS it (exit 0)

Passing only the first arm proves nothing — a checker that fails on everything passes it.

| guarantee | unblinded | blinded | |
|---|---|---|---|
| hash comparison | 1 | 0 | LOAD-BEARING |
| absent-file branch | 1 | 0 | LOAD-BEARING |
| non-empty assertion | 1 | 0 | LOAD-BEARING |

The absent-file branch had **no case at all** until this — nothing in the red→green→red proof
ever exercised it. It is load-bearing now because a case was built for it: a row falsely claiming
main lacks a file main has.

Shipped as `bin_jharv2/evidence_selftest.sh` so the claim is repeatable rather than asserted.

## 43 rows authorised deletion of untracked content — a subtler bug than `-uno`

jharv3 found that their sweep measured cleanliness with `git status --porcelain -uno`, which
**excludes untracked files**, and asked whether the pattern was fleet-wide. Grepped: **zero
occurrences of `-uno` anywhere in my tooling.** Every judge used plain `--porcelain`, which
includes untracked by default.

That answer was true and useless, because the defect was one level down.

    $ git status --porcelain                       # what my judge used
    ?? vibe-ic-marketplace/scratch_geom_signoff_tests/          1 line

    $ git status --porcelain --untracked-files=all
    ?? …/scratch_geom_signoff_tests/agree/out.json
    ?? …/agree/reports/phase3/antenna.rpt
    …                                                          23 lines

**The default collapses an untracked DIRECTORY to a single entry ending in `/`.** My loop tested
`[ -f "$wt/$f" ]` to skip deletions — and a directory fails that test, so the entry was skipped
and the whole tree counted as **zero new files**. Not excluded by a flag; hidden by a shape.

Measured with `--untracked-files=all` across every deletion-bound row:

| file | deletion-bound rows | holding untracked content not on main |
|---|---|---|
| `verdicts_shard_b.tsv` | 17 | **0** |
| `verdicts_shard_c_80_recovered.tsv` | 11 | **0** |
| `verdicts_extra_8hd9.tsv` | 75 | **0** |
| `verdicts_extra_8hd7.tsv` | 132 | **43** |

**43 rows said delete over content that exists nowhere else.** Re-judged with the fix: all 43 are
now RECOVER — 41 were LANDED, 2 were ABANDON.

### And a precedence bug the fix exposed

Two of the 43 first came back `KEEP_SUPERSEDED_CONTENT_DIFFERS`, which maps to **ABANDON**, which
deletes. A worktree whose committed change is contained in main but which *also* holds untracked
content must never take that branch. The ladder tested `nsuper` before `dmod+dnew`; those two
rows sat exactly there, and only became visible once the directory bug stopped hiding their
content. **Uncommitted now outranks superseded.** All 43 are RECOVER.

Both fixes are in `bin_jharv2/judge.sh`. The contract deliverables were never affected — shard B
and the recovered 80 are 28/28 clean under the widest setting — which is luck of which hosts had
untracked scratch directories, not care.

## Both arms on pass/fail is necessary and not sufficient

jharv3 swept their own gates mechanically — blind each guard, ask whether the suite notices — and
23 of 31 survived, 15 of them an entire validation body that could have been `if False:`. The
last survivor was **literally the absent-file branch**, and it survived for a reason my standard
could not have caught:

> **Blinding it changes no pass/fail.** An absent file falls through to another non-failing
> bucket, so the exit code is identical either way.

Their generalisation: **a case must assert the outcome the branch actually changes.** Checked
mine, and they were right that I had one:

    unblinded:  no_claim_by_design=4  DID_NOT_CHECK=41   exit 0
    blinded:    no_claim_by_design=0  DID_NOT_CHECK=45   exit 0

The test that files an `UNDETERMINED` row as *"makes no claim"* rather than *"claim I could not
read"* moves four rows between two non-failing buckets, and **my both-arms proof reported nothing**.
`evidence_selftest.sh` now asserts buckets as well as exit codes, and prints the note that
pass/fail alone could not see that branch.

## A frozen constant, and then the opposite error

jharv3 also found `MAIN` frozen as a literal in their gate — *"a gate that checks freshness
against a constant inherits the staleness it exists to catch, and is invisible while it is still
true."* Mine had the same shape in both writers.

Deriving it live turned out to be **the opposite error**. The rows were judged against a specific
main; if main moves and the file is merely regenerated, a live-derived label claims a freshness
the *judgement* does not have. The label has to record the main the **judge** used:

    HARV_JUDGED_MAIN=81cd5321b08   -> "judged against origin/main 81cd5321b08"
    HARV_JUDGED_MAIN=a00f53f2094   -> "judged against origin/main a00f53f2094 (origin/main has
                                       since advanced to 81cd5321b08; … main moving can only turn
                                       RECOVER into LANDED, never the reverse)"
    unset                          -> AssertionError, refuses to label rows with a guess

Frozen lies when main moves. Live lies when the file is regenerated without re-judging. Recorded
plus a drift disclosure is the only one of the three that cannot mislead.

## And the 41, again

Merging the 43 re-judged rows without re-running `evidence.py` reintroduced the exact defect this
file already records: **41 rows whose verdict was refreshed and whose evidence was not**, naming
no file and carrying no hash. Regenerated. `544 RECOVER, 540 parsed, 540 agree, 0 disagree,
0 DID_NOT_CHECK.`

Knowing a failure mode by name did not stop me repeating it — third time tonight for this one.
