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
