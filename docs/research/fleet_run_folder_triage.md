# Fleet run-folder triage — all 466 unpublished run folders, decided by content

_Ledger row `runs-unpublished`. Every row below was decided by hashing content, never by name._

This file names **all 466** folders that the earlier fleet sweep refused to touch,
gives each one of the three permitted verdicts, states the evidence for it, and
records what was actually applied.

| verdict | folders | size |
|---|---:|---:|
| HARVEST | 362 | 117.6 GB |
| SUPERSEDED | 66 | 22.6 GB |
| REDUNDANT | 38 | 4.5 GB |
| **total** | **466** | **144.6 GB** |

**Not yet applied.**

## 1. The inherited classification compared against the wrong thing

The staged evidence recorded, per host, what it had compared against:

```
cls_105  published GDS in ~/vibe-ic/benchmark-data: 9
cls_108  ... 11      cls_112  ... 72      cls_114  ... 11
cls_120  ... 11      cls_121  ... 11
```

Six hosts, three different answers to the same question, because that path is a
working tree, not the publication of record. Two independent reasons it cannot be:

1. `benchmark-data` left the `vibe-ic` repo; the publication of record is the
   separate repository `github.com/vibeic/benchmark-data`. What sits at
   `~/vibe-ic/benchmark-data` on .105 is a stale leftover of the split.
2. The publication was **withdrawn** on 2026-08-20, one day before this triage:
   `bcf2f94 withdraw all four published cells, and write down what may be published here`.
   A tree-based comparison run today would therefore call every folder unpublished.

So "N of N GDS not published anywhere" in the inherited evidence is not a measurement
of publication. Everything below was recomputed.

**The durability rule used instead.** Content is durable when it exists as a git BLOB
reachable from an upstream ref of a repository that lives on GitHub — a withdrawn file
is still recoverable with `git cat-file blob`, a file that only ever lived in a run
folder is not. Enumerated over `refs/heads/*` and `refs/pull/*/head` of both repos:

```
vibe-ic         1276 upstream refs, 76 551 reachable objects
benchmark-data  all refs
-> 32 632 distinct durable blobs;  15 distinct durable GDS
```

## 2. What decides a folder

Five tests, applied in one fixpoint. Each is stated before it is applied and each
carries a control, because a test that cannot fail decides nothing.

### 2.1 Git blob identity — for every file, not just the GDS

For every regular file: `sha1(b"blob <size>\0" + content)` — the identity git itself
uses — tested for membership in the durable blob set. Exact, no heuristics.

```
466 folders   1 648 543 files   144.6 GB
durable in git:  818 188 files (49.6%)   17.2 GB (11.9%)
symlinks skipped 56 147     unreadable 0
```

Unreadable files are recorded as errors and are **never** counted as covered:
"I could not read it" and "I read it and it was clean" must not produce the same
verdict. There were none.

*Positive control* — the test must fire on something known to be in the repo:
`_plugin54` (a plugin copy) 3903 files, 3658 covered, 66.5 MB -> 54.9 MB covered; the
245 uncovered are `__pycache__/*.pyc`, regenerable from the `.py` that is covered.
*Negative side* — `_adv105_cache` (a 3-file manifest cache) covers 0 of 3.

### 2.2 A GDS of the same layout never hashes equal — normalise the timestamp

Measured on .108: two files of 6 873 312 bytes each, the same layout, different
sha256. GDSII records `BGNLIB` (0x0102) and `BGNSTR` (0x0502) carry the library and
structure modification times, so a re-stream of a published layout would be called
unpublished by a pure-bytes test. `bin/gdsnorm.py` walks the record stream and hashes
record type plus payload, substituting a constant for the payload of those two record
types only. It never writes a GDS.

*Control that the normalisation does not simply collapse everything*: over the 26
durable GDS blobs, distinct raw sha256 = 15 and distinct normalised digests = 15 — no
collapse — and two of them share a record count of 102 959 (spm v1.10.18 vs v1.9.94)
yet still separate.

```
2554 GDS instances hashed across the fleet
   207  byte-identical to a durable blob
     8  same layout, re-streamed (normalised match only)
  1892  byte-identical to a GDS in another folder
   652  exist in exactly one folder and in no repo
```

### 2.3 What counts as a measurement, and what is machine-regenerable

Uncovered content is attributed to a class before it is allowed to block a deletion.
Each regenerable class has a **named** survivor, not a vibe:

| class | bytes | why it does not block |
|---|---:|---|
| `__pycache__/*.pyc` | 2.84 GB | byte-for-byte regenerable from the `.py`, which is a durable blob |
| PDK copies (`libs.ref/`, `libs.tech/`, `pdk_seal/`, `pdks/`) | 12.77 GB | open, versioned, re-downloadable; and every one is duplicated in another folder |
| `pytest-of-*` temp trees | 0.33 GB | fixtures a test in the durable repo builds on demand |
| `node_modules/`, caches, `.venv` | 0.11 GB | reinstallable from the lock files, which are durable |
| **everything else — `artefact`** | **111.4 GB** | treated as a measurement and DOES block |

### 2.4 SUPERSEDED, and the two guards that stop it over-reaching

SUPERSEDED means: every run root in the folder has a successor run of the **same IC**
on the **same PDK**, in a folder that survives, that is later, at a plugin version not
older, at least as complete, and **strictly better on at least one axis**.

**Sibling-arm guard.** A first version of the rule (later + version not older +
`passed>=` + `failed<=`) reaped `121:_run_edge_llm_accel_ng45_v11018` in favour of
`121:_ctl_edge_llm_accel_ng45_patched`: same plugin version 1.10.18, identical
p=152 f=0, three hours apart. Those are the **baseline and patched arms of one
controlled experiment** — the difference between them IS the measurement, and
superseding one with the other destroys it. Hence "strictly better on one axis".
That alone moved 12 folders back to HARVEST.

**Out-of-root guard.** SUPERSEDED is an argument about RUNS. It says nothing about
content that is not under a run root — and the original layout guard had the same
blind spot, because it also only looked under run roots. Measured:

```
SUPERSEDED folders holding artefact content that is outside every run root,
not a durable git blob, and in no surviving folder:   33 of 85    353.5 MB
  .log 212  .json 142  .rb 93  .txt 83  .v 67  .py 58  .gds 18  .def 10  .patch 9
```

That is not scratch. `120:_spmslot_run` holds `debug_gds_filled/spm.gds`, 38 000 630 B,
a **unique layout outside the run root** that the old layout guard could not see;
`120:_c_sha2_scratch` holds 64 MB of logic-equivalence logs; `112:_n25_sn2025` holds an
obstruction-control experiment in `_obsctl/*.def`; four folders hold **patched plugin
source trees** (`plugin_conv/`, `plugin_P/`, `plugin_fix/`) — the exact code an A/B ran,
in no git ref; `121:_c3_adc_scratch` holds the positive and negative **control arms**
of one experiment; and several hold the run's `RESULT.md` and its authored `.patch`.

The split by orphan size decided the treatment:

```
 8 folders  350.4 MB of orphans   6.77 GB of disk  -> HARVEST, the orphan IS the measurement
25 folders    2.7 MB of orphans  18.07 GB of disk  -> extract the orphan first, then reap
```

Of those 25, **14 were extracted and reaped** — their out-of-run content is committed
beside this file under `docs/research/fleet_run_folder_triage_evidence/<host>/<folder>/`, 88 contents,
0.83 MB, each verified blob-identical to the census record after the copy. The other
**11 could not be committed**: their unique content is agent prose in Traditional
Chinese, or a fork of a third-party PDK rule deck, and repo artefacts here are
English-only and should not bundle a third-party deck without an attribution decision.
Those 11 folders (8.69 GB) stay. That limit is a policy, not a measurement — see §8a.

### 2.5 At-risk-layout guard — the 35 layouts the sweep would have destroyed

For every GDS in a folder headed for deletion: does the same content, or the same
**layout** (§2.2 normalised digest), survive in a kept folder or in a git ref?

```
GDS contents that disappear with the sweep               48
  of those, the layout survives elsewhere as a re-stream 10
  pytest-of-* fixture stubs (100 B), regenerable          3
  ---------------------------------------------------------
  LAYOUTS THAT WOULD EXIST NOWHERE AFTERWARDS            35    0.733 GB
  they sit in 29 folders holding                              11.07 GB
```

A first version of this test also flagged `_jw7_tmp` / `_jw7_base_tmp` — five ~100-byte
`pytest-of-designer/**` stubs each, which §2.3 already calls regenerable. Counting them
would have been a false alarm, so the layout test runs the same class filter as
everything else.

**Treatment: preserve the layout, then reap the folder.** Each at-risk GDS was copied
to `~/_kept_layouts/<original path>` **on its own host** — 43 files, 0.877 GB, no
0.9 GB dragged through a three-hop ssh chain — re-hashed after the copy, and recorded
in `~/_kept_layouts/MANIFEST.tsv` with its run identity (IC, PDK, plugin version,
run_at, gate counts). A copy that did not verify would have been removed and reported,
never left there. All 43 verified.

This is **not** a durability claim: `~/_kept_layouts` is exactly as durable as the
folder the file came from. The honest statement is "the layout is kept and labelled,
the run tree around it is gone". The rule is in the program, not in prose —
`bin/verdict.py` refuses to reap any folder holding an artefact-class layout that is
neither durable, nor in a surviving folder, nor in `evidence/kept_layouts.txt`.

*Negative control* — empty `kept_layouts.txt`, i.e. pretend the copies never happened:

```
preserved into _kept_layouts: 0   -> 29 folders HELD, SUPERSEDED 66 -> 46
preserved into _kept_layouts: 35  ->  0 folders HELD, SUPERSEDED     66
```

so it is the preservation that makes those 20 folders (9.3 GB) reapable, not an
assumption.

### 2.6 Final-set verification

A survivor named in an intermediate round can itself be reaped in a later round, and
then the coverage claim that justified the earlier deletion is false —
`_jw7_base_tmp` -> `_jw7_tmp` -> `_jnorec_tmp` is exactly that chain. Every REDUNDANT is
therefore re-checked against the union of artefacts of the **final** HARVEST set only,
violations are reverted, and the result is asserted.
*Control*: force-marking the HARVEST folder with the most unique content
(`121:_jppasearch`, 13 445 contents found nowhere else) as REDUNDANT makes the verifier
reject it — so the verifier discriminates.

### 2.7 Live-use check

Re-measured on all six hosts immediately before the sweep: `/proc/PID/cwd` **and every**
`/proc/PID/fd` of every process, plus every cwd a `herdr` agent reports. **15** of the
466 are held open right now and are pinned to HARVEST — a run in flight is a
measurement being made. An earlier scan two hours before found 8; seven of the fifteen
are runs that started in between, which is why this is re-measured at the moment of
action rather than trusted from a plan.

The open-fd arm is not decoration: `120:_bm4b_sha256_sky130A_run` is held only by an fd
belonging to a running `flow_dashboard.py`, and a cwd-only check would have deleted a
directory a live dashboard had open. `bin/sweeper.py` repeats the whole check per host
at the moment of removal, so a run that starts during the sweep is still safe.

## 3. Result

```
strict byte test alone                     34 folders    4.41 GB removable
  + supersession                          131 folders   45.4  GB
  - sibling-arm guard                     -12 folders
  - live-use pin                          -15 folders
  - out-of-root guard                     -19 folders   (11 of them blocked by policy)
  - at-risk-layout guard                  -20 folders   (bought back by preserving 43 GDS)
  = applied                               104 folders  27.06 GB
```

Nothing that existed only in a reaped folder was destroyed: 88 out-of-run contents were
committed into this repo and 43 layouts were preserved on their own hosts, both
verified by re-hashing, before a single folder was removed.

## 4. Per-host summary

| host | machine | folders | HARVEST | SUPERSEDED | REDUNDANT | size | reclaimed |
|---|---|---:|---:|---:|---:|---:|---:|
| .105 | 8HD-9 | 100 | 85 | 10 | 5 | 29.6 GB | 7.1 GB |
| .108 | 8HD-6 | 6 | 4 | 0 | 2 | 0.2 GB | 0.0 GB |
| .112 | 8HD-d | 68 | 57 | 8 | 3 | 19.6 GB | 1.3 GB |
| .114 | 8HD-8 | 115 | 85 | 19 | 11 | 19.4 GB | 5.5 GB |
| .120 | 8HD-4 | 113 | 79 | 20 | 14 | 35.0 GB | 9.3 GB |
| .121 | 8hd-3 | 64 | 52 | 9 | 3 | 40.8 GB | 3.8 GB |

## 5. REDUNDANT — the same bytes are provably somewhere durable

Every not-in-git artefact content in the folder also lives either in a git blob or in a folder whose FINAL verdict is HARVEST. The principal survivor is named.

38 folders, 4.5 GB.

