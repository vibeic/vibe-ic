# LAND.md — the batch was 23 red; 22 of them were the lane, 1 was the fixture

**Issue:** vibe-ic#2014 — batch `programs/tests/test_landing_merge_verdict.py` (23 cases)
**Branch:** `next/kmerge`, based on `origin/main` `9dff42ceb35556b5039ff884893902235b5fc305`
("fix(landing): the hygiene lane and the review each measure a fresh worktree")
**Clone:** fresh `github.com/vibeic/vibe-ic` main into `~/_kmerge` on this host.
**Image:** `ghcr.io/vibeic/vibeic-eda@sha256:66c33ff2e05781758f596d82bff61ad8a404ef0a7eae3d21ab8a9d55df0d01ff`
(every measurement below ran inside it). Corpus `~/_matrix_benchmark_data` (`git pull`:
already up to date). NDA tokens from `~/.config/vibeic/commercial_pdk.json` into
`VIBEIC_NDA_TOKENS`.
**VERSION-LESS** — no version bump, no baseline write, no re-tier, no push, no PR.

---

## 1. Headline

| arm | how the file was run, in the pinned image | result |
|---|---|---|
| A — brief's lane | `docker exec` into the image, plain `python3 -m pytest` | **23 failed, 115 passed** |
| B — repo's own lane, pre-fix | `tools/ci/run_suite_in_eda_image.sh`, clean clone at `9dff42ceb` | **1 failed, 137 passed** |
| C — repo's own lane, with this patch | same harness, `~/_kmerge` on `next/kmerge` | **138 passed, rc 0** |

**22 of the 23 were lane configuration, not the tree. 1 was a real defect, and it is fixed
here.** The two facts are independent and both are measured below.

## 2. The 22: this file is the suite's engine-driving negative control

`tools/ci/trusted_test_selection.py::CONTROL_TESTS` pins this file into every landing's
denominator, and 23 of its 138 cases execute `tools/gatekeeper-verify-merge.sh` end to end,
which launches the hermetic B1/B2/A1/A2 arms through
`tools/ci/hermetic_candidate_runner.py`. The pinned image has **no Docker CLI and no
`/var/run/docker.sock`**, and no passwd entry for its own `Config.User` of uid 1000. So a
bare run of the file inside the image produces, for each of those 23:

```
[NORECORD] hermetic candidate: cannot resolve the host account home:
    'getpwuid(): uid not found: 1000'
[NORECORD] hermetic landing arm receipt: cannot resolve runner receipt: ...
gatekeeper-verify-merge: B1 arm receipt is NORECORD
```

and, once a passwd entry is supplied (measured, by hand, in a throwaway container):

```
[NORECORD] hermetic candidate: cannot execute Docker CLI:
    [Errno 2] No such file or directory: 'docker'
```

That is a fact about WHERE the suite ran, not about the tree, and **the repo already says
so and already ships the answer**: `tools/ci/run_suite_in_eda_image.sh` exists for exactly
this file, names exactly these 23, quotes exactly these two refusals, and supplies a passwd
entry + a docker-out-of-docker socket + identical host/container paths + `-v /tmp:/tmp`.
Its own header states why a `which("docker")` skip is not the repair: it would delete the
landing gate's only end-to-end proof in the one place it routinely runs.

Run through that harness on the **untouched** clone, the same 138 cases give **1 failed,
137 passed**. I did not weaken, skip or xfail anything to get there — the 22 needed no
change to the tree at all.

**For the coordinator:** the `ee29a2ad` measurement of 389 failures across 177 files was
almost certainly taken without the engine. Before another lane spends effort "fixing" its
batch, re-measure it through `tools/ci/run_suite_in_eda_image.sh`. I make this claim only
for my own file, where it is measured; I did not run any other batch.

## 3. The 1: `test_end_to_end_trusted_verifier_supplies_the_one_bootstrap_evidence`

### What it refused

```
[FAIL] landing_merge_verdict: REFUSE — ... [tier merge-tree]
  REFUSE  1 HYGIENE FINDING(S) INTRODUCED BY THIS BRANCH — present on the candidate
          and NOT on the base ...: [FAIL] macro OBS not crossed (tiny/openpdkx)
          [over published cells carrying a routed DEF]
```

with `hygiene_finding_delta.corpus_transitions[0].bounded_not_checked` holding **three** of
the four gate labels the test asserts — `macro OBS not crossed (tiny/openpdkx)` had come
back `FAIL` instead of `NOT_CHECKED`.

### Root cause, measured not reasoned

The verdict is honest; the fixture lied to it. Running the gate the way arm B2 runs it —
from the candidate subject's own miniature plugin, on the fixture's corpus cell:

```
$ cd <run>/candidate/vibe-ic-marketplace/plugins/vibe-ic
$ python3 programs/macro_obs_geometry_intersect_check.py <corpus>/ic/tiny/v1_openpdkx
ModuleNotFoundError: No module named '_flow_reason_taxonomy'
rc=1
```

against the same command from a full checkout:

```
[CANNOT DETERMINE] macro_obs_geometry_intersect: no macro LEF found. ...
  reason_class=DESIGN_DECLARED_NA -> SKIP
rc=2
```

