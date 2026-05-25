# Rename Mapping v2.0.0 — 執行對照表

**Status**: PROPOSED
**Companion**: `RFC_v2.0_PHASE_REDESIGN.md`、`CANONICAL_FLOW_v2.0.0_PROPOSED.md`

> 這份是 mechanical translation table。執行 rename 時依本表逐項對應。順序很重要：必須先 `phase2a → phase1_<sub>`，再 `phase2b → phase2`，否則 `phase2` 會被誤匹配為 `phase2a` 的前綴。

---

## 1. Phase token 全域替換規則（sed 用）

**執行順序**（不可調換）：

| # | from | to | 備註 |
|---|---|---|---|
| 1 | `phase2a` | `phase1` | 大部分 phase2a 直接收進 phase1。但用做子目錄時要小心，見 §6 |
| 2 | `phase2b` | `phase2` |  |
| 3 | `phase2_phase3` | `phase1_phase2_phase3` | flow YAML 檔名 |
| 4 | `phase23` | `phase23` | 不變（仍指「phase 2 + phase 3 chain」） |
| 5 | `manufacturing/` (top-level) | `phase3/stage5_manufacturing/` | 路徑提升 |
| 6 | `analog/` (top-level) | 看 step 屬於哪 phase（見 §7） | 不能 sed，需逐路徑判斷 |
| 7 | `phase3/mixed_signal/` | `phase3/mixed_signal/` | 不變 |

**特殊處理**：
- 步驟 1 之後，原本指「Phase 1 dialogue」的字面值「phase1」也要保留——它現在涵蓋 dialogue + docs 兩入口。詞語意義從「dialogue-only entry」擴展到「unified spec phase」。
- `phase1_*` 系列檔案要區分：原 dialogue-only 的 `phase1_one_shot_runner.py` 要吸收原 `phase2a_one_shot_runner.py` 的功能。

---

## 2. Skill 目錄改名（6 項）

| 舊 path | 新 path | 動作 |
|---|---|---|
| `skills/phase1` | `skills/phase1` | 內容擴展（dialogue + docs 兩入口） |
| `skills/phase1-coverage-loop` | `skills/phase1-coverage-loop` | 內容擴展涵蓋 docs entry |
| `skills/phase2a-output-verify` | `skills/phase1-output-verify` | rename + 內容合併 |
| `skills/phase2a-completeness-deep-review` | `skills/phase1-completeness-deep-review` | rename |
| `skills/phase2b-rtl-verify` | `skills/phase2-rtl-verify` | rename |
| `skills/phase3-backend-verify` | `skills/phase3-backend-verify` | 不變 |

**Skill 內部 SKILL.md frontmatter 改寫**：所有提到 "Phase 2a" 的描述改成 "Phase 1 (Path A: docs entry)"，提到 "Phase 2b" 的改成 "Phase 2"。

---

## 3. Program 檔名改名（22 項）

| 舊檔名 | 新檔名 | 動作 |
|---|---|---|
| `_phase1_sentinel.py` | `_phase1_sentinel.py` | 不變（路徑 sentinel） |
| `phase1_consistency_check.py` | `phase1_consistency_check.py` | 內容擴展 docs entry |
| `phase1_doc_presence_check.py` | `phase1_doc_presence_check.py` | 不變 |
| `phase1_input_vs_generated_completeness_check.py` | `phase1_input_vs_generated_completeness_check.py` | 內容擴展 |
| `phase1_k5_quality_check.py` | `phase1_k5_quality_check.py` | 不變 |
| `phase1_one_shot_runner.py` | `phase1_one_shot_runner.py` | **吸收 phase2a_one_shot_runner.py 功能**（dispatch by input mode） |
| `phase1_provenance_presence_check.py` | `phase1_provenance_presence_check.py` | 不變 |
| `phase1_quality_parity_check.py` | `phase1_quality_parity_check.py` | 不變 |
| `phase2a_all_l_docs_present_check.py` | `phase1_all_l_docs_present_check.py` | rename |
| `phase2a_coverage_report_gen.py` | `phase1_coverage_report_gen.py` | rename |
| `phase2a_coverage_report_present_check.py` | `phase1_coverage_report_present_check.py` | rename |
| `phase2a_doc_content_implementation_completeness_check.py` | `phase1_doc_content_implementation_completeness_check.py` | rename |
| `phase2a_gate_contract_check.py` | `phase1_gate_contract_check.py` | rename |
| `phase2a_input_vs_generated_completeness_check.py` | `phase1_doc_input_completeness_check.py` | rename + 重命名（避免與 §2 相關 phase1 file 同名） |
| `phase2a_no_waivers_used_check.py` | `phase1_no_waivers_used_check.py` | rename |
| `phase2a_one_shot_runner.py` | **刪除**（功能併入 `phase1_one_shot_runner.py`） | delete |
| `phase2a_structured_field_substance_check.py` | `phase1_structured_field_substance_check.py` | rename |
| `phase2b_one_shot_runner.py` | `phase2_one_shot_runner.py` | rename（取代舊的 phase2_one_shot） |
| `phase2_one_shot_runner.py` | **刪除**（舊版是 2a+2b chain，新版意義不同） | delete |
| `phase23_completion_self_audit_check.py` | `phase23_completion_self_audit_check.py` | 不變 |
| `phase23_one_shot_runner.py` | `phase23_one_shot_runner.py` | 不變（仍是 phase2+phase3 chain） |
| `phase3_backend_step.py` | `phase3_backend_step.py` | 不變 |
| `phase3_one_shot_runner.py` | `phase3_one_shot_runner.py` | 不變 |
| `analog_one_shot_runner.py` | **刪除**（A1-A9 拆進 phase1/2/3 runner） | delete |
| `vibe_ic_one_shot_runner.py` | `vibe_ic_one_shot_runner.py` | 不變（仍是 full chain） |

