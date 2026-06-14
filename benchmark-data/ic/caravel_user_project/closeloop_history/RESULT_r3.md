# caravel_user_project — Benchmark IC #7 — Round-3 Clean-Room RESULT

- **IC:** caravel_user_project (chipfoundry/caravel_user_project, Apache-2.0)
- **Round:** 3 (clean-room close-loop verification of the v1.0.38 caravel fix sweep)
- **Plugin under test:** PUBLIC tree `/home/reyerchu/vibe-ic/vibe-ic-marketplace/plugins/vibe-ic`,
  HEAD `6d77ff63` (v1.0.42; the v1.0.38 caravel sweep #648–#652 and the v1.0.40 #645
  power-define fix are all committed at/below this HEAD). Runner +
  `flow_compliance_check` invoked directly from the public `programs/` dir — NOT slash
  commands, NOT the root tree.
- **Project dir:** `_bench7_caravel_v1034_cleanroom/caravel_r3/`
- **Shape:** A / D (full runner, SoC integration).
- **Blindness:** authored ONLY the design's own input sources
  (`input/design_src/verilog/rtl/*.v` + the design's own harness `defines.v` from
  `_src/caravel_upstream/verilog/rtl/`) into the runner's canonical RTL path. Did NOT
  read the `spm_pilot` checkout, any reference GDS, or the host scorer.

---

## 1. What was run (clean-room full re-run)

Phase 1 was pre-run (L1–L23 present, 24/13 L-docs). Three runner invocations:

| Invocation | RTL state | Outcome |
|---|---|---|
| round1 | no `rtl/` | runner WAIVED `rtl_gen` (`bus_peripheral`, rtl_gen=null, `fallback_skill=spec-to-rtl`); `reference_tb` FAIL `rtl/ missing` (expected). |
| round2 | authored 3 stock user RTL files into `phase2/stage1/rtl/` | `reference_tb` FAIL **compile**; `yosys_synth` FAIL — both root-caused to **`MPRJ_IO_PADS` undefined** (`defines.v` absent from the input bundle). |
| round3 | + design's own `defines.v` | `yosys_synth` **PASS** (cells=189, top=user_project_wrapper); `reference_tb` still FAIL — **phantom DUT module name** (new, deeper defect). |

The spec-to-rtl recovery was performed **inside the runner path** (authored into
`_pl.rtl_dir(project)` = `phase2/stage1/rtl/`, then re-invoked), per
open-benchmark-methodology — not a hand-rolled MCP harness.

---

## 2. SOLE ACCEPTANCE CRITERION (verbatim, this run)

```
python3 .../programs/flow_compliance_check.py _bench7_caravel_v1034_cleanroom/caravel_r3 --strict
Overall: FAIL  (strict=True)
```

Counts (this run): **PASS=3, FAIL=5, MISSING=38 (25 blocked-by-upstream of step 3),
WAIVED-DEFERRED=2, SKIPPED-CONDITION=10, VACUOUS-PASS=1.**

PASS steps (the chain's actual reach): **Step 1 Spec-to-RTL, Step 2 Lint, Step 9
Synthesis**. First mid-chain FAIL = Step 3 (CDC/RDC), Step 4 (Sim), Step 5 (Formal) —
all cascading from a single root cause: the `reference_tb` full-stack TB never compiled,
so no `sim/results.xml`, no CDC report, no formal results. Phase 3 (PnR/sign-off/mfg) is
entirely `blocked-by-upstream(step 3)` and unreachable this round.

**Reach vs round-2:** round-2 was blocked at `reference_tb` (3/48) on the **#645
power-define** wall. Round-3 is *also* blocked at `reference_tb` (3 PASS), but the chain
progressed **past** #645 and #649 — `yosys_synth` now PASSes — and `reference_tb`'s
blocker is now a **different, deeper** defect (phantom DUT name). Net: forward progress,
new failure surface exposed.

---

## 3. Per-fix verdicts (fresh evidence, this run)

### #645 — reference_tb power-define — **RESOLVED**
The generated TB declares power pins as tied wires and guards the DUT power-pin
connections behind `` `ifdef USE_POWER_PINS ``:
`phase2/stage1/sim_full_stack/tb_caravel_user_project_full.v:32-33,59-61`
(`wire vccd1;`/`wire vssd1;` + `` `ifdef USE_POWER_PINS , .vccd1(vccd1) , .vssd1(vssd1) ``).
The round-3 `reference_tb` error class is **PHANTOM-DUT-NAME**, not POWER-PIN — no `vccd*`
appears in any error line. The #645 fix held; the chain advanced past the round-2 blocker.

