# sha256 — clean-room re-run on the captured stack (image 0.2.23 / plugin v1.4.61)

**Headline** — CONVERGENCE RE-RUN. Measured on `vibeic-eda:0.2.23` (klayout `tl::Thread`
use-after-free root-cause fix) + the clean plugin v1.4.61 (the honesty-gate captures)
+ the config-driven commercial PDK. Shape A (full runner), Phase-1 single entry,
clean-room. Results-only; NDA-excluded (commercial-PDK views referred to generically).

## Why this run exists
The first sha256 canary (0.2.22) FAILed phase3 on an intermittent `svrfdrc` heap
crash and its Pillar-1 was satisfiable at 0% functional coverage. Both were captured
as root-cause fixes; this run confirms they auto-recover.

## Convergence checks (the load-bearing questions)
1. **svrfdrc heap crash recurred? NO.** The SVRF sign-off DRC ran to completion on the
   first invocation and produced its report: **224 layers, 15911 derivations, 4533
   rules, 4532 PASS / 1 FAIL**. Zero `rc=139` / `malloc` / `tcache` / `unaligned`
   anywhere in the run. The runner's defense-in-depth retry never fired. (Root cause was
   a `tl::Thread::wait()` that returned without `pthread_join`; TSan 6 races→0, fixed in
   0.2.23.)
2. **Commercial PDK actually used (no silent OSS fallback)? YES.** The
   `commercial_pdk_fallback_guard` held — phase3 resolved to the staged commercial-PDK
   views (a foundry Calibre DRC deck + tech/macro LEF), not a sky130 fallback. The first
   run's silent-wrong-PDK failure mode did not occur.
3. **Functional pillar honest? YES.** `sim_full_stack` reports `functional_verified:
   false, scored_with_golden: 0` and Pillar-1 is a visible FUNCTIONAL_COVERAGE_GAP — it
   no longer silently PASSes a vacuous TB. (sha256 is a memory-mapped register-file
   design; the full-stack TB generator's register-map driver is a named follow-on, so
   the gap is surfaced honestly rather than papered over.)

## Verdict
- Phase 1 PASS · Phase 2 PASS_WITH_WAIVERS · Phase 3 synth/PnR/GDS complete on the
  commercial PDK; DRC sign-off 4532/4533 with the single FAIL a metal density-fill rule
  (test-chip sparsity → foundry fill or a formal density waiver; 0 real geometry).
- The runner's aggregate phase3 string is FAIL because it correctly refuses to
  auto-waive a real DRC rule AND because the functional-coverage gap is now honestly
  non-PASS — both are the honest direction, not a regression. The captured defects
  (crash, silent PDK fallback, vacuous pass) are all GONE.

## Tool substitution
Commercial EDA substituted per the open-source stack: Synopsys VCS → Icarus/Verilator,
Design Compiler → yosys+OpenROAD, sign-off DRC → the vibeic KLayout native SVRF engine
(`svrfdrc`) reading a foundry Calibre deck. Not silicon; open-source sign-off.

## Reproduce
`vibe_ic_one_shot_runner.py <project> --pdk auto` inside a `vibeic-eda:0.2.23` container
with the commercial PDK staged at `<project>/input/pdk/` and
`~/.config/vibeic/commercial_pdk.json` set. Clean-room: fresh run dir, prompt/docs only.