`tools/ci/_gate_dispatch.sh` reads rc 1 as a FINDING and rc 2 as "could not check". So the
gate did not find a defect — it **died at import**, the miniature repository was missing a
module the gate imports, and the resulting FAIL was present on the candidate and absent
from the base. Only this test sees it: the EMPTY-base bootstrap is the one path that turns
a candidate-side gate result into a finding the base has no row for, which is why its
paired sibling (`..._post_bootstrap_equal_corpus_uses_ordinary_delta`, base already
activated) stayed green throughout — measured, both arms of the control in §5.

`programs/_flow_reason_taxonomy.py` was added by `bf6292fa3 fix(flow): classify non-verdict
reasons`, together with the `import` line in `macro_obs_geometry_intersect_check.py`. That
commit had no way to know this fixture stages a hand-written subset of `programs/`.

### The fix

`programs/tests/test_landing_merge_verdict.py` only — the fixture now **derives** the
staging closure from the tree instead of relying on a hand-written list:

* `_import_time_siblings(staged_file, programs)` — the sibling `programs/*.py` a staged file
  imports AT IMPORT TIME (module level plus the bodies of a module-level `if`/`try`, which
  is how this tree spells an optional dependency). It parses the STAGED bytes, not the
  upstream ones, because the fixture deliberately replaces some programs with tiny stubs.
* `_stage_program_import_closure(staged, programs)` — called last in the `sandbox` fixture,
  after every other staging line, and never overwriting a file already staged.

Measured over this fixture's 36 staged programs at parent `9dff42ceb`: this rule adds
**2** files; an indiscriminate `ast.walk` over every import (function-body imports included)
would add **202**, dragging `flow_compliance_check` and its whole phase-1 chain into a
fixture that calls none of it.

The 2 it adds:

| staged program | module-level import it needed | state before |
|---|---|---|
| `macro_obs_geometry_intersect_check.py` | `_flow_reason_taxonomy` | the observed FAIL |
| `matrix_mutation_ledger.py` | `_run_isolation` | latent — same defect, on a gate this fixture does not yet dispatch |

Both are staged into the miniature repo by the fixture's generic
`REQUIRED_AUTHORITY_PATHS | RUNTIME_PATHS` loop; neither dependency is itself a protected
path, so no protected-transition change is involved.

### The stale docstring, also repaired

The test's docstring told the next reader that the failure was
`validate_benchmark_snapshot "$BENCHMARK_B2"` demanding a git remote a materialized
snapshot cannot have, and that **"THE FIX IS NOT ON THIS BRANCH ON PURPOSE"**. That repair
has since landed: `tools/gatekeeper-verify-merge.sh:977` now calls
`reattest_corpus_snapshot_against_arm_receipt "$BENCHMARK_B2" "$B2_RECEIPT"`, exactly the
shape the docstring prescribed. Measured on this branch: `[PASS] benchmark-data checkout
measured`, a 64-character `parent_evidence_sha256`, `base_items` 0 -> `candidate_items` 1
over 4 replacement gates. The paragraph is rewritten rather than deleted, because a stale
"do not look here" is an instruction to the next reader not to look.

## 4. Nothing was weakened

* No assertion relaxed, no `skip`, no `xfail`, no `--write-baseline`, no matrix cell
  re-tiered. `git diff` touches one file; the only executable change is fixture staging.
* The four asserted `bounded_not_checked` labels are asserted as **four**, not trimmed to
  the three that were observed.
* `programs/source_chip_agnostic_check.py .` -> rc 0.

## 5. Evidence, with the arms paired

| # | tree | lane | selection | result |
|---|---|---|---|---|
| 1 | clean clone `9dff42ceb` | image, no engine | whole file | 23 failed, 115 passed |
| 2 | clean clone `9dff42ceb` | `run_suite_in_eda_image.sh` | whole file | **1 failed**, 137 passed |
| 3 | **fresh** control clone `~/_kmerge_ctl` at `9dff42ceb`, `git status` empty | `run_suite_in_eda_image.sh` | the failing test + its paired sibling | **1 failed, 1 passed** — the sibling is green on the same tree, so the fixture is not simply broken |
| 4 | `next/kmerge` | `run_suite_in_eda_image.sh` | whole file | **138 passed, rc 0** |
| 5 | `next/kmerge` | `run_suite_in_eda_image.sh` | `test_arm_env_reachability.py` + `test_inherited_red_deadline.py` (the two neighbours that import/parse this file) | 19 passed |

Run 3 is the red-without-fix control on a tree that has never held the patch — a separate
clone, not a `git checkout` of the branch I am on.

## 6. Nothing was needed from a shared program

The fix is entirely inside my batch. No change was required to
`tools/ci/hermetic_candidate_runner.py`, `tools/ci/_gate_dispatch.sh`,
`tools/gatekeeper-verify-merge.sh`, `tools/ci/protected_landing_transition.py` or
`programs/macro_obs_geometry_intersect_check.py`, and none was made.

One adjacent observation, **not** acted on because it is another lane's file:
`hermetic_candidate_runner._home_path()` raises `Refusal` when `pwd.getpwuid(os.getuid())`
cannot be resolved, which NORECORDs every mount before the engine is ever probed.
`programs/scratch_root_guard.py` asks the identical question and degrades to "host account
home NOT CHECKED ... there is no host home to expose from here". The two do not agree about
what an unresolvable home means. `run_suite_in_eda_image.sh` works around it by supplying a
passwd entry, which is a legitimate lane fix; whether the runner should also degrade rather
than refuse is a question for whoever owns `tools/ci/`.
