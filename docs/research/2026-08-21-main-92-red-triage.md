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

**VERDICT, stated rather than left to be inferred from a zero: IMAGE-ONLY = 0
and HOST-ONLY = 0, so main is genuinely red — none of these is an environment
artefact of one lane.** Every ID except the two named FLAKY reproduces in BOTH
the pinned CI image and on this host, serially, without xdist. Nothing on this
list can be closed by blaming the developer host, and neither of the two agents
holding it is chasing a phantom.

| bucket | n |
|---|--:|
| **BOTH** — red in both lanes, measured SERIALLY: a real property of `867de4289` | **90** |
| **FLAKY** — not deterministic in a lane; ratios below | **2** |
| **IMAGE-ONLY** | **0** |
| **HOST-ONLY** | **0** |
| **xdist harness artefact** | **0** |
| NOT_MEASURED | **0** |

## 2a. How many observations each verdict rests on

A single observation per lane is not enough to call an ID deterministic — it made
me wrong twice tonight. So the 57 non-`1.6x` IDs were re-measured INTERLEAVED
(for each repetition and each file: the IMAGE first, then immediately the HOST,
so both lanes meet the same contention), 4 repetitions, 96 cycles:

```
  49 IDs   BOTH    5/5 red image    5/5 red host
   6 IDs   BOTH    2/2 red image    2/2 red host   (census-bound, own interleaved arm)
   1 ID    FLAKY   4/13    image   13/13    host   test_a_pinless_abstract_is_never_staged
   1 ID    FLAKY   1/10    image    0/10    host   test_live_collection_relays_…_past_old_bound
  ---
  57 total.   IMAGE-ONLY 0 · HOST-ONLY 0 · NOT_MEASURED 0
```

The two census-bound files were too expensive for the 96-cycle pass
(`test_matrix_63x8_census_freshness` 295 s image / 246 s host,
`test_matrix_63x8_coverage` 445 s / 374 s per session), so they got their own
interleaved confirm arm — image then host, back to back, per file.

**Neither FLAKY changed bucket as the sample grew; both got sharper**, and no ID
anywhere moved INTO a lane-only bucket at any sample size.

## 2b. Two answers the other two agents can act on immediately

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

## 2c. Lanes, stated exactly

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

# 6b. Two defects in MY OWN harness, both caught by the tool rather than by luck

**(i) A container cannot see `/tmp`.** The first census-confirm arm read the ID
list from `/tmp/main_92_fail_ids.txt`, which is outside the `-v` mount:
`grep: /tmp/main_92_fail_ids.txt: No such file or directory`. `mapfile` produced
an EMPTY array, and `pytest … "${IDS[@]}"` with no selectors falls back to
`pytest.ini`'s `testpaths = programs/tests` — **so it started the whole suite**,
the one thing the brief forbids on this host. Its own log is pages of dots stuck
at `[ 17%]`.

I then found that container **still up 11 minutes later**, competing with
repetitions 1-15 of pass 3, and killed it **by recorded container ID**
(`docker kill 3173a0133b5d`), never by a pattern that could match my own command
line. Consequence stated rather than hidden: since the flake mechanism at issue
IS contention, that contamination can only make an ID look MORE flaky, never
less — a `BOTH` taken under it is conservative, a `FLAKY` ratio from those cycles
could be inflated. `git -C main92 status --porcelain` is **empty**: across its
whole 12-minute life it wrote nothing into the subject tree.

**(ii) The host half never ran.** `cd X && (A) & (B) & wait` backgrounds
`cd X && (A)` as one unit, so `(B)` executed in the original cwd and died on
`out92/confirm_host.log: No such file or directory`, rc=1, instantly.

Neither half is reported as anything: `rep_bucket.py` globs for junit that does
not exist, so those IDs simply keep the observation count they actually have.
The runner now refuses loudly instead of sweeping wide —

```
if [ "${#IDS[@]}" -eq 0 ]; then
  echo "REFUSED $1 $base: selector list is EMPTY — refusing rather than running the whole suite"
```

— because the failure mode was silent breadth, and an empty selector list must
never be able to mean "everything".

# 7. A third defect in MY OWN runner, caught because the tool said so

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

1. **The 35 IDs of §1 were NOT given repeat treatment.** They have a named,
   non-timing cause — a flow step that arrived without its rows — so their risk
   of being timing flakes is low, but "low" is a judgement and not a
   measurement. They rest on one observation per lane.
2. **Six census-bound IDs rest on TWO observations per lane, not five.**
   `test_matrix_63x8_census_freshness` and `test_matrix_63x8_coverage` cost
   295-445 s per session, so they were excluded from the 96-cycle repeat pass and
   given their own interleaved confirm arm instead: 2/2 red in both lanes. That
   is enough to rule out a one-off, not enough to put a tight bound on a rare
   flake. Their counts are printed per ID in `TRIAGE57.md`.
3. **I did not diagnose the 7 `EXTRACTION_FEEDBACK_ABSENT` IDs or the 2 LVS
   verdict-token IDs** beyond their signature. They are `BOTH` at 5/5 in both
   lanes and they belong to the 38-agent.
4. **The `magic` segfault is characterised, not diagnosed.** I know it is
   `exited -11` on `LEF read, Line 26 (Error): No layer defined for RECT`, at
   4/13 in the CI lane. I did not determine whether the malformed techfile comes
   from the fixture or from the generator under test.

---

# 9. WHY NOTHING CAUGHT IT FOR FIVE COMMITS — the answer is (c)

