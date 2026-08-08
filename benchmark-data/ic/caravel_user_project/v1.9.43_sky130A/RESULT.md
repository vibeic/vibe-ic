# RESULT — caravel_user_project × sky130A (Round 15, `_c_car15_run`)

## VERDICT

**FAIL** — this cell does NOT converge. Re-verified 2026-08-08 against the
evidence already committed in this directory; see "CORRECTION" immediately
below for the full chain (independently reproduced, not re-derived from
design input).

## CORRECTION (2026-08-08) — the headline below is FALSE; this cell does NOT converge

The original §1 headline of this file claimed **"YES — CONVERGES ... a clean
PASS_WITH_WAIVERS with zero FAIL and zero MISSING"**. That claim was false
the moment it was committed: the SAME commit (`cdc54d32f`) that added this
file also added `reports/audit/phase23_completion_audit.json`, which recorded
`"verdict": "FAIL"` — the opposite answer — for the same run. Two independent
re-verifications, done today against the artifacts already committed in this
directory (nothing re-run, nothing regenerated, no design input read beyond
what is already here), confirm the audit JSON, not the §1 prose:

1. **`reports/phase2/dft/atpg_coverage_gate.json`** (committed in the same
   `cdc54d32f` commit, byte-for-byte unchanged since) reads
   `"verdict": "FAIL"`, `"l20_applicability": {"asserts_dft": null, ...}`,
   `"floor_enforced": true`, with the reason: *"L20 is present but
   UN-EXTRACTED ... The foundry floor STANDS — an un-extracted layer must
   not buy a looser verdict than having no layer at all."* — directly
   contradicting §3's claim below that this gate reported
   `verdict=INFORMATIONAL` / `floor_enforced=false`.
2. Running the CURRENT `dft_atpg_coverage_check.py` and `dft_signoff_check.py`
   fresh (read-only, no design input beyond what is already published here)
   against this same directory reproduces **verdict FAIL** for both,
   consistently: measured stuck-at ATPG coverage is **89.5897%**, the
   effective target (foundry floor) is **95.0%**, and this design's own L20
   (`phase1/generated_docs/L20_DFT_SCAN_TOPOLOGY.json`) has never been
   extracted (`extraction_status: "NOT_YET_EXTRACTED"`, `applicability:
   "APPLICABLE"`) — its `dft_present: false` field is the emitter's
   structural default, not an authored "no DFT" decision, so it does not
   license waiving the foundry floor. `reports/phase2/dft/dft_signoff.json`
   (also committed unchanged since `cdc54d32f`, showing `verdict: PASS`) is
   STALE evidence from a moment when the plugin's L20-applicability logic
   evidently disagreed with itself mid-run (`dft_atpg_coverage_check` and
   `dft_signoff_check` computed different `l20_applicability` for the same
   L20 doc at the time this run happened) — it does not reflect what the
   current, coherent code computes, and must not be read as current evidence.
3. Running `flow_compliance_check.py --strict --read-only` fresh against
   this directory reproduces **Overall: FAIL** — Step 11 (DFT insertion)
   fails for the reason in (2), independent of any publish-layout artifact.

**Genuinely real, and NOT retracted**: the internal scan-chain structural
fix described in §2 below (33 internal scan cells, chain covers every flop,
`skip_boundary` correctly selected for the fixed-pinout wrapper) is real and
independently confirmed — `scan_chain.json` and the LEC-equivalence result
it cites are untouched by this correction. What is false is the claim that
the DFT step, and therefore the whole run, *converges*: ATPG **coverage**
(not chain structure) is the open, blocking gap, at 89.59% against a 95%
foundry floor, and the design's own L20 declaration was never extracted far
enough to earn a waiver of that floor.

Separately, re-auditing THIS published (not live-run) directory also
surfaces a number of `files_exist` FAILs against `phase3/stage3/*` paths
(pre/post-route STA, routing, spare-cell, metal fill, foundry handoff) that
are **not** independent evidence of non-convergence — `benchmark-data/
PUBLISHING.md` deliberately excludes `phase3/stage3/*` and `*.log` from what
gets committed, so any published cell (including genuinely converged ones —
measured identically on `spm/v1.9.94_sky130A` and `spm/v1.9.96_gf180mcuD`)
reads FAIL/MISSING on those specific steps when re-audited post-publish.
`flow_compliance_check.py` now emits an explicit advisory when it detects
this shape, so a future reader does not need to rediscover this. The ATPG
floor finding above does not depend on that confound — `coverage.json` and
the L20 doc ARE published, and both checks were run against exactly the data
this directory ships.

