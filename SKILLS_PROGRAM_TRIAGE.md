# Skills → Programs triage (v0.1.50 doctrine sweep)

> **Core doctrine** (user, 2026-05-29): _"我們的 plugin 不是都已經寫成程式了嗎？我把它寫成程式的目的就是以程式為主，如果有需要用到 AI 或者 Claude，那 Claude 應該是備用。也就是說，當我的程式先跑過一遍以後，再用 Claude 來去補足或備援。**核心教訓：把修法寫進工具，而非寫進 prompt。**"_
>
> Programs ALWAYS run first. AI/Claude is a backstop, not the lead. If a skill expresses a rule that an LLM is meant to apply by reading prose, **the rule is in the wrong place** — it should be in a program with pytest.

## Scope

60 skills under `vibe-ic-marketplace/plugins/vibe-ic/skills/`. We classify each into one of six patterns and propose the next action.

## Pattern legend

| Pattern | Meaning | Action |
|---|---|---|
| **A** | **Pure wrapper** — skill just runs program(s) and formats the output | Compress to a thin "run + post-process" stub; the deterministic content lives in programs already |
| **B** | **Enumerable rubric** — skill encodes a finite checklist / category set / severity table that an LLM is asked to apply by reading prose | **Extract the rubric to a program**; skill becomes a Pattern-A wrapper that calls it |
| **C** | **Verify / spot-check** — skill runs AFTER a runner emits artifacts and "looks for issues" | **50–80% can become programs**: schema conformance, value-range checks, file presence — all deterministic |
| **D** | **Orchestrator** — skill describes a workflow / loop | Stays as skill, but workflow steps should be emitted by a program (Mermaid / YAML) so it's machine-readable |
| **E** | **True AI judgment** — skill genuinely requires LLM (NL ↔ Verilog, design trade-offs, narrative authoring) | Stays as skill; but the skill MUST consume program outputs at input, never re-derive deterministic facts |
| **F** | **Hardware / measurement** — skill calls MCP-EDA hardware tools then narrates results | Split: setup + safety = program; result narration = skill (LLM read of scope traces is genuinely judgment) |

## Triage table (all 60 skills)

Sorted by extraction-yield potential (highest first). "Backing programs" = existing programs the skill already cites or could cite.

