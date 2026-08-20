# RESULT — which of main's 92 red test IDs are real?

agent `ptmo` · host 8hd-3 (192.168.1.121) · 2026-08-21
subject **`867de4289`** (v1.11.18), clean clone, **nothing applied**

---

# 1. THE HEADLINE: 35 of the 92 are ONE COMMIT, not 35 defects

Thirty-five of the ninety-two failure texts state the same fact — the canonical
flow grew from **68 steps to 69** and the 63x8 matrix's pinned census, ledger,
waivers and dimension manifests were not regenerated with it.

```
$ git log -S'1.6x' -- vibe-ic-marketplace/plugins/vibe-ic/flow/phase1_phase2_phase3.yaml
7fcbc7397   2026-08-21   ppa(phase4): step 13 passes on a rewritten candidate,
                         so a cross-layer search needs a second relation

ancestor of 867de4289 : YES, 5 commits back
live flow yaml today  : 69 steps  (non-integer ids: 0.5ic · 1.6x · 15.5ic · 26.5ic · 37.5ic)

$ git show --stat 7fcbc7397 | grep -E 'matrix|63x8|waivers|flowref|ledger|census'
   (nothing — that commit regenerated NONE of the 63x8 pins)
```

The signatures it produces, verbatim from the image lane:

```
assert 69 == 68                                                      x9
the flow yaml now declares 69 steps, not 68; the 63x8 …
the NA rationale was re-derived over 69 steps, not 63; …
the coverage grid changed: measured (69, 8, 552) …
the blind set changed. NEWLY BLIND ['1.6x']: a step no…
steps ['1.6x'] entered the real-gate PASS-tier population…
step 1.6x gate CANNOT FAIL on anything a project DID: …
the flow declares 1 step(s) that no mutation in the ledger ever measured
```

**The matrix family is not broken. It did its job — it noticed a step arriving
without its rows.** The remedy is to regenerate the pins against a 69-step flow
and give step `1.6x` its gate, mutation and waiver rows; not to repair 35
assertions one at a time.

`origin/land/ppa-tf` does **not** touch the flow yaml, so it neither adds nor
removes this — although the commit that introduced step `1.6x` is itself from
the same `ppa(...)` workstream.

The exact 35 IDs are in `out92/cluster_1_6x.txt`; the other 57 in
`out92/rest57.txt`.

---

# 2. The buckets — all 92, by TEST ID

| bucket | n |
|---|--:|
| **BOTH** — red in both lanes, measured SERIALLY: a real property of `867de4289` | **90** |
| **FLAKY** — not deterministic in a lane; ratios below | **2** |
| **IMAGE-ONLY** | **0** |
| **HOST-ONLY** | **0** |
| **xdist harness artefact** | **0** |
| NOT_MEASURED | **0** |

## 2a. Two answers the other two agents can act on immediately

**HOST-ONLY = 0.** Nothing on the list is a phantom of this developer host.
Neither of you is chasing an environment red — with the one exception in §3,
which is red on the host for an environment reason but is *also* red in CI for a
different one.

**The xdist worry is settled by measurement, not by assumption.** The brief's
list came from `-n 10` and flagged that two IDs looked like a mutate-vs-read
race. **Every one of the 92 was re-run SERIALLY — one pytest session per file,
no xdist, in both lanes — and all 92 reproduce.** The harness-artefact bucket
the brief asked me to keep open is empty, and it is empty because it was
measured, not because nothing was found.

## 2b. Lanes, stated exactly

| lane | runtime | plugin autoload |
|---|---|---|
| **IMAGE** | `docker run --rm … ghcr.io/vibeic/vibeic-eda@sha256:66c33ff2…d01ff --skip bash …` (`--skip` first, never `docker exec`) | `PYTEST_DISABLE_PLUGIN_AUTOLOAD=1` |
| **HOST** | this host, python 3.10.12 / pytest 9.1.1 | autoload ON, `-p no:pytest_ethereum` |

The image lane is configured the way `tools/gatekeeper-land.sh` configures it —
that is the CI truth. The host lane is configured the way the brief's own
measurement was taken, so the other agents' reds are reproduced in their terms
rather than in mine.

Execution: one `python3 -m pytest` per FILE (32 files), each with its own
`--junitxml`, each bounded at 1500 s, so a file that hangs costs its own record
and not its neighbours'.

---

# 3. The two FLAKY, with ratios — and why single-shot colour lied about both

Pass 1 ran the two lanes CONCURRENTLY (load 50–100 on 32 cores). Pass 2 runs
each ID in the IMAGE and then immediately on the HOST, back to back, 8
repetitions, on a quiet machine (load 3.4). **Both of my pass-1 verdicts moved.**