**Verdict, corrected**: `caravel_user_project × sky130A` does **NOT**
converge on this run. `benchmark-data/ic/INDEX.md`'s audit-verdict column
already read `FAIL` for this cell (`P5 F10 M10 W2`) prior to this
correction — that machine-derived column was right; this file's prose
headline was wrong. The rest of this document (below the original §1) is
left as originally written, for the historical record of what Round 15
actually did and found, EXCEPT where marked `[CORRECTED]`.

---

## 1. Headline — the convergence answer, best-evidenced line [CORRECTED — see above]

**NO — `caravel_user_project × sky130A` does NOT converge**, end to end, on
the plugin state this run measured. Fix 1 (the `--skip-boundary` selector
for a fixed-pinout wrapper) is real and confirmed operative — see §2/§3
below. But Step 11 DFT sign-off's **coverage** dimension is NOT closed: the
independently-reproduced verdict is `dft_signoff_check → verdict=FAIL`
(stuck_at status FAIL, 89.59% measured against a 95% foundry floor,
un-extracted L20 does not waive it) — see the CORRECTION above for the full
evidence chain. The original text below quoted
`flow_compliance_check.py --strict` reporting `PASS=35 FAIL=0 MISSING=0`
and exit 0; that quote is not reproducible against what is committed in this
directory and does not match the sibling `phase23_completion_audit.json`
this same commit shipped, which recorded `verdict: FAIL`.

r14's **sole** remaining phase-3 failure — **Step 11 DFT insertion** — is
**still failing**, for a different sub-reason than r14 recorded (ATPG
coverage vs. floor, not chain structure). The scan-CHAIN part of Step 11 is
fixed (§2); the scan-COVERAGE part is not.

**What "the internal chain is intact" means here, precisely** — the
orchestrator `vibe_ic_one_shot.json` verdict and the phase-3 sign-off gates
this run recorded, quoted verbatim (kept for the historical record; the
`step11_dft_scan_insertion` line below audits chain STRUCTURE only, not
ATPG coverage against the foundry floor — see CORRECTION):

```
overall verdict : PASS_WITH_WAIVERS   (phase1 PASS · phase2 PASS_WITH_WAIVERS · phase3 PASS_WITH_WAIVERS · analog/mixed SKIPPED)  duration 1451.5s
sign-off: 5 of 5 declared sign-off gate(s) PASSED
  PASS  drc         violations=0 report=drc.rpt
  PASS  lvs         netgen LVS: circuits match uniquely (Magic ext2spice vs gate netlist)
  PASS  sta_corner  all analyzed sign-off corners MET (governing worst-slack +0.690 ns)
  PASS  gds         gds=user_project_wrapper.gds size=92753582
  PASS  step11_dft_scan_insertion  33 internal + 0 boundary scan cells; input flops=33; chain covers every flop=True
```

The orchestrator's own sign-off table above never asserts an ATPG-coverage
verdict at all — it only asserts chain structure (`step11_dft_scan_insertion`).
The overall-convergence claim in the original §1 conflated "the orchestrator's
5 declared sign-off gates all passed" with "the full 63-step
`flow_compliance_check.py --strict` audit passed", which is a different,
broader claim that this run's own `phase23_completion_audit.json` already
contradicted on the day it was written.

The SS-corner setup violation that #604 was about stays closed — `reports/phase3/sta_mcorner_ocv.rpt`,
liberty `sky130_fd_sc_hd__ss_100C_1v60.lib`, SPEF `user_project_wrapper.max.spef`:
`worst slack max 7.77 … 7.77 slack (MET)`, `tns max 0.00`; FF-hold corner
`worst slack min 0.41 … slack (MET)`; `post_route_summary.json real_violation_found=false`.
This part is unaffected by the correction above — it is a different sign-off
dimension (timing) than the one that is open (DFT coverage).

