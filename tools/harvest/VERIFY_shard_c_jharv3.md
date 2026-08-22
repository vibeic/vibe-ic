# Shard C, re-verified — jharv3, 2026-08-22

`verdicts_shard_c.tsv` said SHARD c COMPLETE 110 rows. This is the check of that
claim, run against current `origin/main`
`81cd5321b082f9535f1a607a6feb7855498e7fe6`, by CONTENT only.

A file that says it is complete is, like a merge that reports nothing to land,
its own account of itself. So every row was re-measured rather than re-read.

## Result

| | before | after |
|---|---:|---:|
| RECOVER | 90 | **91** |
| LANDED | 17 | 17 |
| ABANDON | 3 | **2** |
| UNREACHABLE | 0 | 0 |
| total | 110 | 110 |

**One verdict flipped. It was an ABANDON, which is the direction that cannot be
undone.**

The path set is unchanged: the 110 rows are exactly the 110 paths in
`_harv_shard_c.tsv`, checked by set difference, and no row was added or dropped.

## The flip

`/home/reyerchu/vibe-ic-wt-caravel-slew-drv3` — ABANDON → **RECOVER**.

The old evidence was:

> a duplicate — its whole HEAD tree is 8656a6908, byte-for-byte the same tree as
> `/home/reyerchu/vibe-ic-wt-caravel-slew-drv2`, which is kept … and BOTH working
> trees are clean

The tree half is true. I re-confirmed it: `rev-parse` gives
`8656a6908624a861803bfa222c43ed5e88b4bc2a` for both heads.

The clean half is false. Measured on .112 with
`git status --porcelain --untracked-files=normal`, **both** trees carry an
untracked `HANDOFF_TO_GATEKEEPER.md` — and the two copies are not the same file:

| | bytes | sha256 |
|---|---:|---|
| drv3 | 9892 | `f05e08482acbcffc…` |
| drv2 | 7455 | `bcf26247eabbb291…` |

Neither is in `origin/main` at all, and being untracked, neither was on any ref
anywhere. The drv3 copy records the traced root cause of the
`step_signoff_drv_wire_length_repair` regression disabled at v1.5.65: a routing
clear loop destroying spare-tie nets so a reroute merged them with unrelated
signals and LVS regressed, and a session-local DRV estimate diverging from
multi-corner OCV sign-off, against the open sky130A harness.

Dropping that directory would have destroyed the only copy.

**The general lesson, because it will recur:** tree identity does not cover
untracked content. Where a worktree's recoverable value *is* the untracked
content, a duplicate-by-tree test is blind to exactly the thing that matters. Any
ABANDON resting on "identical tree" needs the working-tree check beside it.

Both copies are now preserved on `harvest/rescue-112-untracked-caravel-handoffs`
(commit `33d256659929e84e53f83f6cde4be66fca0aca6a`, parented on drv3's own HEAD
so the commit and the prose travel together). Confirmed live by
`git ls-remote --heads origin` and re-read back *through the ref*, not from the
local object store — sha256 matches on both. The working trees were read, not
touched; nothing was moved and nothing was deleted.

## What was checked, and how

All 110 judged head commits were already present in the .108 clone, so committed
content was compared **locally**. No fetch was issued in any shared clone, which
retires the "two agents fetching in one clone" hazard for this pass entirely.

**17 LANDED.** For each, the files the head owns — those differing between the
head and its merge-base with `origin/main` — were compared blob-by-blob against
`origin/main`.

- 2 own a real set (`_jppa_fixtures/tree` 32 files, `_jppa_skills/tree` 28) and
  every one matched. These are the two non-trivial confirmations.
- 15 own nothing, because the head is an ancestor of `origin/main`. For those the
  content test passes *trivially* and therefore proves nothing on its own; what
  actually decides them is the working tree. All 15 were confirmed clean on their
  own hosts.

Zero false LANDED. That was the check worth running: a false LANDED is a
directory someone deletes.

**90 RECOVER.** 88 name a file, and every named file's blob genuinely differs
from `origin/main` — re-resolved by `rev-parse <head>:<path>` against
`rev-parse <main>:<path>`. Two named none: `_v1123` and `_a1456`, both rule L2
(uncommitted edits counted but not named). The contract requires a file a
stranger can check, so both now name one, measured on the host that holds it.

**3 ABANDON.** All three duplicate claims re-checked by tree sha. Two hold —
`_v1126` = `_i_solo_1126` at `f5f659f2a…`, and `wt-j63x8c` shares base-mml's
*identical head commit* `3ab7fc723` — and both those trees are clean. The third
is the flip above.

