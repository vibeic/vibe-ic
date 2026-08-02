# RESULT — caravel_user_project × sky130A (Round 15, `_c_car15_run`)

## 1. Headline — the convergence answer, best-evidenced line

**YES — `caravel_user_project × sky130A` now CONVERGES**, end to end, on the current
`origin/main` plugin, measured on this run (not inherited from r14). Both of this
cell's blockers are on main, I confirmed both operative on this design, and the
full flow reaches a clean **PASS_WITH_WAIVERS** with **zero FAIL and zero MISSING**.

The single most consequential line, from the tool's own **independent 44-step gate**
`flow_compliance_check.py --strict` (exit code **0**):

```
Steps: 63 total (35/39 executed PASS, 3 DEFERRED via waiver, 4 VACUOUS-PASS excluded)
  PASS=35  FAIL=0  MISSING=0  WAIVED-DEFERRED=3  SKIPPED=21  VACUOUS-PASS=4
Overall: PASS_WITH_WAIVERS  (strict=True)
```

r14's **sole** remaining phase-3 failure — **Step 11 DFT insertion** — is now
`✓ [PASS] Step 11: DFT insertion (scan chain + ATPG + at-speed + BSDL)`.
The **failure NAME-SET is now EMPTY**. Trajectory of the name-set across the campaign:

| run | plugin state | phase-3 FAIL name-set |
|---|---|---|
| r14 control (boundary inserted) | pre-both-fixes | { **10** Pre-layout STA, **11** DFT-insertion, **23** Post-route STA, **26** Antenna, **28** PERC } |
| r14 fix (skip-boundary only) | Fix 1 only | { **11** DFT-insertion } |
| **r15 (this run)** | **Fix 1 + Fix 2 on main** | **{ } — empty (FAIL=0)** |

**What "converged" means here, precisely** — the orchestrator
`vibe_ic_one_shot.json` verdict and the five phase-3 sign-off gates, quoted verbatim:

```
overall verdict : PASS_WITH_WAIVERS   (phase1 PASS · phase2 PASS_WITH_WAIVERS · phase3 PASS_WITH_WAIVERS · analog/mixed SKIPPED)  duration 1451.5s
sign-off: 5 of 5 declared sign-off gate(s) PASSED
  PASS  drc         violations=0 report=drc.rpt
  PASS  lvs         netgen LVS: circuits match uniquely (Magic ext2spice vs gate netlist)
  PASS  sta_corner  all analyzed sign-off corners MET (governing worst-slack +0.690 ns)
  PASS  gds         gds=user_project_wrapper.gds size=92753582
  PASS  step11_dft_scan_insertion  33 internal + 0 boundary scan cells; input flops=33; chain covers every flop=True
```

The SS-corner setup violation that #604 was about stays closed — `reports/phase3/sta_mcorner_ocv.rpt`,
liberty `sky130_fd_sc_hd__ss_100C_1v60.lib`, SPEF `user_project_wrapper.max.spef`:
`worst slack max 7.77 … 7.77 slack (MET)`, `tns max 0.00`; FF-hold corner
`worst slack min 0.41 … slack (MET)`; `post_route_summary.json real_violation_found=false`.

## 2. The internal scan chain is INTACT — Step 11 did NOT pass by DFT quietly stopping

The brief's explicit worry ("a Step 11 that passes because DFT quietly stopped would be
worse than the FAIL it replaced") — checked and refuted from the **canonical artifact**
`reports/phase2/dft/scan_chain.json` (not the log):

```
skip_boundary = True   skip_boundary_mode = auto        (deterministic rule, NO agent)
internal_chain_length = 33   boundary_chain_length = 0   input_flop_count = 33
chain_length_matches_flop_count = True   cells_added = {sky130_fd_sc_hd__mux2_1: 33}
area_instances_delta_pct = 10.15   chain_exit = 0   published = True
```