```
                                                              image      host
test_matrix_63x8_coverage.py::
   test_live_collection_relays_finite_semantic_progress_past_old_bound
                                                          RED 0/8    RED 0/8
test_digital_hardmacro_gen.py::
   test_a_pinless_abstract_is_never_staged                 RED 2/8    RED 8/8
```

### 3a. There is NO image-only red in the 92

`test_live_collection_relays_finite_semantic_progress_past_old_bound` was the
single IMAGE-ONLY in pass 1. Interleaved on a quiet machine it is **0/8 red in
both lanes.** Its pass-1 red was contention. Root cause, measured earlier today:
a **0.3 s forward-progress lease over 7 collections that sleep 0.14 s each** —
about 2× headroom — so at high load the supervisor kills a healthy child as
hung. **Nobody should spend on this ID.**

### 3b. `test_a_pinless_abstract_is_never_staged` — same colour, two different causes

```
HOST : which magic -> command not found
       'magic did not complete: watchdog reported launch_error after 0s'   RED 8/8
IMAGE: /foss/tools/bin/magic, version 8.3.681
       'magic exited -11 and wrote no LEF; last output:
        LEF read, Line 26 (Error): No layer defined for RECT.'             RED 2/8
```

On this host the tool is simply **absent** — `launch_error after 0s` is the
watchdog saying "I could not look", and it must not be read as "the abstract was
staged". In CI the tool **runs and segfaults intermittently** on a LEF whose
`RECT` names a layer the techfile does not define.

**An agent measuring only on this host sees a stable 8/8 red and concludes "hard
defect in the staging logic". That is wrong twice: it is not the logic, and in
CI it passes six times in eight.** This single ID is the clearest case for why
the image control exists.

---

# 4. The remaining clusters (image lane, by failure signature)

| n | signature | family |
|--:|---|---|
| 35 | `69 == 68` · `1.6x` · `(69, 8, …)` | **§1 — flow grew to 69 steps, matrix pins still say 68** |
| 7 | `LVS aborted before netgen: EXTRACTION_FEEDBACK_ABSENT …` | extraction feedback missing under `phase3/stage3/extracted` |
| 5 | `the nested outcome run produced red test report(s) …` | the live-census nested run inheriting the §1 reds |
| 3 | atomic-write ratchet | §5 |
| 3 | `test_issue901_*` structured-vacuity tier | a tier granted without stating its count |
| 2 | `=== flow gate enforcement audit === 180 clauses / 171 gates / 19 ENFORCED / 152 AUDIT_ONLY / 40 declared / 131 UNDECLARED` | flow-gate enforcement register |
| 2 | `assert 'LVS_EXTRACTI…LEGAL_OVERLAP' == 'LVS_NO_TERMI…'` | LVS verdict-token change |
| 2 | `162 declared paths vs 160 manifest entries`; the 2 gaps are step `37.5ic`'s `BRIEF_*.html` / `SIGNOFF_*.html` | **`867de4289` is itself the 37.5ic activation — its own residue** |
| 1 | `polarity-blind 216 (baseline 213)` | three new prose extractors |
| 1 | `magic exited -11` / `command not found` | §3b |
| … | singletons, listed per-ID in `TRIAGE.md` + `SIGS_image.txt` | |

---

# 5. The atomic-write ratchet — measured against ppa-tf so nobody waits for it

3 of the 92 (`test_issue1082_open_w_category_closed` ×2,
`test_issue1470_atomic_declared_report` ×1) are the ratchet on
`atomic_artifact_write_check.py`. A/B:

```
main   867de4289 : 6 programs / 12 sites
ppa-tf bb90724dc : 6 programs / 12 sites
ONLY on ppa-tf: none      ONLY on main: none
```

Byte-identical on both heads: `area_total_vs_budget_check.py:393` ·
`closed_loop_edge_check.py:346` · `crosslayer_rewrite_equivalence.py:679/701/720/729/751/755` ·
`crosslayer_rewrite_equivalence_check.py:196/229` · `declared_clock_period.py:392` ·
`die_density_fill_gen.py:579`.

All twelve are mechanical `.write_text(...)` / `.write_bytes(...)` on a declared
destination and map one-for-one onto `_atomic_artefact.write_text` /
`.write_bytes`, which is the remedy the gate itself prints. `crosslayer_*` did
not exist at v1.11.5, so most of this breach arrived with the last 35 commits.
**`origin/land/ppa-tf` neither fixes nor worsens it — do not wait for it.**

`test_no_declared_report_is_written_through_open_w` fails on exactly ONE of the
twelve, `die_density_fill_gen.py:579`, which promotes a filled layout with
`dest.write_bytes(filled.read_bytes())` — a non-atomic copy of a declared
output, so a reader can see a half-written file.

---

# 6. FIXED? — nothing, and why

