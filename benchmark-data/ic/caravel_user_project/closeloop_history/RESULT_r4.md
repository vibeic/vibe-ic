# caravel_user_project — Benchmark IC #7 — Round-4 Clean-Room RESULT

- **IC:** caravel_user_project (chipfoundry/caravel_user_project, Apache-2.0)
- **Round:** 4 (clean-room close-loop verification of the v1.0.43 caravel re-fixes
  #661 phantom-DUT + #662 dependency-macro)
- **Plugin under test:** PUBLIC tree
  `/home/reyerchu/vibe-ic/vibe-ic-marketplace/plugins/vibe-ic`, HEAD `21544a1c`
  (**v1.0.43** — the #661/#648/#646/#662 caravel round-3 re-fixes). Runner +
  `flow_compliance_check` invoked directly from the public `programs/` dir — NOT slash
  commands, NOT the root tree.
- **Project dir:** `_bench7_caravel_v1034_cleanroom/caravel_r4/`
- **Shape:** A / D (full runner, SoC integration).
- **Blindness:** authored ONLY the design's own input sources
  (`input/design_src/verilog/rtl/{defines,user_defines,user_proj_example,user_project_wrapper}.v`)
  into the runner's canonical RTL path `phase2/stage1/rtl/`. Did NOT read the `spm_pilot`
  checkout, any reference GDS, the host scorer, or any prior-round sample.

---

## 1. What was run (clean-room full re-run)

Phase 1 was pre-run at v1.0.43 (L1–L23 present, 24/13 L-docs). Two runner invocations:

| Invocation | RTL state | Outcome |
|---|---|---|
| round1 | no `rtl/` | runner WAIVED `rtl_gen` (`bus_peripheral`, rtl_gen=null, `fallback_skill=spec-to-rtl`); `reference_tb` FAIL `rtl/ missing` (expected). |
| round2 | authored 4 stock user RTL files (incl the design's own `defines.v`) into `phase2/stage1/rtl/` | `full_stack_tb_gen` emits the **correct** `tb_user_project_wrapper_full.v`; it **compiles + PASSes** (no "Unknown module type"); `yosys_synth` **PASS** (cells=189, top=`user_project_wrapper`); `reference_tb` now **WAIVED** (AID-TB N/A for bus_peripheral); chain advances **past** the round-3 wall and halts at a **new** blocker: **Step 3 CDC/RDC**. |

The spec-to-rtl recovery was performed **inside the runner path** (authored into
`_pl.rtl_dir(project)` = `phase2/stage1/rtl/`, then re-invoked), per
open-benchmark-methodology — not a hand-rolled MCP harness. `uprj_netlists.v` was
deliberately NOT staged (it is a gate-netlist `` `include `` wrapper, not synthesizable
source).

---

## 2. SOLE ACCEPTANCE CRITERION (verbatim, this run)

```
python3 .../programs/flow_compliance_check.py _bench7_caravel_v1034_cleanroom/caravel_r4 --strict

=== Vibe-IC phase1_phase2_phase3 compliance ===
Project: /home/reyerchu/AI_IC_design/_bench7_caravel_v1034_cleanroom/caravel_r4
Flow def: /home/reyerchu/vibe-ic/vibe-ic-marketplace/plugins/vibe-ic/flow/phase1_phase2_phase3.yaml
Steps: 59 total (4/46 executed PASS, 3 DEFERRED via waiver)
  PASS=3  FAIL=4  MISSING=38 (25 blocked-by-upstream of step 3)  WAIVED-DEFERRED=3  SKIPPED=10  VACUOUS-PASS=1
...
Overall: FAIL  (strict=True)
```

PASS steps (the chain's actual reach): **Step 1 Spec-to-RTL, Step 2 Lint, Step 9
Synthesis**. First mid-chain FAIL = **Step 3 (CDC/RDC check)** — NEW. Steps 4/5 cascade
(Step 4 WAIVED-DEFERRED cpu-functional-oracle waiver; Step 5 Formal ENV_UNAVAILABLE-waived
to the FPGA-board cap-gap). Phase 3 (Steps 14-38, PnR/sign-off) is entirely
`blocked-by-upstream(step 3)` and unreachable this round. Step 39 FPGA = FAIL
`no-hardware-evidence` (headless, no board — environment, correctly bucketed).

**Reach vs round-3:** round-3 was blocked at **`reference_tb`** (3/48) on the **phantom
DUT** (GAP-A / #661). Round-4 progressed **past** that wall — the full-stack TB now compiles
against the real `user_project_wrapper` top — and the new first mid-chain FAIL has moved
**forward** from `reference_tb` to **Step 3 CDC/RDC**. Net: forward progress, new failure
surface exposed. PASS count is still 3 (the executed-PASS set is the same Steps 1/2/9), but
the BLOCKER has advanced (phantom DUT → multi-clock CDC gate logic). **Did NOT reach Phase 3.**

---

## 3. Per-fix verdicts (fresh evidence, this run)

### #661 — full-stack TB instantiates a PHANTOM DUT (`l1_ic_name_fallback`) — **RESOLVED**
- The new `_v661_resolve_dut_module(project, top_name, l9_top_module)`
  (`phase2_one_shot_runner.py:1927`, called at `:2026`) resolves the DUT **structurally**
  against `rtl/`: honours `--top-name`/`L9.top_module` ONLY when each names a real module,
  else the instantiation-graph root; never instantiates a name absent from `rtl/`.
- **Fresh evidence (this run):**
  - Generated TB `phase2/stage1/sim_full_stack/tb_user_project_wrapper_full.v:45` instantiates
    **`user_project_wrapper u_dut (...)`** — the REAL rtl/ top, NOT `caravel_user_project`.
  - It **compiles + runs**: `generic_full_stack_run/full_stack.log` →
    `tb_user_project_wrapper_full.v:105: $finish called at 1200000` + `full_stack.vvp` +
    `waves.vcd` emitted. **No "Unknown module type"** anywhere.
  - The step verdict flipped from round-3 `reference_tb FAIL (Unknown module type)` to
    round-4 `reference_tb WAIVED` + `full_stack results.json verdict=PASS
    connectivity_verified=true`.
- **Verdict: RESOLVED.** The chain reaches PAST the round-3 reference_tb blocker.
  (One cosmetic residual — the results.json metadata STRING is stale — see GAP-D below;
  it does NOT affect the compile or the verdict.)

### #662 — undefined-macro / unresolved-`include dependency pre-check — **RESOLVED**
- `_v662_resolve_dependency_files(project, auto_stage=True)`
  (`phase2_one_shot_runner.py:3715`, wired into `step_yosys_synth` at `:4737`, fail-open
  advisory) scans staged `rtl/` for USED-but-not-DEFINED macros + unresolved `` `include ``s,
  locates the defining file under `input/design_src/**/rtl/`, and auto-stages it (or emits a
  named remediation hint).
- **Fresh evidence (this run):** the design's own `defines.v` (defining `MPRJ_IO_PADS`,
  `MPRJ_IO_PADS_1/2`) was staged into `rtl/`; `yosys_synth` **PASS** —
  `netlist=netlist_yosys.v cells=189 synth_top=user_project_wrapper
  frontend=read_verilog_v2005`. **No `unknown macro '\`MPRJ_IO_PADS'`** error (the exact
  round-2/round-3 wall is gone). The dependency premise the #662 helper resolves is
  structurally satisfied; synth is clean.
- **Verdict: RESOLVED.** The MPRJ_IO_PADS macro wall that cost two rounds is closed —
  whether the agent stages `defines.v` (as here) or the #662 auto-stage does, the synth
  resolves and no bare undefined-macro failure occurs.

### #650 — pin_order.cfg ingestion — **UNREACHABLE in-flow this round (unchanged from round-3)**
Chain halted at Step 3 (phase2); Phase 3 PnR never ran (`caravel_r4/phase3/` contains only
`analog/`). Cannot re-verify in-flow. Structural code-presence verdict from round-3 stands
(unit-tested: 3 edge sections / 52 pins → 53 `set_io_pin_constraint`). No regression observed.

### #651 — signoff PASS_WITH_WAIVERS rc=3 — **UNREACHABLE in-flow this round (unchanged from round-3)**
Same reason: phase3 sign-off never reached. Structural code-presence verdict from round-3
stands. No regression observed.

---

## 4. NEW chip-AGNOSTIC file-worthy gap candidates

### GAP-C (PRIMARY, blocks the chain) — honestly-deferred MULTI-CLOCK CDC hard-FAILs Step 3 (no cap-gap acceptance path)
- **Step:** Phase 2 / Step 3 `CDC / RDC check` (`cdc_crossing_check.py`).
- **Symptom + evidence (this run):** `flow_compliance_check` →
  `✗ [FAIL] Step 3: CDC / RDC check`,
  `program failed: cdc_crossing_check . --json reports/phase2/gates/cdc_crossing.json`,
  finding `CDC_REPORT_EXISTS / ERROR / "No CDC report found"`. But the runner DID emit CDC
  JSONs — `reports/phase2/cdc/{crossing,async_input,reset_dep}.json` — each with
  `verdict: "SKIPPED-CONDITION"`,
  `reason: "multi-clock design (root_clocks=['user_clock2','wb_clk_i'], scope: top module
  'user_project_wrapper'): a real CDC tool run is required — this runner does not
  synthesize crossing verdicts (#436)"`.
- **Root cause:** the runner (`phase2_one_shot_runner.py:6476-6552`) correctly emits CDC
  `verdict=PASS` (with the clock-edge scan as evidence) for a **single-clock** design, but
  `verdict=SKIPPED-CONDITION` for a **multi-clock** design (honest #436 capability deferral:
  no real CDC tool in the open-source chain). The gate `cdc_crossing_check.py` only counts a
  canonical CDC JSON as findable input when `doc.get("verdict") == "PASS"` (lines 132, 205);
  a `SKIPPED-CONDITION` verdict is invisible to it → it reports "No CDC report found" →
  hard FAIL. There is **no `cap:cdc` capability-gap flag** for Step 3, unlike Steps
  11/12/13/29/30 which carry `cap:dft_scan_insertion_atpg` / `cap:logic_equivalence_check` /
  `cap:sdf_annotated_gatelevel_sim` / etc. and are converted MISSING→SKIPPED-CONDITION
  instead of FAILing.
- **Why systematic:** ANY design with ≥2 root clock domains hard-FAILs Step 3 on the
  open-source runner and cascade-blocks all of Phase 3 (25 downstream steps go MISSING
  `blocked-by-upstream(3)`), even though the runner did everything an open chain can do and
  honestly deferred the real-CDC-tool verdict. Single-clock designs pass; multi-clock
  designs are penalised for a TOOL gap the plugin already acknowledges (#436). Chip-agnostic:
  keys only on "is this a multi-clock SKIPPED-CONDITION CDC deferral?" — a structural verdict
  read, no chip literal.
- **Proposed fix area (Bucket A — deterministic):** teach the Step-3 acceptance path (in
  `cdc_crossing_check.py` and/or the `flow_compliance_check` Step-3 mapping) to treat a
  canonical CDC JSON with `verdict=="SKIPPED-CONDITION"` + a named multi-clock #436 reason as
  an **ENV_UNAVAILABLE / `cap:cdc_multiclock_tool`** honest deferral (review_required, NOT
  executed-PASS) — exactly as Steps 11/12/13/29/30 are handled — so it converts to
  SKIPPED-CONDITION instead of hard-FAIL and stops cascade-blocking Phase 3. Pure verdict /
  reason-string structural test, no LLM.
- **Severity:** HIGH (sole blocker of this benchmark this round; reproduces for any
  multi-clock IC — every SoC with a system clock + a peripheral/user clock).

### GAP-D (SECONDARY, cosmetic but consumer-facing) — full-stack `results.json` keeps STALE phantom `tb`/`dut` strings across a re-invocation
- **Step:** Phase 2 `full_stack_tb_gen` / `_run_generic_full_stack` results emit.
- **Symptom + evidence (this run):** `phase2/stage1/sim_full_stack/results.json` (file mtime
  17:20:27 = round-2 run) reports `"tb": "tb_caravel_user_project_full.v"`,
  `"dut": "caravel_user_project"`, `ts_unix` decoding to **17:19:39** (the round-1
  phantom-DUT generation time) — even though the actual compile this run used
  `tb_user_project_wrapper_full.v` (`full_stack.log`) and the correct TB instantiates
  `user_project_wrapper`. The "do NOT overwrite a richer results.json that already exists"
  guard (`phase2_one_shot_runner.py:2280`) preserved the round-1 STRING fields when the
  round-2 re-invocation should have refreshed `tb`/`dut`/`ts_unix` to the actually-compiled
  TB.
- **Why systematic:** any re-invocation (close-loop, ECO, agent re-run) where the DUT/TB
  identity changes between runs leaves `results.json` advertising the prior identity. A
  downstream consumer that reads `results.json["dut"]` (e.g. a cross-check matrix, a report
  generator, or a later gate keying on DUT identity) gets the phantom name — silently wrong
  provenance. Chip-agnostic: keys only on "does results.json.dut/tb match the TB actually
  compiled in generic_full_stack_run?" — a structural file/string consistency test.
- **Proposed fix area (Bucket A — deterministic):** in the results-emit
  (`_run_generic_full_stack` / line 2280 guard), when a re-run compiles a different
  `tb_<top>_full.v` than the one named in an existing `results.json`, refresh the
  `tb`/`dut`/`ts_unix` identity fields (keep the richer per-vector content but never keep a
  STALE DUT identity). Pure path/string consistency, no LLM.
- **Severity:** LOW-MEDIUM (does not affect this run's verdict — the compile + connectivity
  PASS are correct — but it is a real chip-agnostic provenance-staleness defect that would
  mislead any downstream consumer of the results.json identity fields, and it is exactly the
  kind of stale-metadata trap the methodology warns against).

Both gaps are **PROGRAM-FIRST / Bucket A**: each reduces to a structural verdict/string
consistency check, no natural-language judgment. Per the benchmark-agent doctrine I did NOT
file GitHub issues or edit plugin code — these are returned for the Core-Agent backlog.

---

## 5. Environment-only blockers (separated from plugin gaps)

- **No DE10/FPGA board (NOT a plugin gap):** Step 5 Formal = ENV_UNAVAILABLE-waived to the
  `cap:fpga_board_prototype` cap-gap (no .sof, deliberate Quartus/board skip honestly
  self-reported); Step 39 FPGA final sign-off = FAIL `no-hardware-evidence`. Expected —
  headless host, no board. Correctly bucketed by the gate.
- **Open-source tool capability gaps (NOT plugin gaps, already cap-flagged):** Steps 11
  (DFT/ATPG), 12 (post-DFT), 13 (LEC), 29 (post-layout gate-sim), 30 (post-layout SPICE) =
  SKIPPED-CONDITION with named `cap:` flags (#430) — the open chain does not implement these
  canonical steps. Correctly self-disclosed, NOT counted as FAIL. *(Contrast: GAP-C is a
  multi-clock CDC deferral that the runner ALSO honestly self-reports as a tool gap, but
  which — unlike these — has no cap-flag acceptance path and therefore hard-FAILs. That
  asymmetry is the §4 GAP-C plugin gap, not an environment blocker.)*
- **Manufacturing steps 40-44 SKIPPED-CONDITION:** correct (silicon-dependent, no
  `silicon_received.json` / `htol_results.json`).
- **Input bundle (NOT a plugin gap, fixed since round-3):** `caravel_r4/input/design_src`
  now ships the design's own `defines.v` + `uprj_netlists.v` — the round-3 input-prep
  omission is corrected; `defines.v` staged clean and synth passed. No residual.

---

## 6. Path to this RESULT

`/home/reyerchu/AI_IC_design/_bench7_caravel_v1034_cleanroom/RESULT_r4.md`

Supporting artifacts (all under the run dir, no plugin/MCP writes):
- run logs: `_bench7_caravel_v1034_cleanroom/_logs/run_r4_round{1,2}.log`
- phase2 orchestrator JSON: `caravel_r4/reports/orchestrator/{phase2_one_shot,vibe_ic_one_shot}.json`
- #661 evidence — correct full-stack TB + compile log:
  `caravel_r4/phase2/stage1/sim_full_stack/tb_user_project_wrapper_full.v` (DUT =
  `user_project_wrapper`) + `.../generic_full_stack_run/full_stack.{log,vvp}` + `waves.vcd`
- #662 evidence — synth PASS: `caravel_r4/phase2/stage2/synth/yosys.log` +
  `netlist_yosys.v` (cells=189, top=user_project_wrapper)
- GAP-C evidence — CDC SKIPPED-CONDITION JSONs vs the FAILing gate:
  `caravel_r4/reports/phase2/cdc/{crossing,async_input,reset_dep}.json` +
  `caravel_r4/reports/phase2/gates/cdc_crossing.json`
- GAP-D evidence — stale results.json identity:
  `caravel_r4/phase2/stage1/sim_full_stack/results.json` (tb/dut = phantom, ts_unix = round-1)
- authored RTL: `caravel_r4/phase2/stage1/rtl/{defines,user_defines,user_proj_example,user_project_wrapper}.v`

### Convergence status
**NOT converged.** Round-4 confirmed #661 + #662 RESOLVED (the round-3 phantom-DUT +
macro wall is fully cleared — the full-stack TB now compiles against the real
`user_project_wrapper` top and synth passes), and the chain advanced its blocker FORWARD
from `reference_tb` to **Step 3 CDC/RDC**. Round-4 surfaced **1 new HIGH chip-agnostic
Bucket-A gap (GAP-C: multi-clock CDC honest-deferral hard-FAILs Step 3, no cap-flag) +
1 LOW-MEDIUM Bucket-A gap (GAP-D: stale results.json DUT identity)**. The loop requires:
Core-Agent fixes GAP-C (cap:cdc_multiclock acceptance path) chip-agnostically → re-run
clean-room → confirm Step 3 converts to SKIPPED-CONDITION and the chain advances into
Phase 3 (synth handoff → floorplan → PnR → CTS → route → STA → DRC → LVS → sign-off).
