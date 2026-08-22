> **SESSION 2026-08-22 13:5x–15:0x (jharv3, host 8HD-6/.108) — RE-VERIFIED, no verdict changed.**
>
> Counts stand at **90 RECOVER / 18 LANDED / 2 ABANDON / 0 UNREACHABLE**. What this session
> found is that a finished file still rots while it sits: three claims in it had gone stale in
> under two hours, and one of its gates was passing over an empty set.
>
> - **The 18 LANDED re-derived from scratch — and 16 were passing vacuously.** Their HEAD is
>   inside main's history, so the diff against the merge-base is empty and the test examined
>   nothing. Each is now re-proved by snapshot identity against the 2944 distinct tree hashes on
>   `origin/main a4caccefe`. 0 divergent paths, 0 false LANDED.
> - **All 110 directories re-read on their hosts. Five HEADs had moved**; all five re-judged at
>   the new head, all five verdicts hold, none single-copy. 110/110 still exist; the 20
>   deletion-bound rows are clean; the 9 dirty ones are all RECOVER.
> - **86 of 110 rows were correct and unusable** — every `git fetch origin ...` in them named a
>   `harvest/rescue-*` anchor origin has deleted. All 110 now carry an instruction verified to
>   resolve, by walking the ref after fetching it.
> - **The citation gate reported 0 dead over 1948 citations with this file in its glob.** It
>   matches the backticked form; this file has none of those. It examined none of the file's 445
>   citations while 86 rows were broken. `bin_jharv3_s5/recovery_resolves.py` replaces it and
>   refuses (exit 2) rather than passing over an empty set.
> - **Preservation re-checked against the live tip `218cd9bb6`**: 103/103 judged heads,
>   2950/2950 rescued commits, and 270 of the 273 commit shas the evidence names — the 3 that
>   are not contained are not content this file preserves.
> - One exposure outside my shard was closed because it was cheap and unrecoverable if lost:
>   a shard-A RECOVER head on no live ref, 8 files of work, folded in. See
>   `HANDOVER_shards_a_b_recovery_jharv3.md`.
>
> Detail: `REVERIFY_shard_c_drift_jharv3.md`. Nothing was deleted; no tree, index or HEAD was
> modified on any host.

> **FINAL 2026-08-22T05:2xZ (jharv3): 90 RECOVER / 18 LANDED / 2 ABANDON / 0 UNREACHABLE.**
> `wt-j63x8c` flipped ABANDON -> RECOVER -> ABANDON. Its content never changed and the
> duplicate finding was never in doubt; what changed was *preservation*. Its first
> ABANDON rested on `origin/jmatrix/63x8-main-reds`, which was deleted from origin
> mid-session, leaving the commit on no ref anywhere — so it became RECOVER. It was then
> anchored onto this branch at `6feae9385`, which is the revert condition the row itself
> named, so ABANDON is restored on an anchor that actually exists. **All 110 judged heads
> and all 529 rescued commits are now reachable from this branch.**

> **SUPERSEDED IN ONE ROW, 2026-08-22 (jharv3, third session).** The counts below read
> 90 RECOVER / 18 LANDED / 2 ABANDON. They went to 91 / 18 / 1 and are now **back to
> 90 / 18 / 2** — see the final note below:
> `/home/reyerchu/wt-j63x8c` changed **ABANDON -> RECOVER** because the live origin branch
> its ABANDON rested on, `jmatrix/63x8-main-reds`, was deleted from origin during that
> session, leaving its HEAD on no live origin ref and its named twin undecided and dirty.
> All 18 LANDED were independently re-derived and confirmed. See
> `RESCUE_REFS_GONE_shard_c_jharv3.md` and `anchoring_now_shard_c_jharv3.tsv`.

# SHARD C COMPLETE — 110 rows

`jharv3`, 2026-08-22. The one-screen version. Evidence is in
`verdicts_shard_c.tsv`; the reasoning is in `VERIFY_shard_c_jharv3.md`, which is
long because it records what was wrong as well as what was right.

## The deliverable

`tools/harvest/verdicts_shard_c.tsv` — 110 rows, exactly the 110 paths of
`_harv_shard_c.tsv`, checked by set difference. Judged by CONTENT against
`origin/main` `a4caccefeab577a5337f1854c9c857e4d7a2bd42`.

| verdict | count |
|---|---:|
| RECOVER | 90 |
| LANDED | 18 |
| ABANDON | 2 |
| UNREACHABLE | 0 |

Machine-validated by `bin_jharv3/contract_check.py` against the file *as pushed*:
every RECOVER's named file re-resolved against current main — 65 differ, 23 are
absent from main, 2 are uncommitted, **0 unparseable, 0 overtaken by main**.

## What changed, and why it mattered

It arrived reading 90 / 17 / 3. **One ABANDON was wrong.**