33 flops → 33 scan muxes (one per flop) → 0 boundary cells → chain covers every flop.
LEC confirms behaviour unchanged: `step11_lec_equivalence: yosys equiv verdict=PASS
(RTL vs post_dft_netlist.v, rc=0)`. ATPG coverage is **unchanged from r14** —
`atpg_coverage_gate.json`: `measured_coverage_pct=89.5897` (test coverage),
`raw_coverage_pct=60.5336` (raw stuck-at). A fix that closed Step 11 by deleting DFT
would show a shorter chain or lower coverage; this shows neither. PnR routed the
POST-DFT netlist (`netlist: post_dft_netlist.v (POST-DFT) — 33 internal + 0 boundary,
+33 instances (10.15%)`).

## 3. Both fixes confirmed on main AND confirmed operative on this design

Confirmed in the plugin source (`plugin_work`, staged from committed origin/main), then
confirmed to actually fire on this run — verified, not assumed:

**Fix 1 — `fault chain --skip-boundary` selector** (`fault_scan_chain_insert.py`, 24
`skip_boundary` references). Operative: `scan_chain.json.skip_boundary_evidence` shows
`is_fixed_pinout=true`, `def_template=fixed_dont_change/user_project_wrapper.def`,
`mode=auto`, reason = "FP_DEF_TEMPLATE fixes the top's pin placement → ports are a parent
interface, not chip pads → …insert the internal scan chain only (--skip-boundary)". The
deterministic `is_fixed_pinout_wrapper()` rule selected it with **no agent in the loop**.

