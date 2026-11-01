# Explicit mux constraints at the K-map producer

## Result

**STATUS**: Versionless contributor candidate, uncommitted at author handoff. A supported explicit mux-only/no-other-gates restriction now causes the existing external-mux K-map producer to decline its unsupported SOP implementation. Both the direct producer and public registry return their ordinary backup result. Unconstrained and explicitly allowed SOP output remains byte-identical.

Exact base/HEAD: `9702b8d66d8e3806b1257f532aab36d5828c64fa`; branch `capture/kmap-mux-constraint1102`; checkout `/home/reyerchu/codex_tasks/work/kmap-mux-constraint-capture1102`. Product source SHA256: `34c4294058c61386c7398f6c3360c619403cad3b33a2f16b085321cab71f0442`. External packet: `/home/reyerchu/codex_tasks/out/kmap-mux-constraint-capture1102`. Root independently confirmed current main still matched this base before final packaging. The packet binds the exact base plus reviewable patch; no version change is included.

## Failed behavior and owning seam

A neutral prompt supplies a complete four-column K-map, declares the external selectors, and supplies a multiline public module header containing only the two remaining input variables and a four-bit output. Adding “Use only multiplexers; no other logic gates are allowed.” leaves the truth table unchanged but forbids the producer's implementation. Before any product edit, actual `kmap_grid_synth.synth` and `spec_artifact_registry.generate` returned RTL with `~`, `&` and `|` and artifact type `karnaugh_map`. `pre-edit-reproduction.json` retains those actual wrong returned values and source identity. No hidden source, test, scorer or oracle is involved.

The existing `_synth_mux_decomp` generator already validates the grid, input/selector axes, output width and selector membership. Its emission is always sum-of-products. The repair adds one local applicability refusal after those checks and before emission; it leaves the existing SOP terms, index mapping, declarations and ordinary single-output branch unchanged. `None` and the registry's `(None, None)` are the existing backup return contract. This capture proves that contract; it does not claim that an AI backup was executed or produced accepted RTL.

## Bounded clause grammar

Recognized positive directives include use/only-use multiplexers, implement/build using only multiplexers, and only multiplexers may/can be used, with supported numeric mux ratios. These require a complete clause rather than matching the mux prefix of a longer permitted primitive list. Recognized no-other-gates prohibitions require a complete clause or an `and` continuation, preserving a separate selector-order obligation. Normal single line wrapping is whitespace, not a fresh directive boundary. This is bounded prompt applicability, not a general natural-language constraint framework.

Missing restrictions and ordinary mentions of an external mux continue to emit the old SOP. Explicit permission for gates, allowed primitive lists, exception-qualified permissions and negated restrictions also preserve those bytes. Separate contradictory strict and permissive clauses decline instead of selecting one. Existing malformed axis, don't-care and width refusals remain. Cases outside the supported clause grammar keep existing behavior; no claim is made to resolve every natural-language implementation restriction.

## Review counterexamples retained

Independent review found an initial prefix match wrongly declining an allowed mux-plus-gates list and a negation wrapped across a line. Before repairing those cases, the actual producer and registry produced four wrong returned values; immutable `review-red.xml`, `reviewed-before-clause-fix.py`, test snapshot and identity preserve them. A second review found the same prefix problem in only-mux-may-be-used and both gate-prohibition branches with allowed-set exception tails. Its three neutral wordings, producer/registry paths and wrapped/unwrapped forms produced twelve actual wrong-value failures, preserved in `exception-review-red.xml` and corresponding snapshots/identity. The final grammar applies clause completion consistently to all alternatives. Both original strict forms and the no-other-gates clause followed by a selector obligation remain covered.

## Verification

Initial pre-edit RED: 17 actual wrong-value failures / 22 PASS. Final matched base and candidate use the same 57 IDs from the whole existing `test_kmap_grid_synth.py` module. Base: 19 FAIL / 38 PASS; candidate: 57 PASS; no new failures or skips. `comparison.json` preserves exact node and failure ID sets. All 19 final baseline failures observe forbidden returned logic through a real producer/registry path, rather than a missing API.

| Current control | Expected and observed result |
|---|---|
| Restore exact predecessor producer | 19 wrong-value FAIL / 38 PASS |
| Restore first guard before clause repairs | 16 wrong-value FAIL / 41 PASS |
| Restore guard before exception-tail repair | 12 wrong-value FAIL / 45 PASS |
| Replace bounded guard with blanket mux-word refusal | 25 selected preservation controls FAIL on returned values |
| Restore exact final producer | 57 PASS |

The named production mutations run in a separate isolated checkout; the author checkout is never mutated for a control. Commands, source/test hashes and return codes are retained. The reverse checkout is restored to exact final product source. Earlier broad-word diagnostic receipts are also retained; their preexisting presence-only assertions are not credited as substantive evidence. The current broad control selects the 25 actual value-observing preservation cases, all included in the matched full-module population.

The existing registry test module adds 34 PASS using host immutable Icarus at `/nix/store/49sr1m6qw81ja2hzlva163qlvj5vqmnq-iverilog-12.0/bin`. An earlier unconfigured supplemental run retained four explicit NOT_RUN skips; the pinned-tool run completes those tests. This supplemental verification is source/host-software scoped. The six routing tests, source guard, general entry-surface guard, convergence doctrine, capture emitter, skill compliance and patch whitespace checks are recorded in the packet. Full suite, benchmark/campaign acceptance, actual AI backup and whole-flow native verification remain NOT_RUN.

## Capture and authority

Bucket A AUGMENT owns `programs/kmap_grid_synth.py`; the existing registry remains its consumer. The metadata-only subtype `phase2.rtl_gen.kmap_mux_constraint` names that exact owner and related registry, beside the existing RTL-generation domain. It adds no flow row, gate or acceptance authority. The implementation adds no generator, checker, waiver, skip, threshold or benchmark-specific branch.

This source task does not read benchmark/campaign prompts, candidates, oracle/scorer or private sources. Installed caches, ongoing measurements, dirty shared checkout and earlier frozen capture packets remain unchanged. No memory files were read. Applicable repository guidance requires the source guard and full `run_tests.sh` before mergeability, maintainer review, and no skipped hooks. Root delegated this subtask as an uncommitted source packet; root publishes a versionless contributor PR after independent review and owns broader publication checks. This packet does not claim full-suite merge readiness or benchmark PASS.

## Next

Proceed to independent review of the exact patch, mutation receipts and applicability scope, then root-owned versionless contributor publication.