**淨變動**：22 個 rename + 3 個 delete = -3 net program。

---

## 4. Slash command 改名（6 → 5）

| 舊 command | 新 command | 動作 |
|---|---|---|
| `/vibe-ic-phase1` | `/vibe-ic-phase1` | 內容擴展（兩入口） |
| `/vibe-ic-phase2a` | **刪除** | 功能併入 `/vibe-ic-phase1` |
| `/vibe-ic-phase2b` | `/vibe-ic-phase2` | rename |
| `/vibe-ic-phase2` | **刪除** | 舊版是 2a+2b chain；新版 `/vibe-ic-phase2` = 原 phase2b |
| `/vibe-ic-phase3` | `/vibe-ic-phase3` | 不變 |
| `/vibe-ic-phase23` | `/vibe-ic-phase23` | 不變 |
| `/vibe-ic-analog` | **刪除** | 拆進對應 phase command |
| `/vibe-ic-all` | `/vibe-ic-all` | 不變 |

**淨變動**：8 → 5 commands。

---

## 5. Flow YAML 改名 + 重寫

| 舊 path | 新 path |
|---|---|
| `flow/phase2_phase3.yaml` | `flow/phase1_phase2_phase3.yaml` |

內容改寫：
- 新增 phase1 區塊（19 entities：1 dialogue + 17 doc skills + A1）
- stage_p0 移到 phase2 區塊
- stage_analog 解散：A1→phase1、A2-A4→phase2、A5-A9→phase3
- stage_mixed_signal 移到 phase3 區塊
- stage5_manufacturing 移到 phase3 區塊
- 每個 entity 加 `phase: 1|2|3` 欄位
- 184 個 phase token 全替換

---

## 6. 專案資料夾改名（Layout P）

### 6.1 Top-level

| 舊路徑 | 新路徑 |
|---|---|
| `<project>/phase2a/` | `<project>/phase1/` |
| `<project>/phase2b/` | `<project>/phase2/` |
| `<project>/phase3/` | `<project>/phase3/` |
| `<project>/analog/` | 散到 `<project>/phase1/analog/ phase2/analog/ phase3/analog/` |
| `<project>/manufacturing/` | `<project>/phase3/stage5_manufacturing/` |

### 6.2 phase1 內部

| 舊路徑 | 新路徑 |
|---|---|
| `phase2a/extracted_docs/` | `phase1/input_doc/` |
| （無）dialogue path 之前散在 `tools/phase1_fg/` workspace | `phase1/input_prompt/` |
| `phase2a/generated_docs/L*.json` | `phase1/generated_docs/L*.json` |
| `phase2a/extraction_patterns.json` | `phase1/extraction_patterns.json` |
| `phase2a/extraction_patterns.auto.json` | `phase1/extraction_patterns.auto.json` |
| `phase2a/completeness_check_config.json` | `phase1/completeness_check_config.json` |
| `phase2a/ai_deep_review_patches.json` | `phase1/ai_deep_review_patches.json` |
| `analog/<block>/spec.json` (A1) | `phase1/analog/<block>/spec.json` |

### 6.3 phase2 內部

| 舊路徑 | 新路徑 |
|---|---|
| `phase2b/stage1/rtl/` | `phase2/stage1/rtl/` |
| `phase2b/stage1/rtl.pre_gen_backup/` | `phase2/stage1/rtl.pre_gen_backup/` |
| `phase2b/stage1/sim/` | `phase2/stage1/sim/` |
| `phase2b/stage1/sim_full_stack/` | `phase2/stage1/sim_full_stack/` |
| `phase2b/stage1/formal/` | `phase2/stage1/formal/` |
| `phase2b/stage1/tb/` | `phase2/stage1/tb/` |
| `phase2b/stage1/fpga/` | `phase2/stage1/fpga/` |
| `phase2b/stage2/constraints/` | `phase2/stage2/constraints/` |
| `phase2b/stage2/synth/` | `phase2/stage2/synth/` |
| `phase2b/stage2/dft/` | `phase2/stage2/dft/` |
| `analog/<block>/topology.md` (A2) | `phase2/analog/<block>/topology.md` |
| `analog/<block>/*.sp` (A3) | `phase2/analog/<block>/*.sp` |
| `analog/<block>/corner_results.json` (A4) | `phase2/analog/<block>/corner_results.json` |