| # | Skill | Pattern | Backing programs (existing or proposed) | Action |
|---|---|---|---|---|
| 1 | `rtl-review` | **B** | reset_discipline_check, rtl_hygiene_lint, rtl_precheck_gate, spec_conformance_check + **new** `rtl_review_aggregate.py` (combines + scores) | **EXTRACT** — 6 checklist categories + 0-10 scoring rubric → program (PoC this turn) |
| 2 | `drc-fix` | **B** | eda_drc_klayout + **new** `drc_fix_planner.py` (rule→fix-strategy classifier, fix-order rules) | EXTRACT — 4-step fix workflow + classification table fully deterministic |
| 3 | `lvs-triage` | **B** | eda_lvs + **new** `lvs_triage_classify.py` (4 mismatch categories + top-3 root-cause check) | EXTRACT — entire triage table |
| 4 | `sta-review` | **B** | eda_sta + **new** `sta_triage_classify.py` (5 endpoint categories) | EXTRACT — cell-delay vs net-delay vs logic-depth vs skew vs hold classification rules |
| 5 | `hold-fix` | **B** | eda_sta + **new** `hold_fix_planner.py` (slack-bucket → strategy map; explicit table in skill) | EXTRACT — slack-bucket → strategy is literally a 3-row table |
| 6 | `ir-drop-triage` | **B** | eda_ir_drop + **new** `ir_drop_triage_classify.py` (4 cause categories + 4 fix categories) | EXTRACT — both classifications are explicit |
| 7 | `synth-doctor` | **A** | **synth_doctor.py** already exists (10 patterns) | COMPRESS — skill is already a program-wrapper; deduplicate prose with `--help` output |
| 8 | `atpg-name-harmonize` | **A** | **fix_fault_cut_names.py** already exists | COMPRESS — skill is a 108-line wrapper around one CLI invocation |
| 9 | `phase3-backend-verify` | **C** | phase23_completion_audit, eda_report_audit + **new** `phase3_verify_aggregate.py` | EXTRACT — file-presence + STA-margin + DRC/LVS-PASS checks are deterministic |
| 10 | `phase2-rtl-verify` | **C** | rtl_precheck_gate, spec_conformance_check, eda_lint + **new** `phase2_verify_aggregate.py` | EXTRACT — RTL quality gates are program-checkable |
| 11 | `phase1-output-verify` | **C** | phase1_completeness_check, phase1_input_vs_generated_completeness_check + **new** `phase1_verify_aggregate.py` | EXTRACT — L1-L13 schema conformance is fully deterministic |
| 12 | `compliance-gate-spot-check` | **C** | flow_compliance_check (exists) | COMPRESS — skill spot-checks a program output; the spot-check rules ARE programmable |
| 13 | `tapeout-checklist` | **B** | tapeout_checklist program exists + waivers_schema_check, signoff_waiver_emit | COMPRESS — skill is already a program wrapper; trim prose |
| 14 | `spec-validator` | **A** | ds_quality_check, an_validator, spec_validator, spec_conformance_check ALL EXIST | COMPRESS — skill = "run 4 programs in sequence"; turn into a YAML pipeline + thin narrative |
| 15 | `equivalence-check` | **A** | yosys-based equivalence in eda_lvs yosys_equiv mode | COMPRESS — skill = "call eda_lvs mode=yosys_equiv"; 75 lines → 20 lines |
| 16 | `formal-verify` | **A** | eda_formal (SymbiYosys) | COMPRESS — skill = "call eda_formal with config X"; runbook → program-driven |
| 17 | `ams-sim` | **A** | eda_spice, eda_spice_corner | COMPRESS — skill = "call eda_spice with corner sweep" |
| 18 | `mixed-signal-cosim` | **A** | eda_simulate + eda_spice | COMPRESS — skill = "wire ngspice + iverilog VPI" |
| 19 | `analog-extraction-resim` | **A** | eda_extraction + eda_spice_corner | COMPRESS |
| 20 | `analog-spec-extract` | **C** | phase1_engine (exists for spec extraction) + **new** `analog_spec_extract.py` for A-track | EXTRACT — block-list + spec.json schema is deterministic |
| 21 | `analog-hardmacro-gen` | **A** | eda_chip_top_gate_wrapper_gen + eda_extraction + eda_gds | COMPRESS |
| 22 | `analog-netlist-gen` | **A** | eda_xschem_netlist + eda_spice | COMPRESS |
| 23 | `analog-layout` | **A/E** | eda_analog_layout (matching/common-centroid rules) | COMPRESS the deterministic part; keep judgment on irregular blocks |
| 24 | `analog-output-verify` | **C** | **new** `analog_a1_a9_completeness_check.py` | EXTRACT — A1..A9 artifact presence + spec.json conformance |
| 25 | `analog-hw-testbench-gen` | **A** | eda_fpga_compile + eda_rtl_signaltap_autogen | COMPRESS |
| 26 | `analog-hw-measure` | **F** | device_scope_capture, device_fpga_de10lite_adc_read | Split: capture/safety = program; pattern interpretation = skill |
| 27 | `analog-hw-tuning-loop` | **D** | runner candidate (analog_one_shot_runner) | Stays D; can encode the loop as a program with retry rules |
| 28 | `analog-sizing` | **E** | partial (eda_spice for sweep simulation) | Stays E (topology choice + ratio reasoning genuinely LLM) |
| 29 | `analog-sizing-loop` | **D** | encodable as program-driven loop | Stays D; loop control is deterministic, sizing decision is LLM |
| 30 | `analog-topology-select` | **E** | none | Stays E (true design judgment) |
| 31 | `analog-flow-orchestrate` | **D** | analog_one_shot_runner candidate | Stays D; orchestration is workflow-shaped |
| 32 | `architecture-explore` | **E** | ppa-predict (partial) | Stays E (PPA trade-off reasoning) |
| 33 | `ppa-predict` | **B/E** | ppa_predict_check, eda_synth (cell count) + **new** `ppa_predict_aggregate.py` | EXTRACT — cell-count + area + delay estimation rules are deterministic; trade-off narrative is LLM |
| 34 | `spec-to-rtl` | **E** | rtl_hygiene_lint --fix (post-emit) | Stays E (genuine NL → Verilog authoring) |
| 35 | `spec-review` | **E** | spec_validator (partial) | Stays E (ambiguity detection) but PREFIX with spec_validator program output |
| 36 | `hls-c2rtl` | **E** | external tools (Vitis HLS / XLS) | Stays E |
| 37 | `eco-plan` | **B** | eco_plan_check + **new** `eco_plan_classify.py` (metal-only vs base-layer rules) | EXTRACT — ECO category classification is deterministic |
| 38 | `design-for-eco` | **B** | spare_cell_preservation_check (exists) + design_for_eco programs | COMPRESS — methodology is program-backed |
| 39 | `rtl-repair` | **B** | rtl_hygiene_lint --fix (exists, deterministic) | COMPRESS — skill is "run --fix then verify"; mostly program-driven |
| 40 | `yield-diagnostic` | **C** | wafer_sort_yield_check (exists) + **new** `yield_bin_classify.py` | EXTRACT — bin classification + Pareto analysis is deterministic |
| 41 | `regression-issue-fix` | **A** | regression-related programs in plugin | COMPRESS — issue-intake check is already a program |
| 42 | `regression-manage` | **D** | runner candidate | Stays D |
| 43 | `core-agent-loop` | **D** | runner-shaped loop | Stays D (loop policy + retry rules already programmable) |
| 44 | `field-agent-loop` | **D** | runner-shaped loop | Stays D |
| 45 | `checkpoint-gate` | **A** | checkpoint_gate / flow_compliance_check programs exist | COMPRESS — skill = "run program, gate on PASS" |
| 46 | `community-backlog-submit` | **A** | community_backlog_check / backlog_yaml_schema | COMPRESS |
| 47 | `catalog-glue-author` | **B/E** | ip_catalog_query (exists) + **new** `catalog_glue_emit.py` | Split — glue wrapper emit is templatable program; IP semantic match is LLM |
| 48 | `protocol-timeline-assert` | **B** | **new** `protocol_timeline_tb_emit.py` — L2 timing JSON → cocotb TB | EXTRACT — fully deterministic emit |
| 49 | `protocol-turnaround-audit` | **B** | protocol_turnaround_check (exists) | COMPRESS — semantic walk IS programmable |
| 50 | `fpga-led-probe-allocation` | **B** | **new** `fpga_led_alloc.py` — 4 probe modes → allocation rules | EXTRACT — 4-mode rule table fully deterministic |
| 51 | `fpga-signaltap` | **A** | eda_rtl_signaltap_autogen (exists) | COMPRESS |
| 52 | `fpga-hps-bridge` | **A** | **new** `fpga_hps_bridge_emit.py` — register-map → HPS shim | EXTRACT — code-gen from register map is deterministic |
| 53 | `scope-pattern-attestation` | **F** | device_scope_capture + eda_pass_reference_scope_diff + eda_scope_protocol_decode (exist) | Split — capture + diff are program; pattern interpretation has LLM judgment |
| 54 | `hw-debug-loop` | **D** | runner-shaped | Stays D; debug-step ordering is programmable |
| 55 | `phase1` | **D** | phase1_engine + phase1_one_shot_runner ALREADY EXIST | Skill = entry-point doc; deterministic content is already in runners |
| 56 | `phase1-completeness-deep-review` | **C** | phase1_input_vs_generated_completeness_check (exists) | COMPRESS — skill spot-checks program output |
| 57 | `phase1-coverage-loop` | **D** | runner-shaped | Stays D |
| 58 | `benchmark-verify` | **A** | benchmark_verify_aggregate (candidate) + many existing benchmark programs | COMPRESS — already heavily program-backed |
| 59 | `benchmark-enhancement-capture` | **E** | benchmark enhancement programs exist | Stays E (Bucket A/B/C/D triage is judgment) — but PREFIX with program-emitted summary |
| 60 | `open-benchmark-methodology` | **D** | run-shape decision matrix is a 5-row deterministic table | EXTRACT — the run-shape decision matrix can be `programs/open_benchmark_run_shape.py` |

