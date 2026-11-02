# Retained benchmark handoff recovery

## Summary

**STATUS**: IMPLEMENTED_PENDING_INDEPENDENT_REVIEW. This capture repairs completed-worker retention and reconstructs unaccepted handoffs. It changes no RTL, gate verdict, scorer or acceptance threshold.

The parallel coordinator drains successful in-flight results through the existing checkpoint callback after cancellation and shutdown. Each callback is attempted once; the original interruption remains the exception raised, with a secondary failure retained as its cause.

Ordinary resume may recover a task only from the unique current Phase-2 report owner. It validates the original invocation, issuer and retained producer source, current material, issued route and original native admission interval. A later duplicate refusal stays a separate observation. Changed or missing inputs, reports, hashes, configuration, ambiguous owners and published responses remain blocked. Recovery never materializes a missing Flow109 manifest and never reruns a native producer.

The normal collector and existing task builders determine the resulting handoff. An original authoring waiver remains AI_BACKUP_PENDING; a gated candidate still requires independent AI review and the ordinary acceptance checks. No recovered benchmark PASS is claimed.

## Verification

The owning tests extend test_issue1970_benchmark_dispatch_parallel.py and test_stored_runner_issued_consumer.py. Controls observe real returned worker values and run the ordinary resume consumer around a neutral native waiver/duplicate fixture. Source and material mutations, route changes, ambiguous ownership, configuration changes, publication, admission timing and absent manifest inputs remain refused. Exact predecessor/candidate JUnit reports and remaining failure IDs are retained in the bounded source packet; no whole-suite qualification is claimed.

Two independent review findings were repaired before handoff: a later image admission cannot be attributed to an original invocation, and recovery cannot recreate a missing manifest before checking the measured input population.

## Next

Proceed to independent source review, compose a new consumer epoch, and use ordinary resume. Preserve prior producer receipts and frozen runtime inputs.
