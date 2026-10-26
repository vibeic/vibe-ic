# General evidence scope and score admission capture

## Summary

**STATUS**: CAPTURE_COMPLETE. One merged deterministic recovery is reused and two engineering candidates are recorded. This document captures diagnosis and acceptance criteria; it claims no new implementation, official score, recovered case or convergence.

The general failure class is a mismatch between input contracts and consumers, compounded by an aggregate verdict that prevents independent evidence from being measured. Keep original input/context, reuse native producers and the existing repair API, and make each reported verdict state what it actually establishes.

## Evidence and limits

Published benchmark-data was inspected at commit `6aec3c2ceaff9cc54963215427e7711f15c03dc2`. Its historical Human scorer artifact, `evaluation/verilogeval_human/v1.10.45_gpt_5.6_sol/pass_at_1.json`, has SHA-256 `60d7b1dc2cdc9fd82ea2f7b4daffc51af411ce36d47a3c6becbac0f30eccaeb3`. The artifact contains 156 unique entries keyed by `problem`; its exact `Prob093_ece241_2014_q3` entry is `FAIL` with reason `functional_mismatch (Mismatches: 11 in 60)`. No durable input to this capture identifies the three other questioned tasks or a twelve-cell aggregation, so no such aggregate claim is made. This historical cell motivates diagnosis only; it is not candidate acceptance or source clarification.

The historical manifests explicitly omit generated samples, complete authoring transcripts and input snapshots. Dataset commit equality does not prove byte-identical rendered prompts. Consequently this capture cannot establish that current rendered-source contradictions existed unchanged in old runs, or reconstruct the old reasoning. A previous PASS proves compatibility with that harness; it cannot prove unique source semantics, full test coverage or structural conformance.

The following two reports were previously referenced as current local evidence, but independent review found neither file at its stated path and could not verify either advertised hash:

- `/mnt/ssd2/codex_tasks/out/verilogeval-human-20261026-v1.32.5-full/RESULT.md`, SHA-256 `526a89eeaf941d5ecbd50908f0276ba0452625918094f9f8b7d8f5e71f9628f8`.
- `/mnt/ssd2/codex_tasks/out/verilogeval-v2-20261026-v1.32.5-full/RESULT.md`, SHA-256 `e19dca3466894ef5af5df5d4a60bf8e93c3c598797981a6b778a6e102a675a53`.

They are therefore unavailable and not independently reviewable. No polarity, tally, score or acceptance is derived from them, and this capture measures no current official score. Existing gate evidence remains bound to its original producer and candidate hashes.

The original-input lint defect has a concrete merged implementation in [PR 3654](https://github.com/vibeic/vibe-ic/pull/3654), PR head `6421a53329d6328dd741b9531425fdd0a327827d`, merged at `d49e29e39dc75f3965f944d74c4b463419a46c56` as plugin version `1.32.14`. It removes the nonexistent generated-L9 dependency for original input and emits the existing consumer's row name. A root-accepted landing record (SHA-256 `2105050f3712e02236b667937a68ca3d7394ca1a25d1f9ffae67027cf9516e96`) records the accepted boundary as: recovered exact source, command, runtime and completed per-ID results were reused; missing historical shell exits are `NOT_RECORDED`. This capture reuses that landed identity and boundary without rerunning the valid controls, and makes no broader control-count, benchmark-score or whole-flow claim.

The structural repair gap already has [issue 3655](https://github.com/vibeic/vibe-ic/issues/3655), observed CLOSED during this capture. Closure alone does not prove the current local run has the corresponding code or that its frozen candidate passed normal repair admission. Follow the existing work rather than creating a duplicate implementation.

## Program-first disposition

`recoveries.json` records one Bucket A reuse and two Bucket C candidates. The new policy candidate is not mislabeled as a successful recovery. Its engineering work belongs in the existing dispatcher and reporting consumer, with the smallest necessary controls. No new global checker or benchmark-specific solver is proposed.

The emitter's routing table maps `phase2.lint` to `rtl_hygiene_lint.py` and produces a generic rule sketch. For this recovery the actual owning producer is `design_one_shot_runner.py`, as recorded in `actual_program`; the fix is already merged. The emitted sketch is an unimplemented capture artifact, not a second fix to apply or a passing verifier. Reuse the linked commit instead.

Source ambiguity requires a source-based decision. An omitted reset convention, simultaneous waveform changes or contradictory diagram cannot be resolved merely by remembering which implementation scored previously. Likewise a structure obligation cannot be waived because simulation agrees. Review any proposed distinction between measurement admission and product signoff before changing behavior.

## Neutral acceptance cases for implementation

1. Original-source lint: a valid combinational unit with no generated specification passes through the actual native producer; malformed RTL still fails. Generated-spec input still consumes its required specification. Missing native identity or ambiguous top remains an explicit refusal.
2. Timing interpretation: an explicitly sampled input and explicit output latency are accepted; a candidate one cycle early fails an immutable prompt-derived challenge. A table with unresolved simultaneous events retains its question and cannot acquire a guessed semantic PASS.
3. Reset interpretation: explicit active-low synchronous reset is checked as written; a candidate asynchronous reset fails an appropriate between-edge challenge. A bare reset port does not acquire a default polarity, destination or timing from historical results.
4. Source conflict: contradictory transitions remain recorded unless the current public source contains an applicable precedence or correction. Removing that precedence must restore the unresolved state. An unrelated historical PASS must not change either result.
5. Structural repair: equivalent arithmetic or boolean logic remains acceptable when implementation structure is unrestricted. When the source explicitly requires a component class, bind the native structural evidence and repair to that obligation, retain functional tests and reject stale hashes or an unauthorized mapping policy.
6. Aggregate behavior: exercise the actual score consumer with clean accepted, clarification-held, structurally rejected and genuinely invalid candidates. Prove the declared behavior in each case. If functional measurement of an unresolved candidate is allowed by the reviewed contract, its official score and unresolved review remain independently visible; strict signoff remains blocked. No forced semantic acceptance, denominator filtering or hidden skip is allowed.

Run substantive before/after controls and a real-consumer corpus sweep when implementing these candidates. Historical data diagnoses a flow gap but supplies no expected RTL or production decision branches. Verify tool and source provenance at normal entry; report unavailable coverage honestly.

## Generality and no-cheating boundary

All suggested production decisions derive from current public inputs, declared contracts and measured native evidence. No task IDs, dataset names, old solution bytes, hidden tests, oracle values or expected score appear in a proposed production rule. Evidence links and historical comparisons remain outside author/reviewer inputs for future blind runs. Fresh evaluations use isolated input-only actors; no higher score is promised from these proposals.

Reject a shortcut that converts clarification to PASS, rewrites a prompt to match an oracle, relaxes the official harness, filters the denominator, or treats historical success as repair authorization. Preserve the failure and parent evidence before legitimate repair.

## Validation and handoff

Validate this capture with the existing enhancement emitter, skill compliance checker, output completeness checker, JSON parsing and diff whitespace check. Those checks validate the capture artifact only. Behavioral controls above are acceptance requirements for future code changes, not executed results of this documentation change.

Next: proceed to maintainer review of the generated candidates; reuse the merged lint and existing structural work, then implement the reviewed evidence-scope contract with neutral consumer controls before any fresh benchmark claim.