### #649 — yosys conformance (no more bare VACUOUS_PASS) — **RESOLVED (sim-only path); real-PDK path UNEXERCISED this round**
`reports/phase2/gates/yosys_hilomap.json` + `yosys_script_template.json` (this run) now read:
`verdict=VACUOUS_PASS, reason_class="inline_yosys_p_mode_confirmed",
inline_evidence=["phase2/stage2/synth/yosys.log"]`. It is no longer an unconditional pass:
`_yosys_inline_mode_detect.py` (a) distinguishes `VACUOUS_PASS` (inline mode *positively
confirmed* by the actual yosys.log) from `VACUOUS_PASS_UNCONFIRMED`, and (b) extracts the
real `-- Running command \`...\`` from the log and conformance-checks `hilomap`/`-flatten`
against it. This run's command (`read_verilog -sv -DSIMULATION ...; synth -top
user_project_wrapper -flatten; ...; abc -g cmos2; ...`) binds **no Liberty** → classified
`simulation_only` → hilomap legitimately waived, `-flatten` present → honest pass.
**Caveat:** the *real-PDK* (Liberty-bound) conformance enforcement is NOT exercised this
round because the chain halted in phase2 before phase3's real-PDK synth. Structurally
present and honest; not end-to-end-proven on a real-PDK command here.

### #650 — pin_order.cfg ingestion (set_io_pin_constraint) — **RESOLVED (unit-level); UNREACHABLE in flow**
Chain didn't reach phase3 PnR, so verified by direct unit test against the design's real
`openlane/user_proj_example/pin_order.cfg`:
`phase3_one_shot_runner._v1_0_38_parse_pin_order_cfg` → **3 edge sections (S/E/W, 52 pins)**;
`_v1_0_38_build_pin_placement_tcl` emits **53 `set_io_pin_constraint`** directives
(NONFATAL-guarded), e.g. `set_io_pin_constraint -pin_names {wb_.*} -region bottom:*`.
This is genuine ingestion (feeds the placer), not a presence-only dead-end check.

### #651 — signoff false-PASS → PASS_WITH_WAIVERS rc=3 — **RESOLVED (code-present); UNREACHABLE in flow**
`signoff_audit.py` documents exit code 3 = PASS_WITH_WAIVERS (lines 32, 53, 289) with
`WAIVER_STDOUT_SENTINEL = "PASS_WITH_WAIVERS:"` (line 64), and `flow_compliance_check.py`
(lines 1414-1421) treats a **bare** rc=3 *without* the sentinel as NOT-PASS — closing the
false-PASS gap per CLAUDE.md rule 11. The chain halts in phase2, so the rc=3 path could not
be exercised end-to-end (a full PASS_WITH_WAIVERS fixture would require fabricating an entire
signed-off project — out of scope and not blind-safe). Verified structurally only.

### #652 — manufacturing-skipped vs mid-flow label — **RESOLVED (unit-level); UNREACHABLE in flow**
`final_report_generate._split_skipped_by_stage` unit-tested: a mid-flow SKIPPED-CONDITION
(Step 6 FPGA / Step 39) lands in `midflow`; manufacturing steps (40-44) land in
`manufacturing`; buckets are mutually exclusive and sum to the total. Numeric-id fallback
(`_is_manufacturing_step`, range 40-44) also correct. No more conflating a mid-flow FPGA
skip with "awaiting silicon."

---

## 4. NEW chip-AGNOSTIC file-worthy gap candidates

### GAP-A (PRIMARY, blocks the chain) — full-stack TB instantiates a PHANTOM DUT when L9.top_module is an `l1_ic_name_fallback`
- **Step:** Phase 2 `full_stack_tb_gen` / `reference_tb`.
- **Symptom + evidence:** `reference_tb` FAIL —
  `tb_caravel_user_project_full.v:39: error: Unknown module type: caravel_user_project`,
  `*** These modules were missing: caravel_user_project referenced 1 times.` The
  synthesizable RTL contains `user_project_wrapper` / `user_proj_example` / `counter`, NOT
  `caravel_user_project`.
- **Root cause:** `phase2_one_shot_runner.py:1935` — `top_module = l9.get("top_module") or
  top_name`. L9 has `top_module="caravel_user_project"` with
  `top_module_extraction_strategy="l1_ic_name_fallback"` (Phase 1 found no real
  top-module declaration in the docs and fell back to the L1 ic-name). The runner *already
  receives* `args.top_name="user_project_wrapper"` (passed at line 6864) and yosys already
  resolved the real top, but the TB-gen prefers the phantom L9 field. The #629 reconcile
  helper `_v629_rtl_top_ports(project, top_module)` is also fed the phantom name, so
  `parse_module_ports` finds nothing, the port reconcile is silently skipped, and BOTH the
  DUT module name AND the verbatim L9 ports survive.
- **Why systematic:** ANY IC where `ic_name != top_name` AND L9.top_module is an
  `l1_ic_name_fallback` (i.e. Phase 1 couldn't extract a real top) produces a TB that
  instantiates a non-existent module → reference_tb compile FAIL → Steps 4/5 + all of
  phase3 cascade-blocked. Chip-agnostic: keys only on "does this module name exist in
  rtl/?", a structural check.
- **Proposed fix area (Bucket A — deterministic):** in `phase2_one_shot_runner.py` TB-gen
  (and the parallel `step_reference_tb` / `_reference_tb_generic_full_stack`), resolve the
  DUT module structurally before use: if `L9.top_module` does not match any
  `module <name>` in `rtl/` (reuse `reset_clock_variant_alias.parse_module_ports` /
  `_v629_rtl_top_ports`), prefer `top_name` if IT resolves, else the RTL's actual root
  module; only then fall back to the L9 string. No LLM judgment — pure module-presence test.
- **Severity:** HIGH (sole blocker of this benchmark; reproduces for any SoC/wrapper where
  the doc-set lacks an explicit top-module name).

### GAP-B (SECONDARY) — spec-to-rtl recovery pulls only the named user RTL, not the design's dependency/harness RTL it `` `include``s / depends on
- **Step:** Phase 2 `rtl_gen` WAIVE → `spec-to-rtl` recovery (authoring `input/design_src`
  RTL into `phase2/stage1/rtl/`).
