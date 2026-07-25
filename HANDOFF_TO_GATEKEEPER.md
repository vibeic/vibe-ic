# HANDOFF — ibex × sky130A convergence pass, 2026-07-25

Author: core-agent session on 8HD-7. **Nothing here was pushed.** Four local
commits on `fix/staged-sdc-drv-injection` in this worktree.

---

## 0. READ FIRST — three premises I was given are FALSE (disproved, with evidence)

The coordinator has already corrected its own memory on all three. They are
recorded here so the next reader does not re-inherit them.

**(a) "ibex needs an AI-authored `chip_top.sv`; the bare deterministic runner
cannot produce an ibex GDS."** — FALSE.
`/home/reyerchu/vibe-ic/benchmark-data/ic/ibex/clean_run_v1462_sky130a_20260720`
is, by its own `RESULT.md`, **Shape A — full runner, single front door
`vibe_ic_one_shot_runner.py`, "single detached runner (r1)"**. It produced a
**39,861,732-byte GDS** (three identical copies, sha256
`3d6363ccb273472701f7d419dad472e694c5f8eb54978754498fd412d310cbdd`). Its
`phase2/stage1/rtl/` contains **no `chip_top.sv` at all** — the top is
`ibex_core` directly, via `--top-name ibex_core`. So ibex does not need an
AI-authored chip-top, and whatever made the eight `converge_*` runs fail was
something else.

**(b) "Prior known residual: DT1 at-speed coverage 83% on a 6-fault sample."** —
NOT FOUND anywhere in the ibex artifacts. v1462's `reports/final_summary.md`
records DT1 status as `?`, and `phase2/stage2/dft/dft_atpg_not_run.json` says
`"no primary clock port derivable from RTL"`. A full-tree grep for an 83%
coverage figure under `benchmark-data/ic/ibex/` returns nothing. **DT1 has never
been measured for ibex.** That number belongs to some other cell; do not use it
as an ibex baseline.

**(c) "v1462 ran at utilization 0.25."** — That was the *requested* target. The
achieved utilization is in the raw OpenROAD log:
`[INFO DPL-0006] Core area: 376110.72 um^2, Instances area: 153983.93 um^2,
Utilization: 40.9%`.

---

## 1. The two commits

Worktree `/home/reyerchu/vibe-ic-wt-a857c45b-sdcdrv`, branch
`fix/staged-sdc-drv-injection`, `[ahead 4]` of `origin/main` (`0d2c63d34`) — the
two fix commits below plus two doc-only handoff commits.
**No version file touched** — see §4.

### `ab068229950e5cd64d81fb51fd84d5fc00882997`
*fix(phase3): give a design-supplied SDC the same DRV limits the auto-SDC gets*

`step_pnr` appends the PDK-liberty-derived `set_max_transition` /
`set_max_capacitance` via `_build_auto_silicon_sdc` — but only on the
else-branch, i.e. only when the project stages **no** `constraints/*.sdc`. A
design that ships its own SDC took the staged branch and reached PnR with **no
DRV target at all**, so `repair_design` had nothing to repair slews against. The
more complete the design's own inputs, the weaker the constraint set it was
implemented against.

Proven against unmodified v1.5.78:

```
STAGED-SDC branch -> has set_max_transition? False | has set_max_capacitance? False
AUTO-SDC   branch -> has set_max_transition? True  | has set_max_capacitance? True
```

`_ensure_staged_sdc_drv` supplies only *absent* limits, only from the active
liberty, never overrides a design-declared value, and writes its decision to
`pnr/sdc_drv_parity.json`. Gate-monotonic (OpenSTA takes the tightest of
SDC / liberty-pin / liberty-default, so it can only tighten). 13 tests in
`programs/tests/test_staged_sdc_drv_parity.py`.

**Scope honesty: this is NOT ibex's blocker.** ibex takes the *auto-SDC* branch
(its SDC lives at `input/constraints/`, not project-root `constraints/`), so
v1462's `pnr/constraint.sdc` already carried `set_max_transition 1.5` /
`set_max_capacitance 5.0`. This commit is a real hole for any design that ships
a root `constraints/*.sdc`; it does not move ibex.

### `9c0b57d37e00fe70341b82005117b50a28ef462f`
*fix(phase3): per-corner sign-off STA timed the PRE-PnR netlist and said nothing*

