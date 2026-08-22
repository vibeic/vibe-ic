# Shard C — sixth-session re-verification (jharv3, 2026-08-22, host 8HD-6/.108)

**SHARD C COMPLETE — 110 rows. 74 RECOVER / 34 LANDED / 2 ABANDON / 0 UNREACHABLE.
No verdict changed this session.** Three rows gained evidence; two of them gained a
recovery instruction that did not exist before, because the content they name is now
on origin for the first time.

This session did not re-judge. It tried to break the shard-C deliverable, and where it
could not, it says so with the measurement that failed to break it.

## What was checked, and what it cost to check it honestly

**The deliverable is on the branch and is well-formed.** `verdicts_shard_c.tsv`,
110 rows, every line exactly 3 tab-separated fields, membership against
`_harv_shard_c.tsv` exact and 1:1 — 0 missing, 0 extra.

**No content drift.** `origin/main` is still `a4caccefe`, the exact sha every row was
judged against. The staleness that forced this whole re-sweep has not recurred here.

**Every judged head is on a live origin ref.** 109/110 by containment against refs read
with `ls-remote`; the 110th (`vibe-ic-wt-caravel-slew-drv3`) cites no head token and was
verified by content instead — its rescue commit is contained by the live anchor and the
file reads back at exactly the sha256 the row cites. The anchor moved three times during
the session (`322503f04 → 4b5e7b00c → 37cdaa6bb`) and advanced by fast-forward each time,
so nothing it held was dropped.

**All 36 deletion-bound rows are now verified — not just the 10 on this host.** The other
26 live on .112 and .121 and were reached over the `.102` nested-ssh hop, with those hosts
kept strictly read-only: probes piped in on stdin, nothing written, nothing fetched there.
All 36 exist, all 36 are clean (`-uall`), all 36 are on a live ref.

| verdict | rows | how proved | unproven paths |
|---|---|---|---|
| LANDED | 18 | whole HEAD tree is one of main's 2944 distinct root trees | — |
| LANDED | 16 | every file present holds content main's history held AT that path | **0** |
| ABANDON | 2 | content main never held; rests on preservation, re-verified live | 9 and 1 |

**Every one of the 34 LANDED is fully proved: 0 unproven paths across all of them.**

**Every one of the 74 RECOVER rows now has a recovery instruction that resolves against
live origin.** Before this session two had none at all, and one more was being misreported
(see below). The 16 LANDED rows with no instruction are correct: their content is on main.

## Four ways the measurement lied before it told the truth

Each of these produces a false *"main never held this"* — which manufactures a RECOVER out
of landed work, and whose mirror image manufactures a LANDED out of unlanded work. Each
exits 0 and looks like a clean run.

1. `git log --raw` omits merge-expressed history unless given `-m`. Without it,
   `.image-version-ignore` read as content main never had; with it, main held that exact
   blob at that exact path.
2. Collecting only the post-image blob misses every blob main later **deleted** — still
   content main held there.
3. **This host's `awk` is mawk 1.3.4, which silently never matches a `{40}` interval
   regex.** The gate ran, exited 0, and compared against an empty history set: 164/164
   "unproven", every one false.
4. `git 2.34.1` has no `--pathspec-from-file` for `log`; it errors to stderr and emits
   nothing, which under `2>/dev/null` is indistinguishable from "main held none of these".

The gate therefore **refuses (exit 2)** when the want set is non-empty and the history set
is empty, rather than reporting a pass. `landed_by_history_v4.sh --self-test` shows each
guarantee, and prints the mawk defect as a live observation on this host rather than a claim.

**A row was silently dropped and is now recovered.** `_c_o_edge_llm_matmul_accel_nangate45_scratch/wt_pr`
(.121, LANDED) vanished from my own host-join because `join` was fed unsorted input, said so
on stderr, and still exited 0 — 35 rows where there are 36. Re-joined under `LC_ALL=C sort`:
LANDED, need=17729, **unproven=0**. This is the file's own recurring failure mode — a gate
reporting success over a set smaller than the one it was asked about — and it caught me too.

**The measurement was rebuilt because the per-path form does not scale.** Proving `_a1610`
needs 17736 paths proved; passing that many pathspecs to `git log` does not complete, and
would have stalled rather than failed. Replaced by ONE global pass over main's history
producing all **38994** `(path, blob)` pairs main ever held, then a `comm` per worktree —
the whole sweep in under a minute. It was validated as equivalent *before* being trusted:
it reproduces the slow form's answers exactly on all four rows measured that way
(164/0, 159/0, 158/0, 9/9).

## One evidence defect — the verdict survives it, the wording does not

`_v1126` (.112, ABANDON) holds `.../programs/gate_host_independence_check.py` at blob
`f8ffb71bf`, and **origin/main never held that content at that path** — confirmed twice,
by the global map and by walking all 13 blobs main ever had there. The row says its owned
set is "2 owned file(s) of which 0 differ from origin/main", and that its absent-from-tip
paths are "byte-identical to the same path at merge-base `3d13e2c59eb`". For this file all
three blobs differ: merge-base `af4247142`, worktree `f8ffb71bf`, main's tip `0fbf3b7fa`.
The owned-set rule did not surface it — the same blind spot this corpus already records for
untracked content.

**The ABANDON stands, and it does not stand on that sentence.** HEAD `a7b1ed913e21` is
contained by the live anchor and the file reads back through it at exactly `f8ffb71bf`; the
twin the row names, `_i_solo_1126`, carries RECOVER here and is itself on live
`harvest/rescue-reanchor-3`. Deleting it destroys nothing. What changes is how the row must
be read: **preservation-bound, not "already on main"**. Its named rescue ref was deleted from
origin once already mid-sweep; if that happens again, this one file is what is lost.

## Two single-copy rows, found described and left unprotected — now on origin

Both were correctly marked RECOVER and both correctly had no recovery instruction, because
their value was on no commit anywhere. Describing that is not the same as fixing it, and this
fleet has deleted directories all night.

- **`_v1123`** (.108) — 384 staged changes (234 modified, 7 added, 143 deleted) on HEAD
  `f2bc39fd`, surviving only because a worktree index is a GC root, in a clone already
  warning *"too many unreachable loose objects"* and auto-packing. Now
  `harvest/rescue-108-v1123-staged` at `e285b6473`. Verified by content after fetching back:
  the commit changes exactly 384 paths against its parent, and the file the row names —
  absent from main entirely — reads back at the exact sha256 cited.
- **`_a1456`** (.112) — one staged edit, `test_matrix_63x8_census_freshness.py`. Now
  `harvest/rescue-112-a1456-staged` at `ddbd12352`. Verified end to end: the file read back
  through the pushed ref hashes to `c664219f...8806`, byte-for-byte the sha256 of the staged
  content still on .112, read there in the same session.

Neither directory was touched. Both trees were assembled locally from a **copy** of the index
(`GIT_INDEX_FILE`); `_v1123`'s original index is byte-identical and it still reports its 384
entries, and .112 was only ever read.

## Standing exposures

- `_v1126`'s ABANDON is preservation-bound (above). It is safe today and is one ref-deletion
  from not being.
- Rows whose recovery instruction names `harvest/worktree-triage-jharvest` depend on that
  branch continuing to exist. That is the branch this file is committed to, which is the point,
  but it is a single anchor and origin has deleted `harvest/rescue-*` refs before.

Nothing was deleted. No verdict was weakened, no assertion relaxed, no baseline rewritten.

Gate and raw measurements: `tools/harvest/bin_jharv3_s6/`.
