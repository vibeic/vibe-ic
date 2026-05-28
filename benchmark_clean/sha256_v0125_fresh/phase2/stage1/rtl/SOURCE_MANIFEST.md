# RTL Source Manifest — sha256

| File | Provenance | License |
|------|------------|---------|
| `sha256.v`              | GENERATED (AI-authored from `input/docs/L1..L9.md` + NIST FIPS-180-4 public standard) | Apache-2.0 |
| `sha256_core.v`         | GENERATED (AI-authored from `input/docs/L2/L7/L8.md` + NIST FIPS-180-4 §6.2)            | Apache-2.0 |
| `sha256_w_mem.v`        | GENERATED (AI-authored from NIST FIPS-180-4 §6.2.2 message schedule)                    | Apache-2.0 |
| `sha256_k_constants.v`  | GENERATED (AI-authored from NIST FIPS-180-4 §4.2.2 round constants table)               | Apache-2.0 |

All four RTL files are 100% GENERATED. No file copied from the upstream
secworks/sha256 implementation (per benchmark_clean BLINDNESS RULE — upstream RTL
may be used ONLY as a verify-stage golden oracle, not as a Phase-1/2 input).

NIST FIPS-180-4 is a public NIST standard; its definitions of H[] initial values,
K[] round constants, message schedule (W[t]), and round function (Ch / Maj / Σ0 /
Σ1 / σ0 / σ1) are reproduced here as plain spec implementation, not as code copy.
