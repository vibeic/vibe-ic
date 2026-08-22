# The residual preservation gap, measured after the reanchor fold

`jharv3`, 2026-08-22T05:0xZ. Short and specific, for whoever owns
`harvest/rescue-reanchor-*` and the anchor fold in `b8234d982`.

## What is still not on origin

The fold commit says it preserves 2950 commits. Measured against **every** live origin
ref (1500 refs, 15239 commits reachable):

- **516 of the 529** commits that the deleted `harvest/rescue-*` refs used to hold are
  reachable from **nothing on origin**. Only 13 are covered.
- Full list: `rescue_gap_not_on_origin_jharv3.txt` (one sha per line).

Those 529 were readable only in the `.108` clone `/home/reyerchu/vibe-ic`, behind stale
`refs/remotes/origin/harvest/rescue-*` tracking refs. **Those tracking refs have since
been pruned — 530 became 13.** The objects survive there today solely because of one
local branch built during this session:

```
refs/heads/harvest/rescue-consolidated-8hd6-jharv3   ea622b9882936a3a275bfd0eb96c8e4d63e29ae7
```

Its 529 parents are exactly those commits. Verified after the prune: 529 present, 0
missing. **Pushing it to origin was denied by this session's permission classifier**, so
516 commits currently hang on a single unpushed ref on one reapable host.

To close it, from `.108`:

```bash
git push origin ea622b9882936a3a275bfd0eb96c8e4d63e29ae7:refs/heads/harvest/rescue-consolidated-8hd6-jharv3
```

## Shard C rows affected

Four heads named in `verdicts_shard_c.tsv` are on no live origin ref:

```
RECOVER   /home/reyerchu/_tim_priv/wt-jsetup-timing    66085fbf5545
RECOVER   /home/reyerchu/_dens_priv/wt-jdrc1177        6aa0d6abf176
RECOVER   /home/reyerchu/wt-j63x8c                     8a861bdc6d25  and 3ab7fc723e49 on disk
```

`_v1126` (`a7b1ed913e21`) and `_agentjob_lgate/gate` (`bd20fc88d40b`) **were** picked up
by the fold and are now preserved.

`wt-j63x8c` is the one that matters most: it is the row whose verdict changed
ABANDON -> RECOVER precisely because `jmatrix/63x8-main-reds` was deleted out from under
it. Anchoring `3ab7fc723e49` on origin is what would let it go back to ABANDON.