## 2. The internal scan chain is INTACT — Step 11's CHAIN did not pass by DFT quietly stopping [structural claim unaffected by correction]

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
`raw_coverage_pct=60.5336` (raw stuck-at) — **and, per the CORRECTION above, this
coverage number is BELOW the 95% foundry floor and the design's L20 does not
waive it, so this remains the blocking gap it names.** PnR routed the
POST-DFT netlist (`netlist: post_dft_netlist.v (POST-DFT) — 33 internal + 0 boundary,
+33 instances (10.15%)`).

## 3. Both fixes confirmed on main — Fix 1 operative, Fix 2 claim CORRECTED

Confirmed in the plugin source (`plugin_work`, staged from committed origin/main), then
confirmed to actually fire on this run — verified, not assumed:

**Fix 1 — `fault chain --skip-boundary` selector** (`fault_scan_chain_insert.py`, 24
`skip_boundary` references). Operative: `scan_chain.json.skip_boundary_evidence` shows
`is_fixed_pinout=true`, `def_template=fixed_dont_change/user_project_wrapper.def`,
`mode=auto`, reason = "FP_DEF_TEMPLATE fixes the top's pin placement → ports are a parent
interface, not chip pads → …insert the internal scan chain only (--skip-boundary)". The
deterministic `is_fixed_pinout_wrapper()` rule selected it with **no agent in the loop**.
This fix is real and independently confirmed; it is not what this correction is about.

**Fix 2 — DFT-sign-off / coverage-gate coherence — CLAIM WAS FALSE, CORRECTED HERE.**
The original text below claimed this run showed the two gates agreeing on a
PASS-shaped verdict. Independently re-run today, both gates agree — on
**FAIL**, not PASS:

* `dft_atpg_coverage_check` → **`verdict=FAIL`** (not `INFORMATIONAL` as
  originally claimed), `l20_applicability={"asserts_dft": null, ...}` (not
  `false`), `floor_enforced=true` (not `false`). This IC's L20
  (`phase1/generated_docs/L20_DFT_SCAN_TOPOLOGY.json`) has
  `extraction_status: "NOT_YET_EXTRACTED"` and `applicability: "APPLICABLE"`
  — it was never extracted into an explicit no-DFT decision; its
  `dft_present: false` field is the emitter's skeleton default. Per the
  gate's own current logic (`dft_atpg_coverage_check.py`'s
  `l20_dft_applicability()`): *"An L20 that is PRESENT but has never
  claimed extraction is the SAME uninformative state [as absent] and gets
  the SAME conservative answer ... Only `asserts_dft is False` licenses
  disabling the foundry floor, and ... exactly ONE state produces it:
  `applicability: NOT_APPLICABLE`"* — which this L20 does not declare.
* `dft_signoff_check` → **`verdict=FAIL`, exit 1** (not `PASS`/exit 0 as
  originally claimed): `stuck_at.status=FAIL` (measured 89.59% < 95%
  foundry floor, floor enforced because L20 is un-extracted), `transition=
  ENGINE_LIMITED` (documented OSS-Fault limitation — combinational
  stuck-at only, unaffected by this correction), `bsdl=PASS` (unaffected).

The originally-quoted `l20_applicability.asserts_dft=false` /
`floor_enforced=false` for `dft_atpg_coverage_check`, and `verdict=PASS`
for `dft_signoff_check`, do not match `reports/phase2/dft/
atpg_coverage_gate.json` as committed in this same directory (which has
always read `asserts_dft: null`, `floor_enforced: true`, `verdict: FAIL`
since the commit that added this file), and are not reproducible by running
either program fresh against what this directory ships. The "two-gates-one-
applicability-opposite-verdicts" defect r14 located is **not closed** by
this run — both gates are internally coherent with EACH OTHER today (both
say FAIL), but that coherent answer is the opposite of what this section
originally claimed.

## 4. Run shape / entry point / image (measured) [unaffected by correction]

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

## 5. Per-phase verdict [phase3 row CORRECTED]