## Two things the hosts said that the file did not

`/home/reyerchu/AI_IC_design/wt_jwire2` **has moved**. HEAD is now `a65d80b34`,
not the judged `ba9532031` — 20+ further commits on the #1347 wiring-audit line,
the newest committed 07:13 today. RECOVER stands and now understates the work.
`ls-remote` says the new head is the tip of `fix/jwire2-hygiene-wiring`, so it is
not at risk. Its named-file evidence was measured against the old head.

`/home/reyerchu/_v1123` now carries 384 staged changes, not the 241 recorded. Of
its 241 tracked edits, 224 differ from main's blob and 17 are absent from main
outright; **zero** match main.

These hosts are live. Every row's evidence carries the head it was judged at for
this reason.

## Reachability

All 110 directories were read on the machine that owns them. .108 is this host
(30 rows). .112 (36) and .121 (44) refuse this host's key directly but accept a
hop through .102, so no row was left UNREACHABLE and none was guessed. All 110
still exist; one head had drifted.

## What this pass does not cover

Ignored files were not counted, deliberately: an earlier pass established that
counting untracked build output inflated the dirty set from 15 to about 140. If
a directory's value sits in an ignored path, this sweep does not see it. That is
the honest boundary of the measurement, and the drv3 finding is a warning that
the boundary is where the misses live.

Nothing was deleted. This file decides; a later job executes.

## The same defect, in the other two shards

The drv3 flip is a defect in the *test*, not in one row, so it should be expected
wherever a deletion-bound verdict leans on the HEAD tree alone. Shards A and B
carry 25 LANDED rows and 3 ABANDON rows between them; all 28 were re-measured on
their own hosts.

All 3 ABANDON rows hold, and 21 of the 25 LANDED rows hold — including
`_wt_1390pg`, which *is* dirty but whose single edit is stale rather than novel
(main has 82 lines the disk copy lacks and the disk copy adds none), so its
LANDED survives. That row matters: it shows the check separates staleness from
work instead of flagging every dirty tree.

**Four LANDED rows do not hold**, all on .120:
`_agentjob_i1015/wt`, `_agent_scratch_whatif/wt_C`, `_wt_1236` and `_wt_1486`.
Each holds uncommitted bytes that are not on main — eleven files that main has
never held at all, among them five whole test programs. All four working states
are now preserved on `harvest/rescue-120-falselanded-*`, verified by re-hashing
every transferred file and then reading one back through the pushed ref.

Those rows belong to `jharvest-triage` and `jharv2`. I have not edited their
verdict files. The measurement, the rescue and what the owners should change are
in `FALSE_LANDED_shards_a_b.md`. All four are shard A rows; shard B came through
clean.

## The anchors this file cites were themselves untested

`jharv2` reported a defect worth more than the rows it cost: **a verification
that dereferences while the action does not**. `%(objectname)` on an annotated
tag is the *tag* object; `rev-parse -q --verify $h^{commit}` dereferences it and
passes, while `commit-tree -p <tag>` fails — so a check said yes for a reason the
action could not use, six rescue anchors were never created, and the loop moved
on without a word.

Every RECOVER row here that says *"the commit is on NO live origin branch"* backs
that with an anchor: *Preserved as `<ref>` … `git checkout <sha>`*. Those are
claims about refs I had not tested, made in a night when anchor creation is now
known to have failed silently. So they were tested:

- **86 anchor claims, 13 distinct refs.**
- **13 of 13 live on `origin`** — by `git ls-remote --heads`, not the
  `refs/remotes` cache, which outlives branches origin has deleted.
- Every anchor tip is a **`commit` object, undereferenced** — `cat-file -t` on
  the raw tip, which is the test the tag defect defeats. None is a tag.
- **86 of 86 claimed shas are reachable** from the anchor named for them.

My own six rescue refs were audited the same way and from the recovering party's
side: fetched fresh from `origin` rather than read out of the local object store,
tip asserted to be a commit, and all 15 named files re-hashed *through the ref*.
15 of 15 match. The tag defect does not touch this rescue path — every parent
came from `rev-parse HEAD` in a working tree, so every one was already a commit.

**One caveat, because the alarm was mine.** The first run flagged
`harvest/rescue-112-untracked-caravel-handoffs` as not containing
`b2c404a99d448…`. That was my parser, not the file: the `drv2` row carries two
independent claims — one anchor holding the *commit*
(`harvest/rescue-112-localonly-vibe-ic-repo`, and `b2c404a99d448…` **is**
reachable from it) and one holding the *untracked file*, recovered with
`git show FETCH_HEAD:<path>` and never with a checkout. Cross-joining every ref
in a row against every sha in it manufactured a pairing the row never asserted.

