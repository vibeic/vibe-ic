# Shard C re-verified against a live fleet — 2026-08-22, jharv3, fifth session

Shard C was already complete when this session started: `tools/harvest/verdicts_shard_c.tsv`,
110 rows, 90 RECOVER / 18 LANDED / 2 ABANDON / 0 UNREACHABLE. Nothing here changes a verdict.
What this session re-measured is the part of that file that **decays** — the hosts are live and
origin is being rewritten by other agents while the file sits still — plus one claim in it that
had been proved in a way that proved nothing.

## 1. The deliverable is intact

| check | result |
|---|---|
| rows | 110, header + 110, 0 malformed |
| roster join against `_harv_shard_c.tsv` | 1:1, 0 missing, 0 extra |
| verdict vocabulary | all in {RECOVER, ABANDON, LANDED, UNREACHABLE} |
| counts | 90 / 18 / 2 / 0, unchanged |
| evidence | every prior string preserved verbatim as a prefix (110/110) |
| main it is judged against | `a4caccefeab577a5337f1854c9c857e4d7a2bd42`, still the live `origin/main` |

## 2. The 18 LANDED were re-derived, and 16 of them had been passing vacuously

LANDED authorises deletion, so it is the class where being wrong is unrecoverable. Re-derived
here from scratch, by content:

> a worktree holds work that is not on main iff some path's content at its HEAD differs from
> **both** main's tip **and** the merge-base. (Differing from main's tip alone is not evidence:
> main may simply have moved past a file this old checkout still carries unchanged.)

Run over all 20 deletion-bound rows: **18 CONTENT_ON_MAIN, 0 divergent paths**. The two
ABANDONs came back HOLDS_CONTENT, which is correct — ABANDON does not claim landing, it claims
worthlessness, and both rest on a duplicate finding plus a preservation anchor.

**But 16 of the 18 passed with zero paths examined.** Their HEAD is inside main's history, so
the diff against the merge-base is empty and the test looked at nothing. A stage that examined
nothing and a stage that found nothing print the same thing; only a second, non-vacuous
statement tells them apart. So each of those 16 was re-proved by **snapshot identity**: main's
2951 commits carry 2944 distinct tree hashes, and each of the 16 heads' whole tree is one of
them — this exact byte-for-byte snapshot exists on main. That is content, not ancestry, and it
is not vacuous: it matches a hash against a set built by walking main.

The script self-tests before it judges (`bin_jharv3_s5/rederive_delbound.sh`): a synthetic head
carrying main's tree on an old parent must come back CONTENT_ON_MAIN over 1811 examined paths,
a known RECOVER head must come back HOLDS_CONTENT, and an absent object must ERROR rather than
pass. Raw: `raw_rederived_delbound_s5_jharv3.tsv`, `raw_snapshot_on_main_s5_jharv3.tsv`.

## 3. Disk state re-read on the owning hosts — three HEADs had moved

All 20 deletion-bound directories were read again where they live: 8 on .108 directly, 12 on
.112 and .121 through the .102 hop, read-only, no fetch in any shared clone.

**20 of 20 clean** — 0 tracked modifications, 0 untracked files under `--untracked-files=all`.
**Three HEADs had moved since judging**, which is exactly why the rows say to re-measure:

| path | judged head | head now | verdict after re-judging |
|---|---|---|---|
| `/home/reyerchu/_jcapture` | `b3628c8da99b` | `b6aaf6608531` | LANDED holds — new snapshot `f7da1cd5fbcc` is on main |
| `/home/reyerchu/_jd3` | `a00f53f20948` | `66e0806689ec` | LANDED holds — new snapshot `c51f225c440b` is on main, commit contained by main |
| `/home/reyerchu/wt-j63x8c` | `8a861bdc6d25` | `3ab7fc723e49` | already recorded; both heads are on the branch |

Raw: `raw_disk_state_delbound_s5_jharv3.tsv`.