**Fix 2 — DFT-sign-off / coverage-gate coherence** (this is exactly r14 §7's recommendation,
now landed). `dft_atpg_coverage_check.py:147` defines the shared predicate
`NON_BLOCKING_STUCK_AT_VERDICTS = frozenset({"PASS","INFORMATIONAL"})` /
`stuck_at_signoff_passes()`; `dft_signoff_check.py:406` **consumes that one predicate**
(`stuck_ok = _sa.stuck_at_signoff_passes(stuck_at["status"])`) instead of the old
`== "PASS"`. Operative and coherent on this design:
* `dft_atpg_coverage_check` → `verdict=INFORMATIONAL`, `l20_applicability.asserts_dft=false`,
  `floor_enforced=false` (this IC's L20 declares `dft_present=false`).
* `dft_signoff_check` → **`verdict=PASS`, exit 0**: `stuck_at.status=INFORMATIONAL`
  (accepted as non-blocking via the shared predicate), `transition=ENGINE_LIMITED`
  (documented OSS-Fault limitation — combinational stuck-at only), `bsdl=PASS`.

Both DFT gates now key on the SAME L20 applicability and return **coherent** verdicts —
the two-gates-one-applicability-opposite-verdicts defect r14 located is closed.

## 4. Run shape / entry point / image (measured)

Shape A (full deterministic runner, Path A: provided design + vendor L-docs → GDS),
entered through the one canonical front door (Phase 1). One end-to-end run of
`vibe_ic_one_shot_runner.py`, `--pdk sky130A --ic-name caravel_user_project
--top-name user_project_wrapper --skip-analog`. Duration **1451.5 s**.

**Image — measured, not intended.** The brief header's `--container …:0.2.52` is a stale
template default. I verified with `fault chain --help` that **0.2.52 has NO `--skip-boundary`
flag** and **0.2.54 has it** (same `fault` 0.9.4 binary string, rebuilt between tags), so
Fix 1 is inoperative on 0.2.52 and I ran on **0.2.54**. The orchestrator recorded what it
actually ran in: `image_ref=ghcr.io/vibeic/vibeic-eda:0.2.54`,
`image_id=sha256:3c097801d993…`, `container=vibeic-eda-car15` — a FRESH container created
from the pinned image, `--require-image` enforced.

## 5. Per-phase verdict

| phase | verdict | evidence |
|---|---|---|
| phase1 | PASS (rc 0) | L1–L23 from `input/docs/`; coverage 100 %; class detected `bus_peripheral` (Wishbone up-counter) |
| phase2 | PASS_WITH_WAIVERS (rc 0) | synth; DFT scan **33 internal + 0 boundary**; LEC PASS; ATPG raw 60.53 % / test 89.59 % (INFORMATIONAL — L20 no-DFT); Step 11 DFT-signoff **PASS** |
| phase3 | PASS_WITH_WAIVERS (rc 0) | **5/5 sign-off gates PASS**: DRC 0, LVS match, SS-setup **+7.77 ns MET**, GDS 92,753,582 B; single-corner STA WARNING (#442, non-blocking) |
| analog / mixed | SKIPPED | pure-digital IC, `--skip-analog` |
| **overall** | **PASS_WITH_WAIVERS** | orchestrator + independent `flow_compliance_check --strict` (exit 0) agree; FAIL=0 MISSING=0 |

## 6. What is WAIVED / SKIPPED, and what a foundry would still ask for

**3 WAIVED-DEFERRED** (documented waiver — production tapeout review must close):
* **Step 4 Simulation** — `cpu_functional_oracle_waiver` + `verilator_coverage_measure`
  credited via waiver (#651 — a coverage slot credited by waiver, not a bare PASS).
* **Step 6 FPGA early prototype** & **Step 39 FPGA final sign-off** — `ENV_UNAVAILABLE`
  (fpga-board-prototype cap-gap): no DE10-class board / no Quartus on host; the on-board
  `.sof` is honestly deferred to board bring-up, not faked-PASS.

**21 SKIPPED-CONDITION** (predicate genuinely not applicable / not yet met): analog A1–A9
+ mixed M1–M4 (no analog content — `bus_peripheral`), post-layout GLS (29) + post-layout
SPICE correlation (30) (disclosed OSS capability gaps, sibling-owned skip notes),
manufacturing 40–44 (awaiting silicon — external), and the protocol/analog N/A gates for
this IC class. **4 VACUOUS-PASS** (gate ran, found no applicable input): D1 doc-extraction,
Step 14 yosys-handoff, etc.

**A foundry would still ask for** (none of which is a defect in this run, all disclosed):
1. **Multi-corner MMMC STA sign-off** — current is `STA_SINGLE_CORNER_ONLY` (WARNING #442);
   sign-off must present ≥2 distinct per-corner reports.
2. **Real at-speed / transition ATPG** — current `transition=ENGINE_LIMITED` (OSS Fault does
   combinational stuck-at only); an ATE program needs measured transition-delay coverage.
3. **DFT coverage ≥ 95 %** *if the part declared DFT* — this design declares none
   (L20 `dft_present=false`), so 89.59 % is INFORMATIONAL; a DFT-required part is held to floor.
4. Close the **3 deferred waivers** (FPGA on-board bring-up ×2, functional coverage).
5. **Post-layout GLS + SPICE correlation**, then the manufacturing chain (fab → sort →
   package → final test → reliability).

## 7. What I built — a program-first hardening (the image-capability guard)

The one judgement I had to make this round that the plugin does **not** yet make
deterministically: **choosing 0.2.54 over the brief's stale 0.2.52 pin**, because Fix 1
appends `--skip-boundary` unconditionally and 0.2.52's `fault` rejects it. Distilled into
a deterministic rule so the NEXT blind run recovers it with no agent.

**Measured failure mode** (VERIFY, DO NOT INHERIT — real `fault chain` invocations, minimal
1-flop netlist + in-image sky130 liberty):
* **0.2.52**: `Error: Unknown option '--skip-boundary'` → **RC=64, no netlist produced**.
* **0.2.54**: `Internal scan chain successfully constructed … Boundary scan register NOT
  inserted (--skip-boundary)` — flag honored.

Today `fault_scan_chain_insert.py:438` appends `--skip-boundary` with **no capability
probe**. On an older image the decision `skip_boundary=true` (which is correct and
image-independent for a fixed-pinout wrapper) makes `fault chain` fail RC=64 → the generic
`"produced no scan netlist"` err_report → the wrapper that MOST needs skip-boundary
silently loses its scan chain, with the real cause (image too old) buried in `log_tail`
and no actionable remedy. That is a silent regression of exactly the convergence this round
established.

**The fix (this PR):** post-hoc classify `fault`'s own error — when the decision was
skip-boundary and the run failed with `Unknown option '--skip-boundary'` (chip-AGNOSTIC —
keys on the tool's error string, zero extra Docker calls), replace the generic error with
an ACTIONABLE one that names the cause and both remedies (upgrade to an image whose
`fault chain` exposes `--skip-boundary`; or `VIBEIC_DFT_SKIP_BOUNDARY=off` to accept legacy
boundary insertion, with the caveat that on a fixed-pinout wrapper that re-introduces the
#604 SS-corner violation), and record `skip_boundary_unsupported_by_binary=true` in
`scan_chain.json`. Bidirectional test: image-with-flag → proceeds; image-without-flag +
skip-decision → loud actionable error, never a false `skip_boundary=true` record.
See §8 for ship status.

## 8. Ship

**PR #629** — https://github.com/vibeic/vibe-ic/pull/629 — version-less, against
`vibeic/vibe-ic` (marketplace plugin path). Branched off **fresh `origin/main`**
(`caf75457` v1.9.43; the local shared checkout was 163 commits stale — branched off
origin/main, not it). **Base check**: `git diff --stat origin/main HEAD` = **2 files
changed, +132, 0 deletions** — purely additive, no other cell's work touched; no open PR
touches `fault_scan_chain_insert.py`. Files: `programs/fault_scan_chain_insert.py` (pure
helper `skip_boundary_unsupported_in_log` + loud-degrade in `run_chain`'s failure path)
and new `programs/tests/test_skip_boundary_capability_guard.py` (7 tests). Verification:
46 passed across the guard + scan-chain + #604 suites; chip-agnostic + source guards 14
passed; `py_compile` clean. `fault` binary unmodified — fix is plugin-side. **Not merged
(I am not the gatekeeper.)**

This PR does NOT touch either landed fix (skip-boundary selector, DFT-signoff coherence);
it hardens the image-capability edge around Fix 1 so a future blind run on a stale image
pin fails self-explainingly instead of silently dropping the scan chain.

## 9. Reproduce

```bash
# 1) Verify the flag lives in 0.2.54, not 0.2.52 (the stale template default):
docker run --rm --entrypoint bash ghcr.io/vibeic/vibeic-eda:0.2.54 -lc 'fault chain --help | grep skip-boundary'
docker run --rm --entrypoint bash ghcr.io/vibeic/vibeic-eda:0.2.52 -lc 'fault chain --help | grep skip-boundary || echo NO_FLAG'
# 2) Fresh container from the PINNED image:
docker run -d --name vibeic-eda-car15 -u 1000:0 -v /home/reyerchu:/home/reyerchu \
  --entrypoint sleep ghcr.io/vibeic/vibeic-eda:0.2.54 infinity
# 3) Full flow (skip-boundary auto-selected by the deterministic fixed-pinout rule):
CLAUDE_PLUGIN_ROOT=<plugin> VIBEIC_EDA_IMAGE=ghcr.io/vibeic/vibeic-eda:0.2.54 \
  python3 -u <plugin>/programs/vibe_ic_one_shot_runner.py /home/reyerchu/_c_car15_run \
  --pdk sky130A --ic-name caravel_user_project --top-name user_project_wrapper \
  --container vibeic-eda-car15 --require-image ghcr.io/vibeic/vibeic-eda:0.2.54 --no-dashboard --skip-analog
# 4) Authoritative gate + DFT sign-off:
CLAUDE_PLUGIN_ROOT=<plugin> python3 <plugin>/programs/flow_compliance_check.py /home/reyerchu/_c_car15_run   # Overall PASS_WITH_WAIVERS, exit 0
CLAUDE_PLUGIN_ROOT=<plugin> python3 <plugin>/programs/dft_signoff_check.py /home/reyerchu/_c_car15_run       # verdict PASS, exit 0
```

Standard OSS substitutions throughout (yosys / OpenROAD / OpenSTA / Magic / netgen /
KLayout / iverilog / Fault 0.9.4 for the commercial chain); `fault` unmodified — both fixes
are plugin-side.