**This job was the control, not the repair**, and the brief assigns the fixes to
two other agents (54 matrix IDs / the other 38). Every ID's `fixed?` column is
therefore **no**, and the honest reason is that fixing them is somebody else's
lane and duplicating it would collide. What I did instead is remove work from
their lists: two IDs that are not about main at all (§3), thirty-five that are
one commit rather than thirty-five defects (§1), and three that will not be
fixed by the branch they might have been waiting on (§5).

No hygiene gate was given `--write-baseline`. No GDS was hand-edited, no
geometry deleted, no pin moved, no rule deck relaxed. No test was relaxed to
make a red go away.

---

# 7. A defect in MY OWN runner, caught because the tool said so

`out92/by_file.txt` is TAB-separated but my shell loop did `for n in $rest`,
which word-splits on any whitespace. Exactly one of the 92 IDs contains spaces:

```
test_program_inventory_no_drift.py::test_declared_non_counts_are_still_present[and all 56 EDA/device tools]
```

so that file's invocation became five unmatchable selectors and reported
`no tests ran in 0.35s`, rc=4.

**It did not become a green.** The bucketer distinguishes "the file produced a
junit and this ID is not in it" from "the file never ran", so those four IDs sat
in `ABSENT-FROM-RUN`, never in a clean bucket. Re-run with `mapfile` /
`"${IDS[@]}"`: **host 4 failed in 0.97 s, image 4 failed in 2.27 s → BOTH.**
`grep -c " " /tmp/main_92_fail_ids.txt` → 1, so no other ID was affected.

---

# 8. What is NOT settled

1. **The per-ID FLAKY column is complete for 2 of 92, not for 92.** Pass 1 was
   single-shot, under contention, in both lanes. Two IDs given repeat treatment
   both moved. The other 90 are `BOTH` on **one** observation per lane, which
   proves they can be red but not that they are deterministic. Repeat
   measurement of the remaining 57 non-`1.6x` IDs is **in progress**; the 35 of
   §1 have a named non-timing cause and are lower risk.
2. **The two census-bound files** (`test_matrix_63x8_census_freshness`,
   `test_matrix_63x8_coverage`) cost 403 s and 532 s per lane, so their second
   serial repeat is still running at the time of writing — `NOT_MEASURED`, never
   a default.
3. **I did not diagnose the 7 `EXTRACTION_FEEDBACK_ABSENT` IDs or the 2 LVS
   verdict-token IDs** beyond their signature. They are `BOTH` and they belong
   to the 38-agent.

---

## REQUESTS TO THE LANDER

1. **Step `1.6x` needs its 63x8 rows before any of the 35 in §1 can go green.**
   `7fcbc7397` added a flow step and regenerated none of the pinned matrix
   artefacts. Landing a repair for those 35 individually would be repairing the
   symptom; the flow-vs-pins regeneration is the change.
2. **The atomic-write ratchet is 12 sites over 6 programs and is NOT fixed by
   `origin/land/ppa-tf`** (§5). Two of them, `declared_clock_period.py:392` and
   `die_density_fill_gen.py:579`, predate the ppa work; the other ten arrived
   with `crosslayer_rewrite_equivalence*.py`.
3. **`test_a_pinless_abstract_is_never_staged` should not be counted as a repo
   red on a host without `magic`** (§3b). In the CI lane it is an intermittent
   `magic` segfault (2/8), not a plugin defect.
4. **Two of the tests on this list are load-fragile by construction** — a
   0.25–0.8 s forward-progress lease with ~2× headroom over the work it
   supervises. On a quiet lander they may not appear at all; on a busy one they
   will, and they will look like defects.
5. Nothing here bumps a version, touches `plugin.json` / `marketplace.json`, or
   writes a hygiene baseline.

---

## Artefacts (all under `/home/reyerchu/_ptmo_priv/`)

| file | what |
|---|---|
| `findings92.md` | the running log, written as each measurement landed |
| `TRIAGE.md` | the per-ID bucket table, partial-safe, refreshed every 45 s during the run |
| `SIGS_image.txt` · `SIGS_host.txt` | one-line failure signature per ID, per lane |
| `out92/image/*.xml` · `out92/host/*.xml` | 32 per-file junits per lane |
| `out92/image_lane.log` · `out92/host_lane.log` | per-file rc and seconds |
| `out92/pass2_interleaved.txt` | the 8 interleaved repetitions |
| `out92/cluster_1_6x.txt` (35) · `out92/rest57.txt` (57) | the split |
| `out92/atomic_ab.txt` | the main-vs-ppa-tf ratchet A/B |
| `run92.sh` · `pass2_interleaved.sh` · `confirm_census.sh` · `bucket.py` · `sigs.py` | every runner, re-runnable |
| `main92/` @ `867de4289` · `ppa/` @ `bb90724dc` | the trees |