## 4. Four rows carried a recovery instruction that had stopped resolving

Four rows ended on a 04:52Z correction saying their head was "contained by NO live origin ref at
all" and that its only copies were the directory and one local object store. That was true when
written. It is not true now: the rescue work was folded into this branch at `cc7bc9bba` and
`6feae9385`, and all four heads are contained by the live tip.

`_dens_priv/wt-jdrc1177`, `_tim_priv/wt-jsetup-timing`, `_agentjob_lgate/gate`, `_v1126` — each
now carries a correction naming a recovery command that resolves today. For `_v1126` this also
lifts a recorded exposure: its ABANDON no longer rests solely on its twin being kept.

## 5. Preservation, re-checked against the tip as it is now, not as it was

`origin`'s tip for this branch moved twice during this session (`1cc1e183c` -> `eb4d4f8bc`,
another agent). The first containment pass was run against a tip that was already stale, and the
second pass was run against an object this clone did not yet have — which reports NOT CONTAINED
and reads exactly like data loss. Fetch first, then judge; a missing object is not an absent
commit.

Against the live tip `eb4d4f8bc` (from `ls-remote`, confirmed to be a fast-forward of the tip it
replaced, so nothing was rewritten away):

- **103 of 103** judged heads contained.
- **2950 of 2950** rescued commits contained.
- 0 not contained, 0 objects absent.

## 6. The drift sweep widened from 20 rows to all 110

Section 3 read the 20 deletion-bound directories. The other 90 were then read the same way, on
the hosts that own them — 30 on .108 directly, 36 on .112 and 44 on .121 through the .102 hop,
one connection per host, read-only, no fetch in any shared clone.

**110 of 110 directories still exist and are still checkouts** — 0 GONE, 0 without a `.git`.
**Five HEADs had moved**, three of them the ones already named above:

| path | verdict | head now | re-judged at the new head |
|---|---|---|---|
| `AI_IC_design/wt_jwire2` | RECOVER | `4b1285a1865e` | holds — snapshot not on main; head IS the current tip of live `fix/jwire2-hygiene-wiring` |
| `_gf180_priv/wt` | RECOVER | `5240ead2c7ee` | holds — snapshot not on main; contained by this branch and by `harvest/rescue-reanchor-heads` |
| `_jcapture` | LANDED | `b6aaf6608531` | holds — snapshot on main |
| `_jd3` | LANDED | `66e0806689ec` | holds — snapshot on main |
| `wt-j63x8c` | ABANDON | `3ab7fc723e49` | already recorded; both heads on this branch |

No verdict changed, and no drifted head is single-copy: each of the five is either a snapshot main
already has or is contained by a live origin ref, each checked with `ls-remote` and by walking the
ref rather than from `refs/remotes`. `fix/jwire2-hygiene-wiring` is the case that makes that
distinction load-bearing — it was force-pushed earlier today, so it existed throughout while what
it contained changed.

**Nine directories carry uncommitted content** (`_v1123` 384 modified, `_advkill_lgate`,
`_adv_lgate_unknown`, `_LRNdh`, `wt_k3_dep` in the thousands, `_a1456`, `AI_IC_design/wt-all`, and
both `caravel-slew-drv` twins one untracked file each). **All nine carry RECOVER**, so none of them
is deletion-bound and none is an exposure this file authorises. All 20 deletion-bound rows are
clean.

Raw: `raw_drift_sweep_all110_s5_jharv3.tsv` — every row's head, tree and disk state as read.

## What was not done

Nothing was deleted, on any host. No working tree, index or HEAD was modified anywhere — the
remote reads were `rev-parse` and `status`, and no clone was fetched but this one. All 110 rows were re-read on disk (section 6), but only the drifted heads were re-judged for
content: the 105 rows whose HEAD has not moved stand as measured at 13:36 against the same
`origin/main`, which has not moved either.
