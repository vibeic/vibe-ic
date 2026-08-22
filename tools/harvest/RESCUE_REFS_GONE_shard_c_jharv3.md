# Shard C: the rescue refs, what happened to them, and the one verdict it changed

`jharv3`, 2026-08-22. This file **supersedes and corrects** the version pushed
earlier today in `ac6aa0577`. Read the correction section — the earlier numbers
were true when measured and are no longer true.

## The 110 verdicts, re-derived

Every row was re-derived from scratch against `origin/main`
`a4caccefeab577a5337f1854c9c857e4d7a2bd42` (unchanged across this session) by
CONTENT: `owned` = files the branch changed vs its own merge-base with main, then
each owned file's blob at HEAD vs main's blob at the same path. Ancestry decided
nothing.

**18 of 18 LANDED confirmed — zero false LANDED.** 87 RECOVER have at least one
owned file differing from main; 3 rest on uncommitted or moved-HEAD work.

## One verdict changed: `wt-j63x8c`, ABANDON -> RECOVER

Its ABANDON rested on a stated fact: *"that commit is reachable from the LIVE origin
branch `jmatrix/63x8-main-reds`"*, and the row explicitly disclaimed resting on its
twin — *"does not need the twin and does not rest on it"*.

**`jmatrix/63x8-main-reds` was deleted from origin during this session.** It answered
`ls-remote` at 12:4x and returned nothing 30 minutes later. HEAD
`3ab7fc723e4984597ed5a6662798b60e7bbb505c` is now contained by **no live origin ref of
any kind** — tested individually against all 60 live branch tips and all 1254 live
`refs/pull/*/head`.

With the prop gone the verdict falls back on the twin it disclaimed. That twin,
`jf-63x8-work/base-mml`, shares the *same* HEAD and tree
(`a9f2edf43f00dd7a3410123f951f0822fe058641`, re-verified byte-identical), is itself on
no live origin ref, carries 1650 uncommitted/untracked entries, and **is a row in no
shard with no verdict** — nothing has decided to keep it.

By content the directory holds 9 owned files differing from main, and they are real
work rather than harvest scratch: `tools/gen_matrix_63x8_census.py`,
`programs/matrix_mutation_ledger.py`, and four `matrix_63x8` tests. Three paths in its
tree are absent from main's tip entirely. The directory is clean and its HEAD is
unchanged since judging, so its content is exactly that tree.

A wrong ABANDON is unrecoverable and the only surviving copies are two local object
stores. **RECOVER is the safe token.** It reverts to ABANDON the moment either
`3ab7fc723e49` is placed on a live origin ref, or `base-mml` is given a KEEP decision.

`_v1126` keeps ABANDON: its rescue ref is also gone, but the twin it names,
`_i_solo_1126`, is byte-identical in tree, carries RECOVER in this same file, and **is**
contained by live `harvest/rescue-reanchor-3`. That row is now load-bearing.

## CORRECTION to what this file said earlier

The earlier version reported *"all 24 rescue refs gone; 62 of 110 rows single-copy"*.
That was an accurate measurement at 12:4x — origin then had 86 heads and zero
`harvest/rescue-*`, and 0 `reanchor` refs existed.

**It is no longer the state.** Another agent has since re-anchored the rescued work
onto 12 new branches, `harvest/rescue-reanchor-1..12`. Re-measured at 04:52Z:

| anchoring of the judged HEAD | rows |
|---|---:|
| contained by a live origin **branch** | 85 |
| contained only by a **`refs/pull/*/head`** — weaker: cannot be pushed to, dies with the PR | 20 |
| contained by **nothing** | 5 |

So the exposure is real but far smaller than the earlier file implied. Per row:
`anchoring_now_shard_c_jharv3.tsv`.

The five with no anchor at all:

```
RECOVER   /home/reyerchu/_tim_priv/wt-jsetup-timing     66085fbf5545
RECOVER   /home/reyerchu/_dens_priv/wt-jdrc1177         6aa0d6abf176
RECOVER   /home/reyerchu/_agentjob_lgate/gate           bd20fc88d40b
RECOVER   /home/reyerchu/wt-j63x8c                      8a861bdc6d25 / 3ab7fc723e49 on disk
ABANDON   /home/reyerchu/_v1126                         a7b1ed913e21  (content safe via its kept twin)
```

**Whoever owns `rescue-reanchor-*`: these five are what your sweep did not pick up.**

## Still true, and still the thing to be careful about

`refs/remotes` is a cache of origin and outlives what origin deleted. The .108 clone
`/home/reyerchu/vibe-ic` holds **530 stale `refs/remotes/origin/harvest/rescue-*`
tracking refs and all 529 objects behind them**.

> **UPDATE 2026-08-22T05:0xZ — the prune has already happened.** Those 530 stale
> tracking refs are now **13**. All 529 rescued objects are nevertheless still present,
> and they are reachable in that clone through exactly one thing: the local branch
> `refs/heads/harvest/rescue-consolidated-8hd6-jharv3` (`ea622b988`), built earlier in
> this session, whose 529 parents are those commits. Verified after the prune: 529
> present, 0 missing.
>
> **So the rescued set now hangs on a single unpushed local ref on one host.** Do not
> delete that branch and do not `git gc` this clone. This raises the urgency of the
> denied push below from housekeeping to the only thing standing between that work and
> a reaped machine.

An anchor commit `ea622b9882936a3a275bfd0eb96c8e4d63e29ae7` with all 529 as parents was
built to consolidate them onto one ref, and is held locally at
`refs/heads/harvest/rescue-consolidated-8hd6-jharv3`. **Pushing it to origin was DENIED
by this session's permission classifier, so it is NOT on origin.** It covers 2 of the 5
unanchored heads above. To close that, from .108:

```bash
git push origin ea622b9882936a3a275bfd0eb96c8e4d63e29ae7:refs/heads/harvest/rescue-consolidated-8hd6-jharv3
```

## Re-run it

```bash
git ls-remote --heads origin | wc -l                      # 60 at 04:52Z, was 86
git ls-remote --heads origin 'harvest/rescue-reanchor-*'  # the 12 that replaced the old refs
git fetch --prune --dry-run origin | grep -c deleted      # 530 — never run without --dry-run
```
