# SHARD C COMPLETE — 110 rows

`jharv3`, 2026-08-22. The one-screen version. Evidence is in
`verdicts_shard_c.tsv`; the reasoning is in `VERIFY_shard_c_jharv3.md`, which is
long because it records what was wrong as well as what was right.

## The deliverable

`tools/harvest/verdicts_shard_c.tsv` — 110 rows, exactly the 110 paths of
`_harv_shard_c.tsv`, checked by set difference. Judged by CONTENT against
`origin/main` `81cd5321b082f9535f1a607a6feb7855498e7fe6`.

| verdict | count |
|---|---:|
| RECOVER | 91 |
| LANDED | 17 |
| ABANDON | 2 |
| UNREACHABLE | 0 |

Machine-validated by `bin_jharv3/contract_check.py` against the file *as pushed*:
every RECOVER's named file re-resolved against current main — 66 differ, 23 are
absent from main, 2 are uncommitted, **0 unparseable, 0 overtaken by main**.

## What changed, and why it mattered

It arrived reading 90 / 17 / 3. **One ABANDON was wrong.**

`/home/reyerchu/vibe-ic-wt-caravel-slew-drv3` was called a byte-for-byte
duplicate of its sibling. The HEAD trees *are* identical (`8656a6908`). Both
working trees carry an **untracked** `HANDOFF_TO_GATEKEEPER.md`, and the two
copies are different files — 9892 vs 7455 bytes, neither on main, neither on any
ref. Tree identity cannot see untracked content, and untracked content was the
whole of the value. Dropping that directory would have destroyed the only copy.

## The 19 deletion-bound rows are now measured, not disclosed

The rows that authorise deletion — 17 LANDED and 2 ABANDON — carried a disclosure
that 11 of them rested on an input nobody had measured: untracked content on .112
and .121, which `git status --porcelain -uno` cannot see and which those hosts
would not answer for. `.102` is authorised on both; `ssh .102 "ssh .1xx ..."`
closes it.

**19 of 19: 0 untracked, 0 tracked modifications, HEAD object present, HEAD
unchanged since judging, 0 owned files differing from main. No verdict changed.**

The same defect exists one level down and is also closed: `-uall` reports untracked
files and NOT ignored ones. 121 ignored entries were found under those 19 rows, all
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

- **17 LANDED** — owned files compared blob-by-blob against main; all 17 clean on
  disk. Zero false LANDED.
- **91 RECOVER** — 89 verified by measurement, 2 are uncommitted edits no commit
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

## Two gates are deliberately RED

They are not failures of this shard. They are findings that outlive the agent
that made them, because prose does not survive a regeneration and a gate does.

| gate | state | why |
|---|---|---|
| `bin_jharv3/rescue_contradiction.py` | RED on shard A ×4 | four rows say LANDED over work a rescue ref proves is not on main |
| `bin_jharv3/joined_parity.py` | RED ×8 | the consumable contradicts the shard files it is derived from; 4 of the 8 in the direction that deletes |

Both go green when the underlying verdicts are fixed. `verdicts_shard_a.tsv` and
`verdicts_shard_b.tsv` are untouched — those corrections belong to their owners.

## Nothing was deleted

No directory was removed on any host. No working tree, index or HEAD was
modified anywhere. The only writes were commits and refs pushed to `origin`.
This file decides; a later job executes.
