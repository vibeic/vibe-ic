# Formal proof report — formal_spm

verdict: **PASS**  (all_proved=True, 2/2 tasks PASS)

| task | mode | engine | depth | status | strength | cex frame |
|------|------|--------|-------|--------|----------|-----------|
| bmc | bmc | abc bmc3 | 12 | PASS | bounded |  |
| safety | prove | abc pdr | 20 | PASS | unbounded |  |

proof strength: **unbounded** (unbounded_proved=True)

## Bounded vs unbounded disclosure
- property PROVED UNBOUNDED (mode prove — holds for all reachable states): safety
- functional property proved BOUNDED via BMC to depth 12 (no counterexample within the bound; a full unbounded proof of a wide datapath may be solver-hard — this is a disclosed bounded result, not a full proof)

## Engine availability (honest)
- present: _env_reachable, abc
- absent : amulet, amulet2, avy, bitwuzla, boolector, btormc, pono, yices-smt2, z3

Evidence transcript: `phase2/stage1/formal/formal_spm_formal.sby.log`
SymbiYosys task file: `phase2/stage1/formal/formal_spm_formal.sby`