| host | folder | MB | files | applied | preserved first | evidence |
|---|---|---:|---:|---|---|---|
| .105 | `_ndapdk` | 301 | 11534 | not applied | — | all 2122 not-in-git artefact contents also live in surviving folders; principal survivor 121:_ndapdk |
| .105 | `_plugin1844` | 67 | 3909 | not applied | — | all 0 not-in-git artefact contents also live in surviving folders; principal survivor none needed — every blob is already in git |
| .105 | `_plugin54` | 66 | 3903 | not applied | — | all 0 not-in-git artefact contents also live in surviving folders; principal survivor none needed — every blob is already in git |
| .105 | `_r4_ihp-sg13g2` | 56 | 3702 | not applied | — | all 1 not-in-git artefact contents also live in surviving folders; principal survivor 120:_c_o_sha256_sky130A_run |
| .105 | `_plugin1842` | 56 | 3687 | not applied | — | all 0 not-in-git artefact contents also live in surviving folders; principal survivor none needed — every blob is already in git |
| .108 | `_pcgds_base_8HD-6` | 7 | 1 | not applied | — | all 1 not-in-git artefact contents also live in surviving folders; principal survivor 108:_spmrun_8HD-6 |
| .108 | `_pcgds_8HD-6` | 5 | 1 | not applied | — | all 1 not-in-git artefact contents also live in surviving folders; principal survivor 108:_spmrun_8HD-6 |
| .112 | `_ndapdk` | 301 | 11534 | not applied | — | all 2122 not-in-git artefact contents also live in surviving folders; principal survivor 121:_ndapdk |
| .112 | `_plugin_v11016` | 78 | 4327 | not applied | — | all 0 not-in-git artefact contents also live in surviving folders; principal survivor none needed — every blob is already in git |
| .112 | `_a13_a4probe` | 0 | 71 | not applied | — | all 22 not-in-git artefact contents also live in surviving folders; principal survivor 112:_a13_libprobe |
| .114 | `_ndapdk` | 301 | 11534 | not applied | — | all 2122 not-in-git artefact contents also live in surviving folders; principal survivor 121:_ndapdk |
| .114 | `_jw7_tmp` | 84 | 13247 | not applied | — | all 2 not-in-git artefact contents also live in surviving folders; principal survivor 114:_jnorec_tmp |
| .114 | `_jw7_base_tmp` | 83 | 13206 | not applied | — | all 2 not-in-git artefact contents also live in surviving folders; principal survivor 114:_jnorec_tmp |
| .114 | `_plugin_v11026` | 77 | 4416 | not applied | — | all 0 not-in-git artefact contents also live in surviving folders; principal survivor none needed — every blob is already in git |
| .114 | `_plugin_v11018` | 77 | 4388 | not applied | — | all 0 not-in-git artefact contents also live in surviving folders; principal survivor none needed — every blob is already in git |
| .114 | `_plugin57` | 66 | 3904 | not applied | — | all 0 not-in-git artefact contents also live in surviving folders; principal survivor none needed — every blob is already in git |
| .114 | `_stock1851` | 58 | 3761 | not applied | — | all 0 not-in-git artefact contents also live in surviving folders; principal survivor none needed — every blob is already in git |
| .114 | `_clean54` | 58 | 3754 | not applied | — | all 0 not-in-git artefact contents also live in surviving folders; principal survivor none needed — every blob is already in git |
| .114 | `_stockcur` | 58 | 3752 | not applied | — | all 0 not-in-git artefact contents also live in surviving folders; principal survivor none needed — every blob is already in git |
| .114 | `_plugin1842` | 56 | 3687 | not applied | — | all 0 not-in-git artefact contents also live in surviving folders; principal survivor none needed — every blob is already in git |
| .114 | `_r100a_scratch` | 0 | 15 | not applied | — | all 9 not-in-git artefact contents also live in surviving folders; principal survivor 114:_r100a_run |
| .120 | `_c_plugin97_lecfix` | 448 | 20647 | not applied | — | all 1 not-in-git artefact contents also live in surviving folders; principal survivor 120:_c_plugin97_agefix |
| .120 | `_c_plugin97` | 447 | 20616 | not applied | — | all 0 not-in-git artefact contents also live in surviving folders; principal survivor none needed — every blob is already in git |
| .120 | `_c_plugin998` | 440 | 20502 | not applied | — | all 0 not-in-git artefact contents also live in surviving folders; principal survivor none needed — every blob is already in git |
| .120 | `_ndapdk` | 301 | 11534 | not applied | — | all 2122 not-in-git artefact contents also live in surviving folders; principal survivor 121:_ndapdk |
| .120 | `_mut902` | 116 | 6907 | not applied | — | all 2 not-in-git artefact contents also live in surviving folders; principal survivor 120:_mut902b |
| .120 | `_ibex_plugin_11029` | 77 | 4419 | not applied | — | all 0 not-in-git artefact contents also live in surviving folders; principal survivor none needed — every blob is already in git |
| .120 | `_nda_plugin_11026` | 77 | 4404 | not applied | — | all 0 not-in-git artefact contents also live in surviving folders; principal survivor none needed — every blob is already in git |
| .120 | `_bm4a_plugin` | 77 | 4399 | not applied | — | all 0 not-in-git artefact contents also live in surviving folders; principal survivor none needed — every blob is already in git |
| .120 | `_plugin_v11018` | 77 | 4398 | not applied | — | all 0 not-in-git artefact contents also live in surviving folders; principal survivor none needed — every blob is already in git |
| .120 | `_bm4b_plugin` | 77 | 4388 | not applied | — | all 0 not-in-git artefact contents also live in surviving folders; principal survivor none needed — every blob is already in git |
| .120 | `_v902_base` | 68 | 4236 | not applied | — | all 0 not-in-git artefact contents also live in surviving folders; principal survivor none needed — every blob is already in git |
| .120 | `_wt902_base` | 68 | 4236 | not applied | — | all 0 not-in-git artefact contents also live in surviving folders; principal survivor none needed — every blob is already in git |
| .120 | `_c_plugin84` | 67 | 3927 | not applied | — | all 0 not-in-git artefact contents also live in surviving folders; principal survivor none needed — every blob is already in git |
| .120 | `_plugin54` | 64 | 3818 | not applied | — | all 0 not-in-git artefact contents also live in surviving folders; principal survivor none needed — every blob is already in git |
| .121 | `_plugin_v11026` | 77 | 4405 | not applied | — | all 0 not-in-git artefact contents also live in surviving folders; principal survivor none needed — every blob is already in git |
| .121 | `_plugin_v11018` | 77 | 4384 | not applied | — | all 0 not-in-git artefact contents also live in surviving folders; principal survivor none needed — every blob is already in git |
| .121 | `_plugin_cur` | 65 | 3847 | not applied | — | all 0 not-in-git artefact contents also live in surviving folders; principal survivor none needed — every blob is already in git |

## 6. SUPERSEDED — a later run of the same design on the same PDK replaces it

Every run root in the folder has a successor run of the same IC on the same PDK, in a folder that survives, that is later, at a plugin version not older, at least as complete, and strictly better on at least one axis. The `preserved` column names what was lifted out of the folder before it was removed.

66 folders, 22.6 GB.