- **Symptom + evidence:** with only the 3 named user files present, both `reference_tb`
  (iverilog) and `yosys_synth` (slang) FAIL on `MPRJ_IO_PADS undefined` /
  `unknown macro '\`MPRJ_IO_PADS'` (`yosys.log` errors at `user_project_wrapper.v:64-72`),
  because the port-width macro lives in the design's own `defines.v` — which is part of the
  upstream design's `verilog/rtl/` but was NOT in `caravel_r3/input/design_src/`. Adding the
  design's own `defines.v` flipped `yosys_synth` FAIL→PASS in one re-run.
- **Why systematic:** any design whose top RTL `` `include``s or macro-depends on a sibling
  defines/params file that the input bundle omits will fail spec-to-rtl + synth with a macro/
  include error, with no diagnostic pointing at the missing dependency. The runner has no
  mechanism to pull the full `input/design_src/.../rtl/` tree (or resolve `` `include`` /
  undefined-macro dependencies) into the canonical RTL path; the agent must do it by hand.
- **Proposed fix area (Bucket A — deterministic):** a structural dependency-completeness
  pre-check at spec-to-rtl/synth entry — when the authored `rtl/` references an undefined
  macro or unresolved `` `include`` whose defining file exists under
  `input/design_src/**/rtl/`, either (a) auto-stage that file into `rtl/`, or (b) emit a
  hard, specific diagnostic ("`\`MPRJ_IO_PADS` undefined; candidate `defines.v` found at
  input/design_src/.../rtl/defines.v — stage it"). Both are pure path/macro graph analysis,
  no LLM. (The "stage it" form is the stronger fix; the "diagnostic" form is the floor.)