`_emit_multi_corner_sta`'s docstring said "against the routed netlist". The code
read `<synth>/<top>_synth.v` — the **pre-PnR synthesis netlist** — and read **no
SPEF**, and never varied the RC corner. Those reports land in
`phase3/stage3/sta/per_corner/sta_<CORNER>.rpt`, which is consumed as the
*evidence* that a multi-corner sign-off STA happened (`eda_report_audit` treats a
populated `per_corner/` as the multi-corner claim;
`sta_corner_record_completeness_check` reads the same tree). A pre-layout,
zero-parasitic number was standing in for post-route sign-off.

**Measured before/after**, both variants re-run against the SAME real archived
run (`clean_run_v1462_sky130a_20260720`, whose own artifacts contain the routed
netlist and per-RC-corner extractions):

| corner | OLD (synth netlist, no SPEF) | FIXED (routed + paired RC SPEF) |
|---|---|---|
| TT | wns −18.76  tns −25948.41 | wns −18.20  tns −30641.59 |
| **SS** (setup sign-off corner) | **wns −42.62**  tns −64509.91 | **wns −87.92**  tns −147738.12 |
| FF | wns −7.31  tns −7311.51 | wns −20.92  tns −34851.21 |

**The old report was optimistic by 45.30 ns of WNS at the setup sign-off
corner** (and 83,228 ns of TNS) — the direction that manufactures a false PASS.

**Cross-validation.** That run's own `sta_mcorner_ocv.rpt` times the true worst
corner (SS liberty + max-RC SPEF + 0.95/1.05 OCV derate) and recorded setup
`worst slack max -92.80`. The fixed SS number is **−87.92 un-derated — the same
corner, reproduced independently**, with the derate accounting for the gap.
**The old −42.62 reproduces nothing.**

`_multi_corner_sta_inputs` resolves the basis purely by file existence:
`POST_ROUTE_SPEF` → `POST_ROUTE_NO_SPEF` → `PRE_LAYOUT_ESTIMATE`, pairs each
liberty corner with its own RC corner (SS→max, FF→min, TT→nom) where extracted,
and stamps `STA_BASIS:` / `STA_BASIS_NOTE:` into every emitted report so a
pre-layout number can never be quoted as sign-off. 10 tests in
`programs/tests/test_multi_corner_sta_basis.py`.

---

## 2. CORRECTIONS TO MY OWN EARLIER REPORTING (verbatim, prominent)

- **The earlier "baseline 20 failed / fix 20 failed, identical sets modulo 2
  flakes" is an ARTIFACT and is NOT evidence.** Those runs used `--maxfail=20`
  and **truncated at different points in collection order**. The equal counts
  were the cap, not an equivalence. Do not cite them.
- **The honest baseline is the complete (no-`maxfail`) run:
  `origin/main` `0d2c63d34` → 55 failed, 18310 passed, 498 skipped, 2 xfailed
  (26 m 18 s).** Those 55 are pre-existing on this host: mostly `test_cvdp_gate*`
  and iverilog/yosys-harness tests. The host has `iverilog` and `tclsh` but
  **no `yosys` and no `verilator`**, which CI installs.
- **The "FINAL HEAD" suite line in my earlier batch tested `bebd0422b`**, which
  **predates the corner-pairing improvement**. Current HEAD is `9c0b57d37`.
- **RESOLVED — the complete run on `9c0b57d37` finished after all, and the diff
  is CLEAN.** (An earlier revision of this file said it was unfinished at 95%;
  it completed and two independently-launched waiters produced identical
  results.)

| complete suite (no `--maxfail`) | failed | passed | skipped | xfailed | time |
|---|---|---|---|---|---|
| baseline `origin/main` `0d2c63d34` | **55** | 18310 | 498 | 2 | 26:18 |
| fix HEAD `9c0b57d37` | **55** | **18333** | 498 | 2 | 26:54 |

```
=== ONLY IN FIX (would be regressions) ===     <- EMPTY
=== ONLY IN BASELINE ===                       <- EMPTY
```

**Zero regressions: the two failure sets are identical, all 55 pre-existing.**
The delta is `18333 - 18310 = +23 passing`, which is exactly the 23 tests these
commits add (13 `test_staged_sdc_drv_parity` + 10 `test_multi_corner_sta_basis`).

Re-derive at any time (pure CPU, no AI):

```bash
grep '^FAILED' /home/reyerchu/campaign_v1578/full_sdcbase.log | sed 's/ - .*//' | sort -u > /tmp/FB.txt
grep '^FAILED' /home/reyerchu/campaign_v1578/full_sdcdrv.log  | sed 's/ - .*//' | sort -u > /tmp/FF.txt
comm -13 /tmp/FB.txt /tmp/FF.txt   # ONLY IN FIX  -> candidate regressions
comm -23 /tmp/FB.txt /tmp/FF.txt   # ONLY IN BASELINE
```

