# Step 5 — Formal (bounded SVA / round-invariants on OURS) vs REF formal

**Verdict: EQUIVALENT** (OURS k-induction PROVED; REF formal is a placeholder — OURS stronger)

## What ran
SymbiYosys (`eda_formal`, engine smtbmc/yices, depth 40, **mode prove**) on
OUR `sha256_core` with 3 bound-checkable round-invariant safety properties
(`assert_only.sv`, bound via SystemVerilog `bind`):
- P1: round counter ≤ 64 (no overflow of the 7-bit `round`)
- P2: FSM `state` ∈ {IDLE,ROUNDS,DONE} (≤ 2 — no illegal state)
- P3: `ready` ⟹ `state == IDLE` (ready/idle consistency)

## Result
- OURS: **PASS — "successful proof by k-induction"** (basecase pass + induction
  pass). These are full unbounded proofs, not just BMC to depth 40.

## Honest scope statement
The **full 256-bit SHA-256 hash function is NOT SAT/BDD-closable** as a formal
property (the round function's modular-add + rotate network explodes the solver).
That functional correctness is covered by **NIST KAT + co-sim** (steps 1 & 4),
which is the industry-accepted method for crypto cores. Formal here proves the
*control-FSM safety envelope*, which IS decidable and was proven.

## REF formal comparison
REF's `phase2/stage1/formal/` contains:
- `constraints.sby`: an **auto-generated placeholder** (`prep -top assertions_l3`,
  "Auto-generated formal task placeholder").
- `results.json`: a generic full-stack-TB pass record (opcodes 0x70–0x78 with
  `expected_bytes:"XX"` / `actual_bytes:"XX"` placeholders) from the aid-class
  harness — NOT a real SHA functional proof.

So OUR formal step is genuinely **stronger** than REF's: we ran a real
k-induction proof of concrete RTL invariants; REF only has a placeholder + a
protocol-harness TB record.
