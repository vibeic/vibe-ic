# The disclosure existed and could not reach the verdict

`programs/tests/test_landing_merge_verdict.py`, measured on `88a8bcdf4d`.

## Where the shipping suite actually runs

GitHub Actions is disabled at the **account** level and the appeal was rejected
(`.github/workflows-disabled/README.md`; support ticket 4613114). Nothing runs
server-side. The two places this suite runs are both local, and only one of them
has a container engine:

| lane | where | engine | this file |
|---|---|---|---|
| `tools/gatekeeper-land.sh` invoked on a host | the operator's machine | whatever the host has | green here (this host has `/usr/bin/docker`, server 29.1.3) |
| **the hermetic landing arms** — `tools/gatekeeper-verify-merge.sh:670,701` launch `/subject/tools/ci/hermetic_test_arm_entry.sh` (A1/B1) and `/subject/tools/gatekeeper-land.sh` (A2/B2) through `tools/ci/hermetic_candidate_runner.py` | inside `ghcr.io/vibeic/vibeic-eda@sha256:66c33ff2…` (`tools/ci/protected_landing_transition.py:94` `RUNNER_IMAGE`) | **none, by design** — the image carries no Docker CLI, and `hermetic_candidate_runner.py:884` REFUSES any inspection that exposes `docker.sock` | **23 permanently red** |
| `tools/ci/run_suite_in_eda_image.sh` (census / manual) | the same pinned image, with the host engine bound in | yes; `--no-engine` is its control | green |

`tools/ci/trusted_test_selection.py:50 CONTROL_TESTS` pins
`programs/tests/test_landing_merge_verdict.py` into **every** landing's
denominator. So the answer to "is main carrying resident red" is: **yes, inside
the arms** — the mandatory negative control is red in the one place it is
mandated to run, and it is not red because of the tree.

It never surfaced because `failed_set_delta` (`programs/landing_merge_verdict.py:836`)
sends an id that is `_same_red` on both arms to `preexisting`, not to
`new_failures`. The 23 fail identically on the base arm and the candidate arm, so
the differential absorbs them. A control that cannot discriminate anything is
not a control — it is 23 seats of noise the judge has learned to ignore.

## The shape of the defect

MEASURED, pinned image, no engine:

```
23 failed, 115 passed in 180.40s
      --- B1 runner said (this is the CAUSE; the lines below are the symptom):
      [NORECORD] hermetic candidate: cannot execute Docker CLI:
          [Errno 2] No such file or directory: 'docker'
      [NORECORD] hermetic landing arm receipt: cannot resolve runner receipt: ...
gatekeeper-verify-merge: B1 arm receipt is NORECORD
```

The gate was **already honest**. It said "I did not measure this", in its own
words, with the cause named and labelled as the cause. Three frames up, the only
consumer of that sentence read `returncode != 0` and reported FAIL — "this code
is broken". Different claim, and false. The disclosure was produced and had
nowhere to go.

## What was changed

`programs/_hermetic_engine_capability.py` — the segment between the NORECORD and
the verdict, and nothing else. It returns `MEASURED` or `NOT_MEASURED` and always
names the cause. `NOT_MEASURED` requires **two independent readings**:

1. the run's own output names the engine as unexecutable in the runner's exact
   words (`hermetic_candidate_runner.py:385`, raised only from `OSError`), **and**
2. a probe issued from this process, with the executable name `--docker-bin`
   defaults to, confirms the engine is out of reach.

Either alone is `MEASURED`. The load-bearing direction is the second: a run that
**prints** the marker on a host whose engine answers stays `MEASURED` and stays
red, so no string a candidate emits can buy it a skip. `test_landing_merge_verdict`
calls it at the three points that consume a completed verifier run.

## Both directions, driven

| run | result |
|---|---|
| pinned image, `--no-engine` | `125 passed, 24 skipped` — **0 failed**; every skip carries `NOT_MEASURED — the hermetic arms never started: the container engine CLI 'docker' cannot be executed from this process: [Errno 2] …` |
| pinned image, engine reachable (`run_suite_in_eda_image.sh`) | `149 passed in 613.12s` — **0 skipped**. The 23 really run. |
| host, engine reachable, **judge mutated** (`if False and delta.new_failures`) so a branch that must be refused returns `LAND_OK` | `test_end_to_end_an_innocuous_diff_that_leaves_a_test_red_is_refused` went **RED** (`assert 0 == 1`), not skipped; its paired good-branch guard still passed. The guard was not turned off. |

## The 24th, reported rather than hidden

`test_end_to_end_the_caller_checkout_is_never_touched` used to **PASS** in the
pinned image and now reports `NOT_MEASURED`. It passed because no arm ever ran
and an untouched checkout is exactly what "nothing happened" looks like. It was a
green that measured nothing. That is a coverage change, and it is stated here
rather than special-cased away.

## What this branch would do to its own landing gate

Nothing here is landed. If it were: the base arm reports these ids `failed`, the
candidate arm reports them `skipped`, and `programs/landing_merge_verdict.py:1504`
refuses `failed -> skipped` as **SILENCED** (23) plus `passed -> skipped` as
**WEAKENED** (1). That refusal is correct in general and wrong for this specific
change, and it is the gatekeeper's call, not the author's. Whoever lands this has
to look at the 24 transitions by name and say so.