This supersedes the two flake investigations below: neither
`test_orchestrator_hands_pnr_result_to_lvs` nor
`test_v0_3_41_issue588_runner_lock_all` appears in either complete failure set.

Targeted evidence that *is* complete: every test file matching
`sdc|sta|phase3|corner|pnr|lvs|timing|signoff` on baseline → **1 failed, 2512
passed**, the single failure being the pre-existing
`test_density_fill_raises_a_sparse_layer_to_target`. The matching run on HEAD was
killed deliberately at load 34.65 to stop starving the ibex arms.

### Two alarms I investigated — both resolved, neither is a regression

- `test_v0_3_41_issue590_lvs_upstream_gate.py::test_orchestrator_hands_pnr_result_to_lvs`
  appeared to fail on HEAD but not baseline. **Flake under load.** In isolation:
  `sdcbase` (`0d2c63d34`) **5 passed**, `sdcdrv` (`9c0b57d37`) **5 passed**.
- `test_v0_3_41_issue588_runner_lock_all.py::test_all_four_runners_call_acquire_or_reenter`
  fails **only because my own live ibex runners genuinely hold runner locks**.
  In isolation: **7 passed on both trees.**

Gates that did pass on HEAD: `source_chip_agnostic_check.py` PASS,
`agent_checkin_scope_guard.py --role core-agent` PASS, the 23 new tests green.

---

## 3. ibex sign-off, re-derived from RAW artifacts (v1462 — the only ibex GDS)

| item | result | raw evidence |
|---|---|---|
| GDS | 39,861,732 B, 3 identical copies | sha `3d6363ccb273472701f7d419…` |
| DRC | **0 violations (real)** | KLayout XML `<items></items>` empty; runset `sky130A.lydrc`; top-cell `ibex_core` |
| LVS device-level | **PASS** | `lvs.rpt:5078 Final result: Circuits match uniquely.` (`:4803` 28 symmetries) |
| LVS power-aware | **FAIL** | `:5878 Netlists do not match.` / `:6154 Top level cell failed pin matching.` |
| STA (governing gate) | setup **−45.05 ns**, tns −75201.64; hold +0.45 | `sta_spef_multicorner.rpt` (TT liberty + max-RC SPEF) — what `post_route_signoff_corner_check` reads |
| STA (true worst corner) | **−92.80 ns** pre-ECO / **−71.66 ns** post-ECO | `sta_mcorner_ocv.rpt` (SS + max-RC + derate) — gated by `sta_signoff_rigor_check` |
| DT1 | **never measured** | `dft_atpg_not_run.json` |

**Converged? No.** The blocker, with evidence: OpenROAD's own optimizer converges
to **WNS −3.857 ns** (`estimate_parasitics -global_routing`) while the shipped
SPEF sign-off is −19.60 / −45.05 / −92.80. **The optimizer never sees the timing
it will be graded on.** Supporting raw data: `_15653_/Y` slew **23.33 ns vs a
1.46 ns limit**, `_21312_/Y` cap 1.88 vs 0.33 pF, and
`[WARNING RSZ-0062] Unable to repair all setup violations` with 1707 endpoints
still violating.

Encouraging: **v1.5.78 now ingests `input/reference_flow/orfs_config.mk`**
(`CORE_UTILIZATION`, `PLACE_DENSITY_LB_ADDON`, `TNS_END_PERCENT`,
`CTS_CLUSTER_SIZE/DIAMETER`, `SWAP_ARITH_OPERATORS`, `REMOVE_ABC_BUFFERS`,
`ADDER_MAP_FILE`) — a gap that was open at v1.4.62. So the in-flight arms run the
design's own ORFS recipe and are genuinely new information, not a repeat.

---

## 4. INSTRUCTIONS TO THE LANDING GATEKEEPER

1. **Re-assign the version at YOUR land time.** I deliberately touched neither
   `plugins/vibe-ic/.claude-plugin/plugin.json` nor
   `.claude-plugin/marketplace.json` (`git diff --name-only origin/main..HEAD`
   confirms). A version collision already happened on 2026-07-25.
2. **Run a cross-cell sweep before landing `9c0b57d37`.** It changes the
   per-corner numbers on **every cell** whose routed netlist exists at
   canonicalize time, and they move in the **worse-but-honest** direction — on
   this cell the setup corner moved **45 ns**. I validated it on unit tests plus
   one real archived artifact only. `ab068229` needs no sweep (it is a no-op on
   any design that takes the auto-SDC branch).