That is the same shape as jharv2's coverage checker reporting
`covered=0 uncovered=163` from a hardcoded path: **a broken checker reads exactly
like the disaster it is checking for.** A red from a verifier earns the same
suspicion as a green — the first question is whether the checker asked the
question the file actually answers.

## The file now checks itself, and doing that caught four more false reds — all mine

`verdicts_shard_c.tsv` asserts a contract: three fields, one of four verdicts,
and for RECOVER a file a stranger can go and check. Nothing enforced that. So
`bin_jharv3/contract_check.py` does, reading the file **from the branch as
pushed** rather than from any local copy, and it runs clean:

```
rows=110  {'RECOVER': 91, 'LANDED': 17, 'ABANDON': 2}
RECOVER evidence re-measured: absent_from_main=23  bytes_differ=66  uncommitted=2
CONTRACT OK
```

Those 89 are not a pattern match. For each RECOVER row the checker takes the file
the row names, resolves it at the head that row was judged at, and compares the
blob against `origin/main` — so a row claiming a difference that is not there
fails. The 2 remaining are rule L2, where the value is in bytes no commit holds.

**Every red it produced before it ran clean was the checker's fault, not the
file's.** That is worth writing down, because the first instinct on a red is to
go fix the artefact:

1. `…/riscv_isa_ref_oracle/common.inc` — reported as "names no checkable file".
   `.inc` was missing from an extension allowlist. Measured: the file is absent
   from main, sha256 `a2394e389954c97f…`, 64 lines, exactly as the row says.
2. `.image-version-ignore` — same report. It is a dotfile with **no extension at
   all**, so no allowlist could ever have matched it. Measured: absent from main,
   `cc4363979c546d9e…`, 240 lines, exactly as the row says.
3. `HANDOFF_TO_GATEKEEPER.md` in the drv3 row — "absent at its own head". It is
   untracked; that is the entire point of that row, and the word the checker
   recognised was "uncommitted", not "untracked".
4. Earlier, an anchor reported as not holding a commit, which was the checker
   cross-joining two independent claims in one row.

In each case I measured the artefact **before** touching the checker, and in each
case the artefact was right. The fix was to stop asking a proxy question: the
extension allowlist is gone, replaced by "the token the rule puts before
`sha256`", and the file is resolved rather than pattern-matched.

**The rule, stated once:** relaxing a check to clear a red is forbidden when the
artefact is wrong, and it is the *only* correct move when the checker is wrong.
Those two are indistinguishable from the red alone. What separates them is
measuring the artefact independently first — and a checker that has cried wolf
four times has earned scrutiny, not deference, on its fifth.

## The shard-A correction is now a gate, not a paragraph

`verdicts_joined.tsv` is what a downstream executor actually reads, and it is
**derived** from the three per-shard files. It already carries my shard-C flip
(drv3 reads RECOVER there). It still carries the four shard-A rows as LANDED,
and it will keep carrying them, because every regeneration re-propagates the
per-shard file and no regeneration reads prose.

I am not going to edit `verdicts_shard_a.tsv`. Not only because it is another
agent's deliverable, but because editing it would not hold: if its owner is alive
and regenerates from its own state, my edit vanishes and the rows revert with
nothing to say they ever moved.

So `bin_jharv3/rescue_contradiction.py` makes it a gate instead. The rule:

> If `origin` holds a rescue ref saying a path's working tree was **not** landed,
> then no shard file may call that path LANDED or ABANDON.

The refs are the authority, not the script's opinion — each names its worktree in
its own commit message, and only exists because the content was measured and
pushed. Refs come from `ls-remote`, never `refs/remotes`, which outlives branches
origin has deleted and would let this gate pass on a ref that is gone.

Current state, which is the point:

```
rescue refs on origin naming a worktree: 4
CONTRADICTION verdicts_shard_a.tsv: /home/reyerchu/_agentjob_i1015/wt says LANDED …
CONTRADICTION verdicts_shard_a.tsv: /home/reyerchu/_agent_scratch_whatif/wt_C says LANDED …
CONTRADICTION verdicts_shard_a.tsv: /home/reyerchu/_wt_1236 says LANDED …
CONTRADICTION verdicts_shard_a.tsv: /home/reyerchu/_wt_1486 says LANDED …
  shard a: 4   shard b: 0   shard c: 0
FAIL: 4 rows call a path deletion-safe that a rescue ref contradicts.
```