## Summary

| Pattern | Count | % |
|---|---|---|
| A (compress to thin wrapper) | 19 | 32% |
| B (extract rubric to program) | 16 | 27% |
| C (verify/spot-check → program) | 9 | 15% |
| D (orchestrator workflow) | 9 | 15% |
| E (true LLM judgment) | 6 | 10% |
| F (hardware-measurement split) | 1 | 2% |

**44 of 60 skills (73%) have at least a partial program-extraction path.**
Only 6 of 60 skills (10%) genuinely require LLM judgment with no extractable backing.

## Doctrine compliance pre-extraction

For all current skills, the Pattern-B/C rubric content is **prose the LLM is asked to apply by reading**. That's the doctrine violation: rules live in the prompt, not the tool. The user's correction:

> 「核心教訓：把修法寫進工具，而非寫進 prompt。」

Every Pattern-B/C extraction moves a rule from prompt-space to tool-space.

## Proof-of-concept: `rtl-review` (Pattern B → extracted)

This turn we extract **`rtl_review_aggregate.py`** as the canonical proof of the doctrine — it:

1. Runs the 3 existing programs (`rtl_hygiene_lint`, `reset_discipline_check`, `rtl_precheck_gate`) deterministically
2. Aggregates findings into the 6-category bucket structure rtl-review.md describes
3. Computes the 0–10 score via the rubric's own table
4. Emits the report shape the skill expected the LLM to author
5. Returns PASS / WARN / FAIL verdict + a JSON for downstream gating

The skill is then compressed to a Pattern-A wrapper: "run rtl_review_aggregate, narrate residuals the program flagged, refuse to claim a higher score than the program returned."

After this PoC, the user can prioritize the next 5-10 extractions from the table above. Suggested next-wave (highest leverage, lowest risk):

1. `drc-fix` → `drc_fix_planner.py` — entire fix-strategy table
2. `lvs-triage` → `lvs_triage_classify.py` — 4-category triage
3. `ppa-predict` → `ppa_predict_aggregate.py` — cell+area+delay estimation
4. `hold-fix` → `hold_fix_planner.py` — slack-bucket→strategy table
5. `phase3-backend-verify` → `phase3_verify_aggregate.py` — file+margin+PASS aggregation

Each is small (~150–300 lines + pytest), encodes a clearly-bounded rule set, and lets the skill compress to a thin wrapper. Doing all five would land ~50+ new pytest cases pinning rules that today live only in prompt prose.
