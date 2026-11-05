# Bounded RTL task profile selection

## Result

Bucket A, AUGMENT-EXISTING: the general flow front door now selects the
registry's named `RTL-only` profile for a bounded, source-compatible RTL task.
The thin dispatcher uses the same resolver. A clear RTL request can proceed
without a user-authored feature file or an IC/IP confirmation question.

Author verification is scoped to profile selection and the actual public owner
boundary. This is ready for independent review, with nine preserved base
failures in the nearby suite. Full release acceptance remains NOT_RUN.

## Source and ownership

- Initial exact base: `a24fb130bddd0d6b9ff44077ddd39e59873146ff`.
- Intermediate recomposed base: `5427c4f526efb3f0c7e499b2dce0940eb3472452`.
- Final refreshed base: `d0c5008d5adafe20f6d646577a86d5332b7cee30`.
- Branch: `capture/rtl-profile-current1101`.
- General producer: `programs/flow109.py::resolve_task_manifest`.
- Existing consumers: `prepare_front_door`, the public runner's delivery
  admission, and the dispatcher's ordinary feature forwarding/argv bridge.
- Canonical data: `flow/flow109.json` reference profile, stable-ID owner map,
  and `task_nature_route` delivery/evidence contracts.
- Capture routing: `flow.task_features` in `benchmark/CAPTURE_ROUTING.json`.

The installed plugin, active evaluation, shared dirty checkout, versions and
remote branches were not changed. No hidden tests, reference RTL, previous
scores or live evaluation prompts/results were used. The fixture is a neutral
two-input conjunction request with RTL lint evidence.

## Defect and repair

Before editing, the existing actual public parser/admission/planner was invoked
with no optional manifest. The general entry returned
`DELIVERY_ROUTE_UNDECLARED: IC path or IP path?`; the thin dispatcher reached
`FLOW109_MANIFEST_REQUIRED`. Both returned rc 2 instead of reaching the RTL owner.
`control_substance_check` credited 2/2 failures as observed values.

The resolver copies the complete shipped profile; it does not fill missing
Booleans. It reuses the existing RTL source-delivery check and bounded owner
window check before publishing complete input bytes without replacing an
existing input. Explicit supplied manifests retain their bytes and normal
feature/conflict validation. Physical, unbounded, unsupported or unresolved
scope still receives normal BLOCKING admission refusal.

Independent review exposed a second-call edge: first invocation reached the
owner, while the second identical flagless invocation asked IC/IP again.
That observed value was captured as a separate RED (1/1 substantive). Reuse now
requires equality to the shipped profile and revalidates current sources and
the window. It creates the normal source-bound flow request each time;
there is no new state sidecar or reused execution/acceptance authority.

A second review control showed that a complete explicit manifest incorrectly
depended on the default profile being available and unique. Missing/duplicate
default profiles now return that existing input to its ordinary validation
path. Both observed wrong refusals were retained as value-bearing REDs;
no-input default selection still refuses an unavailable/nonunique profile.

## Executed evidence

Receipts are retained under
`/home/reyerchu/codex_tasks/out/rtl-profile-capture1101/`.

| Receipt | Observed scope/result |
| --- | --- |
| `red.xml`, `control-substance.log` | Original general/adapter refusal, 2/2 value-bearing failures |
| `latest-red.xml`, `latest-red-substance.log` | Exact final-base refusal using the same immutable test bytes as GREEN |
| `repeat-red.xml`, `repeat-red-substance.log` | Actual second-call refusal, 1/1 value-bearing failure |
| `explicit-red.xml`, `explicit-red-substance.log` | Explicit-input independence: 2/2 observed wrong refusals |
| `checked-controls.xml` | 19 positive, physical, unbounded, explicit feature/conflict and repeat controls PASS |
| `latest-base.xml`, `latest-candidate.xml`, `comparison.json` | Same 157 IDs: base 16 FAIL, candidate 9 FAIL, 7 improved, 0 introduced failures |
| `latest-selection-mutation.xml` | Disable production selection: both original refusal values return |
| `latest-repeat-mutation.xml` | Disable production reuse: second-call refusal returns |
| `latest-explicit-mutation.xml` | Remove explicit-input independence: both wrong refusals return |
| `latest-restored.xml` | Restore exact candidate producer: 8 original/repeat/revalidation/explicit controls PASS |
| `final-source-guard.json` | Full plugin source guard PASS |
| `final-entry-guard.json` | Shipped general-entry surface PASS |
| `final-doctrine.json` | Convergence doctrine present PASS |
| `capture-checks.xml` | Capture emitter/routing and skill compliance tests: 82 passed, 4 skipped |

The nine retained failures are six old native-exit expectations (expecting
native exit 4 while the base resolves 1/2) and three old image/delivery tests
expecting ERROR where the base refuses a missing manifest. Exact test names and
each arm's result are in `comparison.json`; no baseline, skip or threshold was
rewritten. The four capture-check skips are disclosed in their JUnit receipt.

The positive test reads the real shipped registry through `_hostpaths.require_repo`.
Its owner trap is after actual parsing, source/delivery admission, manifest
validation, planning and routing; no mocked Program PASS or author/EDA result
is produced. These checks do not measure RTL correctness, tool qualification,
official evaluation score or whole-flow acceptance. The full `run_tests.sh`
release suite is NOT_RUN.

## Publication handoff

The change remains uncommitted and versionless. CONTRIBUTING.md requires a
Signed-off-by trailer on every commit (`git commit -s`), source guard plus the
full `./run_tests.sh` before merge, the PR template and maintainer review.
External contributors do not push `main`; the repo-gatekeeper/maintainer owns
landing and version assignment. No `--no-verify` or force push to `main` is
permitted. The capture skill's non-maintainer path is a versionless PR; its
maintainer path retains gatekeeper review, version assignment and Step-2.7.

## Next

Proceed to independent exact-source review and contribution publication. Keep
the baseline failures and full-suite NOT_RUN visible to the maintainer.
