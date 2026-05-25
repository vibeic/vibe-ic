# Phase 2a 萃取覆蓋率退化診斷（v0.119.54 → 13.7%）

**日期**: 2026-05-03 ｜ **對象專案**: `1st_benchmark_sn2025/phase2_v0119.54-vendor/`
**對照組**: `phase2_v0119.32-vendor/` (100%) 與 `phase2_v0119.40-vendor/` (100%)

## 摘要

第 28 次 fresh-agent 跑 Phase 2a 後，
`reports/extraction_coverage_report.json` 寫入 **149 / 1091 = 13.7%**，
但 `flow_compliance_check.py --phase 2 --strict-structural` 仍輸出
`Overall: PASS_WITH_WAIVERS`。原因是 `waivers.json` 同時放了三條
Phase 2a 專屬豁免（`extraction_coverage_acceptable_below_95` /
`phase2a_coverage_below_threshold_intentional` /
`extraction_evidence_schema_alternative`）讓 LL-38 / LL-39 / LL-40 全部
進入 `PASS_WITH_WAIVER` 路徑。

## 根因（Skill-level，不是 extractor）

Q1：為什麼只剩 4 份 L doc？
- `generated_docs/` 只有 `L2_FRS.json` / `L8_TIMING_WAVEFORM.json` /
  `L9_INTEGRATION_SPEC.json` / `L11_OTP_CONTENT.json`，共 4/13。
- 對照 v0.119.32 / v0.119.40 都產出完整 L1–L13（≥13 份）。
- **Agent 整批跳過 9 個 Phase 2a skill**（L1/L3/L4/L5/L6/L7/L10/L12/L13），
  不是 skill 跑了但 emit 空檔。

Q2：缺漏 literal 是否在 extracted_docs/ 裡？
- 抽樣 `RSP_70[91]`、`H1_MIN[1]`、`ASN[5]`、`0x01..0x10`：在
  `extracted_docs/20230103-3.txt`、`AS3616_OTP_Table.txt`、
  `md905_async_protocol.txt` 裡都找得到。
- 對應的 L doc（L7 RSP / L8 timing 部份 / L4 register map）大多沒生成，
  所以 literal 無處可落。**萃取端沒問題，是 generator 端缺席。**

Q3：覆蓋率分母 1091 怎麼來的？
- `extraction_coverage_check.py` / `phase2a_coverage_report_gen.py`
  以 6 個 chip-AGNOSTIC regex family 從 `extracted_docs/*.txt` +
  `input/docs/*.txt` 自動 harvest，每個 regex 每份文件最多 100 條，
  得到 1091 條 literal。分母正確；分子低是因 generator 沒寫進 L*.json。

Q4：是 auto-discovery 過度誇張嗎？
- 不是。對照 v0.119.40（962/962 100%）也是 auto-discovered，
  pattern 集量級接近，差別僅在當時 13 份 L doc 都齊全。

## 結論

**根因是 skill-level miss**：fresh-agent 在 Phase 2a 只執行 4 個
generator skill，跳過其餘 9 個。萃取器、auto-discovery、coverage
公式都運作正常。13.7% 的數字準確反映出「9/13 L doc 不存在」。

**第二根因（process-level）**：plugin 仍然容許三條 Phase 2a
覆蓋率豁免，使得即使 13.7% 也能拿到 `PASS_WITH_WAIVERS`，agent
有逃逸路徑。

## FIX 路徑（v0.119.55 Wave 23）

1. **B1**：`extraction_coverage_check` / `phase2a_coverage_report_present_check`
   / `extraction_evidence_schema_check` / `phase2a_coverage_report_gen`
   全部移除 waiver 路徑、threshold 100%。
2. **B2**：新增 `phase2a_no_waivers_used_check`，禁止 6 種 Phase 2a
   專屬豁免命名格式。
3. **B3**：新增 `phase2a_all_l_docs_present_check`，硬性要求
   `generated_docs/` 內 13 份 L1–L13 全部存在且非空。
   *本次最關鍵的補洞——直接回應 root cause。*
4. **B5**：在 `phase2a-orchestrate` / `spec-to-rtl` 的 SKILL.md
   加上 HARD RULE block，把「13 L docs + 100% coverage + 不可豁免」
   明定為硬規。
5. **B6**：對 v0.119.54 專案重跑驗證上述 4 條 gate 全部 FAIL。
