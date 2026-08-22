# findings — agent `ptmo`, RUN 5: re-triage against v1.11.47

host 8hd-3 · 2026-08-21

## M0 — THIS TIME THE PREMISE HOLDS, and I checked before believing it

```
git ls-remote origin refs/heads/main
  752a8baaf64c51ecc1038303bfa368e0ef249f03    refs/heads/main
  752a8baaf  landing(ACTIVATE): stop storing vibeic-eda's version number in this repo [v1.11.47]
plugin.json version -> 1.11.47
commits since my last subject e36d81c0a (v1.11.33) -> 16
files changed                                      -> 780
```

Last round the same claim did not resolve and I said so; this round it does, and
it is worth recording that the difference is measured rather than assumed. My
three branches are still unmerged at this instant (`ptmo/main-92-red-triage`
`2b230dce3`, `…-v111133` `f04ccd65a`, `pytest-timeout…` `fc5a19353`), so
v1.11.48 is in flight, not in.

All 32 files carrying the old 92 IDs still exist at `752a8baa`, so the old list
is still runnable as a CLOSURE probe.

## Design for this round

The red list moved in BOTH directions, so the old 92 is no longer the input set —
it is only one of two arms:

* **Phase A — the old 92, re-run.** Answers "which closed". Anything green in
  both lanes here is a genuine closure (with the known-flake rule below).
* **Phase B — the 62 test files batch 2 CHANGED or ADDED.** Answers "what is
  newly red". 23 programs were also added, and the gates that react to added
  programs are already inside the old 92, so Phase A covers that blast radius.

KNOWN-FLAKE RULE, carried forward: an ID measured flaky is routed to FLAKY
whichever way it lands — IMAGE-ONLY, HOST-ONLY **or CLOSED**. Last round that
rule caught a false "one of your reds is fixed"; a flake's colour is not
evidence in either direction.

# ===== (3) THE DISPATCHER QUESTION — I BREAK THE CONVERGENCE, carefully =====

## First, the facts re-measured at v1.11.47 (780 files moved; none of them these)

```
tools/ci/gate_red_since.json   acknowledged rows -> 0      (still empty)
/home/reyerchu/vibe-ic/.git/hooks/  non-sample hooks -> 0  (still not installed)
/home/reyerchu/vibe-ic/.git/gatekeeper-stamp        -> absent (still never written)
batch 2 touched: repo_hygiene_gates.sh
batch 2 did NOT touch: gatekeeper-land.sh, tools/git-hooks/pre-push,
                       gate_red_since.json, tools/ci/_gate_dispatch.sh
```

So nothing in my previous reading has been invalidated by batch 2.

## THE CONVERGENCE IS ON THE LABEL, NOT ON THE MECHANISM

jlandpar and I both answer "(2)". **We disagree on the load-bearing sub-claim.**

| | jlandpar | me |
|---|---|---|
| is the verdict PRODUCED? | **YES** ("the verdict IS produced") | **I cannot confirm it, and I doubt it** |
| what is missing | a deadline nobody arms | a consumer — nothing forces the lane to run |

Three readings agreeing on a label while contradicting each other on whether the
verdict exists is worse than a disagreement, because the label is what gets
quoted. So, plainly: **I do not confirm jlandpar's "the verdict IS produced."**

### Why I doubt it, and the limit of my own evidence

`gatekeeper-land.sh` writes `.git/gatekeeper-stamp` on success and REMOVES it on
failure. No stamp exists in the main git dir or in any of the 104 worktrees.
That is consistent with BOTH:

  (a) it never ran → the verdict was never produced; or
  (b) it ran and failed → the verdict WAS produced, and nobody acted on it.

**Stamp absence cannot distinguish (a) from (b), and I will not pretend it can.**
What tips me toward (a) is that nothing FORCES a run: the hook that would is not
installed, `.github/workflows` does not exist, and there is no crontab entry. A
run under (b) would have to be a human choosing to run an hour-long gate and
then pushing anyway. Possible; not the default path.

## WHERE ALL THREE READINGS ACTUALLY MEET — and jm9 has the right frame

Under (a) OR (b) the hole is identical, and it is **jm9's** question, not mine
and not jlandpar's:

> **does a step verdict get CONSUMED?**

* under (a) there is no consumer because there is no producer run;
* under (b) there is a producer and still no consumer — the only thing that would
  consume a failing landing verdict is the pre-push stamp check, and it is absent;
* jlandpar's unarmed `max_commits` deadline is one INSTANCE of the same class:
  a verdict (this gate is red) that is produced by the hygiene suite and consumed
  by nothing that can ever come due.

**So I confirm the CLASS and break the specific claim.** The generalisation that
survives all three readings is jm9's: *verdicts are produced in several lanes and
consumed in none of them.* That is a stronger and more useful finding than
"(2)", and it is the one I would act on.

### One thing that would settle (a) vs (b) in an afternoon

