# caravel_user_project — Benchmark IC #7 — Round-5 Clean-Room RESULT

- **IC:** caravel_user_project (chipfoundry/caravel_user_project, Apache-2.0)
- **Round:** 5 (clean-room field-verify of the v1.0.44/#673 CDC + #674 results-identity
  fixes; first attempt to drive the chain into Phase 3).
- **Plugin under test:** PUBLIC tree
  `/home/reyerchu/vibe-ic/vibe-ic-marketplace/plugins/vibe-ic`, **v1.0.45**
  (HEAD `ae175d95` = v1.0.44 commit landing #663-#674, incl. **#673** CDC
  SKIPPED-CONDITION deferral + **#674** full_stack results stale tb/dut refresh).
  Runner + `flow_compliance_check` invoked **directly from the public `programs/` dir**
  — NOT slash commands, NOT the root tree.
- **Project dir:** `_bench7_caravel_v1034_cleanroom/caravel_r5/`
- **Shape:** A / D (full runner, SoC integration).
- **Blindness:** authored ONLY the design's own 4 synthesizable input sources
  (`input/design_src/verilog/rtl/{defines,user_defines,user_proj_example,user_project_wrapper}.v`)
  into the runner's canonical RTL path `phase2/stage1/rtl/` (resolved via
  `_path_layout.rtl_dir` = `phase2/stage1/rtl`). Did NOT read any reference GDS, the
  `spm_pilot` checkout, the host scorer, or any prior-round sample. `uprj_netlists.v`
  deliberately NOT staged (27-line gate-netlist `` `include `` wrapper, not synthesizable
  source).

---

## 1. What was run (clean-room full re-run)

Fresh `caravel_r5` created by copying ONLY `caravel/input` (29 files: L1-L9 docs +
design_src incl `defines.v`/`uprj_netlists.v`) — no inherited phase outputs (verified:
no `phase*/reports/sim` dirs before the run). Two runner invocations:

| Invocation | RTL state | Outcome |
|---|---|---|
| round1 | no `rtl/` | Phase 1 **PASS**; runner **WAIVED** `rtl_gen` (`bus_peripheral`, rtl_gen=null, `fallback_skill=catalog-glue-author`); `reference_tb`/`yosys_synth` FAIL `rtl/ missing` (expected). |
| round2 | authored the 4 stock user RTL files into `phase2/stage1/rtl/` (spec-to-rtl/catalog-glue recovery **inside the runner path**) then re-invoked | full-stack TB compiles + PASSes against the real `user_project_wrapper`; `yosys_synth` PASS (cells=189); **Step 3 CDC now SKIPPED-CONDITION** (not FAIL); chain advances PAST the round-4 wall and halts at a **new** blocker: **Step 5 Formal**. |

All artifacts are fresh THIS run (`formal_not_run.json` 18:04:11, `cdc/crossing.json`
18:04:11, `sim_full_stack/results.json` 18:04:03 — all round-2).

---

## 2. SOLE ACCEPTANCE CRITERION (verbatim, this run)

```
python3 .../programs/flow_compliance_check.py _bench7_caravel_v1034_cleanroom/caravel_r5 --strict

=== Vibe-IC phase1_phase2_phase3 compliance ===
Project: /home/reyerchu/AI_IC_design/_bench7_caravel_v1034_cleanroom/caravel_r5
Flow def: .../flow/phase1_phase2_phase3.yaml
Steps: 59 total (4/44 executed PASS, 4 DEFERRED via waiver)
  PASS=3  FAIL=2  MISSING=38 (25 blocked-by-upstream of step 5)  WAIVED-DEFERRED=4  SKIPPED=11  VACUOUS-PASS=1
...
Overall: FAIL  (strict=True)
```

**Executed-PASS set (the chain's actual reach):** Step 1 Spec-to-RTL, Step 2 Lint,
Step 9 Synthesis (= same 3 as round-4). The two FAILs are **Step P0** (umbrella —
4 sub-gates, all pre-existing, see §4) and **Step 5 Formal** (NEW first mid-chain FAIL).
Step 3 CDC is now **SKIPPED-CONDITION** (#673 fix). Step 4 Sim = WAIVED-DEFERRED
(#651 cpu-functional-oracle waiver). Step 6 FPGA = WAIVED-DEFERRED (ENV_UNAVAILABLE
fpga-board cap-gap). **All of Phase 3 (Steps 15-38) is `blocked-by-upstream(5)` —
the chain did NOT reach Phase 3.**

**Reach vs round-4:** round-4 first-mid-chain-FAIL = **Step 3 CDC** (`blocked-by-upstream(3)`
= 25). Round-5 advanced the blocker **forward one step** to **Step 5 Formal**
(`blocked-by-upstream(3)` = **0**, `blocked-by-upstream(5)` now carries the cascade).
PASS count unchanged at 3 (same executed Steps 1/2/9), but the wall moved CDC → Formal.

---

## 3. Per-fix verdicts (fresh evidence, this run)

### #673 — multi-clock CDC hard-FAILed Step 3 (no cap-gap acceptance path) — **RESOLVED**
- **Fresh evidence (this run):**
  - `flow_compliance_check` → **`- [SKIPPED-CONDITION] Step 3: CDC / RDC check`**, reason:
    *"verdict artifact self-reports SKIPPED-CONDITION (#433c): reports/phase2/cdc/crossing.json:
    multi-clock design (root_clocks=['user_clock2','wb_clk_i'], scope: top module
    'user_project_wrapper' (resolved via --top-name)) …"* — NOT a hard FAIL.
  - All three CDC JSONs (`reports/phase2/cdc/{crossing,async_input,reset_dep}.json`) carry
    `verdict: "SKIPPED-CONDITION"` with the named multi-clock #436 reason.
  - **`blocked-by-upstream(3)` count = 0** (grep: 0 hits) — Step 3 no longer cascade-blocks Phase 3.
- **§4.05 negative spot-check (RESOLVED, by code, not fabrication):** the SKIPPED-CONDITION
  promotion in `flow_compliance_check.py:3407-3408` fires **ONLY** when
  `str(d.get("verdict","")).upper().replace("_","-") == "SKIPPED-CONDITION"` (exact match;
  `_SELF_SKIP_VERDICTS = {"SKIP","SKIPPED","SKIPPED-CONDITION"}` at line 1496). A canonical
  CDC report with `verdict=="FAIL"` is **not** in that set and would fall through to the
  gate's FAIL handling — the deferral is gated specifically to the disclosed multi-clock
  SKIPPED-CONDITION, NOT a blanket accept of any CDC JSON. (I did not fabricate a FAIL report;
  the discrimination is proven by the exact-string branch.)
- **Verdict: RESOLVED.** Step 3 is the disclosed honest deferral, Phase 3 is no longer
  blocked by Step 3.

### #674 — full-stack `results.json` kept STALE phantom `tb`/`dut` across re-invocation — **RESOLVED**
- **Fresh evidence (this run):** `phase2/stage1/sim_full_stack/results.json` (mtime 18:04:03,
  THIS run) reports `"tb": "tb_user_project_wrapper_full.v"`, `"dut": "user_project_wrapper"`,
  `verdict: "PASS"`, `connectivity_verified: true`, `ts_unix` → 18:04:03 (THIS run, not a
  prior phantom-generation time). This matches the TB that actually compiled
  (`generic_full_stack_run/full_stack.log`: `tb_user_project_wrapper_full.v:87 $finish at 1200000`)
  and the TB's real instantiation (`tb_user_project_wrapper_full.v:37 user_project_wrapper u_dut (...)`).
- The round-4 GAP-D defect (results.json advertising `dut: caravel_user_project` /
  `tb: tb_caravel_user_project_full.v` with a stale `ts_unix`) is **gone**: the identity
  fields now reflect the REAL compiled DUT, not the stale phantom.
- **Verdict: RESOLVED.** No stale phantom identity remains.

### #650 — pin_order.cfg ingestion — **UNREACHABLE in-flow (unchanged)**
Phase 3 PnR never ran (chain halts at Step 5; `caravel_r5/phase3/` holds only `analog/`).
Cannot re-verify in-flow. Round-3 structural code-presence verdict stands; no regression observed.

### #651 — signoff PASS_WITH_WAIVERS rc=3 — **UNREACHABLE in-flow (unchanged)**
Same reason: phase3 sign-off never reached. (Note: the #651 *waiver-promotion* mechanism
DID fire in-flow this round at **Step 4 Sim** — WAIVED-DEFERRED via
`cpu_functional_oracle_waiver_check` rc=3 + `PASS_WITH_WAIVERS` sentinel — so the rc-3
promotion path is confirmed working, just not at the Phase-3 signoff step.) No regression observed.

---

## 4. NEW chip-AGNOSTIC file-worthy gap candidates (ranked, triaged)

### GAP-E (PRIMARY, NEW this round, blocks the chain) — honestly-deferred formal-skip hard-FAILs Step 5 (no self-skip / cap-gap acceptance path)
- **Step:** Phase 2 / Step 5 `Formal verification`.
- **Symptom + evidence (this run):** `flow_compliance_check` →
  `✗ [FAIL] Step 5: Formal verification`, reason
  `missing files (any_of=False): ['phase2/stage1/formal/results.json']`. But the runner DID
  honestly self-report a skip: `phase2/stage1/formal/formal_not_run.json` (mtime 18:04:11,
  THIS run) carries `verdict: "SKIPPED-CONDITION"`, `fallback_skill: "assertion-gen"`,
  reason *"no formal proof tool ran in this chain … only that run may write formal/results.json
  with all_proved."* And Step 5 ALREADY has a registered cap-flag:
  `_PLATFORM_CAPABILITY_GAPS[5] = "cap:formal_property_proof"` (flow_compliance_check.py:3311),
  with a comment (3301-3308) explicitly stating *"a run without a real SymbiYosys proof leaves
  step 5's required outputs absent → SKIPPED-CONDITION here."*
- **Root cause (structural, traced):** Step 5's `required_outputs` is `any_of` over
  `{formal/*.sby, formal/results.json, sim_full_stack/results.json}`. `sim_full_stack/results.json`
  **IS present** (the Rule-D full-stack TB ran), so the step status is **NOT MISSING** → the
  `_apply_capability_gap` (line 3447, fires ONLY on `status=="MISSING"`) **never runs** →
  the `cap:formal_property_proof` conversion is bypassed. The `gate.all_of` then evaluates
  `files_exist:["phase2/stage1/formal/results.json"]` via `_check_files_exist` (line 2608-2616),
  which is the **only** gate form with **no** self-skip promotion — unlike `_check_json_field_true`
  (line 2592-2597) which promotes to SKIPPED-CONDITION when the SAME artifact self-reports a
  `_SELF_SKIP_VERDICT`. The honest `formal_not_run.json` SKIPPED-CONDITION is a **different
  file** than the one `files_exist` checks (`results.json`), and `_check_files_exist` does not
  consult sibling self-skip artifacts → **hard FAIL**. This is the **identical structural class
  to the just-fixed #673** (an honest SKIPPED-CONDITION self-report invisible to a gate that
  hard-FAILs on an absent canonical output), now at the formal step.
- **Why systematic (chip-AGNOSTIC):** #440 states *no formal proof engine is wired into the
  phase2 runner* — so EVERY IC that reaches Step 5 without an authored real `.sby` emits
  `formal_not_run.json` and hard-FAILs Step 5, cascade-blocking all 25 Phase-3 steps. This IC
  is a no-opcode `bus_peripheral` (L3 `opcodes: []`, `no_opcodes_in_input: true`, no CRC) — there
  are **no SW-visible protocol properties to author SVA from**, so authoring a `.sby` here would
  be fabricating trivial/empty properties: this is genuinely a **gate-acceptance gap, NOT an
  authoring miss**. Keys only on "is there a sibling `formal_not_run.json` with
  verdict=SKIPPED-CONDITION while step-5 has cap:formal_property_proof?" — pure structural
  verdict read, no chip literal.
- **Proposed fix area (Bucket A — deterministic):** teach the Step-5 acceptance path to honor
  the runner's honest `formal_not_run.json` (verdict=SKIPPED-CONDITION) — either (a) make the
  `files_exist` gate path consult a co-located/sibling self-skip artifact (the formal step's
  `formal_not_run.json`) the way `_check_json_field_true` already does, OR (b) when step 5's
  ONLY satisfied required_output is `sim_full_stack/results.json` AND `formal/results.json` is
  absent AND `formal/formal_not_run.json` self-reports SKIPPED-CONDITION, route through
  `_apply_capability_gap` with the existing `cap:formal_property_proof` flag → convert to
  SKIPPED-CONDITION (review_required, NOT executed-PASS), exactly as #673 did for CDC. A real
  authored proof (`.sby` + sby PASS transcript + `formal/results.json`) still gates normally via
  `formal_proof_evidence_check`. Pure verdict/path structural test, no LLM.
- **Severity:** HIGH (sole NEW blocker of this benchmark this round; reproduces for ANY IC that
  reaches Step 5 without an authored SymbiYosys proof — i.e. the entire open-source chain by
  #440 design).

### GAP-F (SECONDARY, PRE-EXISTING — present identically in round-4, now characterized) — analog block extractor fabricates a phantom `por` block from the substring "POR", FAILing P0 for a pure-digital SoC
- **Step:** Phase 1 analog-block extraction → P0 `analog_flow_compliance_check` /
  `analog_digital_interface_check` / `analog_a6_block_pv_check`.
- **Symptom + evidence:** `phase3/analog/analog_block_list.json` =
  `{"blocks":[{"name":"por","type":"por","spec":null,"low_confidence":true,
  "evidence":"input/docs/L3_external_interface.md (POR)",
  "evidence_paragraph":"…tied per `user_defines.v` GPIO POR config."}]}`. The substring **"POR"**
  was scraped out of the phrase **"GPIO POR config"** (POR = power-on-**reset** value/default GPIO
  configuration — a *digital* concept) and fabricated into an *analog* `por` block. P0 then FAILs
  4 sub-gates: `analog_flow_compliance_check` (`ANALOG_A4..A9_MISSING: Block 'por' … MISSING`),
  `analog_digital_interface_check`, `analog_a6_block_pv_check`, and `l_doc_structured_field_count_check`
  (L5_ADI_SPEC short: 1 analog block, needs ≥3 OR `no_analog:true`). The IC is classified
  `bus_peripheral` with `analog_applicable=false` (`verification_track='generic_full_stack'`) —
  the SIBLING analog gates (`analog_block_coverage_check`, `spice_correlation_check`,
  `analog_hardmacro_check`, `mixed_signal_cosim_check`) correctly SKIP as N/A, but
  `analog_flow_compliance_check` / `analog_digital_interface_check` / `analog_a6_block_pv_check`
  have **no class-N/A awareness** (grep: no `analog_applicable`/`generic_full_stack`/`low_confidence`
  token in `analog_flow_compliance_check.py`) and hard-FAIL on the phantom block.
- **Honesty note:** this is **NOT new in round-5** — `caravel_r4/phase3/analog/analog_block_list.json`
  also held `blocks: ['por']` and round-4's P0 FAILed the same 4 sub-gates. It was carried but
  un-called-out in round-4 (where the headline blocker was Step 3). Reported here as a
  pre-existing gap newly characterized, per the no-false-novelty rule.
- **Why systematic (chip-AGNOSTIC):** any design whose docs/RTL contain the digital token "POR"
  (power-on-reset — extremely common) gets a phantom analog `por` block tagged `low_confidence:true`,
  which then drives 3 analog P0 gates that ignore both the `low_confidence` tag AND the
  `analog_applicable=false` class to hard-FAIL a pure-digital SoC. Two independent chip-agnostic
  fix surfaces: (i) the extractor should not promote a `low_confidence` digital-keyword hit ("POR"
  inside "GPIO POR config") to an analog block; (ii) the 3 analog P0 gates should respect
  `analog_applicable=false` / `low_confidence:true` the way their sibling analog gates do.
- **Proposed fix area (Bucket A — deterministic):** (i) in the analog-block extractor, deny-list
  "POR"/"reset"-family substrings when the surrounding context is a digital reset/GPIO-default
  phrase (or require a stronger analog cue than a bare keyword before emitting a block); and/or
  (ii) gate `analog_flow_compliance_check` / `analog_digital_interface_check` /
  `analog_a6_block_pv_check` on the same `analog_applicable` / `verification_track=='generic_full_stack'`
  class predicate the sibling analog gates already honor, so they SKIP (N/A) instead of FAIL on a
  digital IC. Pure structural class/tag read, no LLM.
- **Severity:** MEDIUM (contributes 3 of the 4 P0 sub-gate FAILs; does not by itself block the
  chain past Step 5 — Step 5 is the hard blocker — but it keeps P0 red and would mislead any
  consumer that the digital SoC has an analog POR block requiring A4-A9).

### GAP-G (TERTIARY, PRE-EXISTING) — `l_doc_structured_field_count_check` typed-field-depth FAIL on a minimal SoC
- **Step:** Phase 1 / P0 `l_doc_structured_field_count_check`.
- **Symptom + evidence:** FAIL — 5 L docs carry fewer typed structured fields than required:
  L10 (`test_cases` 0 < 2), L4 (`regmap` 0 registers / 2 otp sub-fields < 5),
  L5 (`adi_spec` 1 analog block < 3 — **this is the phantom `por` from GAP-F**), L7
  (`test_debug` 1 scenario < 3), L8 (`timing_waveform` 6 < 10 typed constants).
- **Why systematic (chip-AGNOSTIC):** the typed-field-depth floors are tuned for protocol/
  mixed-signal ICs; a minimal stock SoC (a Wishbone-mapped counter with no opcodes, no regmap,
  no analog) legitimately has few typed fields. L5's shortfall is partly a knock-on of the GAP-F
  phantom block (fixing GAP-F removes 1 of the 5). The remaining floors (L4 regmap, L7/L8/L10)
  may need a `bus_peripheral`/`generic_full_stack`-class-aware floor or a documented `no_*:true`
  escape hatch, the way L5 already accepts `no_analog:true`.
- **Proposed fix area (Bucket A — deterministic):** make the per-L floors class-aware (lower /
  waive for `bus_peripheral` + `command_protocol_applicable=false` ICs) OR extend the
  `no_analog:true`-style typed escape to L4/L7/L10 so a genuinely minimal SoC can declare
  "no regmap / no protocol scenarios" instead of FAILing the floor. Pure threshold/class read.
- **Severity:** LOW-MEDIUM (1 P0 sub-gate; partly downstream of GAP-F).

### Triage summary (program-first ladder A>B>C>D)
| Gap | Bucket | Rationale |
|---|---|---|
| **GAP-E** Step-5 formal self-skip not honored | **A** | reduces to a sibling-artifact verdict read (`formal_not_run.json` verdict==SKIPPED-CONDITION) + the already-registered `cap:formal_property_proof` flag; no LLM. Identical fix shape to the shipped #673. |
| **GAP-F** phantom `por` analog block + analog-gate class-N/A | **A** | (i) keyword deny-list / context guard in the extractor, (ii) class-predicate gate on 3 analog P0 checks — both structural tag/class reads, no LLM. |
| **GAP-G** L-doc typed-field floor on minimal SoC | **A** | class-aware threshold OR `no_*:true` typed escape — pure threshold/class read. |

All three are **Bucket A (deterministic / program-first)** — none requires natural-language
judgment. Per the benchmark-agent doctrine I did **NOT** file GitHub issues or edit plugin/MCP
code; these are returned for the Core-Agent backlog. GAP-E is the actionable PRIMARY (it is the
NEW blocker and the same proven fix shape as #673); GAP-F/GAP-G are pre-existing P0 residuals
characterized honestly (they were carried silently through round-4).

---

## 5. Environment-only blockers (separated from plugin gaps)

- **No DE10/FPGA board (NOT a plugin gap):** Step 6 FPGA early prototype = WAIVED-DEFERRED
  ENV_UNAVAILABLE (`cap:fpga_board_prototype`, `quartus_map_audit.json verdict=SKIP,
  sof_present=false`); Step 39 FPGA final = WAIVED-DEFERRED ENV_UNAVAILABLE. Correct — headless
  host, no board.
- **SymbiYosys not on host PATH (environment, but distinct from the GAP-E gate gap):** `sby` is
  absent on the host (only `yosys-smtbmc` SMT backend present; the `iic-osic-tools` docker image
  IS present). The runner's #440 design is to NOT auto-run formal and emit `formal_not_run.json`.
  The **engine absence is environment**; the **gate hard-FAILing the honest deferral (GAP-E) is
  the plugin gap.** These are correctly separated: even with `sby` installed, a no-opcode IC has
  no properties to prove — the right answer is the honest SKIPPED-CONDITION the gate should honor.
- **Open-source tool capability gaps (NOT plugin gaps, already cap-flagged):** Steps 11 (DFT/ATPG),
  12 (post-DFT), 13 (LEC), 29 (post-layout gate-sim), 30 (post-layout SPICE) = SKIPPED-CONDITION
  with named `cap:` flags (#430). Steps 40-44 manufacturing = SKIPPED-CONDITION (silicon-dependent).
  Correctly self-disclosed, NOT counted as FAIL.

---

## 6. Path to this RESULT

`/home/reyerchu/AI_IC_design/_bench7_caravel_v1034_cleanroom/RESULT_r5.md`

Supporting artifacts (all under the run dir, no plugin/MCP writes):
- run logs: `_bench7_caravel_v1034_cleanroom/_logs/run_r5_round{1,2}.log`
- SOLE-CRITERION log: `_bench7_caravel_v1034_cleanroom/_logs/flow_compliance_r5_full.log`
- orchestrator JSON: `caravel_r5/reports/orchestrator/{phase2_one_shot,vibe_ic_one_shot}.json`
- **#673 evidence** — Step-3 SKIPPED-CONDITION + multi-clock CDC JSONs:
  `caravel_r5/reports/phase2/cdc/{crossing,async_input,reset_dep}.json` (verdict=SKIPPED-CONDITION)
- **#674 evidence** — refreshed identity:
  `caravel_r5/phase2/stage1/sim_full_stack/results.json` (tb=tb_user_project_wrapper_full.v,
  dut=user_project_wrapper, ts_unix=THIS run) + the compiled TB
  `tb_user_project_wrapper_full.v` (`user_project_wrapper u_dut`) + `generic_full_stack_run/full_stack.log`
- **GAP-E evidence** — honest formal self-skip vs FAILing gate:
  `caravel_r5/phase2/stage1/formal/formal_not_run.json` (verdict=SKIPPED-CONDITION) vs the
  Step-5 FAIL line in `flow_compliance_r5_full.log`
- **GAP-F evidence** — phantom analog block: `caravel_r5/phase3/analog/analog_block_list.json`
  (blocks=[por], low_confidence=true, evidence="GPIO POR config")
- authored RTL: `caravel_r5/phase2/stage1/rtl/{defines,user_defines,user_proj_example,user_project_wrapper}.v`

### Convergence status
**NOT converged.** Round-5 confirmed **#673 RESOLVED** (Step 3 CDC = SKIPPED-CONDITION,
`blocked-by-upstream(3)`=0; §4.05 negative spot-check holds by exact-string code path) and
**#674 RESOLVED** (results.json tb/dut = real `user_project_wrapper`, no stale phantom). The
chain advanced its blocker **forward one step** (Step 3 CDC → **Step 5 Formal**) but did **NOT
reach Phase 3** — Step 5 hard-FAILs on the **identical structural gap class as #673** (an honest
`formal_not_run.json` SKIPPED-CONDITION self-report that the `files_exist` gate does not consult,
bypassing the already-registered `cap:formal_property_proof` flag). The loop requires: Core-Agent
fixes **GAP-E** chip-agnostically (honor the formal self-skip → SKIPPED-CONDITION, mirroring the
#673 fix) → re-run clean-room → confirm Step 5 converts and the chain advances into Phase 3
(synth handoff → floorplan → PnR → CTS → route → STA → DRC → LVS → sign-off), at which point
#650 (pin_order) and #651 (signoff PASS_WITH_WAIVERS) finally become re-verifiable in-flow.
GAP-F/GAP-G are pre-existing P0 residuals to fix in parallel.
