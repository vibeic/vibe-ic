# Runtime companion integrity

Retained execution now includes companion files declared by the exact gate owner. This fixes standalone gate-contract checks whose required backing files live under an otherwise excluded test directory. Unrelated test corpora remain excluded; declared dependencies participate in the bundle digest and are verified before launch.

Historical measurement readers use a separate read-only capability. An unchanged old producer can be verified under its own manifested source contract even when it predates the companion API. The reader cannot launch a child. Current execution still requires complete declared assets; changing source, manifests, paths or dependencies remains an error.

The packaging and historical-reader changes must ship together. Applying only the packaging half caused an observed continuation regression. The combined local implementation restored the previously accepted population through the ordinary consumer, without modifying its acceptance ledger. That observation is component evidence, not an official benchmark score.

## Validation on the publication base

Base: `95a3be2b31bb3fe17c0e5bdbf3f654be020ee078` (plugin 1.35.51).

`python3 -m pytest -q programs/tests/test_runtime_program_tree.py` reports **32 passed, 1 failed**. The sole failing identity is `test_phase_dispatch_seams_verify_retained_children`, an unchanged source-substring assertion. A separate exact-base invocation of that test reproduces the same assertion failure. No full-suite PASS is claimed.

The tests exercise the standalone retained gate, dependency changes/removal, incomplete reused bundles, old-producer historical reads, strict launch refusal, and manifest/path/source tampering. A companion-only update changes bundle identity while the fixture executable source bytes remain unchanged. This publication test deliberately uses the public source surface instead of an unpublished local identity helper.

A broader attempt using an incomplete extracted baseline fixture was invalid because dependencies were missing; it is not counted as baseline product evidence. The source-chip-agnostic gate passed: 2,089 source files scanned and 9,085 tree-wide files inspected by its NDA panel. Its reported limits still apply; this is not a verdict on the stricter declarations in other files. Full `run_tests.sh` and final gatekeeper integration remain pending.

## Capture

`recoveries.json` records two augmentations of existing programs. `runtime.retained_integrity` routes both to the actual runtime owner and names the gate/dispatcher boundaries. No benchmark identifiers, design solutions, private run paths, or conversation transcripts are included. No EDA engine change or image release is claimed.