It goes green the moment those four verdicts are fixed, and it stays red through
every regeneration until they are. That is the delivery mechanism prose could not
provide to an owner nobody can reach.

### The fifth checker defect, and this one was a false GREEN

The first version of this gate printed **`OK: no shard file contradicts a rescue
ref`**. It was wrong. `uncommitted work in (\S+)` captured
`/home/reyerchu/_wt_1486` **with the trailing comma** from its own commit
sentence, so every lookup missed and four real contradictions reported as zero.

Four times tonight a checker cried wolf and the artefact was fine. This time the
checker said nothing was wrong and four things were. **A false green is the worse
failure**: a red gets investigated, a green gets believed and closes the row.

Which is why a gate has to be watched failing before it is trusted passing. This
one was: it is red now, on exactly the four rows measured on .120, and green on
the two shards that were verified clean.

## The checkers had jharv2's defect too, and finding it cost two more false reds

jharv2's second defect was a coverage checker with a **hardcoded repo path** that
reported `covered=0 uncovered=163` on four hosts — a total failure that reads
exactly like a total loss. Both checkers I shipped had the same constant. One had
something worse: it read `FETCH_HEAD:tools/harvest/…`.

`FETCH_HEAD` means *whatever was fetched last*. Run after any other fetch, that
script would have validated a different file — or an older state of this one —
and printed `CONTRACT OK` about a file nobody asked it to check. In
`rescue_contradiction.py` it was worse still, because that script fetches each
rescue ref in a loop: one reordering and it reads the shard file out of a rescue
branch. Both now locate the repo from the script's own path, name and fetch the
ref explicitly, and exit loudly with the missing input named rather than
degrading to a zero. Proven: unlocatable repo → exit 1 naming `VIBEIC_REPO`;
unresolvable ref → exit 1 naming the ref.

### False reds six and seven: I imposed my shard's house style on other people's

Pointed at shards A and B, `contract_check.py` reported **216 and 245 problems**.
Every one was mine. The three shards were written by three agents and their
evidence grammars differ:

| shard | grammar |
|---|---|
| C | `rule R2: <file> sha256 X … differs from origin/main <sha>` |
| A | `<file>: sha256 X in this tree vs Y on main <sha>` |
| B | `sha256(<file>) = <64hex> here, <64hex> on main` |

The contract fixes the **shape** — three fields, one of four verdicts, an
absolute path, evidence a stranger can check. It never fixed the wording. All
three grammars name a file and both hashes; all three are perfectly checkable. My
script knew one of them and called the other two broken.

So grammar-dependent verification is now **coverage**, reported as a number, and
only the contract's real requirements can fail. A row the script cannot parse is
a row it *did not check* — and saying so is the honest result, not a failure.
Then I taught it all three grammars, which turned 21 + 114 unverified rows into
real verification instead of leaving them behind a caveat.

### The stale-main gap is real, and it cost nothing

Shard A cites main `a00f53f20` on **all 114 rows**; shard B on 118 of 131. Only
shard C cites current main throughout. The amendment is explicit that judging
against a stale main is the mistake being corrected, so the tempting conclusion
was "shard A must be re-judged, 114 rows."

That would have sent someone to redo 114 rows — the exact failure the original
brief warns about. So it was measured instead of assumed. Direction bounds the
damage: judging against an *older* main can only make landed work look unlanded.
It inflates RECOVER and cannot manufacture a LANDED, because content that reached
`a00f53f20` is still in `81cd5321b08`'s history.

Measured across all three shards, taking each row's named file and comparing its
content against **current** main:

```
landed_since_judging:  shard a 0    shard b 0    shard c 0
verified_differs:      shard a 81   shard b 86   shard c 66
```

**Zero.** Not one RECOVER row in any shard has been overtaken by main. The
provenance gap is real and worth fixing in the prose; the verdicts survive it
intact, and nobody needs to redo anything.

That is the seventh time tonight a check pointed at someone else's file and the
file was fine. The pattern is stable enough to state as a rule: **when a checker
disagrees with an artefact, the checker is the more likely defect** — it is
younger, it was written to a sample of one, and it has never been reviewed. Go
measure the artefact before you go fix it.

## The consumable contradicts my own shard, in the direction that deletes

jharv2 found 1083 decided rows that never reach `verdicts_joined.tsv` at all.
That prompted the obvious question about my own shard, which I had only
spot-checked: do all 110 of my rows reach it, carrying the verdict I gave them?

They all reach it. **Six carry a different verdict**, and three of those differ
in the direction that gets a directory deleted — my file says RECOVER, the
consumable says LANDED:

| path | shard C | joined view | re-measured against current main |
|---|---|---|---|
| `/home/reyerchu/_jd3` | RECOVER | LANDED | 292 lines at its head vs 218 on main, `f7e68c793cc50edb` ≠ `ac6c915e9083e606` |
| `/home/reyerchu/_a1456` | RECOVER | LANDED | one tracked uncommitted edit, on disk only, on no ref |
| `/home/reyerchu/AI_IC_design/wt_jwire2` | RECOVER | LANDED | named file differs; 20+ commits since judging |

The other three go the safe way — `_jcapture` and `_jcap_priv/wt` (LANDED here,
RECOVER there) and `_v1126` (ABANDON here, RECOVER there) — which costs effort,
not content. Every one of the three dangerous rows was re-measured against
current `origin/main` before this was written. **The shard file is right and the
consumable is wrong.**

The joined rows are tagged `shard=c+retry`, so they were regenerated from some
earlier snapshot of shard C rather than from the file as it stands. That is the
same shape as jharv2's 1083: the last link in the chain — the only one anyone
reads — does not reflect the work behind it.

Running the same check across all three shards found **8 disagreements, 0 absent**
— my 6, plus 2 in shard B, one of which (`/home/reyerchu/_jintent/wt`) is also
deletion-bound in the joined view only. That one is jharv2's to judge; it has
been told.

### Why this is a gate and not an edit

Editing `verdicts_joined.tsv` would not hold. It regenerates, the disagreement
returns silently, and nothing records that anyone ever noticed. So
`bin_jharv3/joined_parity.py` fails while any shard row disagrees with the joined
view, and names which direction each disagreement runs in.

**Proved in four directions before shipping**, because a gate seen only passing is
not a gate:

```
real files                   -> FAIL, 8 disagree     (a count measured independently first)
joined patched to agree      -> OK,   0 disagree
patch removed                -> FAIL, 8 disagree
empty joined view            -> REFUSES, exit 1 — not "0 disagreements"
```

That last one is the whole night in one line: **"found nothing" and "parsed
nothing" print the same thing.** A checker that cannot tell them apart will
eventually report the second and be believed as the first.

### The fourth deletion-bound row, closed by measurement

I flagged `/home/reyerchu/_jintent/wt` to jharv2 and declined to rule on it —
shard B's row, shard B's grammar, and I had not measured it. jharv2 measured it
on .114 against current `origin/main`: head `c5c2e228244`, 6 files owned, 6
differing, working tree clean.

Re-checked here from the commit itself rather than taken on report:

```
vibe-ic-marketplace/README.md   at c5c2e228244  bb44e3d04a429770
                                on current main dbd748602e224556
```

Same values. **`verdicts_shard_b.tsv` says RECOVER and is right; the joined view
says LANDED and is stale** — regenerated while that worktree still sat on bare
main, before it moved to `c5c2e228244`. An executor reading the consumable
deletes six files that differ from main.

So the consumable carries **four** confirmed deletion-bound errors, not three plus
a suspicion: `_jd3`, `_a1456`, `wt_jwire2` in shard C and `_jintent/wt` in shard
B. All four measured, none guessed.

### Not every parity disagreement is a stale consumable

jharv2's other flagged row is the counter-example, and `joined_parity.py` would
misdescribe it without this note. `/home/reyerchu/_jcpath2/wt_new` has gone
**ABANDON → RECOVER → ABANDON** across three measurements — not indecision, and
not a stale file. The two worktrees genuinely diverged and re-converged while we
were writing: they now both sit at `c0ecd5f1310`, tree `5bf932a9082`, both clean
under `--untracked-files=normal`.

These hosts are live. A shard file and a joined view can disagree because the
consumable is stale — the four rows above — or because the *host moved between
the two measurements*, in which case both files were correct at the moment they
were written and neither needs fixing.

The gate cannot tell those apart, and it should not pretend to. It reports the
disagreement and the direction; deciding which kind it is requires going back to
the host. A row that "flaps" across regenerations is evidence about the
directory, not about the file — which is exactly why every row in shard C carries
the head it was judged at, and why the instruction beside each one is
*re-measure before acting*.

### What jharv2 said about their own grammar, kept because it generalises

> I wrote it for a human reader and shipped it as machine-checkable evidence
> without ever writing the machine.

That is the seventh false red seen from the other side. "Checkable by somebody
who was not there" was satisfied for a human and assumed for a machine, and the
assumption went untested because nobody wrote the consumer. It is the same
sentence as *found nothing and parsed nothing print the same thing*, one altitude
up: an unexercised reader and an absent reader are indistinguishable until
something tries to read.