- **Severity:** MEDIUM (the missing file is partly an input-prep omission — see §5 — but the
  silent macro-error-with-no-remediation-hint is a real, chip-agnostic runner UX/robustness
  gap that cost two re-run rounds to diagnose).

Both gaps are **PROGRAM-FIRST / Bucket A**: each reduces to a structural check
("does this module/macro/file resolve in rtl/?"), no natural-language judgment. Per the
benchmark-agent doctrine I did NOT file GitHub issues or edit plugin code — these are
returned for the Core-Agent backlog.

---

## 5. Environment-only blockers (separated from plugin gaps)

- **Input bundle incomplete (NOT a plugin gap):** `caravel_r3/input/design_src/verilog/rtl/`
  shipped only `user_proj_example.v`, `user_project_wrapper.v`, `user_defines.v` — but NOT
  `defines.v`, which the upstream `caravel_user_project` RTL normally ships and which defines
  `MPRJ_IO_PADS`. The clean-room input-prep under-copied. (Earlier round dirs `caravel/` and
  `caravel_r2v/` had `defines.v` placed directly in their `phase2/stage1/rtl/`.) GAP-B above
  is the *plugin* angle (silent error + no remediation hint); the missing file itself is an
  input-prep defect to fix in the manifest/scaffold, not in the plugin.
- **No DE10/FPGA board (NOT a plugin gap):** Step 6 FPGA early prototype = WAIVED-DEFERRED,
  Step 39 FPGA final sign-off = FAIL `no-hardware-evidence`. Expected — headless host, no
  board. Correctly bucketed by the gate.
- **Manufacturing steps 40-44 SKIPPED-CONDITION:** correct (silicon-dependent, no
  `silicon_received.json`).

---

## 6. Path to this RESULT

`/home/reyerchu/AI_IC_design/_bench7_caravel_v1034_cleanroom/RESULT_r3.md`

Supporting artifacts (all under `benchmark-data`-equivalent run dir, no plugin/MCP writes):
- run logs: `_bench7_caravel_v1034_cleanroom/_logs/run_r3_round{1,2,3}.log`
- phase2 orchestrator JSON: `caravel_r3/reports/orchestrator/phase2_one_shot.json`
- yosys synth (PASS): `caravel_r3/phase2/stage2/synth/yosys.log` + `netlist_yosys.v`
- #649 gate JSONs: `caravel_r3/reports/phase2/gates/yosys_{hilomap,script_template}.json`
- generated full-stack TB (phantom-DUT evidence):
  `caravel_r3/phase2/stage1/sim_full_stack/tb_caravel_user_project_full.v`
- authored RTL: `caravel_r3/phase2/stage1/rtl/{defines,user_defines,user_proj_example,user_project_wrapper}.v`

### Convergence status
NOT converged. Round-3 surfaced **2 new chip-agnostic Bucket-A gaps** (GAP-A primary,
GAP-B secondary). The loop requires: Core-Agent fixes GAP-A (+GAP-B) chip-agnostically →
re-run clean-room → confirm `reference_tb` compiles and the chain advances into phase3.
