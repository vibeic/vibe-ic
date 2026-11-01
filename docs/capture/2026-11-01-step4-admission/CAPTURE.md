# Accepted signed functional evidence in canonical Phase 2 admission

## Result

The native receipt schema key is `step_id="4"`; its public display is Step7 Simulation in the pinned 70-row YAML. References below to signed functional evidence mean that native receipt contract. Native schema keys in source and tests remain unchanged.

**STATUS**: Source-only repair ready for independent review; versionless contributor candidate, uncommitted at author handoff. The actual canonical admission consumer now grants one new admission for a current accepted digest of signed functional evidence. Repeating that evidence remains `DUPLICATE_NO_NEW_EVIDENCE`. This is an admission result, not functional, native, whole-flow or benchmark PASS.

Initial source: `b0f565e677f154700abbc53054a98a0599e63244`. Intermediate refreshed base: `8c35f9f6688682d601ee792ccd50c91519614baa`. Final exact refreshed base and candidate HEAD: `9702b8d66d8e3806b1257f532aab36d5828c64fa`; branch `capture/step4-admission-evidence1101`. At author handoff, candidate changes are an uncommitted patch over that HEAD. The refreshed main changes were disjoint to the admission seam. Checkout: `/home/reyerchu/codex_tasks/work/step4-admission-capture1101`. External evidence packet: `/home/reyerchu/codex_tasks/out/step4-admission-capture1101`.

## Reproduction and producer repair

The neutral ordinary project declares a one-bit combinational buffer, a plain design input, minimal L1 document and a persistent expert reference hook. It uses the existing test receipt signer and the real `ai_signed_judgement.check` and `canonical_run_admission.admit` consumers. The fixture report declares source-only scope and makes no functional PASS claim. The program identity hashes the actual in-repo design runner. The fixed image value is a synthetic identity input, not a claim that an EDA image ran.

Before editing, a canonical signed functional PASS receipt was accepted by `check()` but admission refused the same source/program/image/config with `DUPLICATE_NO_NEW_EVIDENCE`. The immutable `red.xml` records two wrong-value failures; `red-substance.log` classifies both as observed values. The earlier matched-current focused run uses the exact same 31 test IDs: base 3 FAIL / 28 PASS; candidate 31 PASS. The final whole owning-module run at the final exact main uses identical 71 test IDs, with only the candidate tests overlaid onto exact base source: base 3 FAIL / 68 PASS; candidate 71 PASS; no new failures. The existing signed-judgement module adds 22 PASS. Final receipts are under `current/`; earlier receipts remain retained at their original source identities.

The producer addition follows the existing native Step1/reset-role binding seam in `build_identity`. It requires the machine `_requested` predicate, an actual nonsymlink regular canonical signed functional receipt with current schema/step/PASS/digest, the existing canonical PASS check, and the current evidence helper. The canonical check requires produced expert output. A stable receipt snapshot is checked before binding only `evidence_sha256`. It does not derive authority from English success text.

The no-request success case (`check()` returning True without a conditional handoff) cannot bind. Neither malformed/absent/stale/FAIL/wrong-step/wrong-schema/unsigned/empty-judgement/symlink receipts nor a requested hook with absent output purchase admission. Raw reviewer/signer/judgement/comment/timestamp changes do not change identity. Step1, reset-role Step3 and Phase3 behavior are preserved.

## Separately bounded consumer repair

A real control exposed another wrong value after the initial producer repair: starting with valid accepted signed functional evidence, then removing it or making it FAIL/stale, created a new identity and incorrectly returned ADMITTED. `imported-review-control.json` and immutable `loss-red.xml` retain that source-only counterexample; all three failures observe returned values.

The approved consumer delta is inside the existing comparison with validated ledger entries. When the current Phase 2 identity lacks the signed functional binding and a prior identity contains it, the comparison removes only that prior signed functional binding and its empty parent if necessary. It refuses only when every remaining identity field matches exactly. It never rewrites an old record. All three loss cases assert byte-identical ledger contents after refusal. Genuine source/program/image/config changes, other consumer bindings and fresh accepted signed functional digests keep their existing meaning; four named-input controls and a new-digest control exercise those boundaries. No Step1/Step3 loss policy is added.

## Canonical evidence scope

The existing signed functional evidence definition is unchanged: persistent expert hook source, generated professional report and Phase1 L documents. Unsigned report churn or a stale receipt does not purchase admission. Under this existing contract, a fresh accepted PASS signature over a different canonical digest is new evidence and grants one admission. The repair does not introduce semantic report normalization or change receipt acceptance.

## Verification

The focused selected expression is `step4 or current_verified_step1 or invalid_step1 or step1_binding or current_reset_judgement or generated_professional_outputs_do_not_reopen or same_identity` in the existing admission test module. `comparison.json` preserves both whole-module and focused exact node-ID and failure-ID sets. The whole admission and signed-judgement modules are also run without selection at final HEAD; no full-suite expansion is claimed.

| Arm | Observed result |
|---|---|
| Initial pre-edit RED | 2 wrong-value failures |
| Producer-only signature-loss RED | 3 wrong-value failures |
| Intermediate focused base / candidate | 3 FAIL / 28 PASS; 31 PASS |
| Final exact base, whole admission module | 3 FAIL / 68 PASS |
| Final candidate, whole admission module | 71 PASS |
| Final existing signed-judgement module | 22 PASS |
| Remove signed functional binding from production source | 3 wrong-value failures |
| Remove signed functional loss comparison from production source | 3 wrong-value failures |
| Add raw receipt bytes to production identity | 1 wrong-value failure |
| Remove machine request checks from production binding | 1 wrong-value failure |
| Restore exact candidate production source | 31 PASS |

Each reverse uses the same applicable test IDs and actual admission consumer; `control_substance_check` grades every reported reverse failure as observed-value evidence. `run_controls.py` and `mutation-identities.json` preserve commands, exact source/test hashes, HEADs, return codes and restoration. The reverse checkout is restored to the candidate source. The six capture-routing tests pass. Source guard, entry-surface guard, doctrine check, enhancement emitter, skill compliance and patch whitespace checks are recorded in the packet. No new checker, global gate, threshold, skip or ledger-edit mechanism is introduced.

## Capture and publication scope

Bucket A AUGMENT targets the existing canonical admission producer and consumer. Routing is beside the existing canonical-admission domain; no new flow row is added. This is a general source-only capture and does not use campaign/task data, benchmark candidates, hidden tests, old scores or memory. Installed caches and ongoing version88 measurement/refusals remain unchanged. Earlier capture checkouts and packets remain frozen. Full-suite, native simulation and canonical campaign verification are NOT_RUN in this bounded packet.

`CONTRIBUTING.md` says external contributors “do not push to main themselves”, requires source guard plus `run_tests.sh` before mergeability, says “No skipping pre-commit hooks”, and directs PR authors to “Wait for at least one maintainer review.” Root delegated this subtask as an uncommitted source packet; root publishes a versionless contributor PR after review. Publication and any required broader merge checks belong to the root/maintainer after independent review.

## Next

Proceed to independent review of the exact patch and receipts. The root/maintainer owns publication; this packet does not assert merge readiness or whole-flow acceptance.
