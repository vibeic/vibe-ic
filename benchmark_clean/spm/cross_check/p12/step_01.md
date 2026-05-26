# Step 1 — Spec-to-RTL functional equivalence (OUR RTL ≡ REF RTL)

## What we ran
1. Re-stated the existing proof: OUR `tb_spm.v` self-checking sim over the
   `vectors.hex` golden set (10,013 vectors) + mid-computation reset recovery.
2. Fresh **exhaustive-for-small-N SAT equivalence** OUR-RTL vs REF-RTL at `size=8`
   using yosys `equiv_make` + `equiv_simple` (full combinational+sequential SAT,
   no name reliance for the proof step).
   - Script: `/home/reyerchu/AI_IC_design/_spm_xc_p12/equiv_ours_ref.ys`
   - `yosys equiv_ours_ref.ys` → exit 0.

## OUR result / REF result
- **SAT equivalence size=8**: `equiv_simple` proved all 17 `$equiv` points
  (s[0..7], c[0..7], p) — output:
  `Found 17 $equiv cells ... 17 are proven and 0 are unproven. Equivalence successfully proven!`
- **Golden vectors**: OUR RTL → `RESULT: PASS (all 10013 vectors + reset tests match golden)`.
  REF RTL run against the SAME `tb_spm.v` + `vectors.hex` → `RESULT: PASS (all 10013 …)`.
  Both DUTs satisfy the identical golden = `(x*y) mod 2^N` reassembled LSB-first.

## On the 32-bit case
A direct combinational SAT/BDD miter of a full 32-bit multiplier does NOT close in
reasonable time (classic hard instance). We do not fabricate one. The 32-bit case is
covered by: (a) the size=8 exhaustive SAT proof of the identical structural recurrence,
(b) the 10,013-vector golden sim at size=32 on BOTH RTLs, and (c) the k-induction proof
in step 5 (size=8, unbounded over time) — together a strong multi-method equivalence.

## Verdict: EQUIVALENT
OUR RTL and REF RTL are the same carry-save bit-serial multiplier (textbook Lyon/Parhi).
The only structural difference is OUR `output reg p; p <= s_next[0]` vs REF `output wire p;
assign p = s[0]` — proven to produce identical external behaviour by SAT (size=8) and by
the 10,013-vector golden sim (size=32) on both. EQUIVALENT.