### 6.4 phase3 內部

| 舊路徑 | 新路徑 |
|---|---|
| `phase3/stage3/*` | `phase3/stage3/*`（不變） |
| `phase3/stage4/gds/` | `phase3/stage4/gds/`（不變） |
| `phase3/stage4/foundry_handoff/` | `phase3/stage4/foundry_handoff/`（不變） |
| `phase3/mixed_signal/` | `phase3/mixed_signal/`（不變） |
| `analog/<block>/layout.mag` (A5) | `phase3/analog/<block>/layout.mag` |
| `analog/<block>/drc_clean.flag` (A6) | `phase3/analog/<block>/drc_clean.flag` |
| `analog/<block>/lvs_match.flag` (A6) | `phase3/analog/<block>/lvs_match.flag` |
| `analog/<block>/pre_vs_post.json` (A7) | `phase3/analog/<block>/pre_vs_post.json` |
| `analog/hardmacro/<block>/` (A8) | `phase3/analog/hardmacro/<block>/` |
| `manufacturing/mask_set_received.json` | `phase3/stage5_manufacturing/mask_set_received.json` |
| `manufacturing/wafer_lot_received.json` | `phase3/stage5_manufacturing/wafer_lot_received.json` |
| `manufacturing/wafer_sort_yield.json` | `phase3/stage5_manufacturing/wafer_sort_yield.json` |
| `manufacturing/wafer_map.csv` | `phase3/stage5_manufacturing/wafer_map.csv` |
| `manufacturing/packaging_log.json` | `phase3/stage5_manufacturing/packaging_log.json` |
| `manufacturing/final_test_yield.json` | `phase3/stage5_manufacturing/final_test_yield.json` |
| `manufacturing/burn_in_results.json` | `phase3/stage5_manufacturing/burn_in_results.json` |

---

## 7. Reports 子資料夾改名

| 舊路徑 | 新路徑 |
|---|---|
| `reports/phase2a/` | `reports/phase1/` |
| `reports/phase2b/` | `reports/phase2/` |
| `reports/phase2b/lint/ cdc/ coverage/ dft/ fpga/ gates/ plugin_quality/` | `reports/phase2/lint/ cdc/ ...`（子夾名不變） |
| `reports/phase3/` | `reports/phase3/`（不變） |
| `reports/phase3/sta/ pnr/ ...` | `reports/phase3/sta/ pnr/ ...`（不變） |
| `reports/analog/` | 散到 `reports/phase1/analog/ phase2/analog/ phase3/analog/` |
| `reports/analog/mixed_signal/` | `reports/phase3/mixed_signal/` |
| `reports/audit/` | `reports/audit/`（不變） |
| `reports/orchestrator/` | `reports/orchestrator/`（不變） |

`report_path()` 在 `_path_layout.py` 內的 routing table 要更新 §3 表格全部 entry。

---

## 8. YAML stage_label 變更（flow YAML 內欄位）

| 舊 stage_label | 新 stage_label | 屬於 |
|---|---|---|
| `stage_p0` | `stage_p0` | Phase 2 |
| `stage1` | `stage1` | Phase 2 |
| `stage2` | `stage2` | Phase 2 |
| `stage_analog` | （解散） | 拆進 phase1/2/3 |
| `stage3` | `stage3` | Phase 3 |
| `stage_mixed_signal` | `stage_mixed_signal` | Phase 3 |
| `stage4` | `stage4` | Phase 3 |
| `stage5_manufacturing` | `stage5_manufacturing` | Phase 3 |

Phase 1 內部維持 flat（無 stage 子分），不新增 `stage0`。

---

## 9. ORGANIC backlog yaml id 改寫

`community/backlogs/` 內未送的 13 個 ORGANIC yaml（git status 看到 untracked）：

| 舊 id 前綴 | 新 id 前綴 |
|---|---|
| `ORGANIC-YYYYMMDD-phase1-*` | `ORGANIC-YYYYMMDD-phase1-*`（不變） |
| `ORGANIC-YYYYMMDD-phase2a-*` | `ORGANIC-YYYYMMDD-phase1-*` |

需要逐檔 review，因為其中 phase1 / phase2a 的內容描述也要連帶改寫。

---

## 10. 不動的東西

- `mcp-eda-server/`：MCP tool 命名不帶 phase 前綴（只 1 個檔名匹配，無 sed 必要）
- `mcp-eda-server/INSTALL_GUIDE.md`：除非提到 Phase 流程才改
- `db/`：IC Knowledge Base 與 phase 無關
- `1st_benchmark_sn2025/PROMPT_v099_oss_run2.md`：benchmark 文件可以重生