The question posed was: is the pin regeneration **(a)** in a list nothing
iterates, **(b)** run but its verdict never made fatal, or **(c)** run, fatal,
and bypassed.

**It is (c).** Saying so plainly, as asked.

## (a) EXCLUDED — the selector does iterate it

`ci_targeted_test_select.py --base 7fcbc7397~1` on the commit that added step
`1.6x` selects **444 test files, 17 of them the matrix family** — including
`test_matrix_63x8_census_freshness.py`, `test_matrix_63x8_ledger.py`,
`test_matrix_mutation_ledger.py` and every `test_matrix_d1..d8`. The tests that
later produced 35 of the 92 reds **were in the selection for the very commit
that broke them.**

One deliberate removal exists and does not change this: the `63x8 census
freshness` gate was deleted from `tools/ci/repo_hygiene_gates.sh` at `e22cce75f`
— *"MOVED OUT OF THE LANDING PATH (owner decision, 2026-08-16)"* — on the stated
grounds that *"a stale census breaks nothing … it simply no longer sits between a
fix and main"*, with the fallback named as *"`test_matrix_63x8_census_freshness.py`
still enforces it in the suite"*. **That fallback is real and is selected.**

## (b) EXCLUDED for the detector — the targeted arm is fatal

`gatekeeper-land.sh` sets `FAILED=1` on a red targeted arm and ends
`exit "$FAILED"`. On failure it does the opposite of stamping:

```
git rev-parse HEAD > "…/gatekeeper-stamp"
echo "=== ALL GATES PASS — stamped … ==="
else
rm -f "…/gatekeeper-stamp"
echo "=== FAILURES ABOVE — stamp removed; the pre-push hook will refuse ==="
```

The only BEST-EFFORT thing in this family is the **repairer**, not the detector:
`--prepare`'s census re-derivation is documented *"Alone among the steps above it
is BEST EFFORT"*, and `--prepare` is **OFF BY DEFAULT**.

## (c) — and the precise shape matters, so here it is exactly

The entire chain rests on one client-side hook, which says so itself:

> *"pre-push — **the ONLY enforced gate on what reaches `main`, by necessity.**
> `gatekeeper-ci.yml` … has never run once. Actions is disabled at the ACCOUNT
> level … So the checks CI would enforce are enforced HERE or nowhere."*

and it is the hook — not `gatekeeper-land.sh` — that makes the expensive tier
compulsory, via the stamp:

```
if [ ! -f "$STAMP" ];                        then pre-push: FAILED — the full suites have not been run
elif [ "$(cat "$STAMP")" != "$HEAD_SHA" ];   then pre-push: FAILED — stamp is for a different commit
```

**MEASURED on this host, in the landing checkout:**

```
/home/reyerchu/vibe-ic/.git/hooks/pre-push                     -> No such file or directory
ls /home/reyerchu/vibe-ic/.git/hooks/ | grep -v '\.sample$'    -> (nothing)
git config --get core.hooksPath                                -> unset
find /home/reyerchu -maxdepth 4 -path '*/.git/hooks/pre-push' -not -name '*.sample'
                                                               -> (nothing)
/home/reyerchu/vibe-ic/.git/gatekeeper-stamp                   -> No such file or directory
```

Every hook in that repository is a disabled `.sample`; `core.hooksPath` is unset;
its **104 worktrees all share that same empty hooks directory**;
`tools/install-git-hooks.sh` exists and has evidently not been run here.

### The part that is about the operator, stated plainly — and the part that is not

The answer is (c), so the class of finding is the one you asked me to name: the
gate is run-and-fatal, and it is not what stands between a change and `main`.
A habit of pushing with `--no-verify` is exactly the shape that turns a
client-side gate into no gate, and it is worth writing down as such.

**But on this host `--no-verify` is not what let the 1.6x drift through, and it
would be wrong to let you conclude that it was.** There was no hook to bypass:
the pre-push hook is not installed in the landing checkout at all, so the stamp
check never ran, with or without the flag. The proximate cause is a MISSING
INSTALL of the only enforcement point the repository has — not a flag used to
step over one that was there.

Both statements are true and neither should be dropped: the enforcement model is
client-side and optional by construction (because Actions is disabled at the
account level and the appeal was rejected), and on this machine the client side
was never armed. `--no-verify` is belt-and-braces over an absent gate.

**The one-line repair is `tools/install-git-hooks.sh`.** I have not run it — it
mutates the operator's own checkout, which is not mine to change, and doing it
silently would be exactly the kind of unattributed edit the gates in this repo
exist to prevent.

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
6. **RUN `tools/install-git-hooks.sh` IN THE LANDING CHECKOUT.** §9: the
   pre-push hook — which the repository itself calls "the ONLY enforced gate on
   what reaches `main`" — is not installed in `/home/reyerchu/vibe-ic`, every
   hook there is a disabled `.sample`, `core.hooksPath` is unset, and the 104
   worktrees share that empty hooks directory. Until it is installed, the
   gatekeeper stamp is never checked and `gatekeeper-land.sh` is advisory in
   practice however fatal it is in code. I did not run the installer: it mutates
   a checkout that is not mine.
7. **Decide whether a stale 63x8 census should block a landing.** `e22cce75f`
   moved that gate out of the landing path by owner decision on the grounds that
   "a stale census breaks nothing". That reasoning is defensible, and it held —
   the fallback test IS still selected. What failed was the layer below it.

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
