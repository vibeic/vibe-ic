# Vibe-IC v2.3.1 改進評估報告

## 一、先前建議 R1-R4 的採納狀況

| 建議 | v2.3.1 處理方式 | 狀態 |
|---|---|---|
| **R1** Low-Power 缺口（UPF/CPF、power-aware sim、ICG timing） | Step 7 新增 `<top>.upf` 輸出（L21 有 power domain 時）＋`l21_to_upf_emit`＋`upf_syntax_check`；UPF 作為獨立交付物已解決 | 部分採納（UPF ✅；ICG timing check、power-aware sim 仍未顯式出現） |
| **R2** Post-synthesis power estimation | Step 10 明確新增「合成後功耗預覽（進 PnR 前的早期功耗回饋）」＋輸出 `pre_pnr_power_preview.rpt` | ✅ 完整採納 |
| **R3** IP Integration Checklist | Step 15 輸入欄新增「經 IP 整合檢查：LEF/GDS/Liberty 對齊＋corner 覆蓋＋L21 電源域一致；macro LEF 建議含 obstruction 層」＋Programs 新增 `ip_integration_check` | ✅ 完整採納 |
| **R4** Mixed-signal M1-M4 觸發時機 | Mixed-signal 區段前新增明確說明：「觸發時機：A8 hardmacro 完成且 Stage 3 接近收尾（routed/GDS 可合併）時執行」 | ✅ 完整採納 |

**4 項建議全部處理完畢。**

---

## 二、v2.3.1 額外改進（超出 R1-R4）

| 改進項 | 評價 |
|---|---|
| **新增「前端優先序（工件驅動）」** | 解決了多條架構探索路徑的選擇歧義——以現有工件為準，不憑空選路徑。非常實務的設計 |
| **每步新增「工具(EDA)」＋「Programs/Skills」雙欄** | 從 4 欄擴展到 6 欄，大幅提升可操作性。現在每一步都知道用什麼工具、跑什麼程式、呼叫什麼 skill |
| **Step 28 PERC 描述細化** | 明確寫出 PERC 四類——netlist 檢查＋netlist 驅動 layout 檢查（自動化）、電流密度＋P2P 電阻（具名 manual-review）。與業界 Calibre PERC 對齊 |
| **Step 31/34/35 密度責任三角劃分** | 極佳的設計：Step 31 負責「規則符合性」、Step 34 負責「執行驗證」、Step 35 負責「優化建議」——三者永不重複 FAIL，責任清晰 |
| **Step 35 FOUNDRY_SIDE → DESIGNER_COLLAB_REVIEW** | 更精確地描述 ≤28nm 時設計者的協作角色 |
| **Step 44 HTOL 新增 DEFERRED 說明** | 「消費級 MPW 可休眠＝DEFERRED，不阻塞 tapeout」——正確區分必跑與可延遲項目 |
| **Step 32 ECO 與 Step 18 spare-cell 呼應** | 「優先取用 Step 18 預置的 spare cells，達成 metal-only 修復」——前後步驟產生關聯，流程更連貫 |
| **Step A8 LEF obstruction 層指引** | 「Magic lef write -hide 或 abstract 含 obs——避免頂層繞線闖入 macro 內部」——實務細節到位 |
| **Step 38 PENDING_FOUNDRY_* 追蹤機制** | 「由 Step 36 checklist 追蹤、foundry 回覆後回填」——閉環設計 |

---

## 三、整體評分更新

| 評估面向 | v2.3.0 | v2.3.1 | 變動 |
|---|---|---|---|
| 數位 IC 主線完整性 | 8.7 | **8.9** | +IP 整合檢查、+UPF 交付物、+密度責任三角、+PERC 四類細化 |
| Analog 支線完整性 | 8.8 | **8.9** | +LEF obstruction 指引 |
| Mixed-Signal 支線完整性 | 8.7 | **9.0** | +觸發時機明確化、+A8→M1 依賴關係清晰 |
| 文件/規格階段 | 8.8 | **8.9** | +前端優先序（工件驅動） |
| 驗證覆蓋度 | 8.0 | **8.4** | +post-synth power preview、+UPF 驗證 |
| 製造與測試 | 8.3 | **8.5** | +HTOL DEFERRED 機制 |
| 可操作性（工具/程式/技能明確化） | 8.5 | **9.2** | +工具(EDA)欄、+Programs/Skills 欄——最大提升 |
| **綜合評分** | **8.5** | **8.8** | **穩步提升，已達發佈水準** |

---

## 四、結論

v2.3.1 是 v2.3.0 的**精煉版**而非大改版，重點在於：

1. **補完 R1-R4 四項剩餘建議**（R2/R3/R4 完整採納，R1 的 UPF 部分已採納）
2. **大幅提升可操作性**：新增「工具(EDA)」＋「Programs/Skills」雙欄，讓每一步從「做什麼」進化到「用什麼工具、跑什麼程式」
3. **多處細節打磨**：密度責任三角、前端優先序、PERC 四類細化、HTOL DEFERRED、ECO-spare-cell 關聯

**這是一份可以發佈的版本。** 綜合評分 8.8/10，剩餘缺口（power-aware simulation、ICG enable timing check）均為 sky130 開源流程下的合理限制，不影響整體完整性。