3. Land order: `ab068229` first (independent, low blast radius), then
   `9c0b57d37` after the sweep.

---

## 5. PATHS

| what | where |
|---|---|
| worktree / branch | `/home/reyerchu/vibe-ic-wt-a857c45b-sdcdrv` · `fix/staged-sdc-drv-injection` |
| baseline worktree | `/home/reyerchu/vibe-ic-wt-a857c45b-sdcbase` (detached at `0d2c63d34`) |
| baseline suite log (complete) | `/home/reyerchu/campaign_v1578/full_sdcbase.log` |
| fix suite log (complete) | `/home/reyerchu/campaign_v1578/full_sdcdrv.log` |
| arm A — stock v1.5.78 (control) | `/home/reyerchu/campaign_v1578/ibex/converge_1.5.78_sky130A_armA_stock` |
| arm B — v1.5.78 + DRV fix | `/home/reyerchu/campaign_v1578/ibex/converge_1.5.78_sky130A_armB_sdcdrv` |
| harvest the arms | `bash /home/reyerchu/campaign_v1578/harvest.sh` |
| raw sign-off re-derivation | `bash /home/reyerchu/campaign_v1578/rederive_signoff.sh <run_dir>` |
| fix-2 real-data measurement | `/home/reyerchu/campaign_v1578/fix2_realdata/` |
| patched plugin overlay (arm B) | `/home/reyerchu/campaign_v1578/plugin_1.5.78_sdcdrv` |
| reference archived run | `/home/reyerchu/vibe-ic/benchmark-data/ic/ibex/clean_run_v1462_sky130a_20260720` |

Both arms are `setsid`-detached and survive this session. Containers
`bench_ibex_v1578_A` / `_B` (image `ghcr.io/vibeic/vibeic-eda:0.2.29`, local
only — **never `docker pull`**, it is not published). At stop time both were
alive with LEC at ~51 min of its fixed 7195 s budget
(`lec_run.py:DEFAULT_YOSYS_TIMEOUT_S`); phase3 follows, so ETA to GDS was
~2.5 h. `harvest.sh` refuses to collect while a runner is still alive.

---

## 6. UNFIXED FINDINGS FOR A SUCCESSOR

1. **Power-aware LVS VPWR/VGND port-order mismatch.** The *only* difference is
   that the two netlists list `VGND`/`VPWR` in opposite order; netgen itself then
   prints `Device classes ibex_core and ibex_core are equivalent`. Looks
   chip-agnostic and cheap. **I deliberately left it pending re-confirmation on
   v1.5.78** — v1462 is v1.4.62, ~100 versions back, and it may already be
   fixed. Do not fix what may already be fixed; check the in-flight arms first.
2. **`_build_auto_silicon_sdc` emits `set_input_delay … [all_inputs]`**, which
   includes the clock port, so OpenSTA rejects it with
   `Warning 441: set_input_delay relative to a clock defined on the same
   port/pin not allowed`. The design's own SDC correctly uses
   `[all_inputs -no_clocks]`. Low impact (OpenSTA already ignores it); I kept it
   out to keep this handoff single-purpose.
3. **Weak sign-off DRC provenance.** The `provenance.jsonl` entry for the KLayout
   sign-off DRC records `duration_ms: 0` and **no input GDS path or hash**, so
   the binding between the 39.8 MB GDS and the clean DRC report rests only on the
   top-cell name and directory layout. That weakens the audit chain.
4. **`pnr.tcl` uses `set_wire_rc -signal -layer met1` while its own comment says
   "Set signal nets to a mid metal layer".** met1 is the lowest, most resistive
   routing layer. Doc/code disagreement at minimum; worth checking whether the
   estimated-vs-extracted divergence in §3 traces here.
5. Note for whoever measures DT1: a `pdk_detected: generic_unmapped` /
   `faults_total: 0` reading in `phase2/stage2/dft/` is the **transient phase-2
   state** (the cut netlist still carries yosys `$_NOR_`/`$_NAND_` cells), not a
   result. The real DT re-grade fires at the END of phase3 on the tech-mapped
   netlist.

## 7. ENVIRONMENT CAVEAT

8HD-7 was **not idle**. Other agents' runs (plugin 1.5.74, spm cells) were
active throughout; load reached 34.65. Suite wall-times and any flake in
`full_sdcdrv.log` should be read with that in mind.
