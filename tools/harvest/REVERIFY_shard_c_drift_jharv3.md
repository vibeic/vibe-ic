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

## 7. 86 rows were correct and still unusable: the recovery instruction had rotted

Content and preservation are only half of a verdict row. The other half is the command a
reader runs, and this file's rows were written when the `harvest/rescue-*` anchors existed.
Origin has since deleted them.

Measured against `git ls-remote` (1574 refs advertised): **86 of 110 rows named only refs origin
no longer has**, so every `git fetch origin ...` instruction in them fails today. The content was
never at risk — every judged head is on this branch — but a reader following the row gets an
error and no way to tell that from real loss.

All 110 rows now carry an instruction that resolves, each verified by *walking* the ref after
fetching it, never from `refs/remotes`. The two rows that needed more than a re-point:

- `vibe-ic-wt-caravel-slew-drv3`, whose whole value is an **untracked** handoff file that was on
  no ref at all. Its rescue commit `33d256659929` is contained by this branch, and the file read
  back through the branch hashes to `f05e08482acbcffc…`, the exact sha256 the row cites. The
  04:52Z note saying it survives only via `pull/333/head` is superseded.
- `AI_IC_design/wt_jwire2`, whose head had moved to the current tip of a branch that was
  force-pushed today (section 6).

Everything each of those rows names as single-copy — the displaced prior heads
(`fdab9b592c22`), the three clone-wide stash commits (`c73e489c17cf`, `fd9d3f64e599`,
`522fd1562983`), the rescue commits — was checked individually: **270 of the 273 commit shas
this file names resolve here and are contained by the branch.** The three that are not are not
content this file preserves: two are the same head that is the live tip of
`fix/jwire2-hygiene-wiring`, and one is a branch tip the prose quotes in passing.

### The gate that reported a pass over nothing

`bin_jharv2/live_ref_citation_check.py` reported **0 dead, 0 moved-off over 1948 citations**,
and shard C was in its glob. It matches the backticked form ``reachable from `X` ``.
**`verdicts_shard_c.tsv` contains zero backticked citations.** It walked this file, examined
none of its 445 recovery citations, and its clean report covered a file where 86 rows were
broken. Nothing was wrong with its arithmetic; its universe was empty.

`bin_jharv3_s5/recovery_resolves.py` is the replacement for this file: it parses the
`git fetch origin X` instruction as well as the prose form, requires that a named ref both live
*and still contain* the row's head, and **exits 2 rather than reporting a pass when it parses no
citations at all**. `--self-test` drives all six of its guarantees, three of them to RED
(dead ref; live ref that no longer contains the head; and the same two again in the second
spelling of the head marker), and refuses if `origin` is unreachable.

Its head-marker pattern was widened once, from `worktree HEAD when judged:` to also accept
`worktree HEAD at re-verification:`. That is a second spelling of the same field, not a relaxed
assertion — the added self-test cases drive rows written in the new spelling to RED on a dead
ref and on a live-but-not-containing ref.

**Result: 110 rows examined, 445 citations parsed, 0 rows without an instruction that resolves.**

## 8. Sixteen verdicts were wrong, and the rule in the rows is why

Everything above re-checked claims. This section changes them. **16 rows move
RECOVER -> LANDED**; the file now reads **74 RECOVER / 34 LANDED / 2 ABANDON / 0 UNREACHABLE**.

Shard C's rule R2 calls a worktree unlanded when one of its files differs from
`git show origin/main:<path>` — that is main's **tip**. The brief's warning has a second half
nobody wrote down. "A branch whose content is fully on main still shows as ahead" is about
ancestry; the same branch also still shows as **different**, because vibe-ic squash-lands and
then main keeps moving. Work that landed on 2026-08-04 differs from the tip of 2026-08-22
exactly as unlanded work does. R2 cannot separate them, and on these 16 rows it did not.

The question that separates them: **did main's history ever hold these bytes at this path?**

For each of the 16 that is answered twice over — once per file, once per tree:

- every blob in the head's tree is among the **55114 distinct blobs reachable from
  `origin/main a4caccefe`**;
- of the paths that differ from main's tip, **every one is content main has held at that path,
  and none is content main never held**;
- and for the very file the row cited as proof of divergence, a **named main commit holds that
  exact blob at that exact path** — e.g. `wt-jdrc1177`'s `die_density_fill_gen.py` at
  `69ce9260dfd4`, `wt_sdc`'s `phase3_one_shot_runner.py` at `ab57adbde7f4`. Two of the 16 go
  further: their whole snapshot **is** one of main's own 2944 tree hashes, which is what a
  squash-land looks like from the branch side.

Each was then re-read on its host *after* the judgement: **0 tracked modifications, 0 untracked
files, HEAD unchanged**, and every gitignored entry attributed by `git check-ignore` to a class
main's own `.gitignore` declares generated or scratch — `rm -rf` has never read `.gitignore`.

### Three rows that qualified on content and did not move

- **`_ld/wt`** — content qualifies exactly like the 16. It stays RECOVER because 14 of its
  ignored entries fall under `benchmark-data/ic/*/clean_run_*/`, a class the deletion-bound
  table does not declare. Main's comment calls that class local run products, which is
  suggestive and is not the same as examined. The missing input is named in the row.
- **`_v1123`** (384 modified) and **`_a1456`** (1 modified) — committed content is landed; the
  rows now say so explicitly, so whoever acts knows the value is exactly the uncommitted files
  and nothing in the history behind them.

### Two traps hit while measuring this, both now gates

1. **`git rev-list --objects` names each blob under only one path.** A `(path, blob)` index
   built from it proves presence and *cannot* prove absence — it misses **109 of main's own tip
   files**, because a sibling path holds the same bytes. A sweep that treats a miss as absence
   invents unlanded work.
2. **`git rev-list <main> -- <path>` simplifies history.** For one file it returned 7 commits
   and hid the one holding the content; `--full-history` returned 14 and found it at
   `bf85ef43adb2`. My first proof run reported NOWHERE for content that was plainly there.

Both are self-test cases in `bin_jharv3_s5/landed_by_history.py`, along with: main's own tip
must come back landed over >1000 files, a known-unlanded head must come back holding work, and
a head tracking zero files must be **REFUSED** rather than passed. Five guarantees, all driven.

Raw: `raw_landed_by_history_s5_jharv3.tsv` (per row: tracked files, paths differing from tip,
paths main has held, ignored entries and classes), `raw_landing_proofs_s5_jharv3.tsv` (the named
file, its blob, and the main commit holding it), `raw_ignored_entries_landedflip_s5_jharv3.tsv`.

## What was not done

Nothing was deleted, on any host. No working tree, index or HEAD was modified anywhere — the
remote reads were `rev-parse` and `status`, and no clone was fetched but this one. All 110 rows were re-read on disk (section 6), but only the drifted heads were re-judged for
content: the 105 rows whose HEAD has not moved stand as measured at 13:36 against the same
`origin/main`, which has not moved either.
