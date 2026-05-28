# SPM RTL Source Manifest

| File | Author | License | Source |
|---|---|---|---|
| spm.v | Vibe-IC Plugin spec-to-rtl fallback (AI-authored from L-docs) | Apache-2.0 | input/docs/L2,L3,L7,L8,L9 |
| chip_top.v | Vibe-IC Plugin spec-to-rtl fallback (AI-authored from L3/L9) | Apache-2.0 | input/docs/L3,L9 |

**Generation strategy**: 100% GENERATED. No open-source IP was pulled.
No upstream `spm.v` was read during Phase 1 or Phase 2. The implementation is
a textbook LSB-first bit-serial shift-and-add modulo-2^N multiplier,
authored solely from the L2 functional spec and L3 port list.

**Blindness attestation**: Per benchmark_clean/METHODOLOGY.md ABSOLUTE
BLINDNESS RULE. Upstream reference RTL may only be used at verify stage
as a golden oracle for equivalence cross-check, never as input.
