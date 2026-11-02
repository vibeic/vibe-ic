# Batch review correction entry

## Summary

**STATUS**: IMPLEMENTED_PENDING_INDEPENDENT_REVIEW. Repeating the canonical `--review-correction REQUEST.json` flag now applies the existing per-request transitions in order under one coordinator lock, then invokes the unchanged normal resume consumer once. The Python API retains a single string and also accepts a nonempty list. An explicit empty list is refused.

Each transition retains its existing hash, source, ownership, archive, publication and acceptance checks. A later malformed or stale request stops before normal resume; earlier valid transitions remain unaccepted and await a fresh review. Repeating the batch reuses the existing immutable transition archives. Duplicate requests retain the existing idempotence contract. Program regate and correction operations remain mutually exclusive.

## Verification

The owning correction tests cover repeated CLI flags, both real correction transitions, one normal consumer invocation, the legacy single-string API, malformed and stale second requests, safe retry, duplicate requests, empty lists and mixed regate refusal. The original candidate, prompt, review and challenge evidence remains preserved. No verdict cache, new command, ledger writer, gate or alternate orchestration path is introduced.

The source packet retains exact predecessor/candidate identities, JUnit reports, substantive-control grading and bounded results. These component controls do not establish benchmark acceptance or full-suite qualification.

## Next

Proceed to independent review and use the canonical repeated flags after composing the accepted source into a new consumer epoch.