| host | folder | MB | files | applied | preserved first | evidence |
|---|---|---:|---:|---|---|---|
| .105 | `_c_car11_run` | 1257 | 1175 | not applied | 3 file(s) -> `docs/research/fleet_run_folder_triage_evidence/105/_c_car11_run/` | all 2 run(s) have a later, not-older-version, at-least-as-complete successor; e.g. caravel_user_project@sky130A v0.119.62 2026-07-31T18:39:42 p=157 f=0  ->  120:_c_nda_caravel_user_project_run v0.119.62 2026-08-05T09:04:22 p=160 f=0 |
| .105 | `_c_car14_scratch` | 819 | 637 | not applied | 1 layout(s) -> `~/_kept_layouts/`; 6 file(s) -> `docs/research/fleet_run_folder_triage_evidence/105/_c_car14_scratch/` | all 1 run(s) have a later, not-older-version, at-least-as-complete successor; e.g. caravel_user_project@sky130A v0.119.62 2026-08-01T16:24:57 p=156 f=0  ->  120:_c_nda_caravel_user_project_run v0.119.62 2026-08-05T09:04:22 p=160 f=0 |
| .105 | `_c_car13_run` | 817 | 626 | not applied | 1 layout(s) -> `~/_kept_layouts/` | all 1 run(s) have a later, not-older-version, at-least-as-complete successor; e.g. caravel_user_project@sky130A v0.119.62 2026-08-01T10:06:08 p=156 f=0  ->  120:_c_nda_caravel_user_project_run v0.119.62 2026-08-05T09:04:22 p=160 f=0 |
| .105 | `_c_car12_run` | 817 | 622 | not applied | 1 layout(s) -> `~/_kept_layouts/` | all 1 run(s) have a later, not-older-version, at-least-as-complete successor; e.g. caravel_user_project@sky130A v0.119.62 2026-07-31T22:24:00 p=156 f=0  ->  120:_c_nda_caravel_user_project_run v0.119.62 2026-08-05T09:04:22 p=160 f=0 |
| .105 | `_c_car9_run` | 794 | 834 | not applied | 4 file(s) -> `docs/research/fleet_run_folder_triage_evidence/105/_c_car9_run/` | all 2 run(s) have a later, not-older-version, at-least-as-complete successor; e.g. caravel_user_project@sky130A v0.119.62 2026-07-31T15:00:45 p=155 f=0  ->  120:_c_nda_caravel_user_project_run v0.119.62 2026-08-05T09:04:22 p=160 f=0 |
| .105 | `_c_car14_run` | 718 | 4750 | not applied | — | all 1 run(s) have a later, not-older-version, at-least-as-complete successor; e.g. caravel_user_project@sky130A v0.119.62 2026-08-01T16:10:56 p=157 f=0  ->  120:_c_nda_caravel_user_project_run v0.119.62 2026-08-05T09:04:22 p=160 f=0 |
| .105 | `_c_car8_run` | 635 | 890 | not applied | 3 file(s) -> `docs/research/fleet_run_folder_triage_evidence/105/_c_car8_run/` | all 2 run(s) have a later, not-older-version, at-least-as-complete successor; e.g. caravel_user_project@sky130A v0.119.62 2026-07-31T13:41:37 p=156 f=0  ->  120:_c_nda_caravel_user_project_run v0.119.62 2026-08-05T09:04:22 p=160 f=0 |
| .105 | `_c_subsv2_run` | 570 | 4679 | not applied | 2 layout(s) -> `~/_kept_layouts/` | all 1 run(s) have a later, not-older-version, at-least-as-complete successor; e.g. subservient@sky130A v0.119.62 2026-08-01T13:18:16 p=153 f=0  ->  105:_r11014_subservient_sky130A v1.10.14 2026-08-09T13:26:46 p=154 f=0 |
| .105 | `_c_subsv_run` | 96 | 606 | not applied | 1 layout(s) -> `~/_kept_layouts/` | all 1 run(s) have a later, not-older-version, at-least-as-complete successor; e.g. subservient@sky130A v0.119.62 2026-07-31T05:14:45 p=151 f=0  ->  105:_r11014_subservient_sky130A v1.10.14 2026-08-09T13:26:46 p=154 f=0 |
| .105 | `_r11014_subservient_gf180mcuD` | 68 | 682 | not applied | — | all 1 run(s) have a later, not-older-version, at-least-as-complete successor; e.g. subservient@gf180mcuD v1.10.14 2026-08-09T10:57:35 p=154 f=0  ->  105:_bm_scratch_sub_gf180 v1.10.18 2026-08-09T13:54:47 p=154 f=0 |
| .112 | `_agent_scratch_sn` | 449 | 12032 | not applied | 10 file(s) -> `docs/research/fleet_run_folder_triage_evidence/112/_agent_scratch_sn/` | all 1 run(s) have a later, not-older-version, at-least-as-complete successor; e.g. Universal Serial Bus (USB 2.0)@ihp-sg13g2 v0.119.62 2026-08-04T03:31:41 p=173 f=13  ->  112:_agentjob_sn25 v1.10.30 2026-08-11T14:53:07 p=173 f=13 |
| .112 | `_c12_edge_llm_matmul_accel_sky130A` | 345 | 536 | not applied | — | all 1 run(s) have a later, not-older-version, at-least-as-complete successor; e.g. edge_llm_matmul_accel@sky130A v1.10.11 2026-08-09T13:08:26 p=151 f=1  ->  105:_bm_edge_matmul_sky130A_v11018 v1.10.18 2026-08-09T15:58:26 p=151 f=1 |
| .112 | `_gk198_gk` | 90 | 805 | not applied | 7 file(s) -> `docs/research/fleet_run_folder_triage_evidence/112/_gk198_gk/` | all 1 run(s) have a later, not-older-version, at-least-as-complete successor; e.g. subservient@ihp-sg13g2 v0.119.62 2026-07-27T14:41:43 p=0 f=37  ->  105:_c_subsv_ndapdk_run v1.10.26 2026-08-09T16:43:19 p=154 f=0 |
| .112 | `_gk198_run` | 6 | 205 | not applied | 1 file(s) -> `docs/research/fleet_run_folder_triage_evidence/112/_gk198_run/` | all 1 run(s) have a later, not-older-version, at-least-as-complete successor; e.g. subservient@ihp-sg13g2 v0.119.62 2026-07-27T14:39:34 p=0 f=37  ->  105:_c_subsv_ndapdk_run v1.10.26 2026-08-09T16:43:19 p=154 f=0 |
| .112 | `_probe_hawaii_capres` | 1 | 208 | not applied | — | all 1 run(s) have a later, not-older-version, at-least-as-complete successor; e.g. u_hawaii_adc@ihp-sg13g2 v1.10.18 2026-08-09T12:47:32 p=0 f=0  ->  112:_c12_u_hawaii_adc_ihp-sg13g2_v11027 v1.10.27 2026-08-09T16:19:13 p=0 f=0 |
| .112 | `_c12_u_hawaii_adc_ihp-sg13g2` | 1 | 207 | not applied | — | all 1 run(s) have a later, not-older-version, at-least-as-complete successor; e.g. u_hawaii_adc@ihp-sg13g2 v1.10.26 2026-08-09T16:13:59 p=0 f=0  ->  112:_c12_u_hawaii_adc_ihp-sg13g2_v11027 v1.10.27 2026-08-09T16:19:13 p=0 f=0 |
| .112 | `_c12_u_hawaii_adc_ihp-sg13g2_pre11026_20260810_001247` | 1 | 206 | not applied | — | all 1 run(s) have a later, not-older-version, at-least-as-complete successor; e.g. u_hawaii_adc@ihp-sg13g2 v1.10.16 2026-08-09T10:31:28 p=0 f=0  ->  112:_c12_u_hawaii_adc_ihp-sg13g2_v11027 v1.10.27 2026-08-09T16:19:13 p=0 f=0 |
| .112 | `_c12_u_hawaii_adc_ihp-sg13g2_v11018` | 1 | 206 | not applied | — | all 1 run(s) have a later, not-older-version, at-least-as-complete successor; e.g. u_hawaii_adc@ihp-sg13g2 v1.10.18 2026-08-09T12:46:38 p=0 f=0  ->  112:_c12_u_hawaii_adc_ihp-sg13g2_v11027 v1.10.27 2026-08-09T16:19:13 p=0 f=0 |
| .114 | `_c_aes5_run` | 1217 | 649 | not applied | — | all 1 run(s) have a later, not-older-version, at-least-as-complete successor; e.g. opentitan_aes@sky130A v0.119.62 2026-07-31T17:58:26 p=150 f=3  ->  114:_c_nda_opentitan_aes_run v0.119.62 2026-08-05T07:46:43 p=163 f=0 |
| .114 | `_c_edge1_run` | 608 | 4207 | not applied | — | all 1 run(s) have a later, not-older-version, at-least-as-complete successor; e.g. edge_llm_accel@nangate45 v0.119.62 2026-08-01T13:08:57 p=151 f=0  ->  121:_ctl_edge_llm_accel_ng45_patched v1.10.18 2026-08-09T22:36:10 p=152 f=0 |
| .114 | `_v784` | 520 | 1170 | not applied | 4 layout(s) -> `~/_kept_layouts/` | all 2 run(s) have a later, not-older-version, at-least-as-complete successor; e.g. subservient@gf180mcuD v0.119.62 2026-08-04T03:05:52 p=153 f=1  ->  105:_r11014_sub_gf180_util035 v1.10.14 2026-08-09T11:15:57 p=154 f=0 |
| .114 | `_c_subsvg_run` | 397 | 7351 | not applied | 2 layout(s) -> `~/_kept_layouts/` | all 1 run(s) have a later, not-older-version, at-least-as-complete successor; e.g. subservient@gf180mcuD v0.119.62 2026-08-01T17:25:22 p=153 f=0  ->  105:_r11014_sub_gf180_util035 v1.10.14 2026-08-09T11:15:57 p=154 f=0 |
| .114 | `_agent_scratch_ibexsky` | 396 | 11574 | not applied | 8 file(s) -> `docs/research/fleet_run_folder_triage_evidence/114/_agent_scratch_ibexsky/` | all 2 run(s) have a later, not-older-version, at-least-as-complete successor; e.g. ibex@sky130A v1.9.82 2026-08-05T16:55:52 p=160 f=1  ->  114:_c12_ibex_sky130A v1.10.11 2026-08-09T09:28:45 p=160 f=1 |
| .114 | `_c_o_subservient_gf180mcuD_run` | 260 | 586 | not applied | 4 layout(s) -> `~/_kept_layouts/` | all 1 run(s) have a later, not-older-version, at-least-as-complete successor; e.g. subservient@gf180mcuD v0.119.62 2026-08-04T02:49:13 p=154 f=0  ->  105:_r11014_sub_gf180_util035 v1.10.14 2026-08-09T11:15:57 p=154 f=0 |
| .114 | `_ot_aes_run` | 211 | 1338 | not applied | 4 file(s) -> `docs/research/fleet_run_folder_triage_evidence/114/_ot_aes_run/` | all 1 run(s) have a later, not-older-version, at-least-as-complete successor; e.g. opentitan_aes@sky130A v1.10.2 2026-08-08T17:40:05 p=162 f=0  ->  114:_c12_opentitan_aes_sky130A v1.10.18 2026-08-10T14:42:03 p=162 f=0 |
| .114 | `_c_aes9_run` | 190 | 660 | not applied | 5 file(s) -> `docs/research/fleet_run_folder_triage_evidence/114/_c_aes9_run/` | all 1 run(s) have a later, not-older-version, at-least-as-complete successor; e.g. opentitan_aes@sky130A v0.119.62 2026-08-01T08:54:59 p=150 f=3  ->  114:_c_nda_opentitan_aes_run v0.119.62 2026-08-05T07:46:43 p=163 f=0 |
| .114 | `_c_aes3_run` | 184 | 646 | not applied | — | all 1 run(s) have a later, not-older-version, at-least-as-complete successor; e.g. opentitan_aes@sky130A v0.119.62 2026-07-31T09:51:36 p=150 f=2  ->  114:_c_nda_opentitan_aes_run v0.119.62 2026-08-05T07:46:43 p=163 f=0 |
| .114 | `_agent_scratch_ibex3` | 122 | 4014 | not applied | — | all 1 run(s) have a later, not-older-version, at-least-as-complete successor; e.g. ibex@sky130A v1.9.82 2026-08-05T13:59:29 p=159 f=1  ->  114:_c12_ibex_sky130A v1.10.11 2026-08-09T09:28:45 p=160 f=1 |
| .114 | `_c_aes7_run` | 106 | 637 | not applied | — | all 1 run(s) have a later, not-older-version, at-least-as-complete successor; e.g. opentitan_aes@sky130A v0.119.62 2026-07-31T17:58:26 p=150 f=3  ->  114:_c_nda_opentitan_aes_run v0.119.62 2026-08-05T07:46:43 p=163 f=0 |
| .114 | `_c_aes_run` | 102 | 619 | not applied | — | all 1 run(s) have a later, not-older-version, at-least-as-complete successor; e.g. opentitan_aes@ihp-sg13g2 v0.119.62 2026-07-31T07:24:21 p=146 f=5  ->  120:_c_nda3_opentitan_aes_run v0.119.62 2026-08-04T14:43:37 p=160 f=1 |
| .114 | `_c_aes2_run` | 101 | 625 | not applied | — | all 1 run(s) have a later, not-older-version, at-least-as-complete successor; e.g. opentitan_aes@ihp-sg13g2 v0.119.62 2026-07-31T09:03:36 p=148 f=4  ->  120:_c_nda3_opentitan_aes_run v0.119.62 2026-08-04T14:43:37 p=160 f=1 |
| .114 | `_c_cv_spm_run` | 71 | 652 | not applied | 1 layout(s) -> `~/_kept_layouts/` | all 1 run(s) have a later, not-older-version, at-least-as-complete successor; e.g. spm@ihp-sg13g2 v0.119.62 2026-08-03T06:14:46 p=150 f=4  ->  105:_c_nda2_spm_run v0.119.62 2026-08-05T07:07:57 p=154 f=0 |
| .114 | `_c12_opentitan_aes_sky130A_PREFIX_20260809_1257` | 50 | 1281 | not applied | — | all 1 run(s) have a later, not-older-version, at-least-as-complete successor; e.g. opentitan_aes@sky130A v1.10.11 2026-08-09T04:57:43 p=160 f=0  ->  114:_c12_opentitan_aes_sky130A v1.10.18 2026-08-10T14:42:03 p=162 f=0 |
| .114 | `_c_o_opentitan_aes_sky130A_run` | 45 | 816 | not applied | — | all 1 run(s) have a later, not-older-version, at-least-as-complete successor; e.g. opentitan_aes@sky130A v0.119.62 2026-08-04T02:31:12 p=161 f=1  ->  114:_c_nda_opentitan_aes_run v0.119.62 2026-08-05T07:46:43 p=163 f=0 |
| .114 | `_c_spm_run` | 33 | 611 | not applied | 2 layout(s) -> `~/_kept_layouts/` | all 1 run(s) have a later, not-older-version, at-least-as-complete successor; e.g. spm@sky130A v1.9.86 2026-08-05T22:14:12 p=154 f=0  ->  105:_agentjob_p1a v1.10.18 2026-08-09T11:18:38 p=154 f=0 |
| .114 | `_final_gf1802` | 15 | 387 | not applied | 1 layout(s) -> `~/_kept_layouts/` | all 1 run(s) have a later, not-older-version, at-least-as-complete successor; e.g. spm@gf180mcuD v0.119.62 2026-07-27T00:18:35 p=0 f=3  ->  120:_spmpass v1.10.96 2026-08-20T04:11:34 p=154 f=0 |
| .114 | `_final_gf180` | 2 | 271 | not applied | — | all 1 run(s) have a later, not-older-version, at-least-as-complete successor; e.g. spm@sky130A v0.119.62 2026-07-27T00:16:01 p=0 f=1  ->  105:_agentjob_p1a v1.10.18 2026-08-09T11:18:38 p=154 f=0 |
| .120 | `_c_sha2_run` | 2726 | 2118 | not applied | 1 layout(s) -> `~/_kept_layouts/`; 13 file(s) -> `docs/research/fleet_run_folder_triage_evidence/120/_c_sha2_run/` | all 3 run(s) have a later, not-older-version, at-least-as-complete successor; e.g. sha256@sky130A v0.119.62 2026-07-31T16:26:13 p=157 f=0  ->  120:_c_o_sha256_sky130A_run v1.9.84 2026-08-05T14:51:52 p=159 f=0 |
| .120 | `_agent_scratch_sha256sky` | 1088 | 735 | not applied | 3 file(s) -> `docs/research/fleet_run_folder_triage_evidence/120/_agent_scratch_sha256sky/` | all 1 run(s) have a later, not-older-version, at-least-as-complete successor; e.g. sha256@sky130A v1.9.82 2026-08-05T12:33:43 p=159 f=0  ->  120:_c_o_sha256_sky130A_run v1.9.84 2026-08-05T14:51:52 p=159 f=0 |
| .120 | `_c_o_caravel_user_project_sky130A_run` | 647 | 645 | not applied | 1 layout(s) -> `~/_kept_layouts/` | all 1 run(s) have a later, not-older-version, at-least-as-complete successor; e.g. caravel_user_project@sky130A v1.9.86 2026-08-05T15:51:24 p=158 f=0  ->  105:_c_car_v11027_run v1.10.27 2026-08-09T16:48:08 p=158 f=0 |
| .120 | `_c_sha4_run` | 603 | 381 | not applied | 6 file(s) -> `docs/research/fleet_run_folder_triage_evidence/120/_c_sha4_run/` | all 1 run(s) have a later, not-older-version, at-least-as-complete successor; e.g. sha256@sky130A v0.119.62 2026-08-02T15:28:49 p=157 f=0  ->  121:_bm_sha256_sky130A_121 v1.10.29 2026-08-10T08:38:16 p=159 f=0 |
| .120 | `_c_nda_sha256_run` | 515 | 262 | not applied | — | all 1 run(s) have a later, not-older-version, at-least-as-complete successor; e.g. sha256@sky130A v0.119.62 2026-08-04T15:21:14 p=159 f=0  ->  121:_bm_sha256_sky130A_121 v1.10.29 2026-08-10T08:38:16 p=159 f=0 |
| .120 | `_c_nda2_sha256_run` | 489 | 744 | not applied | 1 layout(s) -> `~/_kept_layouts/` | all 1 run(s) have a later, not-older-version, at-least-as-complete successor; e.g. sha256@ihp-sg13g2 v0.119.62 2026-08-05T09:02:39 p=157 f=1  ->  120:_r10_sha256_ndapdk_run v1.10.26 2026-08-09T17:05:56 p=157 f=1 |
| .120 | `_c_cv_caravel_user_project_run` | 318 | 12100 | not applied | 1 layout(s) -> `~/_kept_layouts/` | all 1 run(s) have a later, not-older-version, at-least-as-complete successor; e.g. caravel_user_project@ihp-sg13g2 v0.119.62 2026-08-03T06:53:17 p=157 f=3  ->  121:_c_caravel_user_project_ndapdk v1.10.26 2026-08-10T00:49:54 p=157 f=0 |
| .120 | `_c_ndam_spm_run` | 314 | 12054 | not applied | 1 layout(s) -> `~/_kept_layouts/` | all 1 run(s) have a later, not-older-version, at-least-as-complete successor; e.g. spm@sky130A v0.119.62 2026-08-03T01:41:23 p=154 f=0  ->  105:_agentjob_p1a v1.10.18 2026-08-09T11:18:38 p=154 f=0 |
| .120 | `_final_ihp2` | 29 | 380 | not applied | 1 layout(s) -> `~/_kept_layouts/` | all 1 run(s) have a later, not-older-version, at-least-as-complete successor; e.g. spm@ihp-sg13g2 v0.119.62 2026-07-26T23:50:17 p=0 f=4  ->  105:_c_nda2_spm_run v0.119.62 2026-08-05T07:07:57 p=154 f=0 |
| .120 | `_spmlec` | 29 | 376 | not applied | 1 layout(s) -> `~/_kept_layouts/` | all 1 run(s) have a later, not-older-version, at-least-as-complete successor; e.g. spm@ihp-sg13g2 v0.119.62 2026-07-26T17:54:38 p=0 f=4  ->  105:_c_nda2_spm_run v0.119.62 2026-08-05T07:07:57 p=154 f=0 |
| .120 | `_spmcombo` | 28 | 377 | not applied | 1 layout(s) -> `~/_kept_layouts/` | all 1 run(s) have a later, not-older-version, at-least-as-complete successor; e.g. spm@ihp-sg13g2 v0.119.62 2026-07-26T17:44:12 p=0 f=4  ->  105:_c_nda2_spm_run v0.119.62 2026-08-05T07:07:57 p=154 f=0 |
| .120 | `_spmpf` | 28 | 377 | not applied | 1 layout(s) -> `~/_kept_layouts/` | all 1 run(s) have a later, not-older-version, at-least-as-complete successor; e.g. spm@ihp-sg13g2 v0.119.62 2026-07-26T17:54:56 p=0 f=4  ->  105:_c_nda2_spm_run v0.119.62 2026-08-05T07:07:57 p=154 f=0 |
| .120 | `_provgap2` | 28 | 373 | not applied | 1 layout(s) -> `~/_kept_layouts/` | all 1 run(s) have a later, not-older-version, at-least-as-complete successor; e.g. spm@ihp-sg13g2 v0.119.62 2026-07-26T17:13:48 p=0 f=0  ->  105:_c_nda2_spm_run v0.119.62 2026-08-05T07:07:57 p=154 f=0 |
| .120 | `_provgap` | 28 | 373 | not applied | 1 layout(s) -> `~/_kept_layouts/` | all 1 run(s) have a later, not-older-version, at-least-as-complete successor; e.g. spm@ihp-sg13g2 v0.119.62 2026-07-26T17:09:21 p=0 f=0  ->  105:_c_nda2_spm_run v0.119.62 2026-08-05T07:07:57 p=154 f=0 |
| .120 | `_spmfinal` | 28 | 375 | not applied | 1 layout(s) -> `~/_kept_layouts/` | all 1 run(s) have a later, not-older-version, at-least-as-complete successor; e.g. spm@ihp-sg13g2 v0.119.62 2026-07-26T17:42:16 p=0 f=0  ->  105:_c_nda2_spm_run v0.119.62 2026-08-05T07:07:57 p=154 f=0 |
| .120 | `_bm4a_spm_gf180mcuD_run` | 20 | 550 | not applied | — | all 1 run(s) have a later, not-older-version, at-least-as-complete successor; e.g. spm@gf180mcuD v1.10.18 2026-08-09T13:11:55 p=154 f=0  ->  120:_spmpass v1.10.96 2026-08-20T04:11:34 p=154 f=0 |
| .120 | `_final_sky2` | 9 | 388 | not applied | — | all 1 run(s) have a later, not-older-version, at-least-as-complete successor; e.g. spm@sky130A v0.119.62 2026-07-27T00:17:54 p=0 f=3  ->  105:_agentjob_p1a v1.10.18 2026-08-09T11:18:38 p=154 f=0 |
| .120 | `_final_sky` | 2 | 271 | not applied | — | all 1 run(s) have a later, not-older-version, at-least-as-complete successor; e.g. spm@sky130A v0.119.62 2026-07-27T00:15:59 p=0 f=1  ->  105:_agentjob_p1a v1.10.18 2026-08-09T11:18:38 p=154 f=0 |
| .120 | `_final_ihp3` | 2 | 271 | not applied | — | all 1 run(s) have a later, not-older-version, at-least-as-complete successor; e.g. spm@ihp-sg13g2 v0.119.62 2026-07-26T23:51:37 p=0 f=1  ->  105:_c_nda2_spm_run v0.119.62 2026-08-05T07:07:57 p=154 f=0 |
| .120 | `_final_ihp` | 1 | 170 | not applied | — | all 1 run(s) have a later, not-older-version, at-least-as-complete successor; e.g. spm@ihp-sg13g2 v0.119.62 2026-07-26T23:48:14 p=0 f=0  ->  105:_c_nda2_spm_run v0.119.62 2026-08-05T07:07:57 p=154 f=0 |
| .121 | `_ibex_v1102_sky130A_run` | 779 | 512 | not applied | — | all 1 run(s) have a later, not-older-version, at-least-as-complete successor; e.g. ibex@sky130A v1.10.2 2026-08-08T13:32:29 p=159 f=1  ->  114:_c12_ibex_sky130A v1.10.11 2026-08-09T09:28:45 p=160 f=1 |
| .121 | `_c12_caravel_user_project_sky130A_v11026` | 647 | 700 | not applied | — | all 1 run(s) have a later, not-older-version, at-least-as-complete successor; e.g. caravel_user_project@sky130A v1.10.26 2026-08-09T16:36:33 p=158 f=0  ->  105:_c_car_v11027_run v1.10.27 2026-08-09T16:48:08 p=158 f=0 |
| .121 | `_c_subsv5_run` | 458 | 664 | not applied | 1 layout(s) -> `~/_kept_layouts/` | all 1 run(s) have a later, not-older-version, at-least-as-complete successor; e.g. subservient@sky130A v0.119.62 2026-08-02T20:53:47 p=152 f=0  ->  105:_r11014_subservient_sky130A v1.10.14 2026-08-09T13:26:46 p=154 f=0 |
| .121 | `_c_subsv6_run` | 453 | 665 | not applied | 1 layout(s) -> `~/_kept_layouts/` | all 1 run(s) have a later, not-older-version, at-least-as-complete successor; e.g. subservient@sky130A v0.119.62 2026-08-02T22:53:14 p=152 f=0  ->  105:_r11014_subservient_sky130A v1.10.14 2026-08-09T13:26:46 p=154 f=0 |
| .121 | `_c_nda2_subservient_run` | 353 | 12109 | not applied | 2 layout(s) -> `~/_kept_layouts/` | all 1 run(s) have a later, not-older-version, at-least-as-complete successor; e.g. subservient@ihp-sg13g2 v0.119.62 2026-08-05T09:21:41 p=153 f=0  ->  105:_c_subsv_ndapdk_run v1.10.26 2026-08-09T16:43:19 p=154 f=0 |
| .121 | `_c_subsv4_run` | 296 | 449 | not applied | 1 layout(s) -> `~/_kept_layouts/` | all 1 run(s) have a later, not-older-version, at-least-as-complete successor; e.g. subservient@sky130A v0.119.62 2026-08-02T16:31:48 p=152 f=0  ->  105:_r11014_subservient_sky130A v1.10.14 2026-08-09T13:26:46 p=154 f=0 |
| .121 | `_c_o_subservient_gf180mcuD_run` | 276 | 611 | not applied | 4 layout(s) -> `~/_kept_layouts/` | all 1 run(s) have a later, not-older-version, at-least-as-complete successor; e.g. subservient@gf180mcuD v1.9.84 2026-08-05T14:45:57 p=154 f=0  ->  105:_r11014_sub_gf180_util035 v1.10.14 2026-08-09T11:15:57 p=154 f=0 |
| .121 | `_c_nda_edge_llm_matmul_accel_run` | 153 | 561 | not applied | — | all 1 run(s) have a later, not-older-version, at-least-as-complete successor; e.g. edge_llm_matmul_accel@sky130A v0.119.62 2026-08-04T17:48:45 p=149 f=3  ->  105:_c_nda_edge_llm_matmul_accel_run v0.119.62 2026-08-05T08:53:28 p=152 f=1 |
| .121 | `_c3_adc_scratch` | 121 | 1340 | not applied | 2 layout(s) -> `~/_kept_layouts/`; 15 file(s) -> `docs/research/fleet_run_folder_triage_evidence/121/_c3_adc_scratch/` | all 2 run(s) have a later, not-older-version, at-least-as-complete successor; e.g. u_hawaii_adc@ihp-sg13g2 v0.119.62 2026-07-31T09:25:43 p=157 f=7  ->  121:_c_adc9_run v0.119.62 2026-08-01T08:51:31 p=158 f=6 |