`tools/ci/landing_completion_record.py` already builds "the exact machine
completion record for one hermetic landing arm", and `full:completion-record` is
a declared stage. If that record were PUBLISHED per landing instead of living in
a temp dir, "was a verdict produced for commit X" would be a lookup rather than
an inference from a missing stamp. Note the shape is already familiar:
`gate_red_since_check.py` records that the hygiene `--summary-json` is written
into a `tempfile.TemporaryDirectory` and destroyed — *"Nothing compares two
records; there is no second record to compare to."* Same defect, one lane over.

## M1 — PHASE A COMPLETE, 92/92 at v1.11.47: batch 2 closed 65

```
   CLOSED          65      green in BOTH lanes now
   BOTH            25      still red in both
   FLAKY-KNOWN      2      green this run, but a flake's colour is not evidence
   IMAGE-ONLY       0
   HOST-ONLY        0
   NOT_MEASURED     0
```

### Item (2), the one that matters most: STILL ZERO

**IMAGE-ONLY = 0 and HOST-ONLY = 0**, now across **three independent
measurements spanning 29 versions** — v1.11.18, v1.11.33, v1.11.47. Every old
red that is still red is red in BOTH lanes. Nothing on this board can be closed
by blaming this host.

### On the count: mine is 65, the brief says batch 2 fixed 68

Mine is 65 CLOSED + 2 FLAKY-KNOWN that happen to be green = 67 if those are
counted as fixed, which I decline to do. The residual unit is probably one ID
bucketed differently. My number rests on green in BOTH lanes; I have not tried
to reconcile to 68 because reconciling to someone else's number is how a
measurement stops being one.

## M2 — THE `1.6x` REPAIR IS 33/35 DONE, AND THE TWO SURVIVORS NAME THE GAP

```
1.6x cluster: 35   CLOSED 33   still BOTH 2
   test_matrix_mutation_ledger.py::test_every_enforced_cell_carries_a_named_mutation[step1.6x]
   test_matrix_mutation_ledger.py::test_the_coverage_is_complete_and_the_count_is_stated
```

Somebody regenerated the 63x8 pins — the census, the ledger, every `d1..d8`
dimension went green. **The MUTATION ledger did not get a row for step `1.6x`.**
So the repair covered "the grid knows this step exists" but not "this step's
cell carries a named mutation", and the coverage count is correspondingly short.

That is a precise, one-line-of-work finding for whoever did the regeneration:
`matrix_mutation_ledger` needs a named mutation for `1.6x`. It is the last 2 of
the 35 and nothing else in the cluster is outstanding.

## M3 — the 25 survivors, and what they are NOT

Only 2 of the 25 are `1.6x`. The other 23 were never that cluster and are
unaffected by the pin regeneration:

* 6 x `test_matrix_d3_outputs_produced[step15/17/19/20/30/32]` — declared outputs
  not produced, six different steps
* 3 x `test_issue901_*` — structured-vacuity tier granted without stating its count
* 2 x `test_flow_manifest_declaration_parity` — flow yaml vs the evidence manifest
* 2 x `test_v0_2_96_issue460_coverage_bridge` — e2e oracle pass vs coverage
* 2 x `test_matrix_63x8_coverage` (NA precondition; enforced-while-red)
* 1 each: `flow_compliance_check_gate`, `issue306_register_paydown`,
  `issue490_drc_report_check_argv`, `matrix_63x8_census_freshness` x2,
  `matrix_63x8_ledger`, `matrix_mutation_ledger` (coverage count),
  `organic900_901_ratchet_and_json_vacuity`

## M4 — A CORRECTION I OWE THE RECORD: the six deleted test files ARE explained

Phase B reported six files `ABSENT_ON_THIS_TREE`. I checked `--diff-filter=R`,
found no renames, and wrote that "six deletions with no renames deserve one
deliberate sentence in the landing record, and I can't find one."

**I was wrong. I read the commit SUBJECT and not its BODY.** `752a8baa` says it
outright:

> "`tools/vibeic-eda/VERSION` made this repository remember another repository's
> release number … **It is deleted, with `sync_image_version.py` and the seven
> tests that policed the pin.**"

And the count checks out — seven test files, not six:

```
git show --diff-filter=D --name-only 752a8baa
  .image-version-ignore
  tools/vibeic-eda/VERSION
  tools/vibeic-eda/sync_image_version.py
  mcp-eda/test/test_image_version_sync.py                       <- the 7th
  programs/tests/test_benchmark_data_is_a_record_not_a_pointer.py
  programs/tests/test_image_version_unreachable_is_not_a_failed_pin.py
  programs/tests/test_issue1297_anchor_layer_depth_is_measured.py
  programs/tests/test_issue423_report_only_gate_emits_no_verdict_token.py
  programs/tests/test_issue566_anchor_behind_is_not_a_blocker.py
  programs/tests/test_issue969_970_report_half_is_as_safe_as_it_claims.py
```

I saw six because my Phase-B list only covers `programs/tests/`. Ten files, one
coherent removal of a pin that no longer exists. **The deletions are attributed
and sound**, and the alarm I raised — that a test asserting "a report-only gate
emits no verdict token" was being dropped in the same batch as the dispatcher
argument — was mine, not the repo's.

