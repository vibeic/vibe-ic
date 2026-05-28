# sha256 v0.1.25 — Close-Loop Timing-Fix + Cross-Check Result

**Project**: `/home/reyerchu/AI_IC_design/sha256_v0125_rerun`
**Updated**: 2026-05-28 (timing-fix re-run; supersedes the earlier draft)
**Mode**: BLIND for Phase 1/2/3. Upstream secworks RTL used ONLY as a
verify-stage oracle, AFTER timing closed.

## Overall verdict: PASS_WITH_WAIVERS — timing now MET at L9's 25.9 ns

| Metric | Before (fresh run) | After (this re-run) |
|--------|--------------------|---------------------|
| Clock period | 20.0 ns (runner fallback — wrong) | **25.9 ns** (L9 §9.1.1 authoritative) |
| Post-route setup WNS | **-102.76 ns (VIOLATED)** | **+10.95 ns (MET)** |
| Hold | — | No hold violations |
| Functional KAT (abc, empty) | broken (W-schedule bug, undetected) | **PASS** at RTL, register, and gate level |
| Cross-check vs upstream secworks | not run | **bit-exact PASS** |
| Cells (placed) | 9236 synth | 10324 placed (+ buffers/spares) |
| GDS | ~1.4 MB | 1.70 MB (538 x 538 um, 35% util, 90726 um^2) |

## FIPS-180-4 Known-Answer Tests

| Vector | Expected digest | Generated RTL | Post-PnR gate netlist | Upstream secworks oracle |
|--------|-----------------|---------------|-----------------------|--------------------------|
| `"abc"` | `ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad` | PASS | PASS | PASS |
| `""` (empty) | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` | PASS | PASS | PASS |

Latency 66 cycles/block (2 init + 64 rounds) — identical for generated RTL and
the upstream oracle.

## Root-cause correction vs the earlier draft

The earlier RESULT.md claimed the -102.76 ns WNS was "expected for a single-cycle
FIPS-180-4 round implementation". **That diagnosis was wrong on two counts:**

1. The generated RTL is already a **multi-cycle (66-cycle) iterative** core — one
   round per clock — not a single-cycle-whole-hash combinational monster. No
   re-architecture of the round datapath was needed.
2. The -102.76 ns was almost entirely **unbuffered high-fanout control nets**:
   the post-route critical path showed two consecutive zero-strength AOI gates
   with 19.97 ns and **97.52 ns** single-gate delays. Those are wire-RC, not
   logic depth — the FSM init/next/state decode drives the load-enable of
   hundreds of next-state flops, and `reset_n` fans out to 1059 sinks
   (`[WARNING GRT-0281]`). The OpenROAD pnr.tcl ran **no `set_wire_rc`, no
   `repair_design`, and no `repair_timing -setup`** — only `repair_timing -hold`.
   So nothing ever buffered those nets.

After adding `set_wire_rc` + `repair_design` + `repair_timing -setup` (pre-CTS
and post-global-route) the critical path becomes the genuine SHA-256 compression
modular-adder chain (`maj3`/`xnor3` carry logic, 15.61 ns) and slack is +10.95 ns
at 25.9 ns. The existing RTL closes timing as-is.

## Functional bug found & fixed (would have shipped broken silicon)

The fresh-run "full-stack TB 8/8 PASS" was a generic opcode/protocol bring-up
smoke test with `expected_bytes:"XX"` placeholders — it NEVER checked SHA-256
correctness. A real FIPS KAT exposed a message-schedule indexing bug in
`sha256_w_mem.v`. The W[t+16] recurrence used the wrong ring-buffer slots:

    new_w = sigma1(w_mem[1]) + w_mem[6] + sigma0(w_mem[14]) + w_mem[15]   // WRONG

Corrected to the forward-window form (FIPS-180-4 §6.2.2 step 1):

    new_w = sigma1(w_mem[14]) + w_mem[9] + sigma0(w_mem[1]) + w_mem[0]    // FIXED

With the fix, all KAT vectors pass at all three levels and match the upstream
oracle bit-for-bit. This is the only RTL change made.

## Plugin gaps (backlog candidates)

1. **SDC period regex required a trailing `ns`** — `_resolve_clock_spec` only
   matched `period ... <num> ns`. Real SDC `create_clock ... -period 25.9` lines
   (with `set_units -time ns` on a separate line) carry no trailing `ns`, so the
   docs-authoritative 25.9 fell through to the 20.0 fallback. Fixed by making
   `ns` optional and adding the `-period` token (v0.1.26).
2. **Phase-3 PnR ran no setup/DRV repair and no wire-RC model** — the pnr.tcl
   template only ran `repair_timing -hold`. High-fanout control/reset nets were
   left on zero-strength gates with no buffer tree (97 ns single-gate delay).
   Fixed by adding `set_wire_rc` + `repair_design` + `repair_timing -setup`
   (pre-CTS and post-global-route).
3. **Phase-3 prefers a stale phase2 silicon SDC over re-resolving the period** —
   `step_pnr` copies `phase2/stage2/constraints/chip_top.sdc` verbatim if present,
   so even after fixing the regex the period stayed 20.0 until that stale SDC was
   corrected to 25.9. The FPGA-side SDC (`phase2/stage1/fpga/chip_top.sdc`) DID
   correctly carry 25.907 ns from L9 — only the silicon-side copy was wrong.
4. **Full-stack TB does not validate datapath correctness** — placeholder
   `expected_bytes:"XX"` means a functionally broken hash core reports PASS. A
   class-aware KAT (FIPS vectors for hash/crypto IPs) is needed for genuine
   functional sign-off.

## Artifact paths

- Post-route STA: `phase3/stage3/sta/post_route_timing.rpt` (+10.95 ns MET @ 25.9 ns)
- Corrected silicon SDC: `phase2/stage2/constraints/chip_top.sdc`
- Post-PnR gate netlist: `phase3/stage3/pnr/chip_top_pnr.v`
- GDS / DEF: `phase3/stage3/pnr/chip_top.gds`, `chip_top.def`
- Fixed RTL: `phase2/stage1/rtl/sha256_w_mem.v`
- KAT TBs: `phase2/stage1/sim/tb_sha256_kat.v`, `.../tb_core_kat.v`,
  `cross_check/tb_oracle_core.v`
- Upstream oracle (verify-stage only): `cross_check/upstream_oracle/`