## 7. HARVEST — holds a measurement that exists nowhere else

These stay. The evidence column says what the measurement is and where it should go.

362 folders, 117.6 GB.

| host | folder | MB | files | evidence | where it should go |
|---|---|---:|---:|---|---|
| .105 | `_c_o_edge_llm_matmul_accel_nangate45_run` | 9561 | 798 | run edge_llm_matmul_accel@nangate45 v1.9.84 2026-08-05T14:31:00 verdict=FAIL gates 158/0 of 246; 3 run roots; 26 file contents (1 MB) exist in no other folder and in no repo; 3 GDS | publishable candidate — `benchmark-data/ic/edge_llm_matmul_accel/v1.9.84_nangate45/` |
| .105 | `_c_car_run` | 2533 | 2399 | run caravel_user_project@sky130A v0.119.62 2026-07-31T08:54:36 verdict=FAIL gates 157/0 of -; 5 run roots; 878 file contents (971 MB) exist in no other folder and in no repo; 12 GDS | publishable candidate — `benchmark-data/ic/caravel_user_project/v0.119.62_sky130A/` |
| .105 | `_n_sha256` | 2085 | 5488 | HELD BY THE AT-RISK-LAYOUT GUARD: 6 streamed layout(s), 145.9 MB, exist in no git ref, in no surviving folder and were not preserved into _kept_layouts; e.g. _n_sha256/run_stock_baseline/phase3/stage4/gds/sha256.gds | publish or preserve the layout before this folder can be reaped |
| .105 | `_c_car7_run` | 1895 | 1743 | HELD BY THE AT-RISK-LAYOUT GUARD: 9 streamed layout(s), 835.5 MB, exist in no git ref, in no surviving folder and were not preserved into _kept_layouts; e.g. _c_car7_run/iter3/phase3/stage4/gds/user_project_wrapper.gds | publish or preserve the layout before this folder can be reaped |
| .105 | `_w1_repro` | 1496 | 687 | no flow audit record; content is json x366, log x113, txt x79, gds x21; 321 file contents (1040 MB) exist in no other folder and in no repo; 21 GDS | keep in place — sole copy of its content |
| .105 | `_c_car15_run` | 716 | 4667 | LIVE — held open right now: cwd pid=121520 tail -n0 -F /home/reyerchu/_c_car15_run/runA.log | leave alone until the run finishes |
| .105 | `_c12_caravel_user_project_sky130A` | 647 | 702 | LIVE — held open right now: cwd pid=3962628 /usr/bin/python3 /home/reyerchu/.claude/plugins/cache/vibe-ic-marketplace/vibe-i | leave alone until the run finishes |
| .105 | `_c_car_v11027_run` | 647 | 706 | run caravel_user_project@sky130A v1.10.27 2026-08-09T16:48:08 verdict=FAIL gates 158/0 of 246; 282 file contents (121 MB) exist in no other folder and in no repo; 3 GDS | publishable candidate — `benchmark-data/ic/caravel_user_project/v1.10.27_sky130A/` |
| .105 | `_c_car10_run` | 629 | 579 | HELD BY THE AT-RISK-LAYOUT GUARD: 3 streamed layout(s), 277.6 MB, exist in no git ref, in no surviving folder and were not preserved into _kept_layouts; e.g. _c_car10_run/iter1/phase3/stage4/gds/user_project_wrapper.gds | publish or preserve the layout before this folder can be reaped |
| .105 | `_bm_edge_matmul_sky130A_v11018` | 301 | 713 | run edge_llm_matmul_accel@sky130A v1.10.18 2026-08-09T15:58:26 verdict=FAIL gates 151/1 of 246; 349 file contents (208 MB) exist in no other folder and in no repo; 5 GDS | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .105 | `_jseal_evidence` | 293 | 730 | run spm3@gf180mcuD v1.10.96 2026-08-19T17:03:00 verdict=FAIL gates 149/6 of 246; 2 run roots; 183 file contents (243 MB) exist in no other folder and in no repo; 15 GDS | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .105 | `_agent_scratch_r2_otaes` | 227 | 16 | no flow audit record; content is json x6, stdout x4, exit x4, gds x2; 16 file contents (227 MB) exist in no other folder and in no repo; 2 GDS | keep in place — sole copy of its content |
| .105 | `_c_subsv_ndapdk_run` | 199 | 755 | run subservient@ihp-sg13g2 v1.10.26 2026-08-09T16:43:19 verdict=FAIL gates 154/0 of 246; 361 file contents (50 MB) exist in no other folder and in no repo; 4 GDS | publishable candidate — `benchmark-data/ic/subservient/v1.10.26_ihp-sg13g2/` |
| .105 | `_c_nda_edge_llm_matmul_accel_run` | 157 | 602 | run edge_llm_matmul_accel@sky130A v0.119.62 2026-08-05T08:53:28 verdict=FAIL gates 152/1 of 246; 52 file contents (5 MB) exist in no other folder and in no repo; 3 GDS | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .105 | `_r11014_subservient_sky130A` | 124 | 792 | run subservient@sky130A v1.10.14 2026-08-09T13:26:46 verdict=FAIL gates 154/0 of 246; 203 file contents (33 MB) exist in no other folder and in no repo; 5 GDS | publishable candidate — `benchmark-data/ic/subservient/v1.10.14_sky130A/` |
| .105 | `_s130sub_run_big` | 107 | 690 | run subservient@sky130A v1.10.29 2026-08-10T00:02:43 verdict=FAIL gates 153/1 of 246; 243 file contents (36 MB) exist in no other folder and in no repo | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .105 | `_c_nda2_spm_run` | 101 | 595 | LIVE — held open right now: cwd pid=2496008 /usr/bin/python3 /home/reyerchu/.claude/plugins/cache/vibe-ic-marketplace/vibe-i | leave alone until the run finishes |
| .105 | `_s130sub_run` | 86 | 644 | run subservient@sky130A v1.10.29 2026-08-10T16:10:16 verdict=FAIL gates 153/1 of 246; 191 file contents (16 MB) exist in no other folder and in no repo | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .105 | `_bench_ve_run` | 76 | 10182 | no flow audit record; content is json x3622, py x3391, md x1102, yaml x795; 3420 file contents (5 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .105 | `_hyg32work` | 73 | 4875 | no flow audit record; content is py x3987, patch x252, yaml x210, md x186; 285 file contents (1 MB) exist in no other folder and in no repo; 1 GDS | keep in place — sole copy of its content |
| .105 | `_w6ctlC` | 71 | 4510 | no flow audit record; content is py x3981, yaml x210, md x182, json x69; 1 file contents (0 MB) exist in no other folder and in no repo; 1 GDS | keep in place — sole copy of its content |
| .105 | `_c_nda_elm_v11026_run` | 65 | 547 | run edge_llm_matmul_accel@- v1.10.26 2026-08-09T16:42:42 verdict=FAIL gates 151/1 of 246; 346 file contents (45 MB) exist in no other folder and in no repo; 3 GDS | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .105 | `_agentjob_r3a` | 64 | 843 | no flow audit record; content is json x272, stdout x268, rc x268, txt x24; 571 file contents (63 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .105 | `_agent_scratch_otaes` | 64 | 3740 | no flow audit record; content is py x3506, pyc x130, json x38, md x31; 17 file contents (1 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .105 | `_r11014_sub_gf180_util035` | 53 | 653 | run subservient@gf180mcuD v1.10.14 2026-08-09T11:15:57 verdict=FAIL gates 154/0 of 246; 264 file contents (36 MB) exist in no other folder and in no repo; 3 GDS | publishable candidate — `benchmark-data/ic/subservient/v1.10.14_gf180mcuD/` |
| .105 | `_bm_scratch_sub_gf180` | 50 | 343 | run subservient@gf180mcuD v1.10.18 2026-08-09T13:54:47 verdict=FAIL gates 154/0 of 246; 200 file contents (44 MB) exist in no other folder and in no repo | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .105 | `_agentjob_p1a` | 45 | 1953 | run spm@sky130A v1.10.18 2026-08-09T11:18:38 verdict=PASS_WITH_WAIVERS gates 154/0 of 246; 4 run roots; 18 file contents (1 MB) exist in no other folder and in no repo; 4 GDS | publishable candidate — `benchmark-data/ic/spm/v1.10.18_sky130A/` |
| .105 | `_sshut_run` | 41 | 2020 | run spm@gf180mcuD v1.10.18 2026-08-09T11:18:38 verdict=PASS_WITH_WAIVERS gates 154/0 of 246; 6 run roots; 93 file contents (6 MB) exist in no other folder and in no repo; 12 GDS | publishable candidate — `benchmark-data/ic/spm/v1.10.18_gf180mcuD/` |
| .105 | `_r11014_edge_llm_accel_sky130A` | 35 | 252 | no flow audit record; content is json x192, md x14, v x13, txt x9; 54 file contents (34 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .105 | `_c_nda_edge_llm_accel_run` | 30 | 288 | run edge_llm_accel@nangate45 v1.10.29 2026-08-09T22:36:10 verdict=FAIL gates 0/0 of 246; 74 file contents (28 MB) exist in no other folder and in no repo | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .105 | `_s130sub_scratch` | 27 | 29 | no flow audit record; content is log x14, xml x6, gds x4, tcl x2; 27 file contents (27 MB) exist in no other folder and in no repo; 4 GDS | keep in place — sole copy of its content |
| .105 | `_h32work` | 3 | 1041 | no flow audit record; content is sample x210, lib x188, md x105, py x71; 57 file contents (1 MB) exist in no other folder and in no repo; 1 GDS | keep in place — sole copy of its content |
| .105 | `_h32mine` | 3 | 1984 | no flow audit record; content is sample x532, json x164, py x140, lib x110; 226 file contents (1 MB) exist in no other folder and in no repo; 1 GDS | keep in place — sole copy of its content |
| .105 | `_c12_subservient_sky130A` | 2 | 249 | LIVE — held open right now: cwd pid=3962668 /usr/bin/python3 /home/reyerchu/.claude/plugins/cache/vibe-ic-marketplace/vibe-i | leave alone until the run finishes |
| .105 | `_agent_scratch_r2_mmnan` | 1 | 15 | no flow audit record; content is py x6, pyc x4, v x3, json x1; 5 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .105 | `_agentjob_d9page` | 1 | 9 | no flow audit record; content is json x4, html x3, py x1, log x1; 9 file contents (1 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .105 | `_w6scratch` | 0 | 101 | run -@- v- - verdict=PASS_WITH_WAIVERS gates -/- of -; 3 run roots; 48 file contents (0 MB) exist in no other folder and in no repo; 5 GDS | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .105 | `_jd9scratch` | 0 | 45 | no flow audit record; content is log x13, txt x9, py x8, json x5; 37 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .105 | `_agent_scratch_edge_llm_matmul_accel` | 0 | 22 | no flow audit record; content is txt x6, pid x6, log x6, md x2; 22 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .105 | `_agent_scratch_mmnan` | 0 | 13 | no flow audit record; content is txt x4, py x4, tcl x1, rpt x1; 7 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .105 | `_agent_scratch_spm8` | 0 | 18 | no flow audit record; content is json x14, txt x4; 9 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .105 | `_agent_scratch_mm4` | 0 | 15 | no flow audit record; content is txt x3, tcl x3, stale x3, log x3; 9 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .105 | `_agent_scratch_mm9` | 0 | 4 | no flow audit record; content is md x4; 3 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .105 | `_bm_scratch_edge_matmul` | 0 | 5 | no flow audit record; content is vvp x1, v x1, sh x1, md x1; 5 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .105 | `_batchA` | 0 | 9 | no flow audit record; content is log x3, txt x2, sh x2, out x1; 8 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .105 | `_rgtmp_mainnow` | 0 | 224 | no flow audit record; content is py x115, yaml x74, json x26, txt x3; 4 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .105 | `_m` | 0 | 21 | no flow audit record; content is py x19, md x2; 21 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .105 | `_v1360` | 0 | 12 | no flow audit record; content is md x4, log x3, sh x2, py x2; 12 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .105 | `_agent_scratch_mm6` | 0 | 2 | no flow audit record; content is md x2; 2 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .105 | `_v1442` | 0 | 7 | no flow audit record; content is xml x4, sh x1, md x1, log x1; 7 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .105 | `_ver3` | 0 | 15 | no flow audit record; content is txt x5, set x4, sh x2, log x2; 13 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .105 | `_r68` | 0 | 10 | no flow audit record; content is py x3, txt x2, md x2, log x2; 10 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .105 | `_v1447` | 0 | 5 | no flow audit record; content is sh x2, txt x1, md x1, bak x1; 4 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .105 | `_agent_scratch_elm_r10` | 0 | 5 | no flow audit record; content is json x2, sv x1, pid x1, md x1; 5 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .105 | `_v1380` | 0 | 7 | no flow audit record; content is sh x3, log x2, py x1, md x1; 7 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .105 | `_agent_scratch_mm5` | 0 | 1 | no flow audit record; content is md x1; 1 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .105 | `_R1` | 0 | 3 | no flow audit record; content is xml x1, md x1, log x1; 3 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .105 | `_v1393` | 0 | 5 | no flow audit record; content is txt x2, sh x2, md x1; 5 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .105 | `_agent_scratch_spm2` | 0 | 3 | no flow audit record; content is json x2, md x1; 1 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .105 | `_capA_run` | 0 | 1 | no flow audit record; content is md x1; 1 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .105 | `_v1412` | 0 | 5 | no flow audit record; content is log x3, sh x1, md x1; 5 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .105 | `_v1235` | 0 | 6 | no flow audit record; content is sh x2, log x2, txt x1, md x1; 6 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .105 | `_v1448` | 0 | 5 | no flow audit record; content is sh x2, log x2, md x1; 5 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .105 | `_v1417` | 0 | 6 | no flow audit record; content is sh x2, md x2, log x2; 6 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .105 | `_v1399` | 0 | 4 | no flow audit record; content is sh x2, md x1, log x1; 4 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .105 | `_d7atom` | 0 | 5 | no flow audit record; content is py x2, sh x1, md x1, log x1; 5 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .105 | `_R4` | 0 | 5 | no flow audit record; content is sh x2, out x1, md x1, log x1; 5 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .105 | `_o443` | 0 | 5 | no flow audit record; content is txt x2, py x2, md x1; 5 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .105 | `_v1467` | 0 | 2 | no flow audit record; content is md x2; 2 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .105 | `_adv105_cache` | 0 | 3 | no flow audit record; content is xml x1, log x1, json x1; 3 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .105 | `_v1392` | 0 | 5 | no flow audit record; content is sh x2, py x1, path x1, md x1; 5 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .105 | `_v1488` | 0 | 3 | no flow audit record; content is sh x1, py x1, md x1; 3 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .105 | `_v1487` | 0 | 2 | no flow audit record; content is sh x1, md x1; 2 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .105 | `_v1466` | 0 | 4 | no flow audit record; content is py x2, sh x1, md x1; 4 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .105 | `_v1465` | 0 | 2 | no flow audit record; content is sh x1, md x1; 2 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .105 | `_ver` | 0 | 3 | no flow audit record; content is sh x1, md x1, log x1; 3 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .105 | `_atom` | 0 | 1 | no flow audit record; content is md x1; 1 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .105 | `_v1396` | 0 | 2 | no flow audit record; content is sh x1, md x1; 2 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .105 | `_v1471` | 0 | 1 | no flow audit record; content is md x1; 1 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .105 | `_synthetic_spef_repro` | 0 | 1 | no flow audit record; content is spef x1; 1 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .105 | `_cvdp` | 0 | 3 | no flow audit record; content is sh x1, md x1, log x1; 3 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .105 | `_v1491` | 0 | 1 | no flow audit record; content is md x1; 1 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .105 | `_vx` | 0 | 1 | no flow audit record; content is md x1; 1 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .105 | `_o434` | 0 | 1 | no flow audit record; content is md x1; 1 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .105 | `_c1272` | 0 | 1 | no flow audit record; content is md x1; 1 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .108 | `_spmrun_8HD-6` | 163 | 1349 | run (unknown — fill in via L1_DATASHEET.json[ic_name])@gf180mcuD v1.10.96 2026-08-20T01:42:28 verdict=FAIL gates 141/4 of 246; 3 run roots; 785 file contents (91 MB) exist in no other folder and in no repo; 11 GDS | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .108 | `_pcbase_8HD-6` | 7 | 24 | no flow audit record; content is json x12, log x6, txt x2, gds x1; 12 file contents (7 MB) exist in no other folder and in no repo; 1 GDS | keep in place — sole copy of its content |
| .108 | `_pcfinal_8HD-6` | 5 | 24 | no flow audit record; content is json x12, log x6, txt x2, gds x1; 12 file contents (5 MB) exist in no other folder and in no repo; 1 GDS | keep in place — sole copy of its content |
| .108 | `_w3_scratch` | 0 | 19 | no flow audit record; content is sv x13, txt x5, json x1; 7 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .112 | `_n8_sn2025` | 2179 | 84315 | run Universal Serial Bus (USB 2.0)@- v0.119.62 2026-07-30T17:13:39 verdict=FAIL gates 166/13 of -; 2 run roots; 70 file contents (5 MB) exist in no other folder and in no repo; 7 GDS | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .112 | `_n9_sn2025_scratch` | 2036 | 50500 | run Universal Serial Bus (USB 2.0)@ihp-sg13g2 v0.119.62 2026-07-30T18:29:46 verdict=FAIL gates 167/12 of -; 5 run roots; 118 file contents (2 MB) exist in no other folder and in no repo; 20 GDS | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .112 | `_agentjob_sn25` | 2025 | 48635 | run Universal Serial Bus (USB 2.0)@ihp-sg13g2 v1.10.30 2026-08-11T14:53:07 verdict=FAIL gates 173/13 of 246; 4 run roots; 133 file contents (9 MB) exist in no other folder and in no repo; 20 GDS | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .112 | `_n24_sn2025` | 1345 | 36088 | HELD BY THE OUT-OF-ROOT GUARD: 21 artefact content(s), 0.15 MB, live outside every run root of this folder, in no surviving folder and in no git ref; supersession is an argument about runs and does not cover them | the out-of-run content is the deliverable — publish it or fold it into the repo |
| .112 | `_n11_sn2025` | 1323 | 44030 | run Universal Serial Bus (USB 2.0)@ihp-sg13g2 v0.119.62 2026-07-31T09:56:55 verdict=FAIL gates 168/12 of -; 3 run roots; 481 file contents (9 MB) exist in no other folder and in no repo; 6 GDS | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .112 | `_r6_sn2025` | 1271 | 53799 | HELD BY THE AT-RISK-LAYOUT GUARD: 2 streamed layout(s), 0.0 MB, exist in no git ref, in no surviving folder and were not preserved into _kept_layouts; e.g. _r6_sn2025/scratch_geom_signoff_tests/fill/phase3/stage4/gds/top.filled.gds | publish or preserve the layout before this folder can be reaped |
| .112 | `_n9_sn2025` | 1262 | 42018 | run Universal Serial Bus (USB 2.0)@ihp-sg13g2 v0.119.62 2026-07-30T18:25:35 verdict=FAIL gates 169/10 of -; 28 file contents (8 MB) exist in no other folder and in no repo; 7 GDS | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .112 | `_r5_rank` | 1127 | 7584 | run (unknown — fill in via L1_DATASHEET.json[ic_name])@- v0.119.62 2026-05-24T21:46:35 verdict=PASS_WITH_WAIVERS gates 0/0 of -; 4 run roots; 41 file contents (3 MB) exist in no other folder and in no repo; 40 GDS | publishable candidate — `benchmark-data/ic/(unknown — fill in via L1_DATASHEET.json[ic_name])/v0.119.62_-/` |
| .112 | `_r4_diff` | 1112 | 683 | run (unknown — fill in via L1_DATASHEET.json[ic_name])@- v0.119.62 2026-05-24T21:46:35 verdict=PASS_WITH_WAIVERS gates 0/0 of -; 5 run roots; 6 file contents (9 MB) exist in no other folder and in no repo; 42 GDS | publishable candidate — `benchmark-data/ic/(unknown — fill in via L1_DATASHEET.json[ic_name])/v0.119.62_-/` |
| .112 | `_a13_diff3` | 853 | 446 | run (unknown — fill in via L1_DATASHEET.json[ic_name])@- v0.119.62 2026-05-24T21:46:35 verdict=PASS_WITH_WAIVERS gates 0/0 of -; 4 run roots; 4 file contents (1 MB) exist in no other folder and in no repo; 28 GDS | publishable candidate — `benchmark-data/ic/(unknown — fill in via L1_DATASHEET.json[ic_name])/v0.119.62_-/` |
| .112 | `_r4_sn2025` | 837 | 33260 | run Universal Serial Bus (USB 2.0)@- v0.119.62 2026-07-30T10:41:56 verdict=FAIL gates 166/11 of -; 186 file contents (54 MB) exist in no other folder and in no repo; 5 GDS | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .112 | `_r4_props` | 752 | 402 | run (unknown — fill in via L1_DATASHEET.json[ic_name])@- v0.119.62 2026-05-24T21:46:35 verdict=PASS_WITH_WAIVERS gates 0/0 of -; 3 run roots; 2 file contents (0 MB) exist in no other folder and in no repo; 24 GDS | publishable candidate — `benchmark-data/ic/(unknown — fill in via L1_DATASHEET.json[ic_name])/v0.119.62_-/` |
| .112 | `_n25_sn2025` | 576 | 12250 | HELD BY THE OUT-OF-ROOT GUARD: 78 artefact content(s), 54.63 MB, live outside every run root of this folder, in no surviving folder and in no git ref; supersession is an argument about runs and does not cover them | the out-of-run content is the deliverable — publish it or fold it into the repo |
| .112 | `_scratch_i199` | 565 | 728 | run (unknown — fill in via L1_DATASHEET.json[ic_name])@sky130A v0.119.62 2026-07-27T19:55:02 verdict=FAIL gates 152/5 of -; 2 run roots; 339 file contents (419 MB) exist in no other folder and in no repo; 6 GDS | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .112 | `_takeover_20260818` | 430 | 113 | no flow audit record; content is patch x89, status x4, head x4, diff x4; 69 file contents (427 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .112 | `_n24_sn2025_scratch` | 146 | 7912 | run Universal Serial Bus (USB 2.0)@ihp-sg13g2 v0.119.62 2026-08-02T23:30:58 verdict=FAIL gates 171/12 of -; 149 file contents (40 MB) exist in no other folder and in no repo | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .112 | `_gk198_canonical` | 132 | 963 | run ibex@ihp-sg13g2 v0.119.62 2026-07-27T16:42:14 verdict=FAIL gates 162/4 of -; 3 run roots; 112 file contents (5 MB) exist in no other folder and in no repo | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .112 | `_probe_plugin_capres` | 78 | 4329 | no flow audit record; content is py x3692, pyc x210, yaml x175, md x161; 1 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .112 | `_owner112` | 67 | 3806 | no flow audit record; content is py x3567, pyc x136, json x34, md x32; 27 file contents (1 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .112 | `_agentjob_i1037sw` | 65 | 3894 | no flow audit record; content is py x3722, md x79, json x43, sh x18; 22 file contents (2 MB) exist in no other folder and in no repo; 1 GDS | keep in place — sole copy of its content |
| .112 | `_verify_streamout_gate` | 50 | 31 | no flow audit record; content is py x14, gds x5, txt x3, xml x2; 22 file contents (48 MB) exist in no other folder and in no repo; 5 GDS | keep in place — sole copy of its content |
| .112 | `_pyuvm_venv` | 35 | 792 | no flow audit record; content is pyc x323, py x323, txt x14, typed x9; 6 file contents (28 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .112 | `_r5` | 35 | 213 | no flow audit record; content is json x92, py x77, pyc x17, sh x12; 100 file contents (14 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .112 | `_v632` | 4 | 20 | no flow audit record; content is py x8, txt x5, json x4, log x2; 18 file contents (4 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .112 | `_unattr_work` | 4 | 41 | no flow audit record; content is txt x14, log x13, xml x12, py x1; 38 file contents (4 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .112 | `_slice33` | 2 | 114 | no flow audit record; content is txt x93, sh x8, log x7, py x3; 97 file contents (2 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .112 | `_c12_edge_llm_accel_sky130A` | 2 | 255 | run edge_llm_accel@sky130A v1.10.11 2026-08-09T04:56:21 verdict=FAIL gates 0/0 of 246; 63 file contents (1 MB) exist in no other folder and in no repo | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .112 | `_a13_diff2` | 2 | 50 | no flow audit record; content is json x30, sp x6, md x6, lib x6; 7 file contents (2 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .112 | `_agentjob_i1011` | 1 | 14 | no flow audit record; content is json x8, py x3, txt x1, md x1; 12 file contents (1 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .112 | `_a13_rank_harness` | 1 | 309 | no flow audit record; content is json x105, sp x98, log x72, md x15; 118 file contents (1 MB) exist in no other folder and in no repo; 2 GDS | keep in place — sole copy of its content |
| .112 | `_c12_u_hawaii_adc_sky130A` | 1 | 206 | run u_hawaii_adc@sky130A v1.10.11 2026-08-09T09:00:24 verdict=FAIL gates 0/0 of 246; 18 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .112 | `_c12_u_hawaii_adc_ihp-sg13g2_v11027fix` | 1 | 187 | run u_hawaii_adc@ihp-sg13g2 v1.10.27 2026-08-09T16:19:13 verdict=FAIL gates 0/0 of 246; 3 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .112 | `_c12_u_hawaii_adc_ihp-sg13g2_v11027` | 1 | 185 | run u_hawaii_adc@ihp-sg13g2 v1.10.27 2026-08-09T16:19:13 verdict=FAIL gates 0/0 of 246; 1 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .112 | `_gk198_fresh` | 1 | 95 | run -@- v0.119.62 2026-07-27T15:14:06 verdict=FAIL gates 157/2 of -; 7 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .112 | `_c12_u_hawaii_adc_ihp-sg13g2_v11027fixfull` | 1 | 187 | run u_hawaii_adc@ihp-sg13g2 vUNRESOLVED 2026-08-09T16:29:10 verdict=FAIL gates 0/0 of 246; 27 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .112 | `_agentjob_i1001` | 0 | 224 | no flow audit record; content is json x216, log x4, txt x3, py x1; 115 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .112 | `_wt904_scratch` | 0 | 15 | no flow audit record; content is txt x9, py x2, json x2, out x1; 14 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .112 | `_wt903_scratch` | 0 | 10 | no flow audit record; content is txt x3, sh x2, log x2, json x2; 8 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .112 | `_a13_adv` | 0 | 167 | no flow audit record; content is json x101, sp x22, md x22, lib x22; 30 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .112 | `_a13_four` | 0 | 110 | run (unknown — fill in via L1_DATASHEET.json[ic_name])@- v- - verdict=- gates -/- of -; 4 run roots; 11 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .112 | `_a13_trees` | 0 | 87 | run (unknown — fill in via L1_DATASHEET.json[ic_name])@- v- - verdict=- gates -/- of -; 5 run roots; 6 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .112 | `_agent_scratch_sn27` | 0 | 26 | no flow audit record; content is txt x11, py x11, tlef x1, pyc x1; 24 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .112 | `_probe_round3post2` | 0 | 82 | no flow audit record; content is json x40, sp x8, md x8, lib x8; 4 file contents (0 MB) exist in no other folder and in no repo; 6 GDS | keep in place — sole copy of its content |
| .112 | `_probe_round3post` | 0 | 82 | no flow audit record; content is json x40, sp x8, md x8, lib x8; 4 file contents (0 MB) exist in no other folder and in no repo; 6 GDS | keep in place — sole copy of its content |
| .112 | `_probe_final` | 0 | 82 | no flow audit record; content is json x40, sp x8, md x8, lib x8; 4 file contents (0 MB) exist in no other folder and in no repo; 6 GDS | keep in place — sole copy of its content |
| .112 | `_a13_gap10` | 0 | 38 | no flow audit record; content is json x32, md x4, sp x2; 38 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .112 | `_probe_round3pre` | 0 | 82 | no flow audit record; content is json x40, sp x8, md x8, lib x8; 1 file contents (0 MB) exist in no other folder and in no repo; 6 GDS | keep in place — sole copy of its content |
| .112 | `_probe_premerge` | 0 | 82 | no flow audit record; content is json x40, sp x8, md x8, lib x8; 1 file contents (0 MB) exist in no other folder and in no repo; 6 GDS | keep in place — sole copy of its content |
| .112 | `_probe_after2` | 0 | 82 | no flow audit record; content is json x40, sp x8, md x8, lib x8; 1 file contents (0 MB) exist in no other folder and in no repo; 6 GDS | keep in place — sole copy of its content |
| .112 | `_probe_after` | 0 | 82 | no flow audit record; content is json x40, sp x8, md x8, lib x8; 1 file contents (0 MB) exist in no other folder and in no repo; 6 GDS | keep in place — sole copy of its content |
| .112 | `_ord_round3` | 0 | 64 | no flow audit record; content is json x32, sp x8, md x8, lib x8; 4 file contents (0 MB) exist in no other folder and in no repo; 4 GDS | keep in place — sole copy of its content |
| .112 | `_a13_libprobe` | 0 | 58 | no flow audit record; content is json x34, sp x8, md x8, lib x8; 2 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .112 | `_a13_t2report` | 0 | 28 | run (unknown — fill in via L1_DATASHEET.json[ic_name])@- v- - verdict=- gates -/- of -; 2 run roots; 2 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .112 | `_vpp_pad_work` | 0 | 7 | no flow audit record; content is md x7; 7 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .112 | `_extract` | 0 | 1 | no flow audit record; content is md x1; 1 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .112 | `_refute_synth` | 0 | 10 | no flow audit record; content is json x6, sp x2, md x2; 10 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .112 | `_refute_digest` | 0 | 6 | run -@- v- - verdict=PASS_WITH_WAIVERS gates -/- of -; 2 run roots; 4 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .114 | `_c_cv_edge_llm_matmul_accel_run` | 2623 | 11739 | run User Request@- v0.119.62 2026-08-03T14:43:00 verdict=FAIL gates 144/6 of -; 121 file contents (1112 MB) exist in no other folder and in no repo; 4 GDS | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .114 | `_c12_opentitan_aes_sky130A` | 1895 | 1519 | run opentitan_aes@sky130A v1.10.18 2026-08-10T14:42:03 verdict=FAIL gates 162/0 of 246; 256 file contents (1507 MB) exist in no other folder and in no repo | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .114 | `_n2_ibex` | 1290 | 720 | run ibex@sky130A v0.119.62 2026-07-30T19:52:41 verdict=FAIL gates 155/2 of -; 275 file contents (1090 MB) exist in no other folder and in no repo; 3 GDS | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .114 | `_c15_ibex_sky130A` | 892 | 492 | run Bit-Manipulation Extension@sky130A v1.10.18 2026-08-09T17:19:17 verdict=FAIL gates 160/1 of 246; 181 file contents (757 MB) exist in no other folder and in no repo | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .114 | `_c12_ibex_sky130A` | 891 | 584 | run ibex@sky130A v1.10.11 2026-08-09T09:28:45 verdict=FAIL gates 160/1 of 246; 174 file contents (754 MB) exist in no other folder and in no repo | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .114 | `_c_o_ibex_sky130A_run` | 886 | 542 | run ibex@sky130A v1.9.86 2026-08-05T19:16:31 verdict=FAIL gates 160/1 of 246; 2 run roots; 129 file contents (750 MB) exist in no other folder and in no repo | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .114 | `_c_nda3_ibex_run` | 822 | 975 | run ibex@- v1.10.26 2026-08-10T03:28:29 verdict=FAIL gates 160/1 of 246; 382 file contents (387 MB) exist in no other folder and in no repo; 4 GDS | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .114 | `_agentjob_sha114` | 622 | 555 | run sha256@sky130A v1.10.29 2026-08-10T08:11:05 verdict=FAIL gates 159/0 of 246; 291 file contents (576 MB) exist in no other folder and in no repo | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .114 | `_c_ndapdk_otaes_run` | 486 | 1499 | run -@- v1.10.18 2026-08-10T18:20:24 verdict=FAIL gates 162/0 of 246; 176 file contents (280 MB) exist in no other folder and in no repo; 1 GDS | publishable candidate — `benchmark-data/ic/-/v1.10.18_-/` |
| .114 | `_c_nda2_edge_llm_matmul_accel_run` | 378 | 11781 | run edge_llm_matmul_accel@ihp-sg13g2 v0.119.62 2026-08-04T14:12:55 verdict=FAIL gates 151/2 of -; 148 file contents (67 MB) exist in no other folder and in no repo; 2 GDS | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .114 | `_c_rt_edge_llm_matmul_accel_run` | 339 | 11603 | run -@- v0.119.62 2026-08-04T09:29:58 verdict=FAIL gates 0/0 of -; 29 file contents (21 MB) exist in no other folder and in no repo; 1 GDS | publishable candidate — `benchmark-data/ic/-/v0.119.62_-/` |
| .114 | `_c_nda_opentitan_aes_run` | 262 | 897 | run opentitan_aes@sky130A v0.119.62 2026-08-05T07:46:43 verdict=FAIL gates 163/0 of 246; 152 file contents (189 MB) exist in no other folder and in no repo | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .114 | `_probe` | 247 | 13576 | HELD BY THE AT-RISK-LAYOUT GUARD: 21 streamed layout(s), 17.3 MB, exist in no git ref, in no surviving folder and were not preserved into _kept_layouts; e.g. _probe/D164fixed/phase3/stage3/pnr/spm.gds | publish or preserve the layout before this folder can be reaped |
| .114 | `_jnorec_tmp` | 222 | 25084 | run -@- v1.10.96 2026-08-19T19:06:34 verdict=INSUFFICIENT_DATA gates 0/0 of 246; 15 run roots; 145 file contents (0 MB) exist in no other folder and in no repo; 111 GDS | publishable candidate — `benchmark-data/ic/-/v1.10.96_-/` |
| .114 | `_c_aes8_run` | 190 | 663 | HELD BY THE OUT-OF-ROOT GUARD: 9 artefact content(s), 0.13 MB, live outside every run root of this folder, in no surviving folder and in no git ref; supersession is an argument about runs and does not cover them | the out-of-run content is the deliverable — publish it or fold it into the repo |
| .114 | `_c_subsvg_scratch` | 164 | 6986 | no flow audit record; content is py x3360, pyc x2942, yaml x174, md x170; 41 file contents (39 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .114 | `_c_aes10_run` | 148 | 7144 | no flow audit record; content is py x3371, pyc x2967, sv x277, yaml x174; 5 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .114 | `_bench_rtllm_run` | 134 | 14841 | run freq_div@- v0.119.62 2026-08-02T01:28:40 verdict=FAIL gates 149/1 of -; 50 run roots; 3262 file contents (16 MB) exist in no other folder and in no repo | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .114 | `_r4_gf180mcuD` | 119 | 5178 | HELD BY THE AT-RISK-LAYOUT GUARD: 4 streamed layout(s), 4.2 MB, exist in no git ref, in no surviving folder and were not preserved into _kept_layouts; e.g. _r4_gf180mcuD/run/phase3/stage3/pnr/spm.gds | publish or preserve the layout before this folder can be reaped |
| .114 | `_agent_scratch_adc3` | 110 | 6971 | no flow audit record; content is py x3462, pyc x3098, yaml x154, md x131; 11 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .114 | `_plugin54` | 103 | 6546 | no flow audit record; content is py x3240, pyc x2827, yaml x174, md x161; 2 file contents (1 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .114 | `_pcfinal_8HD-8` | 99 | 121 | no flow audit record; content is json x66, log x17, txt x14, lyrdb x5; 78 file contents (69 MB) exist in no other folder and in no repo; 3 GDS | keep in place — sole copy of its content |
| .114 | `_cache784` | 79 | 7547 | no flow audit record; content is py x3525, js x1140, ts x1115, map x463; 1 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .114 | `_jw6_scratch` | 75 | 4754 | no flow audit record; content is py x4096, md x265, yaml x212, json x76; 1 file contents (0 MB) exist in no other folder and in no repo; 1 GDS | keep in place — sole copy of its content |
| .114 | `_jgate_tmp` | 74 | 6889 | no flow audit record; content is py x4070, sample x658, json x156, log x120; 32 file contents (0 MB) exist in no other folder and in no repo; 1 GDS | keep in place — sole copy of its content |
| .114 | `_agent_scratch_p_spm_sky` | 66 | 3739 | no flow audit record; content is py x3504, pyc x167, json x30, md x20; 4 file contents (2 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .114 | `_bench_rtllm2_run` | 65 | 10533 | run freq_div@- v0.119.62 2026-08-02T13:10:37 verdict=FAIL gates 149/1 of -; 48 run roots; 3187 file contents (16 MB) exist in no other folder and in no repo | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .114 | `_n_ibex` | 65 | 319 | run ibex@ihp-sg13g2 v0.119.62 2026-07-30T14:29:04 verdict=FAIL gates 156/1 of -; 80 file contents (4 MB) exist in no other folder and in no repo | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .114 | `_plugin_cur` | 58 | 3773 | no flow audit record; content is py x3240, yaml x174, md x160, pyc x113; 3 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .114 | `_l20check_scratch` | 58 | 3910 | no flow audit record; content is py x3369, yaml x174, md x169, json x149; 79 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .114 | `_c_rt_spm_run` | 56 | 162 | run -@- v0.119.62 2026-08-04T09:30:01 verdict=FAIL gates 0/0 of -; 4 file contents (0 MB) exist in no other folder and in no repo; 1 GDS | publishable candidate — `benchmark-data/ic/-/v0.119.62_-/` |
| .114 | `_r6_gf180mcuD` | 55 | 1297 | HELD BY THE AT-RISK-LAYOUT GUARD: 1 streamed layout(s), 0.0 MB, exist in no git ref, in no surviving folder and were not preserved into _kept_layouts; e.g. _r6_gf180mcuD/scratch/postest.gds | publish or preserve the layout before this folder can be reaped |
| .114 | `_c15_opentitan_aes_sky130A` | 51 | 1283 | run GHASH@sky130A v1.10.18 2026-08-09T13:07:17 verdict=FAIL gates 160/0 of 246; 83 file contents (3 MB) exist in no other folder and in no repo | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .114 | `_c_aes4_run` | 45 | 805 | run GHASH@- v0.119.62 2026-07-31T11:07:33 verdict=FAIL gates 158/2 of -; 73 file contents (1 MB) exist in no other folder and in no repo | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .114 | `_agentjob_u5fix` | 42 | 380 | no flow audit record; content is sv x275, json x38, txt x14, tcl x11; 10 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .114 | `_r7_gf180` | 27 | 612 | HELD BY THE OUT-OF-ROOT GUARD: 1 artefact content(s), 0.00 MB, live outside every run root of this folder, in no surviving folder and in no git ref; supersession is an argument about runs and does not cover them | the out-of-run content is the deliverable — publish it or fold it into the repo |
| .114 | `_c_aes10_scratch` | 13 | 26 | no flow audit record; content is v x8, json x6, sh x4, ys x3; 18 file contents (9 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .114 | `_jf2_tmpB` | 13 | 3432 | run spm@sky130A v1.10.18 2026-08-09T11:18:38 verdict=PASS_WITH_WAIVERS gates 154/0 of 246; 2 run roots; 20 file contents (0 MB) exist in no other folder and in no repo; 58 GDS | publishable candidate — `benchmark-data/ic/spm/v1.10.18_sky130A/` |
| .114 | `_bdsplit_measure` | 12 | 56 | no flow audit record; content is json x10, xml x8, log x8, sh x6; 43 file contents (12 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .114 | `_advf4_out` | 11 | 20 | no flow audit record; content is err x5, xml x4, log x4, sh x2; 20 file contents (11 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .114 | `_jf2_tmp` | 6 | 6190 | run -@- v- - verdict=PASS gates -/- of -; 2 run roots; 151 file contents (0 MB) exist in no other folder and in no repo; 227 GDS | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .114 | `_a6_hawaii` | 3 | 271 | no flow audit record; content is mag x59, json x34, sp x33, ext x32; 174 file contents (1 MB) exist in no other folder and in no repo; 6 GDS | keep in place — sole copy of its content |
| .114 | `_c_o_aes_domrestore_scratch` | 3 | 272 | no flow audit record; content is sv x254, svh x8, txt x4, log x3; 7 file contents (1 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .114 | `_jf2_tmpV` | 2 | 2960 | run -@- v- - verdict=PASS gates -/- of -; 19 file contents (0 MB) exist in no other folder and in no repo; 57 GDS | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .114 | `_c_nda_u_hawaii_adc_run` | 2 | 162 | run u_hawaii_adc@- v0.119.62 2026-08-05T09:19:07 verdict=FAIL gates 0/0 of 246; 68 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .114 | `_capC_scratch` | 1 | 177 | no flow audit record; content is v x66, jsonl x53, cpp x14, h x8; 92 file contents (1 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .114 | `_agentjob_pdk` | 1 | 24 | no flow audit record; content is json x14, lef x3, csv x3, tlef x2; 8 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .114 | `_agent_scratch_aes` | 1 | 111 | no flow audit record; content is sv x95, svh x4, txt x3, before x3; 11 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .114 | `_bench_rtllm3_scratch` | 1 | 123 | no flow audit record; content is v x67, txt x20, vvp x10, log x9; 33 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .114 | `_atkB` | 0 | 46 | no flow audit record; content is py x18, pyc x13, xml x4, txt x2; 5 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .114 | `_agent_scratch_edge_llm_matmul_accel2` | 0 | 19 | no flow audit record; content is log x11, txt x5, sv x1, md x1; 19 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .114 | `_agentjob_p1d` | 0 | 18 | no flow audit record; content is txt x10, json x4, md x2, py x1; 18 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .114 | `_c_o_u_hawaii_adc_sky130A_scratch` | 0 | 20 | no flow audit record; content is txt x8, sp x5, log x5, md x1; 18 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .114 | `_mainred_scratch` | 0 | 21 | no flow audit record; content is py x7, log x3, nc x2, fails x2; 15 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .114 | `_agentjob_gates` | 0 | 14 | LIVE — held open right now: cwd pid=1940038 /bin/bash -c source /home/reyerchu/.claude/shell-snapshots/snapshot-bash-1786460 | leave alone until the run finishes |
| .114 | `_jfind63_tmp` | 0 | 24 | no flow audit record; content is rpt x6, py x6, flag x4, yaml x3; 1 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .114 | `_agent_scratch_adcsky` | 0 | 13 | no flow audit record; content is py x5, pyc x4, md x2, json x2; 3 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .114 | `_bench_rtllm6_run` | 0 | 134 | no flow audit record; content is v x100, txt x18, batch x8, log x3; 53 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .114 | `_bench_rtllm8_run` | 0 | 128 | no flow audit record; content is v x100, txt x19, log x3, tsv x2; 50 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .114 | `_bench_rtllm7_run` | 0 | 123 | no flow audit record; content is v x100, txt x14, log x3, csv x3; 44 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .114 | `_agentjob_r3c` | 0 | 61 | no flow audit record; content is out x23, md x11, err x9, json x5; 47 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .114 | `_bench_rtllm4_run` | 0 | 84 | no flow audit record; content is v x59, txt x12, log x2, md x1; 16 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .114 | `_agent_scratch_aes11` | 0 | 2 | no flow audit record; content is json x2; 1 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .114 | `_agent_scratch_aes10` | 0 | 4 | no flow audit record; content is json x2, sh x1, log x1; 4 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .114 | `_bench_rtllm5_run` | 0 | 73 | no flow audit record; content is v x50, txt x13, json x4, log x3; 9 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .114 | `_bench_rtllm3_run` | 0 | 58 | no flow audit record; content is v x50, json x3, log x2, txt x1; 7 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .114 | `_agentjob_i904` | 0 | 12 | no flow audit record; content is json x6, txt x2, md x2, log x2; 12 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .114 | `_agent_scratch_adc2` | 0 | 7 | no flow audit record; content is txt x3, log x2, json x2; 6 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .114 | `_c_aes6_run` | 0 | 12 | no flow audit record; content is md x4, json x3, log x2, txt x1; 12 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .114 | `_agent_scratch_adc` | 0 | 13 | no flow audit record; content is json x6, txt x4, err x2, stdout x1; 9 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .114 | `_wt913` | 0 | 15 | no flow audit record; content is py x5, rpt x4, json x3, txt x1; 13 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .114 | `_agentjob_d9d` | 0 | 15 | no flow audit record; content is txt x13, md x1, log x1; 15 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .114 | `_c_o_u_hawaii_adc_sky130A_c2_scratch` | 0 | 43 | no flow audit record; content is mag x18, tcl x10, ext x8, spice x5; 43 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .114 | `_r100a_run` | 0 | 15 | no flow audit record; content is v x12, md x2, log x1; 3 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .114 | `_rtllm_gen_parallel2serial_scratch` | 0 | 26 | no flow audit record; content is v x9, list x8, json x8, patch x1; 7 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .114 | `_agentjob_i927` | 0 | 8 | no flow audit record; content is sh x3, txt x2, md x1, log x1; 8 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .114 | `_jw6_demo` | 0 | 27 | run -@- v- - verdict=PASS_WITH_WAIVERS gates -/- of -; 3 file contents (0 MB) exist in no other folder and in no repo; 2 GDS | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .114 | `_capC_run` | 0 | 1 | no flow audit record; content is md x1; 1 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .114 | `_rtllm_gen_LIFObuffer_run` | 0 | 2 | no flow audit record; content is md x1, log x1; 2 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .114 | `_rtllm_gen_parallel2serial_run` | 0 | 2 | no flow audit record; content is md x1, log x1; 2 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .114 | `_c_cv_edge_llm_matmul_accel_scratch` | 0 | 1 | no flow audit record; content is md x1; 1 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .114 | `_rtllm_gen_right_shifter_run` | 0 | 2 | no flow audit record; content is md x1, log x1; 2 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .114 | `_rtllm_gen_right_shifter_scratch` | 0 | 8 | no flow audit record; content is v x7, py x1; 4 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .114 | `_agentjob_test114` | 0 | 2 | no flow audit record; content is md x1, log x1; 2 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .114 | `_c_edge1_scratch` | 0 | 1 | no flow audit record; content is v x1; 1 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .120 | `_c_cv_opentitan_aes_scratch` | 2014 | 1179 | run opentitan_aes@- v0.119.62 2026-08-03T17:28:33 verdict=FAIL gates 156/4 of -; 167 file contents (910 MB) exist in no other folder and in no repo; 3 GDS | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .120 | `_agentjob_blind` | 1887 | 35953 | run caravel_user_project@sky130A v0.119.62 2026-08-02T23:41:04 verdict=FAIL gates 156/2 of -; 139 run roots; 112 file contents (0 MB) exist in no other folder and in no repo; 67 GDS | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .120 | `_c_o_sha256_sky130A_scratch` | 1866 | 45999 | run sha256@sky130A v0.119.62 2026-08-03T11:50:49 verdict=FAIL gates 159/1 of -; 45 run roots; 98 file contents (8 MB) exist in no other folder and in no repo; 35 GDS | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .120 | `_c_sha_run` | 1830 | 2011 | HELD BY THE AT-RISK-LAYOUT GUARD: 6 streamed layout(s), 168.1 MB, exist in no git ref, in no surviving folder and were not preserved into _kept_layouts; e.g. _c_sha_run/pp3/phase3/stage3/pnr/sha256.gds | publish or preserve the layout before this folder can be reaped |
| .120 | `_c_sha2_scratch` | 1794 | 1613 | HELD BY THE AT-RISK-LAYOUT GUARD: 3 streamed layout(s), 101.2 MB, exist in no git ref, in no surviving folder and were not preserved into _kept_layouts; e.g. _c_sha2_scratch/d0_agefix/phase3/stage3/pnr/sha256.gds | publish or preserve the layout before this folder can be reaped |
| .120 | `_scan` | 1273 | 49386 | run spm@sky130A v0.119.62 2026-07-28T20:54:27 verdict=FAIL gates 149/1 of -; 46 run roots; 817 file contents (40 MB) exist in no other folder and in no repo; 30 GDS | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .120 | `_c_sha5_run` | 1255 | 1024 | HELD BY THE OUT-OF-ROOT GUARD: 10 artefact content(s), 0.07 MB, live outside every run root of this folder, in no surviving folder and in no git ref; supersession is an argument about runs and does not cover them | the out-of-run content is the deliverable — publish it or fold it into the repo |
| .120 | `_c_o_sha256_sky130A_run` | 1093 | 1815 | run sha256@sky130A v1.9.84 2026-08-05T14:51:52 verdict=FAIL gates 159/0 of 246; 6 run roots; 268 file contents (55 MB) exist in no other folder and in no repo; 5 GDS | publishable candidate — `benchmark-data/ic/sha256/v1.9.84_sky130A/` |
| .120 | `_c_cv_subservient_scratch` | 1061 | 48011 | run caravel_user_project@sky130A v0.119.62 2026-08-02T23:41:04 verdict=FAIL gates 156/2 of -; 44 run roots; 28 file contents (5 MB) exist in no other folder and in no repo; 25 GDS | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .120 | `_c_sha3_run` | 1037 | 705 | HELD BY THE OUT-OF-ROOT GUARD: 4 artefact content(s), 0.02 MB, live outside every run root of this folder, in no surviving folder and in no git ref; supersession is an argument about runs and does not cover them | the out-of-run content is the deliverable — publish it or fold it into the repo |
| .120 | `_ibex_ndapdk_run` | 964 | 795 | run ibex@- v1.10.29 2026-08-10T06:07:57 verdict=FAIL gates 160/1 of 246; 329 file contents (476 MB) exist in no other folder and in no repo; 4 GDS | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .120 | `_c_rt_opentitan_aes_run` | 645 | 2144 | run -@- v0.119.62 2026-08-04T09:29:51 verdict=FAIL gates 0/0 of -; 94 file contents (408 MB) exist in no other folder and in no repo | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .120 | `_bm4b_sha256_sky130A_run` | 613 | 537 | LIVE — held open right now: fd pid=2607581 /usr/bin/python3 /home/reyerchu/_bm4b_plugin/programs/flow_dashboard.py /home/re | leave alone until the run finishes |
| .120 | `_c_rt_subservient_run` | 599 | 23216 | run -@- v0.119.62 2026-08-04T09:29:51 verdict=FAIL gates 0/0 of -; 22 file contents (0 MB) exist in no other folder and in no repo; 2 GDS | publishable candidate — `benchmark-data/ic/-/v0.119.62_-/` |
| .120 | `_c_o_subservient_sky130A_run` | 593 | 1298 | run subservient@sky130A v1.9.84 2026-08-05T15:40:49 verdict=FAIL gates 154/1 of 246; 3 run roots; 506 file contents (506 MB) exist in no other folder and in no repo; 3 GDS | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .120 | `_c_o_sha256_sky130A_c3_scratch` | 575 | 10801 | run -@- v- - verdict=- gates -/- of -; 32 file contents (350 MB) exist in no other folder and in no repo; 3 GDS | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .120 | `_c_cv_subservient_run` | 565 | 12461 | run subservient@ihp-sg13g2 v0.119.62 2026-08-03T14:40:58 verdict=FAIL gates 151/2 of -; 2 run roots; 311 file contents (145 MB) exist in no other folder and in no repo; 4 GDS | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .120 | `_spmpass` | 537 | 1613 | run spm@gf180mcuD v1.10.96 2026-08-20T04:11:34 verdict=FAIL gates 154/0 of 246; 289 file contents (197 MB) exist in no other folder and in no repo; 233 GDS | publishable candidate — `benchmark-data/ic/spm/v1.10.96_gf180mcuD/` |
| .120 | `_spmslot_run` | 462 | 3648 | HELD BY THE AT-RISK-LAYOUT GUARD: 8 streamed layout(s), 141.8 MB, exist in no git ref, in no surviving folder and were not preserved into _kept_layouts; e.g. _spmslot_run/debug_gds_filled/spm.gds | publish or preserve the layout before this folder can be reaped |
| .120 | `_c_plugin97_agefix` | 448 | 20647 | run spm@sky130A v0.119.62 2026-07-24T17:23:59 verdict=PASS_WITH_WAIVERS gates 0/0 of -; 24 run roots; 1 file contents (2 MB) exist in no other folder and in no repo; 9 GDS | publishable candidate — `benchmark-data/ic/spm/v0.119.62_sky130A/` |
| .120 | `_gsmall_fill` | 438 | 502 | no flow audit record; content is json x265, log x75, txt x52, lyrdb x20; 220 file contents (316 MB) exist in no other folder and in no repo; 16 GDS | keep in place — sole copy of its content |
| .120 | `_c_nda_caravel_user_project_run` | 343 | 12111 | run caravel_user_project@sky130A v0.119.62 2026-08-05T09:04:22 verdict=FAIL gates 160/0 of 246; 304 file contents (34 MB) exist in no other folder and in no repo; 5 GDS | publishable candidate — `benchmark-data/ic/caravel_user_project/v0.119.62_sky130A/` |
| .120 | `_c_ndam_spm_scratch` | 305 | 12323 | HELD BY THE OUT-OF-ROOT GUARD: 68 artefact content(s), 0.50 MB, live outside every run root of this folder, in no surviving folder and in no git ref; supersession is an argument about runs and does not cover them | the out-of-run content is the deliverable — publish it or fold it into the repo |
| .120 | `_c_rt_caravel_user_project_run` | 300 | 11624 | run -@- v0.119.62 2026-08-04T09:29:50 verdict=FAIL gates 0/0 of -; 9 file contents (0 MB) exist in no other folder and in no repo; 1 GDS | publishable candidate — `benchmark-data/ic/-/v0.119.62_-/` |
| .120 | `_pcfinal` | 289 | 373 | no flow audit record; content is json x203, log x51, txt x47, lyrdb x15; 92 file contents (122 MB) exist in no other folder and in no repo; 9 GDS | keep in place — sole copy of its content |
| .120 | `_c12_drvrepro` | 265 | 9387 | no flow audit record; content is py x4980, pyc x3464, yaml x385, md x327; 40 file contents (11 MB) exist in no other folder and in no repo; 7 GDS | keep in place — sole copy of its content |
| .120 | `_c_o_sha256_sky130A_c2_scratch` | 256 | 14554 | run -@- v- - verdict=- gates -/- of -; 35 file contents (1 MB) exist in no other folder and in no repo | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .120 | `_gband` | 249 | 1342 | run spm@gf180mcuD v1.10.96 2026-08-19T22:30:52 verdict=FAIL gates 154/0 of 246; 228 file contents (44 MB) exist in no other folder and in no repo; 224 GDS | publishable candidate — `benchmark-data/ic/spm/v1.10.96_gf180mcuD/` |
| .120 | `_c_aes11_run` | 184 | 377 | no flow audit record; content is sv x275, json x19, md x13, tcl x11; 41 file contents (134 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .120 | `_c_nda3_opentitan_aes_run` | 150 | 596 | run opentitan_aes@ihp-sg13g2 v0.119.62 2026-08-04T14:43:37 verdict=FAIL gates 160/1 of -; 78 file contents (73 MB) exist in no other folder and in no repo | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .120 | `_gk_pc2` | 144 | 118 | no flow audit record; content is json x65, log x17, txt x13, lyrdb x5; 46 file contents (39 MB) exist in no other folder and in no repo; 3 GDS | keep in place — sole copy of its content |
| .120 | `_gk_precheck` | 144 | 118 | no flow audit record; content is json x65, log x17, txt x13, lyrdb x5; 47 file contents (77 MB) exist in no other folder and in no repo; 3 GDS | keep in place — sole copy of its content |
| .120 | `_pcver` | 138 | 155 | no flow audit record; content is json x80, log x25, txt x18, gds x6; 55 file contents (68 MB) exist in no other folder and in no repo; 6 GDS | keep in place — sole copy of its content |
| .120 | `_c_cv_opentitan_aes_run` | 122 | 602 | run opentitan_aes@ihp-sg13g2 v0.119.62 2026-08-03T07:41:42 verdict=FAIL gates 160/1 of -; 55 file contents (42 MB) exist in no other folder and in no repo; 1 GDS | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .120 | `_n_edge_llm_accel` | 121 | 7632 | HELD BY THE OUT-OF-ROOT GUARD: 5 artefact content(s), 0.03 MB, live outside every run root of this folder, in no surviving folder and in no git ref; supersession is an argument about runs and does not cover them | the out-of-run content is the deliverable — publish it or fold it into the repo |
| .120 | `_r10_sha256_ndapdk_run` | 116 | 465 | LIVE — held open right now: cwd pid=2947005 /usr/bin/python3 /home/reyerchu/_r10_plugin_11026/programs/flow_dashboard.py /ho | leave alone until the run finishes |
| .120 | `_mut902b` | 116 | 6960 | no flow audit record; content is py x3558, pyc x3281, json x78, md x20; 0 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .120 | `_pcb` | 77 | 121 | no flow audit record; content is json x66, log x17, txt x14, lyrdb x5; 58 file contents (51 MB) exist in no other folder and in no repo; 3 GDS | keep in place — sole copy of its content |
| .120 | `_r10_plugin_11026` | 77 | 4380 | no flow audit record; content is py x3705, pyc x247, yaml x175, md x161; 1 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .120 | `_c_rt_subservient_scratch` | 70 | 4163 | no flow audit record; content is py x3456, yaml x205, md x175, pyc x150; 13 file contents (2 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .120 | `_wt902_fix` | 68 | 4242 | no flow audit record; content is py x3693, yaml x175, md x162, pyc x117; 1 file contents (1 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .120 | `_v902_fix` | 68 | 4237 | no flow audit record; content is py x3693, yaml x175, md x161, pyc x117; 1 file contents (1 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .120 | `_c_plugin84_lecfix` | 67 | 3928 | no flow audit record; content is py x3264, pyc x246, yaml x174, md x160; 1 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .120 | `_c_plugin84_cvg` | 67 | 3928 | no flow audit record; content is py x3264, pyc x246, yaml x174, md x160; 1 file contents (2 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .120 | `_agent_scratch_r2_sha256` | 60 | 39 | no flow audit record; content is tcl x7, gds x7, log x6, py x5; 36 file contents (60 MB) exist in no other folder and in no repo; 7 GDS | keep in place — sole copy of its content |
| .120 | `_c_sha_scratch` | 57 | 146 | no flow audit record; content is log x45, v x43, rpt x17, tcl x16; 85 file contents (54 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .120 | `_agentjob_gdrc` | 43 | 18 | no flow audit record; content is py x10, lyrdb x2, log x2, gds x2; 16 file contents (1 MB) exist in no other folder and in no repo; 2 GDS | keep in place — sole copy of its content |
| .120 | `_c_nda2_opentitan_aes_run` | 42 | 397 | run -@- v0.119.62 2026-08-04T10:50:00 verdict=FAIL gates 0/0 of -; 13 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .120 | `_e2e902` | 36 | 1152 | no flow audit record; content is py x1128, pyc x18, v x2, vvp x1; 6 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .120 | `_c14_spm_sky130A` | 27 | 663 | run spm@sky130A v1.10.18 2026-08-09T11:00:46 verdict=PASS_WITH_WAIVERS gates 154/0 of 246; 275 file contents (12 MB) exist in no other folder and in no repo; 3 GDS | publishable candidate — `benchmark-data/ic/spm/v1.10.18_sky130A/` |
| .120 | `_final_ihp4` | 21 | 187 | run -@sky130A v0.119.62 2026-07-27T00:02:24 verdict=FAIL gates 0/2 of -; 18 file contents (1 MB) exist in no other folder and in no repo | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .120 | `_c12_spm_gf180mcuD` | 20 | 549 | LIVE — held open right now: fd pid=1864153 /usr/bin/python3 /home/reyerchu/.claude/plugins/cache/vibe-ic-marketplace/vibe-i | leave alone until the run finishes |
| .120 | `_agent_scratch_sha` | 16 | 134 | no flow audit record; content is log x27, v x23, pyc x16, tcl x10; 71 file contents (6 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .120 | `_agent_scratch_p_spm_ihp` | 15 | 463 | run -@- v- - verdict=- gates -/- of -; 204 file contents (8 MB) exist in no other folder and in no repo; 3 GDS | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .120 | `_nda_spm_run` | 15 | 606 | LIVE — held open right now: cwd pid=2918439 /usr/bin/python3 /home/reyerchu/_nda_plugin_11026/vibe-ic/programs/flow_dashboar | leave alone until the run finishes |
| .120 | `_agentjob_d9b` | 10 | 16 | no flow audit record; content is json x6, txt x4, md x1, log x1; 14 file contents (10 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .120 | `_agent_scratch_sha256` | 10 | 19 | no flow audit record; content is log x5, v x3, vvp x2, txt x2; 16 file contents (7 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .120 | `_bdsplit_measure` | 7 | 32 | no flow audit record; content is log x7, xml x6, json x4, txt x2; 23 file contents (7 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .120 | `_bm4b_sandbox` | 6 | 52 | no flow audit record; content is json x30, md x12, v x4, txt x3; 10 file contents (5 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .120 | `_agent_scratch_sha2562` | 5 | 10 | no flow audit record; content is vvp x2, v x2, py x2, pyc x1; 9 file contents (5 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .120 | `_agent_scratch_cup` | 4 | 27 | no flow audit record; content is log x7, tcl x6, py x6, txt x5; 23 file contents (4 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .120 | `_c_o_subservient_sky130A_scratch` | 3 | 18 | no flow audit record; content is v x9, tcl x5, ys x4; 14 file contents (3 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .120 | `_harv_priv` | 3 | 165 | LIVE — held open right now: cwd pid=1160948 sleep 60 | leave alone until the run finishes |
| .120 | `_c12_u_hawaii_adc_sky130A` | 2 | 254 | LIVE — held open right now: cwd pid=1864184 /usr/bin/python3 /home/reyerchu/.claude/plugins/cache/vibe-ic-marketplace/vibe-i | leave alone until the run finishes |
| .120 | `_agentjob_905move` | 1 | 37 | no flow audit record; content is txt x25, md x5, py x4, json x2; 34 file contents (1 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .120 | `_wt_ckwiring_evidence` | 1 | 8 | no flow audit record; content is log x4, txt x2, json x2; 7 file contents (1 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .120 | `_agent_scratch_p_caravel` | 1 | 18 | no flow audit record; content is json x6, rpt x5, txt x2, py x2; 10 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .120 | `_tri32` | 1 | 84 | no flow audit record; content is patch x66, tsv x5, sh x3, py x2; 14 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .120 | `_r100b_run` | 0 | 18 | no flow audit record; content is v x6, list x6, md x2, json x2; 4 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .120 | `_r100b_run_fork` | 0 | 15 | no flow audit record; content is v x6, list x6, json x2, md x1; 1 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .120 | `_fh` | 0 | 68 | no flow audit record; content is ys x9, log x9, txt x6, sv x6; 51 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .120 | `_intB_measure` | 0 | 18 | no flow audit record; content is txt x8, rc x6, json x4; 10 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .120 | `_r10_repro` | 0 | 32 | no flow audit record; content is json x16, txt x5, v x4, py x3; 23 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .120 | `_agentjob_p1b` | 0 | 3 | no flow audit record; content is py x1, log x1, json x1; 3 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .120 | `_sva31` | 0 | 47 | no flow audit record; content is sv x7, ys x6, log x6, txt x4; 39 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .120 | `_agentjob_pin` | 0 | 7 | no flow audit record; content is txt x3, json x2, py x1, log x1; 7 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .120 | `_agentjob_r3b` | 0 | 30 | no flow audit record; content is txt x16, json x6, py x4, md x3; 29 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .120 | `_adv_out` | 0 | 8 | no flow audit record; content is sh x3, xml x1, txt x1, py x1; 8 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .120 | `_sva_probe` | 0 | 5 | no flow audit record; content is sv x5; 4 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .121 | `_c_o_edge_llm_matmul_accel_nangate45_run` | 9560 | 778 | run edge_llm_matmul_accel@nangate45 v0.119.62 2026-08-04T00:23:25 verdict=FAIL gates 158/0 of -; 2 run roots; 10 file contents (0 MB) exist in no other folder and in no repo; 3 GDS | publishable candidate — `benchmark-data/ic/edge_llm_matmul_accel/v0.119.62_nangate45/` |
| .121 | `_c_o_edge_llm_accel_nangate45_run` | 9194 | 990 | run edge_llm_accel@nangate45 v0.119.62 2026-08-03T23:28:45 verdict=FAIL gates 151/1 of -; 4 run roots; 316 file contents (7803 MB) exist in no other folder and in no repo | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .121 | `_run_edge_llm_accel_ng45_v11018` | 4589 | 568 | run edge_llm_accel@nangate45 v1.10.18 2026-08-09T19:27:30 verdict=FAIL gates 152/0 of 246; 269 file contents (3829 MB) exist in no other folder and in no repo | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .121 | `_c_caravel_user_project_ndapdk` | 1985 | 589 | run caravel_user_project@ihp-sg13g2 v1.10.26 2026-08-10T00:49:54 verdict=FAIL gates 157/0 of 246; 289 file contents (731 MB) exist in no other folder and in no repo; 3 GDS | publishable candidate — `benchmark-data/ic/caravel_user_project/v1.10.26_ihp-sg13g2/` |
| .121 | `_jppasearch` | 1750 | 37355 | run spm@sky130A v1.11.7 2026-08-20T18:03:00 verdict=FAIL gates 153/1 of 246; 55 run roots; 13445 file contents (925 MB) exist in no other folder and in no repo; 219 GDS | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .121 | `_c5_adc_scratch` | 1311 | 61606 | run spm@sky130A v0.119.62 2026-07-24T17:23:59 verdict=PASS_WITH_WAIVERS gates 0/0 of -; 63 run roots; 2 file contents (0 MB) exist in no other folder and in no repo; 27 GDS | publishable candidate — `benchmark-data/ic/spm/v0.119.62_sky130A/` |
| .121 | `_c_rt_edge_llm_accel_run` | 1201 | 11825 | run edge_llm_accel@- v1.9.84 2026-08-05T15:10:05 verdict=FAIL gates 152/1 of 246; 2 run roots; 123 file contents (522 MB) exist in no other folder and in no repo; 1 GDS | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .121 | `_c_cv_edge_llm_accel_run` | 1073 | 11837 | run edge_llm_accel@ihp-sg13g2 v0.119.62 2026-08-03T06:32:34 verdict=FAIL gates 148/6 of -; 89 file contents (410 MB) exist in no other folder and in no repo; 1 GDS | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .121 | `_bm_sha256_sky130A_121` | 833 | 583 | run sha256@sky130A v1.10.29 2026-08-10T08:38:16 verdict=FAIL gates 159/0 of 246; 298 file contents (763 MB) exist in no other folder and in no repo | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .121 | `_c12_caravel_user_project_sky130A` | 647 | 700 | LIVE — held open right now: cwd pid=4104591 /usr/bin/python3 /home/reyerchu/.claude/plugins/cache/vibe-ic-marketplace/vibe-i | leave alone until the run finishes |
| .121 | `_c_sub_gf180_v11029_run` | 530 | 544 | run subservient@gf180mcuD v1.10.29 2026-08-10T02:26:43 verdict=FAIL gates 152/2 of 246; 245 file contents (506 MB) exist in no other folder and in no repo | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .121 | `_c_nda_edge_llm_accel_run` | 507 | 11705 | run edge_llm_accel@- v0.119.62 2026-08-05T07:23:17 verdict=FAIL gates 151/2 of 246; 76 file contents (207 MB) exist in no other folder and in no repo; 1 GDS | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .121 | `_ctl_edge_llm_accel_ng45_patched` | 429 | 349 | run edge_llm_accel@nangate45 v1.10.18 2026-08-09T22:36:10 verdict=FAIL gates 152/0 of 246; 88 file contents (226 MB) exist in no other folder and in no repo | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .121 | `_c_adc7_scratch` | 405 | 15176 | run u_hawaii_adc@ihp-sg13g2 v0.119.62 2026-07-31T18:53:20 verdict=FAIL gates 158/6 of -; 32 file contents (0 MB) exist in no other folder and in no repo; 7 GDS | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .121 | `_c_adc10_run` | 400 | 4683 | run u_hawaii_adc@ihp-sg13g2 v0.119.62 2026-08-01T20:24:41 verdict=FAIL gates 156/8 of -; 60 file contents (120 MB) exist in no other folder and in no repo; 8 GDS | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .121 | `_c_adc9_run` | 338 | 717 | run u_hawaii_adc@ihp-sg13g2 v0.119.62 2026-08-01T08:51:31 verdict=FAIL gates 158/6 of -; 27 file contents (57 MB) exist in no other folder and in no repo; 8 GDS | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .121 | `_c_adc8_run` | 338 | 713 | run u_hawaii_adc@ihp-sg13g2 v0.119.62 2026-07-31T21:09:34 verdict=FAIL gates 158/6 of -; 20 file contents (57 MB) exist in no other folder and in no repo; 8 GDS | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .121 | `_ndapdk` | 301 | 11534 | no flow audit record; content is tag x3329, png x3328, oa x3328, dm x631; 0 file contents (0 MB) exist in no other folder and in no repo; 1 GDS | keep in place — sole copy of its content |
| .121 | `_c_adc7_run` | 260 | 700 | run u_hawaii_adc@ihp-sg13g2 v0.119.62 2026-07-31T19:08:33 verdict=FAIL gates 158/6 of -; 17 file contents (0 MB) exist in no other folder and in no repo; 7 GDS | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .121 | `_c_o_subservient_gf180mcuD_scratch` | 211 | 11635 | HELD BY THE OUT-OF-ROOT GUARD: 21 artefact content(s), 6.17 MB, live outside every run root of this folder, in no surviving folder and in no git ref; supersession is an argument about runs and does not cover them | the out-of-run content is the deliverable — publish it or fold it into the repo |
| .121 | `_c12_caravel_user_project_sky130A_docker-upgrade-kill-20260809` | 184 | 485 | LIVE — held open right now: cwd pid=4016154 /usr/bin/python3 /home/reyerchu/.claude/plugins/cache/vibe-ic-marketplace/vibe-i | leave alone until the run finishes |
| .121 | `_c_cv_sha256_run` | 160 | 336 | run sha256@ihp-sg13g2 v0.119.62 2026-08-03T06:41:59 verdict=FAIL gates 157/0 of -; 95 file contents (7 MB) exist in no other folder and in no repo; 1 GDS | publishable candidate — `benchmark-data/ic/sha256/v0.119.62_ihp-sg13g2/` |
| .121 | `_c_rt_sha256_run` | 151 | 213 | run -@- v0.119.62 2026-08-04T09:30:05 verdict=FAIL gates 0/0 of -; 36 file contents (3 MB) exist in no other folder and in no repo; 1 GDS | publishable candidate — `benchmark-data/ic/-/v0.119.62_-/` |
| .121 | `_c6_adc_scratch` | 112 | 7448 | no flow audit record; content is py x6575, yaml x348, md x320, json x82; 21 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .121 | `_plugin_v11018_patched` | 76 | 4362 | no flow audit record; content is py x3693, pyc x242, yaml x175, md x161; 3 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .121 | `_c_adc8_scratch` | 74 | 7290 | no flow audit record; content is py x3289, js x1151, ts x1126, map x461; 5 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .121 | `_bench_cvdp302_run` | 69 | 4202 | no flow audit record; content is py x3393, sv x304, yaml x174, md x162; 326 file contents (8 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .121 | `_c_mm1_run` | 68 | 4137 | run edge_llm_matmul_accel@- v0.119.62 2026-08-01T11:33:26 verdict=FAIL gates 0/0 of -; 56 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .121 | `_n_adc` | 67 | 4210 | run u_hawaii_adc@- v0.119.62 2026-07-30T15:41:53 verdict=FAIL gates 0/0 of -; 2 run roots; 125 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .121 | `_bench_cvdp_run` | 59 | 3862 | no flow audit record; content is py x3391, yaml x174, md x161, pyc x49; 3 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .121 | `_fix619_scratch` | 33 | 2910 | no flow audit record; content is pyc x1275, py x1256, txt x68, typed x32; 54 file contents (2 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .121 | `_sha256_probe121` | 32 | 484 | no flow audit record; content is json x198, rpt x90, tcl x70, log x49; 9 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .121 | `_c12_spm_sky130A` | 28 | 668 | LIVE — held open right now: cwd pid=3630420 /usr/bin/python3 /home/reyerchu/.claude/plugins/cache/vibe-ic-marketplace/vibe-i | leave alone until the run finishes |
| .121 | `_c_cv_u_hawaii_adc_run` | 24 | 237 | run u_hawaii_adc@asap7 v0.119.62 2026-08-03T05:39:24 verdict=FAIL gates 0/0 of -; 84 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .121 | `_c_rt_u_hawaii_adc_run` | 21 | 108 | run -@asap7 v0.119.62 2026-08-04T09:30:11 verdict=FAIL gates 0/0 of -; 33 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole record of this (IC, PDK, plugin version) attempt |
| .121 | `_bench_cvdp302_resume_scratch` | 4 | 137 | no flow audit record; content is sv x88, out x10, ids x7, txt x4; 105 file contents (4 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .121 | `_sha256_kat_121` | 3 | 16 | no flow audit record; content is v x6, vvp x4, hex x2, txt x1; 12 file contents (3 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .121 | `_agentjob_i903` | 3 | 12 | no flow audit record; content is txt x9, py x1, md x1, log x1; 11 file contents (3 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .121 | `_c12_sha256_gf180mcuD` | 2 | 249 | LIVE — held open right now: cwd pid=3630457 /usr/bin/python3 /home/reyerchu/.claude/plugins/cache/vibe-ic-marketplace/vibe-i | leave alone until the run finishes |
| .121 | `_agentjob_p1c` | 1 | 16 | no flow audit record; content is txt x8, ids x3, log x2, sh x1; 15 file contents (1 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .121 | `_agent_scratch_edge7` | 1 | 15 | no flow audit record; content is txt x7, json x3, md x2, log x2; 14 file contents (1 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .121 | `_atk_dead_alive` | 0 | 52 | no flow audit record; content is py x20, pyc x14, xml x6, txt x4; 9 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .121 | `_wt922_scratch` | 0 | 21 | no flow audit record; content is txt x8, json x8, py x4; 20 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .121 | `_adv121_cache` | 0 | 12 | no flow audit record; content is xml x4, log x4, json x4; 9 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .121 | `_agentjob_extract` | 0 | 13 | no flow audit record; content is json x4, txt x3, py x3, log x3; 13 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .121 | `_agentjob_denom` | 0 | 3 | no flow audit record; content is py x1, log x1, json x1; 2 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .121 | `_capB_run` | 0 | 1 | no flow audit record; content is md x1; 1 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .121 | `_c_subsv3_run` | 0 | 1 | no flow audit record; content is md x1; 1 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .121 | `_residue_run` | 0 | 1 | no flow audit record; content is md x1; 1 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .121 | `_agentjob_i981` | 0 | 8 | no flow audit record; content is lib x3, spice x2, md x2, log x1; 1 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .121 | `_c4_adc_scratch` | 0 | 12 | no flow audit record; content is md x6, json x6; 9 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |
| .121 | `_c_o_sta_probe` | 0 | 4 | no flow audit record; content is v x2, tcl x2; 4 file contents (0 MB) exist in no other folder and in no repo | keep in place — sole copy of its content |

## 8. What I could not settle

**a. 11 folders, 8.69 GB, are held back by a policy and not by a measurement.** Their
only unique out-of-run content is agent prose in Traditional Chinese (`agent.log`,
`RESULT_R24_previous_round.md`, an `L13_LAB_CALIBRATION.json`) or a fork of the open
gf180mcu DRC rule deck. Repo artefacts here are English-only, and bundling a
third-party deck needs an attribution decision I should not make unilaterally, so the
content could not be committed and the folders stay. Whoever owns those two policies
can free 8.69 GB by answering them; nothing else about those folders is in doubt. The
exact blocking files are listed in `~/_jruns/census/extract_blocked.json`.

**b. Regenerability of the big EDA intermediates is asserted, not proved.**
6.57 GB of the unique-artefact volume is `phase2/stage2/dft/tv.json.raw_tv.json`
(ATPG vectors, 435 files, up to 860 MB each) and a further ~12 GB is
`routed_preantenna.def` / `*.spef` / `*.sdf`. I classified these as *artefact*, i.e.
as blocking — the conservative call. Whether re-running the same ATPG or extraction
on the same netlist reproduces them byte-for-byte is a question I did not run, because
running EDA on five other hosts is outside what this job may do. If someone measures
that they are reproducible, roughly 19 GB more becomes reapable.

**c. `design_input_digest` is present in only a minority of audits,** so "same design"
is keyed on the IC name from `reports/final_summary.md` plus the PDK token, not on the
input hash. 163 run records carry the literal placeholder
`(unknown — fill in via L1_DATASHEET.json[ic_name])` as their IC name; those group
together only by PDK and I did **not** let that placeholder identify a design for
supersession — a placeholder is an absent measurement, not a shared one.

**d. 251 of the 466 folders have no flow audit record at all** (no
`reports/audit/phase23_completion_audit.json`, no `reports/final_summary.md`). They
cannot be superseded, because there is nothing to compare; they are decided by the
byte test alone and otherwise stay. This is the honest floor of the method.

**e. The `/proc` scan raced on the two busiest hosts** — 86 and 77 read errors on .121
(processes exiting mid-scan), 3 on .112, 1 on .114. Two independent scans were unioned
on .121, and `bin/sweeper.py` repeats the check at the moment of removal, but a process
that both started and held a folder inside a scan gap would not appear. A folder that
could not be inspected is never reported clean.

**f. Other agents were working the same tree** while this ran. The census numbers are a
snapshot taken at 02:40-04:00 on 2026-08-21, re-verified for existence and live use at
the moment of each removal; ALREADY-GONE is reported separately from a deletion this
job performed.

## 9. Reproducing this

Everything is under `~/_jruns` on 8HD-9:

```
bin/rsh <host>            run a command on any of the six hosts (routing is not uniform:
                          .112/.114/.120 go via 8HD-a, .121 goes via 8HD-a then .112)
bin/gdsnorm.py            layout digest of a GDSII stream (timestamp-blanked)
bin/worker.py             per-file git-blob-identity census for one host
bin/ident.py              run-identity extraction (IC, PDK, version, verdict, gates)
bin/classify.py           attribute uncovered content to a class
bin/cover.py              removability fixpoint on content alone
bin/outroot.py            the out-of-run-root measurement of section 2.4
bin/verdict.py            the three verdicts, five guards, final-set verify + asserts
bin/livescan.py           /proc cwd + every fd + herdr, for one host
bin/keeper.py             preserve an at-risk layout on its own host, verified
bin/extract.py            the out-of-run content to lift into this repo, verified
bin/sweeper.py            apply, with the live-use re-check built in
bin/report.py             this file
census/  ident/  survey/  evidence/  keeplog/   the measured data
findings.md               the running log, written as each measurement landed
```

_466 folders named above. That number is the acceptance test._