The runner guard still earned its place: `ABSENT_ON_THIS_TREE` meant those files
were never counted green. But a guard firing is not by itself a finding, and I
turned one into a finding before reading the whole commit.

Worth quoting from that same message, because it is the discipline this whole
thread is about:

> "THREE BRIEF CLAIMS THAT DID NOT REPRODUCE, and the measurement wins each
> time … the brief listed 9 reference points where the measurement found 14 code
> points and 11 test files."

## M5 — PHASE B: the verdict CHANGED. IMAGE-ONLY is no longer 0, and it matters.

62 files, 2168 cases per lane. Six more were deleted by `752a8baa` and reported
`ABSENT_ON_THIS_TREE`, never counted green.

```
  BOTH 9 | IMAGE-ONLY 3 | HOST-ONLY 2      (single shot)
```

Interleaved repeats, 6x, image-then-host back to back, on all five
lane-different IDs — **none of these is a flake**:

```
                                                              image     host
test_pad_and_seal_ring…::test_a_declared_required_ring_…       6/6 RED  0/6
test_pad_and_seal_ring…::test_a_project_that_answered_nothing… 6/6 RED  0/6
test_pad_and_seal_ring…::test_answering_the_die_area_…         6/6 RED  0/6
test_matrix_63x8_coverage::test_nested_outcome_run_outlives…   0/6      6/6 RED
test_v1_4_21_dft_atpg_liberty_resolver::test_sky130_fault_cut… 0/6      0/6
```

* **IMAGE-ONLY = 3, deterministic.** First time in four measurements.
* **HOST-ONLY = 1, deterministic** (`test_nested_outcome_run_outlives…`). NOTE:
  I previously characterised this family as load-driven. At 6/6 vs 0/6 on a
  quiet machine it is NOT load here — it is a real lane difference. **I am
  correcting my earlier reading of this ID.**
* **1 was a one-off environment red**: `test_sky130_fault_cut_produces_real_scan_pairs`
  failed once on the host with `exit 124 … Pull complete …` — the host timed out
  PULLING A DOCKER IMAGE. 0/6 on repeat. In the image lane it SKIPs.

### The 3 IMAGE-ONLY, root-caused to one line

The failing assertion is `seal["marker"] is True`. `state` is `DISCLOSED_SKIP` in
BOTH lanes; only the ARTEFACT differs. Driving `die_finishing_gen.run()` directly
with an empty declaration:

```
HOST  state DISCLOSED_SKIP  marker True   exists True
      reason: "no seal-ring generator is declared for the this PDK PDK — die
               finishing may not be supported for it, so this step is SKIPPED"
IMAGE state DISCLOSED_SKIP  marker False  exists False
      reason: "no streamed GDS to seal (looked for phase3/stage3/pnr/*.gds,
               phase3/stage4/gds/*.gds)"
```

**Two different skip paths, and only one of them writes the marker.** On the host
no PDK is installed, so the "no generator declared for this PDK" branch fires and
writes `phase3/stage3/pnr/die_finishing.SKIPPED.txt`. In the image the PDK IS
available, so control reaches the "no streamed GDS" branch — which returns
`DISCLOSED_SKIP` and writes **no marker at all**.

The flow declares that marker as the artefact standing in for a finished die. So
**in the CI lane a project with a PDK and no GDS produces a disclosed skip that
leaves no trace on disk.** That is precisely the shape this repo hunts: a skip
that discloses in its return value and not in the tree, where the tree is what
the next gate reads.

This is the strongest argument yet for the image control: the host CANNOT see
this defect, because on the host the code never reaches the branch that has it.

**Incidental defect in the same message**, worth one character of somebody's
time: `"for the this PDK PDK"` — the reason string interpolates a placeholder
into a sentence that already carries the noun.

## M6 — I WROTE SCRATCH INTO THE SUBJECT TREE, and caught it at `git add`

The IMAGE-lane probe in M5 ran `cd programs` and then
`tempfile.mkdtemp(dir="…")` where the quoting collapsed, so mkdtemp fell back to
the CWD — **inside the subject checkout**:

```
vibe-ic-marketplace/plugins/vibe-ic/programs/tmpm3qz6c1d/seal/die_finishing.json
vibe-ic-marketplace/plugins/vibe-ic/programs/tmpm3qz6c1d/seal/input/submission_template/tapeout_declaration.json
```

`git add -A` surfaced them and they were removed before any commit; the tree now
shows only my three docs. **They were never committed and never measured
against.**

Worth naming the mechanism that would have caught it in a real run and did not
run here: `suite_write_guard` asserts that a pytest session writes nothing
`git status --porcelain` would show, and it PASSED in every lane I ran — because
I did this OUTSIDE pytest, in a hand-written probe. A guard scoped to the test
harness does not cover an operator poking at the same tree by hand. That is the
third harness defect of my own I have had to record on this job, and all three
share one shape: **the scratch went where I did not look.**
