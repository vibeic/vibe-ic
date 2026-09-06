# Consume measured RTL review producer contracts

`rtl_hygiene_lint` and `reset_discipline_check` emit arrays of findings.
`rtl_precheck_gate` emits an object whose `auditors` value is an array of
execution results. The review aggregator must consume these actual contracts;
the legacy findings envelopes and nested auditor mapping remain readable.

Valid findings retain their rule, severity, file, line and message. A failed
auditor remains an ERROR; an explicitly skipped auditor produces a named
NOT_MEASURED INFO record. Missing, malformed or empty auditor evidence is not
a clean execution. Empty hygiene/reset arrays remain valid clean results.

The existing score formula and CLI policy are unchanged: the report is
ADVISORY by default; `--strict` is BLOCKING for a non-PASS verdict. This change
does not turn the aggregate into a substitute for flow compliance or semantic
AI review, and does not change benchmark routing or scoring.

Verification exercises all three real producers, a checked-in example resolved
through `_hostpaths.require_repo`, malformed records, genuine failures, legacy
formats, and strict failure propagation. No benchmark answer is embedded.