| phase | verdict | evidence |
|---|---|---|
| phase1 | PASS (rc 0) | L1–L23 from `input/docs/`; coverage 100 %; class detected `bus_peripheral` (Wishbone up-counter) |
| phase2 | PASS_WITH_WAIVERS (rc 0) claimed by orchestrator; **DFT sign-off itself is FAIL** | synth; DFT scan **33 internal + 0 boundary** (structure OK); LEC PASS; ATPG raw 60.53 % / test 89.59 % — **below the 95% foundry floor, L20 un-extracted so no waiver applies**; Step 11 DFT-signoff **FAIL** (corrected — see §3) |
| phase3 | **FAIL** (`reports/audit/phase23_completion_audit.json` verdict, confirmed by independent re-run) | DRC 0, LVS match, SS-setup **+7.77 ns MET** and GDS 92,753,582 B are genuinely clean; but the flow-compliance audit's Overall verdict is FAIL, driven by Step 11 (see §3) and (on a re-audit of this published tree specifically) by `phase3/stage3/*` paths PUBLISHING.md excludes from commit — see the CORRECTION note on those |
| analog / mixed | SKIPPED | pure-digital IC, `--skip-analog` |
| **overall** | **FAIL** | `reports/audit/phase23_completion_audit.json` (verdict FAIL, matching an independent `flow_compliance_check.py --strict --read-only` re-run against this directory) — the orchestrator's own PASS_WITH_WAIVERS self-assessment disagrees with the audit and is the less authoritative of the two, per `benchmark-data/ic/INDEX.md`'s own reading convention |

## 6. What is actually open — CORRECTED: this is a blocking gap, not a foundry nice-to-have

The original §6 filed the ATPG-coverage shortfall under "what a foundry would
still ask for" (framed as non-blocking / disclosed). That framing was wrong:
under this plugin's OWN gate (`dft_atpg_coverage_check` / `dft_signoff_check`),
89.59% against a 95% floor with an un-extracted L20 is a **FAIL**, not a
disclosed deferral. What remains true and still open:

1. **DFT/ATPG coverage must reach ≥95%, or the design's L20 must be
   genuinely extracted into an explicit `applicability: NOT_APPLICABLE`
   no-DFT decision** (not merely leaving the emitter's `dft_present: false`
   skeleton default in place) — whichever is the honest answer for this
   design. This is the blocking gap; closing it is what would make Step 11,
   and this cell, converge.
2. **Multi-corner MMMC STA sign-off** — current is `STA_SINGLE_CORNER_ONLY`
   (WARNING #442); sign-off must present ≥2 distinct per-corner reports.
   (Unaffected by this correction.)
3. **Real at-speed / transition ATPG** — current `transition=ENGINE_LIMITED`
   (OSS Fault does combinational stuck-at only); an ATE program needs
   measured transition-delay coverage. (Unaffected by this correction.)
4. Close the **3 deferred waivers** (FPGA on-board bring-up ×2, functional
   coverage). (Unaffected by this correction.)
5. **Post-layout GLS + SPICE correlation**, then the manufacturing chain
   (fab → sort → package → final test → reliability). (Unaffected by this
   correction.)

## 7. What I built — a program-first hardening (the image-capability guard) [unaffected by correction; separate PR, unrelated to §1/§3]

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
See §8 for ship status. **This hardening is unrelated to the ATPG-coverage gap in §3/§6 —
it does not, and was never claimed to, close it.**

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
(image-capability guard status as of Round 15; unrelated to this correction).**

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
# 4) Authoritative gate + DFT sign-off (ORIGINAL run-directory reproduce commands — the
#    run directory above no longer exists; to reproduce the CORRECTION's findings against
#    the evidence actually committed here, use step 5 instead):
CLAUDE_PLUGIN_ROOT=<plugin> python3 <plugin>/programs/flow_compliance_check.py /home/reyerchu/_c_car15_run   # historical; run dir no longer exists
CLAUDE_PLUGIN_ROOT=<plugin> python3 <plugin>/programs/dft_signoff_check.py /home/reyerchu/_c_car15_run       # historical; run dir no longer exists

# 5) Reproduce the CORRECTION (2026-08-08) against THIS committed directory, read-only,
#    no design input beyond what is already published here:
cd benchmark-data/ic/caravel_user_project/v1.9.43_sky130A
python3 <plugin>/programs/dft_atpg_coverage_check.py . --json /dev/stdout   # verdict FAIL, floor_enforced=true
python3 <plugin>/programs/dft_signoff_check.py . --json /dev/stdout        # verdict FAIL, exit 1
python3 <plugin>/programs/flow_compliance_check.py --strict --read-only .  # Overall: FAIL, exit 1
```

Standard OSS substitutions throughout (yosys / OpenROAD / OpenSTA / Magic / netgen /
KLayout / iverilog / Fault 0.9.4 for the commercial chain); `fault` unmodified — both fixes
are plugin-side.