`/home/reyerchu/vibe-ic-wt-caravel-slew-drv3` was called a byte-for-byte
duplicate of its sibling. The HEAD trees *are* identical (`8656a6908`). Both
working trees carry an **untracked** `HANDOFF_TO_GATEKEEPER.md`, and the two
copies are different files — 9892 vs 7455 bytes, neither on main, neither on any
ref. Tree identity cannot see untracked content, and untracked content was the
whole of the value. Dropping that directory would have destroyed the only copy.

## The 20 deletion-bound rows are measured, not disclosed

The rows that authorise deletion — 18 LANDED and 2 ABANDON — carried a disclosure
that 11 of them rested on an input nobody had measured: untracked content on .112
and .121, which `git status --porcelain -uno` cannot see and which those hosts
would not answer for. `.102` is authorised on both; `ssh .102 "ssh .1xx ..."`
closes it.

**20 of 20: 0 untracked, 0 tracked modifications, HEAD object present, HEAD
unchanged since judging, 0 owned files differing from current main.** No verdict
changed by this measurement; the one verdict that did change, `_jd3`, changed
because main moved, and it was measured to this same standard before it moved.

The same defect exists one level down and is also closed: `-uall` reports untracked
files and NOT ignored ones. 121 ignored entries were found under those 20 rows, all
121 attributed by `git check-ignore` to a rule `origin/main`'s own `.gitignore`
declares generated or scratch. One row's evidence was wrong and is corrected —
`wt-j63x8c` claimed a twin that "is kept" and is in fact in no shard at all.

See `IGNORED_AND_UNTRACKED_CLOSED_shard_c.md`; gate
`bin_jharv3/ignored_accounted.py` (`--self-test` shows all five guarantees red).

## Coverage

All 110 heads were already in the .108 clone, so committed content was compared
**locally** — no fetch in any shared clone, which retires the two-agents-one-clone
hazard for this pass. All 110 directories were then read on the host that owns
them: .108 directly, .112 and .121 through a hop via .102. Nothing was guessed
and nothing was left UNREACHABLE.

- **18 LANDED** — owned files compared blob-by-blob against main; all 18 clean on
  disk. Zero false LANDED.
- **90 RECOVER** — 88 verified by measurement, 2 are uncommitted edits no commit
  holds and now name their file.
- **2 ABANDON** — both duplicate claims re-confirmed by tree sha, both trees clean.

## Preserved

Six single-copy working states, on origin, none of which existed on any ref:

```
harvest/rescue-112-untracked-caravel-handoffs
harvest/rescue-120-falselanded-_agentjob_i1015-wt
harvest/rescue-120-falselanded-_agent_scratch_whatif-wt_C
harvest/rescue-120-falselanded-_wt_1236
harvest/rescue-120-falselanded-_wt_1486
```

Every transferred file was re-hashed here against what the host reported
(169 of 169, 0 mismatches) before anything was committed, and files were read
back *through* the pushed refs to close the round trip.

## Gate state

Every shard-C gate is green. The reds that remain are findings about other files,
kept red because prose does not survive a regeneration and a gate does.

| gate | state | what it checks |
|---|---|---|
| `bin_jharv3/contract_check.py` | GREEN | shape, vocabulary, 1:1 roster join, every RECOVER's named file re-resolved against current main |
| `bin_jharv3/reverify_shard_c.py` | GREEN | every evidence claim re-derived from the repository alone |
| `bin_jharv3/ignored_accounted.py` | GREEN on B and C | deletion-bound rows clean on disk; every ignored entry attributed by `git check-ignore` to a rule main declares generated or scratch. **RED on shard A ×5** — five of its twelve deletion-bound rows are dirty on disk |
| `bin_jharv3/absent_from_main_accounted.py` | GREEN | 17472 paths these rows hold that main's tip lacks: 17471 identical at the merge-base, 1 covered by a live origin ref |
| `bin_jharv3/abandon_survivable.py` | ALLOW ×2 | both shard-C ABANDONs shown survivable, by two independent rules each |
| `bin_jharv3/vacuous_universal.py` | 0 findings in C | no empty-set universal, no stale main cite, no unaccounted untracked |
| `bin_jharv3/rescue_contradiction.py` | RED on shard A ×4 | four rows say LANDED over work a rescue ref proves is not on main |
| `bin_jharv3/joined_parity.py` | RED ×2, was ×8 | shard A and C now agree with the consumable; shard B's two remain |

`verdicts_shard_a.tsv` and `verdicts_shard_b.tsv` are untouched — those corrections
belong to their owners, and `bin_jharv3/joined_from_shard.py --shard b` closes the
parity half in one command. The disk measurement behind the shard-A red is in
`HANDOVER_shards_a_b_untracked_ignored_jharv3.md`, with no verdict attached.

## Nothing was deleted

No directory was removed on any host. No working tree, index or HEAD was
modified anywhere. The only writes were commits and refs pushed to `origin`.
This file decides; a later job executes.
